"""Coletor do Portal da Transparência Quality Sistemas (web.qualitysistemas.com.br).

Funcionamento verificado (Terenos, Rochedo, Bandeirantes):

* o portal é uma SPA React que consome ``/api/v1/...``;
* a API exige o cookie ``qs_portal``, obtido com ``GET /index.html``;
* ``GET /api/v1/contratos/{entidade}/{ano}?mes=0`` devolve todos os registros do ano
  (contratos principais, aditivos e apostilamentos);
* link público de cada contrato: ``/contratos/{entidade}/contrato/{nº}_{ano}_{codEntidade}``.

``{entidade}`` é o último segmento da URL do portal (ex.: ``prefeitura_municipal_de_terenos``).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from scrapers.parsers import finalizar

HOST = "https://web.qualitysistemas.com.br"
TIMEOUT = (8, 40)  # a API consulta o servidor da prefeitura em tempo real; pode travar


class QualityIndisponivel(Exception):
    """A Quality informou que os dados da entidade estão indisponíveis no momento."""


def entidade_da_url(url: str) -> str:
    partes = [p for p in urlparse(url).path.split("/") if p]
    return partes[-1] if partes else ""


def link_contrato(entidade: str, numero: str, entidade_codigo: str | None) -> str | None:
    m = re.match(r"^\s*(\d+)\s*/\s*(\d{4})\s*$", str(numero or ""))
    if not m or not entidade_codigo:
        return None
    return f"{HOST}/contratos/{entidade}/contrato/{m.group(1)}_{m.group(2)}_{entidade_codigo}"


def link_lista(url: str, ano: int) -> str:
    return f"{HOST}/contratos/{entidade_da_url(url)}/{ano}"


def coletar_quality(sessao: requests.Session, url: str, ano: int) -> list[dict]:
    entidade = entidade_da_url(url)
    sessao.get(f"{HOST}/index.html", timeout=TIMEOUT, headers={"Cache-Control": "no-store"})
    r = sessao.get(f"{HOST}/api/v1/contratos/{entidade}/{ano}", params={"mes": 0},
                   timeout=TIMEOUT, headers={"Accept": "application/json"})
    if r.status_code == 503:
        raise QualityIndisponivel(r.json().get("message", "Dados indisponíveis no momento."))
    r.raise_for_status()
    dados = r.json()
    regs = []
    for c in dados.get("contratos", []):
        if "principal" not in str(c.get("tipo", "")).lower():
            continue  # aditivos/apostilamentos ficam de fora
        numero = str(c.get("contrato") or "")
        ano_num = numero.split("/")[-1].strip() if "/" in numero else ""
        if ano_num.isdigit() and int(ano_num) != int(ano):
            continue
        vig = str(c.get("vigencia") or "")
        datas = re.findall(r"\d{2}/\d{2}/\d{4}", vig)
        reg = {
            "numero": numero,
            "ano_contrato": int(ano_num) if ano_num.isdigit() else int(ano),
            "data_assinatura": datas[0] if datas else None,
            "fornecedor": c.get("fornecedor"),
            "cnpj": c.get("cpfCnpj"),
            "objeto": c.get("objeto") or c.get("assunto"),
            "valor": c.get("valor"),
            "vigencia_inicio": datas[0] if datas else None,
            "vigencia_fim": datas[-1] if len(datas) > 1 else None,
            "processo": c.get("processo"),
            "fiscal_gestor": ", ".join(f.get("nome", "") for f in c.get("fiscais") or []),
            "link_contrato": link_contrato(entidade, numero, c.get("entidadeCodigo")),
            "link_os": None, "link_empenho": None, "empenhos": [],
        }
        regs.append(finalizar(reg))
    return regs


def detalhar_contrato_quality(sessao: requests.Session, url: str, reg: dict) -> dict:
    """Completa um contrato com PDF, empenhos/pagamentos, saldo e fiscais (CREA/ART)."""
    entidade = entidade_da_url(url)
    chave = (reg.get("link_contrato") or "").rsplit("/", 1)[-1]
    if not chave:
        return reg
    r = sessao.get(f"{HOST}/api/v1/contratos/{entidade}/contrato/{chave}", timeout=TIMEOUT,
                   headers={"Accept": "application/json"})
    if not r.ok:
        return reg
    d = r.json()
    pagina = reg.get("link_contrato")
    arq = d.get("arquivo") or {}
    if arq.get("disponivel") and arq.get("downloadUrl"):
        reg["link_contrato"] = arq["downloadUrl"]           # PDF do contrato
    reg["link_empenho"] = pagina                              # página do contrato (aba de empenhos)
    reg["link_pagina_contrato"] = pagina
    reg["valor_atualizado"] = d.get("valorAtualizado")
    reg["valor_pago"] = d.get("totalEmpenho")          # "Total pago" no portal
    reg["saldo_empenhado_a_pagar"] = d.get("saldoAPagar")
    base = d.get("valorAtualizado") or reg.get("valor")
    if base is not None and reg["valor_pago"] is not None:
        reg["saldo"] = round(float(base) - float(reg["valor_pago"]), 2)  # saldo contratual
    fiscais = d.get("fiscais") or []
    if fiscais:
        reg["fiscal_gestor"] = "; ".join(
            f"{f.get('nome', '')} ({f.get('tipo', '')})".replace(" ()", "") for f in fiscais)
        reg["fiscal_crea_art"] = "; ".join(
            f"{f.get('nome', '')}: CREA {f.get('crea') or '—'} / ART {f.get('art') or '—'}" for f in fiscais)
    reg["empenhos"] = [{
        "numero": e.get("empenho"),
        "data": e.get("data"),
        "valor_pago": e.get("valor"),
        "liquidacao": e.get("liquidacao"),
        "ordem_pagamento": e.get("op"),
        "historico": e.get("historico"),
        "vinculo": "Vinculado ao contrato",
    } for e in d.get("empenhos") or []]
    reg["vinculo_pagamentos"] = "Portal (por contrato)"
    return reg


def enriquecer_quality(sessao: requests.Session, url: str, contratos: list[dict]) -> None:
    for reg in contratos:
        try:
            detalhar_contrato_quality(sessao, url, reg)
        except (requests.RequestException, ValueError):
            continue
