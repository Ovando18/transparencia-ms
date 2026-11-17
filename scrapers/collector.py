"""Coletor multiplataforma de contratos nos Portais da Transparência municipais de MS.

Fluxo por município:
1. roteia pelo tipo de plataforma (SCPI, Betha Cloud, Betha e-Gov, Quality, ...);
2. tenta os endpoints JSON internos conhecidos da plataforma (``ENDPOINTS_JSON``);
3. se não houver JSON, faz scraping HTML do portal (tabelas de contratos);
4. filtra por exercício e pelo escopo de Engenharia/Agronomia/Geociências;
5. em qualquer falha, NÃO quebra: devolve um diagnóstico (status) e o link
   direto para consulta manual na aba de Contratos do portal.

Os endpoints internos das plataformas não são documentados publicamente e mudam
entre versões; por isso ficam centralizados em ``ENDPOINTS_JSON`` para ajuste.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.plataformas import (
    BETHA_CLOUD, BETHA_EGOV, CR2, MEGASOFT, QUALITY, SCPI,
    _raiz_transparencia, link_contratos, link_despesas,
)
from scrapers.keywords import classificar_objeto
from scrapers.plataforma_quality import QualityIndisponivel, coletar_quality
from scrapers.plataforma_scpi import coletar_scpi
from scrapers.parsers import (
    extrair_lista_json, links_para_contratos, normalizar_registro, tabelas_de_contratos,
)

try:  # cache do Streamlit quando disponível; no-op em scripts/testes
    import streamlit as st

    _cache = st.cache_data(ttl=60 * 60 * 6, show_spinner=False, max_entries=500)
except Exception:  # pragma: no cover
    def _cache(fn):
        return fn

# ---------------------------------------------------------------------------
# Status de acesso
# ---------------------------------------------------------------------------
ST_COLETADO = "Online - Coletado"
ST_SEM_ENG = "Online - Sem contratos de engenharia"
ST_TIMEOUT = "Instável / Timeout"
ST_BLOQUEADO = "Bloqueado (SSL / Firewall)"
ST_MANUAL = "Consulta Manual"
ST_SEM_URL = "URL não cadastrada"

TIMEOUT = (6, 20)  # (conexão, leitura) em segundos
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36 FiscalizaObras-MS/1.0")

# Endpoints JSON candidatos por plataforma. Placeholders: {raiz}, {url}, {ano}.
ENDPOINTS_JSON: dict[str, list[str]] = {
    MEGASOFT: [
        "{url}/api/contratos?exercicio={ano}",
    ],
    CR2: [
        "{url}/api/contratos?ano={ano}",
    ],
}

# Plataformas que são SPAs (conteúdo só aparece com JavaScript) e não expõem
# endpoint público estável: viram "Consulta Manual" após a sondagem.
PLATAFORMAS_SPA = {BETHA_CLOUD}


class ConsultaManual(Exception):
    """O portal exige navegação dinâmica/autenticação: consulta manual."""


def _sessao(verificar_ssl: bool = True) -> requests.Session:
    s = requests.Session()
    # sem obedecer "Retry-After" (alguns portais pedem minutos de espera e travariam a pesquisa)
    retry = Retry(total=1, read=0, backoff_factor=0.8, status_forcelist=(502, 504),
                  allowed_methods=("GET",), respect_retry_after_header=False)
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": USER_AGENT,
                      "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                      "Accept-Language": "pt-BR,pt;q=0.9"})
    s.verify = verificar_ssl
    if not verificar_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return s


def _get(sessao: requests.Session, url: str) -> requests.Response:
    r = sessao.get(url, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r


def _tentar_json(sessao, modelos: Iterable[str], url: str, ano: int) -> list[dict] | None:
    raiz = _raiz_transparencia(url)
    for modelo in modelos:
        alvo = modelo.format(raiz=raiz, url=url.rstrip("/"), ano=ano)
        try:
            r = _get(sessao, alvo)
        except requests.HTTPError:
            continue
        ctype = r.headers.get("Content-Type", "")
        if "json" not in ctype and not r.text.lstrip().startswith(("[", "{")):
            continue
        try:
            lista = extrair_lista_json(r.json())
        except ValueError:
            continue
        if lista:
            return [normalizar_registro(item, alvo) for item in lista]
    return None


def _tentar_html(sessao, url: str, ano: int) -> list[dict] | None:
    r = _get(sessao, url)
    regs = tabelas_de_contratos(r.text, r.url)
    if regs:
        return regs
    for link in links_para_contratos(r.text, r.url):
        for alvo in (link, f"{link}{'&' if '?' in link else '?'}ano={ano}"):
            try:
                r2 = _get(sessao, alvo)
            except requests.RequestException:
                continue
            regs = tabelas_de_contratos(r2.text, r2.url)
            if regs:
                return regs
    return None


def _coletar_bruto(sessao, url: str, plataforma: str, ano: int) -> list[dict]:
    if plataforma == SCPI:
        return coletar_scpi(sessao, url, ano)
    if plataforma == QUALITY:
        return coletar_quality(sessao, url, ano)
    if plataforma in ENDPOINTS_JSON:
        regs = _tentar_json(sessao, ENDPOINTS_JSON[plataforma], url, ano)
        if regs is not None:
            return regs
    if plataforma in PLATAFORMAS_SPA:
        _get(sessao, url)  # confirma que está online
        raise ConsultaManual("Portal em aplicação dinâmica (SPA) — requer navegação no navegador.")
    if plataforma == BETHA_EGOV:
        alvo = link_contratos(url, plataforma) or url
        regs = _tentar_html(sessao, alvo, ano)
    else:
        regs = _tentar_html(sessao, url, ano)
    if regs is None:
        raise ConsultaManual("Portal online, mas a listagem de contratos não está em HTML estático.")
    return regs


def _diagnostico(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ConsultaManual):
        return ST_MANUAL, str(exc)
    if isinstance(exc, QualityIndisponivel):
        return ST_TIMEOUT, f"Quality: {exc}"
    if isinstance(exc, requests.exceptions.SSLError):
        return ST_BLOQUEADO, "Certificado SSL inválido ou recusado."
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectTimeout)):
        return ST_TIMEOUT, "Tempo de resposta esgotado."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return ST_TIMEOUT, "Falha de conexão (portal fora do ar ou instável)."
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else "?"
        if code in (401, 403, 406, 451):
            return ST_BLOQUEADO, f"Acesso negado pelo servidor (HTTP {code})."
        return ST_TIMEOUT, f"Erro HTTP {code}."
    return ST_MANUAL, f"Erro inesperado: {type(exc).__name__}: {exc}"[:300]


@_cache
def coletar_municipio(nome: str, grupo: str, url: str, plataforma: str, ano: int,
                      verificar_ssl: bool = True) -> dict:
    """Coleta (com cache) os contratos de engenharia de um município."""
    inicio = time.time()
    lk_contratos = link_contratos(url, plataforma)
    lk_despesas = link_despesas(url, plataforma)
    resultado = {
        "municipio": nome, "grupo": grupo, "url": url, "plataforma": plataforma,
        "link_manual": lk_contratos or url, "link_despesas": lk_despesas or url,
        "status": ST_COLETADO, "detalhe": "", "total_bruto": 0, "contratos": [], "tempo_s": 0.0,
    }
    if not url:
        resultado.update(status=ST_SEM_URL, detalhe="Município sem URL na planilha oficial.")
        return resultado
    try:
        sessao = _sessao(verificar_ssl)
        brutos = _coletar_bruto(sessao, url, plataforma, ano)
        resultado["total_bruto"] = len(brutos)
        contratos = []
        for reg in brutos:
            d = reg.get("data_assinatura") or reg.get("vigencia_inicio")
            if not reg.get("ano_contrato") and d and d.year != int(ano):
                continue
            eh_eng, areas, termos = classificar_objeto(reg.get("objeto"))
            if not eh_eng:
                continue
            reg.update(municipio=nome, grupo=grupo, plataforma=plataforma, portal=url,
                       areas=areas, termos=termos, exercicio=int(ano),
                       link_consulta_contratos=lk_contratos, link_consulta_despesas=lk_despesas)
            contratos.append(reg)
        resultado["contratos"] = contratos
        if not contratos:
            resultado.update(status=ST_SEM_ENG,
                             detalhe=f"{len(brutos)} registro(s) lidos; nenhum de engenharia em {ano}.")
        else:
            resultado["detalhe"] = f"{len(contratos)} de {len(brutos)} registro(s) no escopo técnico."
    except Exception as exc:  # noqa: BLE001 - resiliência total por município
        status, detalhe = _diagnostico(exc)
        resultado.update(status=status, detalhe=detalhe)
    resultado["tempo_s"] = round(time.time() - inicio, 1)
    return resultado


def coletar_varios(municipios: list[dict], ano: int, verificar_ssl: bool = True,
                   max_workers: int = 8,
                   ao_concluir: Callable[[int, int, dict], None] | None = None) -> list[dict]:
    """Coleta em paralelo; ``ao_concluir(feitos, total, resultado)`` atualiza a UI."""
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:  # pragma: no cover
        ctx = None

        def add_script_run_ctx(thread=None, ctx=None):  # type: ignore
            return thread

    def _init():
        if ctx is not None:
            import threading
            add_script_run_ctx(threading.current_thread(), ctx)

    resultados: list[dict] = []
    total = len(municipios)
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, total or 1)), initializer=_init) as ex:
        futuros = {
            ex.submit(coletar_municipio, m["nome"], m.get("grupo", ""), m.get("url", ""),
                      m.get("plataforma", "Outros"), int(ano), verificar_ssl): m
            for m in municipios
        }
        for i, fut in enumerate(as_completed(futuros), start=1):
            m = futuros[fut]
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001
                status, detalhe = _diagnostico(exc)
                res = {"municipio": m["nome"], "grupo": m.get("grupo", ""), "url": m.get("url", ""),
                       "plataforma": m.get("plataforma", ""), "link_manual": m.get("url", ""),
                       "link_despesas": m.get("url", ""), "status": status, "detalhe": detalhe,
                       "total_bruto": 0, "contratos": [], "tempo_s": 0.0}
            resultados.append(res)
            if ao_concluir:
                ao_concluir(i, total, res)
    return resultados


def limpar_cache() -> None:
    clear = getattr(coletar_municipio, "clear", None)
    if callable(clear):
        clear()
