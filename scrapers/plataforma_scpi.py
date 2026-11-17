"""Coletor do Portal da Transparência Fiorilli SCPI (35 municípios de MS).

Funcionamento verificado no portal de Corumbá (SCPI 9.x, ASP.NET + DevExpress):

1. ``GET  {raiz}/Default.aspx``                     -> abre sessão (cookies), exercício atual;
2. ``POST {raiz}/Default.aspx`` (opcional)          -> troca o exercício
   (``cmbExercicio_VI`` + ``btnCallBackTrocaEntExercicio``);
3. ``GET  {raiz}/InformacoesContratos.aspx``         -> página da grade de contratos;
4. ``POST {raiz}/InformacoesContratos.aspx``         -> clique no botão-imagem
   "Exportar JSON" (``ASPxPageControl1$btnExportarJSON.x/.y``), que devolve TODOS os
   contratos do exercício em JSON.

Campos do JSON: CODIGO, ANO, FORNECEDOR, INSMF (CNPJ), VALCON, VIGENI, VENCIMENTO_ATUAL,
OBJETO_COMPLETO, LICIT, PROCLIC, RESPON, CONTRATONUM...
"""
from __future__ import annotations

import json
import re

import requests
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup

from config.plataformas import _raiz_transparencia
from scrapers.parsers import finalizar, parse_data

TIMEOUT_EXPORT = (8, 120)


def _campos_form(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    return {i.get("name"): i.get("value", "")
            for i in soup.select("form input[name]")
            if i.get("type") not in ("submit", "image", "button", "checkbox")}


def _exercicio_atual(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    el = soup.find(id="cmbExercicio_VI") or soup.find(id="lblExercicio")
    return el.get("value") if el else None


def raizes_candidatas(url: str) -> list[str]:
    """A URL da planilha e variações usadas pelo Fiorilli SCPI (HTTP e porta 8079).

    Ex.: https://pmchapadao.rcmsuporte.com.br/transparencia/ falha no HTTPS (nome não
    reconhecido no certificado), enquanto os demais portais da mesma hospedagem
    respondem em http://<host>:8079/transparencia."""
    raiz = _raiz_transparencia(url)
    p = urlparse(raiz)
    host, caminho = p.hostname or "", p.path or "/transparencia"
    cands = [raiz]
    if p.scheme == "https":
        cands.append(urlunparse(("http", p.netloc, caminho, "", "", "")))
    if p.port != 8079:
        cands += [f"http://{host}:8079{caminho}", f"https://{host}:8079{caminho}"]
    vistos, saida = set(), []
    for c in cands:
        if c not in vistos:
            vistos.add(c)
            saida.append(c)
    return saida


class PortalSemResposta(Exception):
    """Nenhum endereço do portal respondeu; a mensagem traz o erro de cada tentativa."""


def _motivo(exc: Exception) -> str:
    txt = str(exc)
    if isinstance(exc, requests.exceptions.SSLError):
        return "erro de SSL/certificado"
    if isinstance(exc, requests.exceptions.Timeout):
        return "tempo esgotado"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    if "Name or service not known" in txt or "NameResolution" in txt or "getaddrinfo" in txt:
        return "endereço inexistente (DNS)"
    if "refused" in txt.lower():
        return "conexão recusada"
    if "reset" in txt.lower() or "aborted" in txt.lower():
        return "conexão derrubada pelo servidor"
    return "sem resposta"


def abrir_sessao_scpi(sessao: requests.Session, url: str) -> tuple[str, requests.Response]:
    """Abre o portal na primeira raiz que responder; guarda-a em ``sessao.scpi_raiz``."""
    tentativas: list[str] = []
    for i, raiz in enumerate(raizes_candidatas(url)):
        try:
            r = sessao.get(f"{raiz}/Default.aspx", timeout=TIMEOUT_EXPORT if i == 0 else (6, 40))
            r.raise_for_status()
            sessao.scpi_raiz = raiz
            return raiz, r
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, requests.HTTPError) as exc:
            tentativas.append(f"{raiz} → {_motivo(exc)}")
    raise PortalSemResposta("Nenhum endereço respondeu. Tentativas: " + "; ".join(tentativas))


def exportar_contratos_json(sessao: requests.Session, url: str, ano: int) -> list[dict]:
    raiz, r = abrir_sessao_scpi(sessao, url)
    if _exercicio_atual(r.text) != str(ano):
        form = _campos_form(r.text)
        form.update({"cmbExercicio_VI": str(ano), "cmbExercicio": str(ano), "lblExercicio": str(ano),
                     "btnCallBackTrocaEntExercicio": "TrocarEntidadeExercicio"})
        r = sessao.post(f"{raiz}/Default.aspx", data=form, timeout=TIMEOUT_EXPORT)
        r.raise_for_status()

    r = sessao.get(f"{raiz}/InformacoesContratos.aspx", timeout=TIMEOUT_EXPORT)
    r.raise_for_status()
    form = _campos_form(r.text)
    if "ASPxPageControl1$btnExportarJSON" not in r.text:
        raise ValueError("Página de contratos do SCPI sem o botão de exportação JSON.")
    form["ASPxPageControl1$btnExportarJSON.x"] = "8"
    form["ASPxPageControl1$btnExportarJSON.y"] = "8"
    r = sessao.post(f"{raiz}/InformacoesContratos.aspx", data=form, timeout=TIMEOUT_EXPORT)
    r.raise_for_status()
    if "json" not in r.headers.get("Content-Type", ""):
        raise ValueError("SCPI não devolveu JSON na exportação de contratos.")
    dados = json.loads(r.content.decode("utf-8-sig"))
    return dados if isinstance(dados, list) else []


def normalizar_scpi(item: dict) -> dict:
    def g(*chaves):
        for c in chaves:
            if item.get(c) not in (None, ""):
                return item[c]
        return None

    reg = {
        "numero": g("CODIGO", "CONTRATONUM"),
        "ano_contrato": g("ANO"),
        "data_assinatura": g("DATAASSINATURA", "DTASSINATURA", "DATA_ASSINATURA", "VIGENI"),
        "fornecedor": g("FORNECEDOR"),
        "cnpj": g("INSMF", "CNPJ"),
        "objeto": g("OBJETO_COMPLETO", "OBJETO"),
        "valor": g("VALCON", "VALOR"),
        "vigencia_inicio": g("VIGENI"),
        "vigencia_fim": g("VENCIMENTO_ATUAL", "VIGENF", "VENCIMENTO"),
        "modalidade": g("LICIT", "FUNDLEGAL"),
        "processo": g("PROCLIC"),
        "fiscal_gestor": g("RESPON"),
        "link_contrato": None, "link_os": None, "link_empenho": None, "empenhos": [],
    }
    reg = finalizar(reg)
    reg["data_assinatura"] = parse_data(reg["data_assinatura"]) if reg["data_assinatura"] else None
    return reg


def coletar_scpi(sessao: requests.Session, url: str, ano: int) -> list[dict]:
    """Contratos CELEBRADOS no exercício (campo ANO == ano)."""
    itens = exportar_contratos_json(sessao, url, ano)
    # quantos contratos (do ano e anteriores ainda listados) cada CNPJ tem com o município
    por_cnpj: dict[str, int] = {}
    for it in itens:
        d = _digitos(it.get("INSMF"))
        por_cnpj[d] = por_cnpj.get(d, 0) + 1
    regs = []
    for it in itens:
        try:
            if int(it.get("ANO") or ano) != int(ano):
                continue
        except (TypeError, ValueError):
            pass
        reg = normalizar_scpi(it)
        reg["contratos_mesmo_cnpj"] = por_cnpj.get(_digitos(it.get("INSMF")), 1)
        regs.append(reg)
    return regs


# ---------------------------------------------------------------------------
# Pagamentos (SCPI não tem URL por empenho: os pagamentos são trazidos ao painel)
# ---------------------------------------------------------------------------
def exportar_pagamentos_json(sessao: requests.Session, url: str) -> list[dict]:
    """Exporta 'Despesas por Pagamento/Empenho' do exercício já selecionado na sessão."""
    raiz = getattr(sessao, "scpi_raiz", None) or _raiz_transparencia(url)
    r = sessao.get(f"{raiz}/DespesasPorPagamentoEmpenho.aspx", timeout=TIMEOUT_EXPORT)
    r.raise_for_status()
    if "btnExportarJSON" not in r.text:
        return []
    form = _campos_form(r.text)
    form["btnExportarJSON.x"] = "8"
    form["btnExportarJSON.y"] = "8"
    r = sessao.post(f"{raiz}/DespesasPorPagamentoEmpenho.aspx", data=form, timeout=TIMEOUT_EXPORT)
    r.raise_for_status()
    if "json" not in r.headers.get("Content-Type", ""):
        return []
    dados = json.loads(r.content.decode("utf-8-sig"))
    return dados if isinstance(dados, list) else []


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _padroes_vinculo(reg: dict) -> list[re.Pattern]:
    pads = []
    for campo, rotulo in (("numero", r"contrato"), ("processo", r"(?:licita\w*|processo)")):
        m = re.match(r"^\s*0*(\d+)\s*/\s*(\d{2,4})\s*$", str(reg.get(campo) or ""))
        if m:
            num, ano = m.group(1), m.group(2)[-2:]
            pads.append(re.compile(rf"{rotulo}[^0-9]{{0,25}}0*{num}\s*/\s*(?:20)?{ano}\b", re.I))
    return pads


def vincular_pagamentos(contratos: list[dict], pagamentos: list[dict]) -> None:
    por_cnpj: dict[str, list[dict]] = {}
    for p in pagamentos:
        por_cnpj.setdefault(_digitos(p.get("CPFCNPJ")), []).append(p)
    for reg in contratos:
        lista = por_cnpj.get(_digitos(reg.get("cnpj")), [])
        inicio = reg.get("vigencia_inicio") or reg.get("data_assinatura")
        pads = _padroes_vinculo(reg)
        emp = []
        for p in lista:
            d = parse_data(p.get("DTLAN"))
            if inicio and d and d < inicio:
                continue
            hist = str(p.get("PRODU") or "")
            emp.append({
                "numero": None,
                "data": d,
                "valor_pago": p.get("VALOR"),
                "ordem_pagamento": p.get("ORDPG"),
                "nota_fiscal": p.get("NOTA_FISCAL"),
                "historico": hist,
                "vinculo": ("Vinculado ao contrato" if any(x.search(hist) for x in pads)
                            else "Pagamento ao fornecedor (CNPJ)"),
            })
        emp.sort(key=lambda e: e["data"] or parse_data("01/01/1900"), reverse=True)
        reg["empenhos"] = emp
        vinc = [e for e in emp if e["vinculo"] == "Vinculado ao contrato"]
        n_ctr = int(reg.get("contratos_mesmo_cnpj") or 1)
        reg["pago_ao_fornecedor"] = round(sum(e["valor_pago"] or 0 for e in emp), 2)
        if vinc:
            base, rotulo = vinc, "Histórico cita o contrato/processo"
        elif emp and n_ctr <= 1:
            base, rotulo = emp, "Pelo CNPJ (único contrato da empresa)"
        elif emp:
            base, rotulo = [], f"Empresa com {n_ctr} contratos: pagamentos não atribuídos"
        else:
            base, rotulo = [], "Sem pagamentos no exercício"
        reg["vinculo_pagamentos"] = rotulo
        if base:
            reg["valor_pago"] = round(sum(e["valor_pago"] or 0 for e in base), 2)
            if reg.get("valor") is not None:
                reg["saldo"] = round(reg["valor"] - reg["valor_pago"], 2)
        else:
            reg["valor_pago"] = 0.0 if not emp else None
            reg["saldo"] = reg.get("valor") if not emp else None


def enriquecer_scpi(sessao: requests.Session, url: str, contratos: list[dict]) -> None:
    if not contratos:
        return
    try:
        vincular_pagamentos(contratos, exportar_pagamentos_json(sessao, url))
    except (requests.RequestException, ValueError):
        pass
