"""Base estruturada de municípios de MS para o FiscalizaObras-MS.

* 4 municípios com Fiscais Fixos (fora das regiões): Campo Grande, Dourados,
  Paranaíba e Três Lagoas;
* 18 Regiões de Fiscalização (75 municípios) conforme ``REGIÕES 2026.pdf``;
* URL oficial de cada Portal da Transparência conforme
  ``Transparências MS completo.xlsx``;
* plataforma do portal detectada pela URL (roteamento do coletor).

Ordem de carregamento:
1. ``data/municipios_ms.json`` (gerado por ``scripts/gerar_base_municipios.py``);
2. se não existir, mas os dois arquivos oficiais estiverem na raiz, gera o JSON;
3. caso contrário, base PROVISÓRIA: 79 municípios, sem regiões e sem URLs
   (nada é inventado) — o painel exibe um aviso para carregar os arquivos.
"""
from __future__ import annotations

import json
from functools import lru_cache

from config.base_builder import (
    FISCAIS_FIXOS,
    JSON_PATH,
    MUNICIPIOS_MS,
    construir_base,
    localizar_arquivos_fonte,
    salvar_base,
)
from config.plataformas import detectar_plataforma, link_contratos, link_despesas

__all__ = [
    "FISCAIS_FIXOS", "MUNICIPIOS_MS", "carregar_base", "recarregar_base",
    "listar_regioes", "municipios_da_regiao", "municipios_fixos", "todos_municipios",
    "info_municipio", "detectar_plataforma", "link_contratos", "link_despesas",
]


def _base_provisoria() -> dict:
    def reg(n, grupo):
        return {"nome": n, "grupo": grupo, "url": "", "fornecedor_planilha": "",
                "plataforma": "Outros"}
    return {
        "oficial": False,
        "gerado_em": None,
        "fontes": {},
        "fiscais_fixos": [reg(n, "Fiscais Fixos") for n in FISCAIS_FIXOS],
        "regioes": {str(i): {"nome": f"Região {i}", "municipios": []} for i in range(1, 19)},
        "nao_mapeados": [reg(n, "Sem região") for n in MUNICIPIOS_MS if n not in FISCAIS_FIXOS],
        "pendencias": [
            "Arquivos oficiais não carregados: coloque 'Transparências MS completo.xlsx' e "
            "'REGIÕES 2026.pdf' na raiz do projeto e execute "
            "'python scripts/gerar_base_municipios.py' (ou use o upload na barra lateral)."
        ],
        "resumo": {"fiscais_fixos": 4, "municipios_em_regioes": 0, "com_url": 0, "total": 79},
    }


@lru_cache(maxsize=1)
def carregar_base() -> dict:
    if JSON_PATH.exists():
        try:
            return json.loads(JSON_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    xlsx, pdf = localizar_arquivos_fonte()
    if xlsx and pdf:
        try:
            base = construir_base(xlsx, pdf, xlsx.name, pdf.name)
            salvar_base(base)
            return base
        except Exception as exc:  # noqa: BLE001 - nunca derrubar o painel
            prov = _base_provisoria()
            prov["pendencias"].insert(0, f"Falha ao processar os arquivos oficiais: {exc}")
            return prov
    return _base_provisoria()


def recarregar_base() -> dict:
    carregar_base.cache_clear()
    return carregar_base()


def listar_regioes() -> list[tuple[str, str, list[str]]]:
    """[(numero, rótulo, [municípios])] em ordem numérica."""
    base = carregar_base()
    out = []
    for num in sorted(base["regioes"], key=int):
        r = base["regioes"][num]
        out.append((num, r["nome"], [m["nome"] for m in r["municipios"]]))
    return out


def municipios_da_regiao(numero: str) -> list[dict]:
    return list(carregar_base()["regioes"].get(str(numero), {}).get("municipios", []))


def municipios_fixos() -> list[dict]:
    return list(carregar_base()["fiscais_fixos"])


def municipios_sem_regiao() -> list[dict]:
    return list(carregar_base().get("nao_mapeados", []))


def todos_municipios() -> list[dict]:
    base = carregar_base()
    lst = list(base["fiscais_fixos"])
    for r in base["regioes"].values():
        lst.extend(r["municipios"])
    lst.extend(base.get("nao_mapeados", []))
    return lst


def info_municipio(nome: str) -> dict | None:
    return next((m for m in todos_municipios() if m["nome"] == nome), None)
