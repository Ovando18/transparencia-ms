"""Detecção do fornecedor/plataforma do Portal da Transparência pela URL e
montagem de links diretos para as abas de Contratos / Despesas (Empenhos)."""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

SCPI = "SCPI"
BETHA_CLOUD = "Betha Cloud"
BETHA_EGOV = "Betha e-Gov"
QUALITY = "Quality"
MEGASOFT = "Megasoft"
CR2 = "CR2"
OUTROS = "Outros"

PLATAFORMAS = [SCPI, BETHA_CLOUD, BETHA_EGOV, QUALITY, MEGASOFT, CR2, OUTROS]

# (regex sobre a URL em minúsculas, plataforma) – a primeira que casar vence
_REGRAS_URL: list[tuple[str, str]] = [
    (r"betha\.cloud", BETHA_CLOUD),
    (r"e-gov\.betha|egov\.betha|betha\.com\.br", BETHA_EGOV),
    (r"fiorilli|scpi|rcmsuporte", SCPI),
    # Fiorilli SCPI em servidor próprio: http://<ip-ou-host>:<porta>/transparencia/
    (r"^https?://[^/]+:\d{2,5}/transparencia", SCPI),
    (r"quality", QUALITY),
    (r"megasoft", MEGASOFT),
    (r"cr2", CR2),
]

# Pistas textuais na coluna "sistema/fornecedor" da planilha
_REGRAS_TEXTO: list[tuple[str, str]] = [
    (r"betha.*cloud|cloud.*betha", BETHA_CLOUD),
    (r"e-?gov", BETHA_EGOV),
    (r"betha", BETHA_EGOV),
    (r"fiorilli|scpi", SCPI),
    (r"quality", QUALITY),
    (r"megasoft", MEGASOFT),
    (r"cr2", CR2),
]


def detectar_plataforma(url: str | None, fornecedor_planilha: str | None = None) -> str:
    u = (url or "").strip().lower()
    for padrao, plat in _REGRAS_URL:
        if u and re.search(padrao, u):
            return plat
    f = (fornecedor_planilha or "").strip().lower()
    for padrao, plat in _REGRAS_TEXTO:
        if f and re.search(padrao, f):
            return plat
    return OUTROS


def _raiz_transparencia(url: str) -> str:
    """Para SCPI: http://host:porta/transparencia (sem barra final)."""
    p = urlparse(url)
    path = p.path or "/"
    m = re.search(r"(?i)^(.*?/transparencia)", path)
    base_path = m.group(1) if m else "/transparencia"
    return urlunparse((p.scheme or "http", p.netloc, base_path, "", "", "")).rstrip("/")


def link_contratos(url: str | None, plataforma: str) -> str | None:
    """Link direcionado para a área de Contratos/Licitações do portal."""
    if not url:
        return None
    if plataforma == SCPI:
        return _raiz_transparencia(url) + "/?AcessoIndividual=lnkContratos"
    if plataforma == BETHA_EGOV and ".faces" in url:
        return re.sub(r"[^/]+\.faces", "con_contratos.faces", url, count=1)
    # Betha Cloud (SPA com hash), Quality, Megasoft, CR2 e demais: portal raiz
    return url


def link_despesas(url: str | None, plataforma: str) -> str | None:
    """Link direcionado para Empenhos/Pagamentos do portal."""
    if not url:
        return None
    if plataforma == SCPI:
        return _raiz_transparencia(url) + "/?AcessoIndividual=lnkDespesasPorEmpenho"
    if plataforma == BETHA_EGOV and ".faces" in url:
        return re.sub(r"[^/]+\.faces", "con_empenhos.faces", url, count=1)
    return url
