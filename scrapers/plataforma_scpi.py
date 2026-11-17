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


def exportar_contratos_json(sessao: requests.Session, url: str, ano: int) -> list[dict]:
    raiz = _raiz_transparencia(url)
    r = sessao.get(f"{raiz}/Default.aspx", timeout=TIMEOUT_EXPORT)
    r.raise_for_status()
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
    regs = []
    for it in itens:
        try:
            if int(it.get("ANO") or ano) != int(ano):
                continue
        except (TypeError, ValueError):
            pass
        regs.append(normalizar_scpi(it))
    return regs


# ---------------------------------------------------------------------------
# Pagamentos (SCPI não tem URL por empenho: os pagamentos são trazidos ao painel)
# ---------------------------------------------------------------------------
def exportar_pagamentos_json(sessao: requests.Session, url: str) -> list[dict]:
    """Exporta 'Despesas por Pagamento/Empenho' do exercício já selecionado na sessão."""
    raiz = _raiz_transparencia(url)
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
        base = vinc or emp
        reg["valor_pago"] = round(sum(e["valor_pago"] or 0 for e in base), 2) if base else 0.0
        reg["vinculo_pagamentos"] = ("Histórico cita o contrato/processo" if vinc
                                     else ("Pelo CNPJ da contratada" if emp else "Sem pagamentos no exercício"))
        if reg.get("valor") is not None and base:
            reg["saldo"] = round(reg["valor"] - reg["valor_pago"], 2)


def enriquecer_scpi(sessao: requests.Session, url: str, contratos: list[dict]) -> None:
    if not contratos:
        return
    try:
        vincular_pagamentos(contratos, exportar_pagamentos_json(sessao, url))
    except (requests.RequestException, ValueError):
        pass
