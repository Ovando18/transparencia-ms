"""Conversão dos resultados da coleta em DataFrame e aplicação dos filtros do painel."""
from __future__ import annotations

import pandas as pd

from scrapers.keywords import AREA_TODAS, normalizar, pertence_area

COLUNAS = [
    "Região/Grupo", "Município", "Nº Contrato", "Data Assinatura", "Empresa Contratada",
    "CNPJ", "Objeto Resumido", "Valor (R$)", "Pago (R$)", "Saldo (R$)", "Vigência", "Área Técnica",
    "Docs", "Pagamentos", "Link Contrato", "Link OS", "Link Empenho", "Portal Oficial",
    # colunas auxiliares (não exibidas na tabela principal)
    "Objeto Completo", "Vigência Início", "Vigência Fim", "Plataforma", "Termos",
    "Doc Contrato", "Doc OS", "Doc Empenho", "Doc Completa", "Vínculo Pagamentos", "Fiscal",
    "Fiscal CREA/ART", "Processo", "Link Consulta Contratos", "Link Consulta Despesas",
    "Empenhos", "ID",
]


def _resumir(txt: str | None, n: int = 140) -> str:
    t = (txt or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _vigencia(ini, fim) -> str:
    f = lambda d: d.strftime("%d/%m/%Y") if d else ""  # noqa: E731
    if ini and fim:
        return f"{f(ini)} a {f(fim)}"
    if fim:
        return f"até {f(fim)}"
    return f(ini)


def resultados_para_df(resultados: list[dict]) -> pd.DataFrame:
    linhas = []
    for res in resultados:
        for c in res.get("contratos", []):
            emp = c.get("empenhos") or []
            dc, dos = bool(c.get("link_contrato")), bool(c.get("link_os"))
            de = bool(emp) or bool(c.get("link_empenho"))
            vinculo = c.get("vinculo_pagamentos") or ""
            linhas.append({
                "Região/Grupo": c.get("grupo") or res.get("grupo"),
                "Município": c.get("municipio") or res.get("municipio"),
                "Nº Contrato": c.get("numero") or "",
                "Data Assinatura": pd.to_datetime(c.get("data_assinatura")) if c.get("data_assinatura") else pd.NaT,
                "Empresa Contratada": c.get("fornecedor") or "",
                "CNPJ": c.get("cnpj") or "",
                "Objeto Resumido": _resumir(c.get("objeto")),
                "Valor (R$)": c.get("valor"),
                "Pago (R$)": c.get("valor_pago"),
                "Saldo (R$)": c.get("saldo"),
                "Vigência": _vigencia(c.get("vigencia_inicio"), c.get("vigencia_fim")),
                "Área Técnica": "; ".join(c.get("areas") or []),
                "Docs": f"{'✅' if dc else '❌'} Contrato · {'✅' if de else '❌'} Empenho · {'✅' if dos else '➖'} OS",
                "Pagamentos": (f"{len(emp)} pagamento(s) · {vinculo}" if emp
                               else (vinculo or "Não localizados no portal")),
                # Links ESPECÍFICOS do contrato. Sem documento direto, "Contrato" abre a área de
                # contratos do portal; "Empenho" fica vazio (pagamentos ficam na Ficha Técnica).
                "Link Contrato": c.get("link_contrato") or c.get("link_consulta_contratos"),
                "Link OS": c.get("link_os"),
                "Link Empenho": c.get("link_empenho"),
                "Portal Oficial": c.get("portal") or res.get("url"),
                "Objeto Completo": c.get("objeto") or "",
                "Vigência Início": c.get("vigencia_inicio"),
                "Vigência Fim": c.get("vigencia_fim"),
                "Plataforma": c.get("plataforma") or res.get("plataforma"),
                "Termos": ", ".join(c.get("termos") or []),
                "Doc Contrato": dc, "Doc OS": dos, "Doc Empenho": de,
                "Doc Completa": dc and de,  # OS é opcional (raramente publicada nos portais)
                "Vínculo Pagamentos": vinculo,
                "Fiscal": c.get("fiscal_gestor") or "",
                "Fiscal CREA/ART": c.get("fiscal_crea_art") or "",
                "Processo": str(c.get("processo") or ""),
                "Link Consulta Contratos": c.get("link_consulta_contratos"),
                "Link Consulta Despesas": c.get("link_consulta_despesas"),
                "Empenhos": emp,
            })
    df = pd.DataFrame(linhas, columns=COLUNAS[:-1])
    df["ID"] = range(len(df))
    if not df.empty:
        for col in ("Valor (R$)", "Pago (R$)", "Saldo (R$)"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_values(["Região/Grupo", "Município", "Data Assinatura"], na_position="last")
    return df.reset_index(drop=True)


def aplicar_filtros(df: pd.DataFrame, area: str = AREA_TODAS, texto: str = "",
                    valor_min: float = 0.0, valor_max: float = 0.0,
                    somente_doc_completa: bool = False) -> pd.DataFrame:
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if area and area != AREA_TODAS:
        m &= df["Área Técnica"].map(lambda a: pertence_area(a, area))
    if texto.strip():
        alvo = normalizar(texto)
        digitos = "".join(ch for ch in texto if ch.isdigit())
        blob = (df["Objeto Completo"] + " " + df["Nº Contrato"].astype(str) + " "
                + df["Empresa Contratada"] + " " + df["CNPJ"]).map(normalizar)
        hit = blob.str.contains(alvo, regex=False)
        if len(digitos) >= 4:
            hit |= df["CNPJ"].str.replace(r"\D", "", regex=True).str.contains(digitos, regex=False)
        m &= hit
    if valor_min:
        m &= df["Valor (R$)"].fillna(0) >= valor_min
    if valor_max:
        m &= df["Valor (R$)"].fillna(0) <= valor_max
    if somente_doc_completa:
        m &= df["Doc Completa"]
    return df[m].reset_index(drop=True)


def status_para_df(resultados: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Região/Grupo": r.get("grupo"),
        "Município": r.get("municipio"),
        "Plataforma": r.get("plataforma"),
        "Status": r.get("status"),
        "Detalhe": r.get("detalhe"),
        "Registros Lidos": r.get("total_bruto", 0),
        "Contratos Engenharia": len(r.get("contratos", [])),
        "Tempo (s)": r.get("tempo_s", 0.0),
        "Acesso Manual (Contratos)": r.get("link_manual") or None,
        "Portal Oficial": r.get("url") or None,
    } for r in resultados]).sort_values(["Região/Grupo", "Município"]).reset_index(drop=True)


def brl(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
