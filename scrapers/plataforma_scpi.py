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
