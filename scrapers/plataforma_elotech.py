"""Coletor do Portal da Transparência Elotech Oxy (ex.: navirai.oxy.elotech.com.br).

Funcionamento verificado em Naviraí (API pública, sem autenticação):

* contratos:   ``GET {host}/portaltransparencia-api/api/contratos?entidade=N&exercicio=AAAA&page=P&size=S``
  (traz também contratos de anos anteriores ainda vigentes e atas de registro de preço);
* arquivos:    ``GET .../api/contratos/arquivos?idOxy=<id>``  -> PDF em ``.../api/files/arquivo/<idArquivo>``;
* fiscais:     ``GET .../api/responsaveis/contrato?idOxy=<id>``;
* empenhos:    ``GET {host}/portaltransparencia-api/empenhos/lista?entidade=N&exercicio=AAAA&page=P&size=S``
  (todos os empenhos do ano; o credor vem como "CNPJ - NOME");
* páginas públicas: ``/portaltransparencia/N/contratos/detalhes?...`` e
  ``/portaltransparencia/N/empenhos/detalhe?...``.

Prefeituras que mantêm um site próprio (ex.: WordPress) com link para o Oxy são
detectadas por ``localizar_portal_oxy``.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import requests

from scrapers.parsers import finalizar, formatar_cnpj, parse_data
from scrapers.plataforma_scpi import _digitos, _padroes_vinculo

TIMEOUT = (8, 60)
_RE_OXY = re.compile(r"(https?://[a-z0-9-]+\.oxy\.elotech\.com\.br)/portaltransparencia/(\d+)", re.I)


def localizar_portal_oxy(sessao: requests.Session, url: str) -> str | None:
    """Devolve a URL do portal Oxy (a própria URL ou o link encontrado no site da prefeitura)."""
    if _RE_OXY.search(url or ""):
        return url
    try:
        r = sessao.get(url, timeout=(6, 20))
    except requests.RequestException:
        return None
    m = _RE_OXY.search(r.text)
    return f"{m.group(1)}/portaltransparencia/{m.group(2)}/" if m else None


def _base(url_oxy: str) -> tuple[str, str]:
    m = _RE_OXY.search(url_oxy)
    return m.group(1), m.group(2)


def _paginado(sessao, endpoint: str, params: dict, tamanho: int = 1000, max_paginas: int = 30) -> list[dict]:
    itens: list[dict] = []
    for pagina in range(max_paginas):
        r = sessao.get(endpoint, params={**params, "page": pagina, "size": tamanho}, timeout=TIMEOUT,
                       headers={"Accept": "application/json"})
        r.raise_for_status()
        d = r.json()
        itens += d.get("content") or []
        if d.get("last", True):
            break
    return itens


def link_pagina_contrato(url_oxy: str, c: dict) -> str:
    host, ent = _base(url_oxy)
    return (f"{host}/portaltransparencia/{ent}/contratos/detalhes?entidade={c.get('entidade') or ent}"
            f"&exercicio={c.get('exercicio')}&contrato={c.get('contrato')}&tipoAto={c.get('tipoAto')}")


def link_empenho(url_oxy: str, entidade, exercicio, empenho) -> str:
    host, ent = _base(url_oxy)
    return (f"{host}/portaltransparencia/{ent}/empenhos/detalhe?search={quote(f'id.entidade=={entidade}')}"
            f"&entidade={entidade}&exercicio={exercicio}&empenho={empenho}")


def coletar_elotech(sessao: requests.Session, url_oxy: str, ano: int) -> list[dict]:
    host, ent = _base(url_oxy)
    api = f"{host}/portaltransparencia-api/api"
    todos = _paginado(sessao, f"{api}/contratos", {"entidade": ent, "exercicio": ano}, tamanho=500)
    por_cnpj: dict[str, int] = {}
    for c in todos:
        if c.get("tipoAto") == 1:
            d = _digitos(c.get("cnpjCpf"))
            por_cnpj[d] = por_cnpj.get(d, 0) + 1
    regs = []
    for c in todos:
        if c.get("tipoAto") != 1:      # 1 = Contrato (demais: atas de registro de preço etc.)
            continue
        disp = str(c.get("displayContrato") or "")
        ano_ct = disp.split("/")[-1] if "/" in disp else str(c.get("exercicio") or "")
        if ano_ct.isdigit() and int(ano_ct) != int(ano):
            continue                    # contrato de ano anterior ainda vigente
        valor = c.get("valorContratado")
        if valor is not None and c.get("valorAditivo"):
            valor = float(valor) + float(c["valorAditivo"])
        reg = {
            "numero": disp,
            "ano_contrato": int(ano_ct) if ano_ct.isdigit() else int(ano),
            "data_assinatura": c.get("inicioVigencia"),
            "fornecedor": c.get("nome"),
            "cnpj": formatar_cnpj(c.get("cnpjCpf")),
            "objeto": c.get("objeto"),
            "valor": valor,
            "vigencia_inicio": c.get("inicioVigencia"),
            "vigencia_fim": c.get("terminoVigencia"),
            "processo": c.get("displayLicitacao"),
            "modalidade": c.get("descricaoTipoLicitacao"),
            "link_contrato": None, "link_os": None, "link_empenho": None, "empenhos": [],
        }
        reg = finalizar(reg)
        reg["id_oxy"] = c.get("idOxy")
        reg["link_pagina_contrato"] = link_pagina_contrato(url_oxy, c)
        reg["contratos_mesmo_cnpj"] = por_cnpj.get(_digitos(c.get("cnpjCpf")), 1)
        regs.append(reg)
    return regs


def enriquecer_elotech(sessao: requests.Session, url_oxy: str, ano: int, contratos: list[dict]) -> None:
    if not contratos:
        return
    host, ent = _base(url_oxy)
    api = f"{host}/portaltransparencia-api/api"

    # PDF do contrato e fiscais
    for reg in contratos:
        reg["link_contrato"] = reg.get("link_pagina_contrato")
        if not reg.get("id_oxy"):
            continue
        try:
            arqs = sessao.get(f"{api}/contratos/arquivos", params={"idOxy": reg["id_oxy"]}, timeout=TIMEOUT).json()
            pdf = next((a for a in arqs if "contrato" in str(a.get("nomeArquivo", "")).lower()), None)
            pdf = pdf or (arqs[0] if arqs else None)
            if pdf and pdf.get("idArquivo"):
                reg["link_contrato"] = f"{api}/files/arquivo/{pdf['idArquivo']}"
            resp = sessao.get(f"{api}/responsaveis/contrato", params={"idOxy": reg["id_oxy"]}, timeout=TIMEOUT).json()
            if resp:
                reg["fiscal_gestor"] = "; ".join(f"{r.get('ocupante')} ({str(r.get('tipo', '')).title()})"
                                                 for r in resp if r.get("ocupante"))
        except (requests.RequestException, ValueError):
            continue

    # empenhos do exercício, ligados por CNPJ do credor e citação do contrato/processo
    try:
        # o parâmetro "search" é obrigatório (sem ele a API devolve lista vazia)
        empenhos = _paginado(sessao, f"{host}/portaltransparencia-api/empenhos/lista",
                             {"entidade": ent, "exercicio": ano, "search": f"id.entidade=={ent}"},
                             tamanho=2000)
    except (requests.RequestException, ValueError):
        return
    por_cnpj: dict[str, list[dict]] = {}
    for e in empenhos:
        m = re.match(r"\s*([\d./-]{11,18})\s*-", str(e.get("nome") or ""))
        if m:
            por_cnpj.setdefault(_digitos(m.group(1)), []).append(e)

    for reg in contratos:
        lista = por_cnpj.get(_digitos(reg.get("cnpj")), [])
        inicio = reg.get("vigencia_inicio") or reg.get("data_assinatura")
        pads = _padroes_vinculo(reg)
        emp = []
        for e in lista:
            d = parse_data(e.get("data"))
            if inicio and d and d < inicio:
                continue
            hist = str(e.get("historico") or "")
            emp.append({
                "numero": e.get("empenhoExercicio") or e.get("empenho"),
                "data": d,
                "valor_empenhado": e.get("valorEmpenhado"),
                "valor_pago": e.get("valorPago"),
                "historico": hist,
                "link": link_empenho(url_oxy, e.get("entidade") or ent, e.get("exercicio") or ano, e.get("empenho")),
                "vinculo": ("Vinculado ao contrato" if any(p.search(hist) for p in pads)
                            else "Pagamento ao fornecedor (CNPJ)"),
            })
        emp.sort(key=lambda x: x["data"] or parse_data("01/01/1900"), reverse=True)
        reg["empenhos"] = emp
        vinc = [x for x in emp if x["vinculo"] == "Vinculado ao contrato"]
        n_ctr = int(reg.get("contratos_mesmo_cnpj") or 1)
        reg["pago_ao_fornecedor"] = round(sum(x["valor_pago"] or 0 for x in emp), 2)
        if vinc:
            base, rotulo = vinc, "Histórico cita o contrato/processo"
        elif emp and n_ctr <= 1:
            base, rotulo = emp, "Pelo CNPJ (único contrato da empresa)"
        elif emp:
            base, rotulo = [], f"Empresa com {n_ctr} contratos: empenhos não atribuídos"
        else:
            base, rotulo = [], "Sem empenhos no exercício"
        reg["vinculo_pagamentos"] = rotulo
        if base:
            reg["valor_pago"] = round(sum(x["valor_pago"] or 0 for x in base), 2)
            if reg.get("valor") is not None:
                reg["saldo"] = round(reg["valor"] - reg["valor_pago"], 2)
            # "Abrir empenho": o empenho mais recente atribuído a este contrato
            reg["link_empenho"] = base[0]["link"]
        else:
            reg["valor_pago"] = 0.0 if not emp else None
            reg["saldo"] = reg.get("valor") if not emp else None
