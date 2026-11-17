"""FiscalizaObras-MS — Painel de fiscalização de contratos públicos de Engenharia,
Agronomia e Geociências nos Portais da Transparência das prefeituras de MS (Crea-MS).

Execução local:  streamlit run app.py
"""
from __future__ import annotations

from datetime import date
import html

import pandas as pd
import streamlit as st

from config import municipios_ms as cfg
from config.base_builder import construir_base, salvar_base
from scrapers.collector import coletar_varios, limpar_cache, ST_COLETADO, ST_SEM_ENG
from scrapers.keywords import AREA_TODAS, AREAS_TECNICAS
from utils.dados import aplicar_filtros, brl, resultados_para_df, status_para_df
from utils.export_excel import gerar_excel
from utils import styles

st.set_page_config(page_title="FiscalizaObras-MS | Crea-MS", page_icon="🏗️", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown(styles.CSS, unsafe_allow_html=True)

TODOS_REGIAO = "Todos os municípios da região"
TODOS_FIXOS = "Todos os Fiscais Fixos"
MODO_REGIAO = "Por Região de Fiscalização (1 a 18)"
MODO_FIXOS = "Municípios com Fiscais Fixos"
SEM_REGIAO = "0"  # pseudo-região para municípios ainda não mapeados
ANO_ATUAL = max(2026, date.today().year)

ss = st.session_state
ss.setdefault("resultados", None)
ss.setdefault("exercicio_coletado", None)

base = cfg.carregar_base()


# ===========================================================================
# SIDEBAR
# ===========================================================================
def _rotulo_regiao(num: str) -> str:
    if num == SEM_REGIAO:
        return f"Sem região definida ({len(cfg.municipios_sem_regiao())} municípios)"
    nomes = next((n for k, _, n in cfg.listar_regioes() if k == num), [])
    resumo = ", ".join(nomes[:4]) + ("…" if len(nomes) > 4 else "")
    return f"Região {num} — {resumo}" if nomes else f"Região {num} (sem municípios na base)"


with st.sidebar:
    st.markdown('<div class="fo-side-titulo">🏗️ FiscalizaObras-MS</div>'
                '<div class="fo-side-sub">Crea-MS · Fiscalização de contratos técnicos</div>',
                unsafe_allow_html=True)

    if not base.get("oficial"):
        st.warning("Base oficial de municípios não carregada. Envie a planilha e o PDF abaixo.", icon="⚠️")

    with st.expander("📂 Base oficial de municípios", expanded=not base.get("oficial")):
        r = base.get("resumo", {})
        st.caption(f"Fiscais fixos: **{r.get('fiscais_fixos', 0)}** · Em regiões: "
                   f"**{r.get('municipios_em_regioes', 0)}/75** · Com URL: **{r.get('com_url', 0)}/79**")
        if base.get("gerado_em"):
            st.caption(f"Gerada em {base['gerado_em']}")
        up_xlsx = st.file_uploader("Transparências MS completo.xlsx", type=["xlsx"], key="up_xlsx")
        up_pdf = st.file_uploader("REGIÕES 2026.pdf", type=["pdf"], key="up_pdf")
        if st.button("Processar arquivos", disabled=not (up_xlsx and up_pdf), width="stretch"):
            try:
                nova = construir_base(up_xlsx.getvalue(), up_pdf.getvalue(), up_xlsx.name, up_pdf.name)
                salvar_base(nova)
                cfg.recarregar_base()
                st.success("Base atualizada.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Não foi possível processar os arquivos: {exc}")
        for p in base.get("pendencias", []):
            st.caption(f"• {p}")

    st.markdown("### Modo de pesquisa")
    modo = st.radio("Modo de pesquisa", [MODO_REGIAO, MODO_FIXOS], label_visibility="collapsed")

    selecionados: list[dict] = []
    if modo == MODO_REGIAO:
        opcoes = [k for k, _, n in cfg.listar_regioes()]
        if cfg.municipios_sem_regiao():
            opcoes.append(SEM_REGIAO)
        regiao = st.selectbox("Região de Fiscalização", opcoes, format_func=_rotulo_regiao)
        lista = cfg.municipios_sem_regiao() if regiao == SEM_REGIAO else cfg.municipios_da_regiao(regiao)
        nomes = [m["nome"] for m in lista]
        if nomes:
            st.caption("Municípios: " + ", ".join(nomes))
        escolha = st.multiselect("Municípios", [TODOS_REGIAO] + nomes, default=[TODOS_REGIAO],
                                 disabled=not nomes)
        selecionados = lista if (TODOS_REGIAO in escolha or not escolha) else [m for m in lista if m["nome"] in escolha]
    else:
        fixos = cfg.municipios_fixos()
        escolha = st.multiselect("Municípios com Fiscais Fixos", [TODOS_FIXOS] + [m["nome"] for m in fixos],
                                 default=[TODOS_FIXOS])
        selecionados = fixos if (TODOS_FIXOS in escolha or not escolha) else [m for m in fixos if m["nome"] in escolha]

    st.markdown("### Filtros de auditoria")
    exercicio = st.selectbox("Exercício", list(range(ANO_ATUAL, ANO_ATUAL - 7, -1)), index=0)
    area = st.selectbox("Área técnica", [AREA_TODAS] + list(AREAS_TECNICAS))
    texto = st.text_input("Busca livre", placeholder="Objeto, nº do contrato, CNPJ ou empresa")
    c1, c2 = st.columns(2)
    valor_min = c1.number_input("Valor mín. (R$)", min_value=0.0, step=10000.0, format="%.2f")
    valor_max = c2.number_input("Valor máx. (R$)", min_value=0.0, step=10000.0, format="%.2f",
                                help="0 = sem limite")
    so_doc = st.checkbox("Somente documentação completa (Contrato + Empenho)",
                         help="A Ordem de Serviço é exibida quando o portal a publica, mas não é exigida.")

    with st.expander("⚙️ Opções avançadas"):
        verificar_ssl = not st.toggle("Aceitar portais com certificado SSL inválido", value=False,
                                      help="Alguns portais municipais usam certificados vencidos. "
                                           "Ative apenas se o portal for conhecido.")
        workers = st.slider("Consultas simultâneas", 2, 16, 8)

    pesquisar = st.button("🔎 Pesquisar Contratos nos Portais", type="primary", width="stretch",
                          disabled=not selecionados)
    if st.button("♻️ Limpar Cache / Atualizar Dados", width="stretch"):
        limpar_cache()
        st.cache_data.clear()
        ss.resultados = None
        st.toast("Cache limpo. A próxima pesquisa consultará os portais novamente.")


# ===========================================================================
# COLETA
# ===========================================================================
# ---------------------------------------------------------------------------
# Link direto para a Ficha de um contrato: ?mun=<município>&ano=<ano>&ct=<nº contrato>
# (usado em "Abrir empenho" quando o portal não tem página própria por empenho)
# ---------------------------------------------------------------------------
_qp = st.query_params
_alvo = (_qp.get("mun"), _qp.get("ano"), _qp.get("ct"))
if all(_alvo) and ss.get("deep_link_feito") != _alvo:
    _m = cfg.info_municipio(_alvo[0])
    if _m:
        selecionados, exercicio, pesquisar = [_m], int(_alvo[1]), True
        ss.ficha_alvo = (_alvo[0], _alvo[2])
        ss.aba_ativa = "🔎 Ficha Técnica de Fiscalização"
    ss.deep_link_feito = _alvo

if pesquisar and selecionados:
    total = len(selecionados)
    with st.status(f"Consultando {total} portal(is) da transparência…", expanded=True) as caixa:
        barra = st.progress(0.0, text="Iniciando…")
        log = st.empty()
        linhas: list[str] = []

        def _progresso(feitos: int, tot: int, res: dict) -> None:
            icone = "✅" if res["status"] in (ST_COLETADO, ST_SEM_ENG) else "⚠️"
            linhas.append(f"{icone} **{res['municipio']}** — {res['status']} ({len(res['contratos'])} contrato(s))")
            barra.progress(feitos / tot, text=f"{feitos}/{tot} portais consultados")
            log.markdown("\n\n".join(linhas[-8:]))

        resultados = coletar_varios(selecionados, int(exercicio), verificar_ssl, workers, _progresso)
        ok = sum(r["status"] in (ST_COLETADO, ST_SEM_ENG) for r in resultados)
        caixa.update(label=f"Consulta concluída: {ok}/{total} portais responderam automaticamente.",
                     state="complete" if ok == total else "error", expanded=False)
    ss.resultados = resultados
    ss.exercicio_coletado = int(exercicio)


# ===========================================================================
# ÁREA PRINCIPAL
# ===========================================================================
st.markdown(styles.cabecalho(
    "FiscalizaObras-MS",
    "Pesquisa, auditoria e extração de contratos de obras e serviços de Engenharia, Agronomia e "
    "Geociências diretamente dos Portais da Transparência das prefeituras de Mato Grosso do Sul."),
    unsafe_allow_html=True)

if not base.get("oficial"):
    st.markdown('<div class="fo-aviso"><b>Base provisória:</b> a divisão em 18 Regiões e as URLs dos portais '
                'vêm dos arquivos oficiais <i>Transparências MS completo.xlsx</i> e <i>REGIÕES 2026.pdf</i>, '
                'que ainda não foram carregados. Use “Base oficial de municípios” na barra lateral ou coloque '
                'os arquivos na raiz do projeto.</div>', unsafe_allow_html=True)

resultados = ss.resultados
df_total = resultados_para_df(resultados) if resultados else resultados_para_df([])
df = aplicar_filtros(df_total, area, texto, valor_min, valor_max, so_doc)
status_df = status_para_df(resultados) if resultados else pd.DataFrame()

n_mun = len(resultados or [])
n_online = sum(r["status"] in (ST_COLETADO, ST_SEM_ENG) for r in (resultados or []))
pct_doc = (df["Doc Completa"].mean() * 100) if len(df) else 0.0
st.markdown(styles.kpis([
    ("Contratos encontrados", f"{len(df):,}".replace(",", "."),
     f"de {len(df_total)} no escopo técnico" if resultados else "aguardando pesquisa", ""),
    ("Valor global contratado", brl(df["Valor (R$)"].sum()) if len(df) else "R$ 0,00",
     f"Exercício {ss.exercicio_coletado or exercicio}", "verde"),
    ("Municípios consultados", str(n_mun), f"{n_online} com coleta automática" if n_mun else "—", ""),
    ("Com documentação anexa", f"{pct_doc:.0f}%".replace(".", ","), "Contrato + Empenho (OS opcional)", "amarelo"),
]), unsafe_allow_html=True)

if resultados is None:
    st.info("Selecione uma **Região de Fiscalização** ou os **Municípios com Fiscais Fixos** na barra lateral "
            "e clique em **Pesquisar Contratos nos Portais**.", icon="👈")
    st.stop()

if ss.exercicio_coletado != int(exercicio):
    st.caption(f"⚠️ Resultados referem-se ao exercício {ss.exercicio_coletado}. "
               "Clique em Pesquisar para consultar o exercício selecionado.")

topo1, topo2 = st.columns([3, 1])
topo1.caption(f"Exibindo **{len(df)}** contrato(s) após filtros · {n_mun} município(s) consultado(s).")
topo2.download_button("📥 Exportar Planilha (.xlsx)",
                      data=gerar_excel(df, status_df, ss.exercicio_coletado),
                      file_name=f"FiscalizaObras-MS_{ss.exercicio_coletado}_{date.today():%Y%m%d}.xlsx",
                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      type="primary", width="stretch", disabled=df.empty)

ABAS = ["📑 Contratos", "🔎 Ficha Técnica de Fiscalização", "🌐 Status dos Portais Consultados"]
# seletor com estado (st.tabs volta à 1ª aba quando a página recarrega ao escolher um contrato)
aba = st.segmented_control("Visualização", ABAS, default=ABAS[0], key="aba_ativa",
                           label_visibility="collapsed") or ABAS[0]

if aba == ABAS[0]:
    if df.empty:
        st.warning("Nenhum contrato de Engenharia/Agronomia/Geociências encontrado com os filtros atuais. "
                   "Verifique a aba **Status dos Portais** — portais em *Consulta Manual* precisam ser "
                   "conferidos pelo link direto.", icon="🔍")
    else:
        visiveis = ["Região/Grupo", "Município", "Nº Contrato", "Data Assinatura", "Empresa Contratada", "CNPJ",
                    "Objeto Resumido", "Valor (R$)", "Pago (R$)", "Saldo (R$)", "Vigência", "Docs", "Pagamentos",
                    "Link Contrato", "Link OS", "Link Empenho", "Portal Oficial"]
        tabela = df[visiveis].copy()
        try:
            base_app = (st.context.url or "").split("?")[0]
        except Exception:  # noqa: BLE001
            base_app = ""
        if base_app:
            from urllib.parse import urlencode
            sem_link = tabela["Link Empenho"].isna() & df["Empenhos"].map(bool)
            tabela.loc[sem_link, "Link Empenho"] = [
                f"{base_app}?{urlencode({'mun': r['Município'], 'ano': ss.exercicio_coletado, 'ct': r['Nº Contrato']})}"
                for _, r in df[sem_link].iterrows()]
        for col in ("Link Contrato", "Link OS", "Link Empenho", "Portal Oficial"):
            tabela[col] = tabela[col].fillna("")  # célula vazia em vez de "None"
        moeda = dict(format="localized")
        st.dataframe(
            tabela, width="stretch", hide_index=True, height=min(640, 42 + 35 * len(df)),
            column_config={
                "Data Assinatura": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Valor (R$)": st.column_config.NumberColumn("Valor (R$)", **moeda),
                "Pago (R$)": st.column_config.NumberColumn("Pago (R$)", **moeda,
                                                           help="Soma dos pagamentos localizados no portal"),
                "Saldo (R$)": st.column_config.NumberColumn("Saldo (R$)", **moeda),
                "Objeto Resumido": st.column_config.TextColumn(width="large"),
                "Empresa Contratada": st.column_config.TextColumn(width="medium"),
                "Docs": st.column_config.TextColumn("Status Documental", width="medium"),
                "Pagamentos": st.column_config.TextColumn("💰 Pagamentos", width="medium",
                                                          help="Detalhe de cada pagamento na Ficha Técnica"),
                "Link Contrato": st.column_config.LinkColumn("📄 Contrato", display_text="Abrir contrato"),
                "Link OS": st.column_config.LinkColumn("📋 Ordem de Serviço", display_text="Abrir OS",
                                                       help="Vazio = OS não publicada no portal"),
                "Link Empenho": st.column_config.LinkColumn(
                    "💰 Empenho do contrato", display_text="Abrir empenho",
                    help="Quality: página do contrato no portal, com seus empenhos. SCPI (sem página por empenho "
                         "no portal): abre a Ficha Técnica deste contrato no painel, com todos os pagamentos."),
                "Portal Oficial": st.column_config.LinkColumn("🌐 Portal", display_text="Portal"),
            })
        st.caption("**Quality:** “Abrir contrato” baixa o PDF e “Abrir empenho” abre a página do contrato no portal. "
                   "**SCPI:** o portal não tem endereço próprio por empenho; “Abrir empenho” abre, em nova aba, a "
                   "**Ficha Técnica deste contrato** com os pagamentos localizados.")

if aba == ABAS[1]:
    if df.empty:
        st.info("Nenhum contrato disponível para detalhamento.")
    else:
        rotulos = {int(r["ID"]): f"{r['Município']} · Nº {r['Nº Contrato'] or 's/n'} · "
                                 f"{(r['Empresa Contratada'] or 'Contratada não informada')[:45]} · "
                                 f"{brl(r['Valor (R$)'])}" for r in df.to_dict("records")}
        ids = list(rotulos)
        idx = 0
        if ss.get("ficha_alvo"):
            mun_a, ct_a = ss.ficha_alvo
            achado = df[(df["Município"] == mun_a) & (df["Nº Contrato"] == ct_a)]
            if not achado.empty:
                idx = ids.index(int(achado.iloc[0]["ID"]))
            ss.ficha_alvo = None
        sel = st.selectbox("Selecione o contrato", ids, index=idx, format_func=rotulos.get)
        c = df[df["ID"] == sel].iloc[0]

        st.markdown(f"#### {c['Município']} — Contrato nº {c['Nº Contrato'] or 's/n'}")
        st.markdown(" ".join([
            styles.badge(c["Região/Grupo"] or "—", "info"),
            styles.badge(c["Plataforma"] or "—", "info"),
            *[styles.badge(a, "ok") for a in (c["Área Técnica"] or "").split("; ") if a],
            styles.badge("Documentação completa" if c["Doc Completa"] else "Documentação incompleta",
                         "ok" if c["Doc Completa"] else "alerta"),
        ]), unsafe_allow_html=True)

        b1, b2, b3, b4 = st.columns(4)
        lk_ctr = c["Link Contrato"] or c["Portal Oficial"]
        b1.link_button("📄 Abrir / Baixar Contrato" if c["Doc Contrato"] else "📄 Área de Contratos do Portal",
                       lk_ctr or "about:blank", width="stretch", type="primary", disabled=not lk_ctr)
        if c["Link OS"]:
            b2.link_button("📋 Abrir Ordem de Serviço", c["Link OS"], width="stretch", type="primary")
        else:
            b2.button("📋 OS não publicada no portal", disabled=True, width="stretch")
        if c["Link Empenho"]:
            b3.link_button("💰 Empenhos deste Contrato", c["Link Empenho"], width="stretch", type="primary")
        else:
            lk_desp = c["Link Consulta Despesas"] or c["Portal Oficial"]
            b3.link_button("💰 Consulta de Despesas (geral)", lk_desp or "about:blank", width="stretch",
                           disabled=not lk_desp,
                           help="O portal não tem página por empenho. Os pagamentos localizados estão abaixo.")
        b4.link_button("🌐 Portal Oficial", c["Portal Oficial"] or "about:blank", width="stretch",
                       disabled=not c["Portal Oficial"])

        valor, pago, saldo = c["Valor (R$)"], c["Pago (R$)"], c["Saldo (R$)"]
        exec_pct = (pago / valor * 100) if pd.notna(valor) and valor and pd.notna(pago) else None
        st.markdown(styles.kpis([
            ("Valor contratado", brl(valor), c["Vigência"] or "", ""),
            ("Total pago", brl(pago) if pd.notna(pago) else "Não atribuído",
             (c["Vínculo Pagamentos"] or "—") + (f" · pago à empresa no ano: {brl(c['Pago ao Fornecedor (R$)'])}"
                                                 if pd.isna(pago) and pd.notna(c["Pago ao Fornecedor (R$)"]) else ""),
             "verde"),
            ("Saldo contratual", brl(saldo), "valor (com aditivos) − pago", ""),
            ("Execução financeira", f"{exec_pct:.0f}%" if exec_pct is not None else "—", "pago ÷ contratado", "amarelo"),
        ]), unsafe_allow_html=True)

        e, d = st.columns([3, 2])
        with e:
            st.markdown(f'<div class="fo-card"><h4>Objeto do contrato</h4>'
                        f'<div class="dado">{html.escape(c["Objeto Completo"] or "—")}</div>'
                        f'<div class="campo">Termos técnicos identificados</div>'
                        f'<div class="dado">{c["Termos"] or "—"}</div>'
                        f'<div class="campo">Processo</div><div class="dado">{c["Processo"] or "—"}</div></div>',
                        unsafe_allow_html=True)
        with d:
            data_ass = c["Data Assinatura"].strftime("%d/%m/%Y") if pd.notna(c["Data Assinatura"]) else "—"
            st.markdown(f'<div class="fo-card"><h4>Contratada e fiscalização</h4>'
                        f'<div class="campo">Razão social</div><div class="dado">{html.escape(c["Empresa Contratada"] or "—")}</div>'
                        f'<div class="campo">CNPJ</div><div class="dado">{c["CNPJ"] or "—"}</div>'
                        f'<div class="campo">Assinatura · Vigência</div>'
                        f'<div class="dado">{data_ass} · {c["Vigência"] or "—"}</div>'
                        f'<div class="campo">Fiscal do contrato</div><div class="dado">{html.escape(c["Fiscal"] or "Não informado no portal")}</div>'
                        f'<div class="campo">CREA / ART do fiscal</div><div class="dado">{html.escape(c["Fiscal CREA/ART"] or "Não informado no portal")}</div>'
                        f'</div>', unsafe_allow_html=True)

        st.markdown("##### Empenhos e pagamentos")
        emp = pd.DataFrame(c["Empenhos"] or [])
        if not emp.empty:
            emp["data"] = pd.to_datetime(emp["data"], dayfirst=True, errors="coerce")
            ordem = [x for x in ["data", "numero", "liquidacao", "ordem_pagamento", "nota_fiscal", "valor_empenhado",
                                 "valor_pago", "vinculo", "link", "historico"]
                     if x in emp.columns and emp[x].notna().any()]
            st.dataframe(emp[ordem], width="stretch", hide_index=True, column_config={
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "numero": "Nº Empenho", "liquidacao": "Liquidação", "ordem_pagamento": "Ordem de Pagamento",
                "nota_fiscal": "Nota Fiscal",
                "valor_empenhado": st.column_config.NumberColumn("Empenhado (R$)", format="localized"),
                "valor_pago": st.column_config.NumberColumn("Valor pago (R$)", format="localized"),
                "link": st.column_config.LinkColumn("Empenho no portal", display_text="Abrir empenho"),
                "vinculo": "Vínculo", "historico": st.column_config.TextColumn("Histórico", width="large"),
            })
            if "vinculo" in emp.columns and (emp["vinculo"] == "Pagamento ao fornecedor (CNPJ)").any():
                st.caption("“Pagamento ao fornecedor (CNPJ)”: pago à mesma empresa após o início da vigência, sem "
                           "citar este contrato no histórico. Só entra no **Total pago** quando a empresa tem um "
                           "único contrato com o município; caso contrário, confira o histórico de cada pagamento.")
        else:
            st.caption("Nenhum pagamento localizado no portal para este contrato no exercício.")

if aba == ABAS[2]:
    if status_df.empty:
        st.info("Nenhum portal consultado.")
    else:
        resumo = status_df["Status"].value_counts()
        st.markdown(" ".join(styles.badge(f"{k}: {v}", "ok" if k in (ST_COLETADO, ST_SEM_ENG) else "alerta")
                             for k, v in resumo.items()), unsafe_allow_html=True)
        st.dataframe(status_df, width="stretch", hide_index=True, column_config={
            "Detalhe": st.column_config.TextColumn(width="large"),
            "Acesso Manual (Contratos)": st.column_config.LinkColumn(display_text="Abrir contratos"),
            "Portal Oficial": st.column_config.LinkColumn(display_text="Abrir portal"),
        })
        st.caption("**Consulta Manual**: portal online, porém a listagem exige navegação dinâmica — use o link "
                   "direto. **Instável / Timeout** e **Bloqueado**: tente novamente mais tarde ou acesse manualmente.")
