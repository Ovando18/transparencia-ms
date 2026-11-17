"""Identidade visual institucional (paleta oficial de Mato Grosso do Sul)."""
from __future__ import annotations

import html

AZUL = "#004B87"
VERDE = "#007A33"
AMARELO = "#F2A900"
FUNDO = "#F4F6F9"
CARD = "#FFFFFF"
BORDA = "#DCE3EC"
TEXTO = "#1F2A37"
TEXTO_SUAVE = "#5A6B7D"

CSS = f"""
<style>
  .stApp {{ background: {FUNDO}; }}
  .block-container {{ padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1600px; }}
  h1, h2, h3, h4 {{ color: {AZUL}; letter-spacing: -0.01em; }}

  /* Cabeçalho institucional */
  .fo-header {{
    background: {CARD}; border: 1px solid {BORDA}; border-radius: 12px;
    border-top: 5px solid {AZUL}; padding: 1.1rem 1.4rem; margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(16, 42, 67, .06);
    display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  }}
  .fo-header h1 {{ margin: 0; font-size: 1.75rem; font-weight: 750; color: {AZUL}; }}
  .fo-header p {{ margin: .2rem 0 0; color: {TEXTO_SUAVE}; font-size: .95rem; }}
  .fo-faixa {{ display: flex; height: 6px; width: 120px; border-radius: 3px; overflow: hidden; }}
  .fo-faixa span:nth-child(1) {{ flex: 2; background: {AZUL}; }}
  .fo-faixa span:nth-child(2) {{ flex: 1; background: {AMARELO}; }}
  .fo-faixa span:nth-child(3) {{ flex: 2; background: {VERDE}; }}

  /* KPIs */
  .fo-kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .8rem; margin-bottom: 1rem; }}
  @media (max-width: 900px) {{ .fo-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
  .fo-kpi {{
    background: {CARD}; border: 1px solid {BORDA}; border-radius: 10px; padding: .85rem 1rem;
    box-shadow: 0 1px 2px rgba(16, 42, 67, .05); border-left: 4px solid {AZUL};
  }}
  .fo-kpi.verde {{ border-left-color: {VERDE}; }}
  .fo-kpi.amarelo {{ border-left-color: {AMARELO}; }}
  .fo-kpi .rotulo {{ color: {TEXTO_SUAVE}; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }}
  .fo-kpi .valor {{ color: {TEXTO}; font-size: 1.55rem; font-weight: 700; margin-top: .15rem;
                    font-variant-numeric: tabular-nums; }}
  .fo-kpi .nota {{ color: {TEXTO_SUAVE}; font-size: .78rem; }}

  /* Cards e badges */
  .fo-card {{ background: {CARD}; border: 1px solid {BORDA}; border-radius: 10px; padding: 1rem 1.2rem;
              box-shadow: 0 1px 2px rgba(16, 42, 67, .05); margin-bottom: .8rem; }}
  .fo-card h4 {{ margin: 0 0 .5rem; font-size: 1rem; }}
  .fo-card .campo {{ color: {TEXTO_SUAVE}; font-size: .78rem; text-transform: uppercase; letter-spacing: .03em; }}
  .fo-card .dado {{ color: {TEXTO}; font-size: .95rem; margin-bottom: .5rem; }}
  .fo-badge {{ display: inline-block; padding: .12rem .55rem; border-radius: 999px; font-size: .75rem;
               font-weight: 600; margin-right: .3rem; border: 1px solid transparent; }}
  .fo-badge.ok {{ background: #E8F3EC; color: {VERDE}; border-color: #BFDCCB; }}
  .fo-badge.alerta {{ background: #FEF6E0; color: #8A6100; border-color: #F5DC9A; }}
  .fo-badge.info {{ background: #E6EEF6; color: {AZUL}; border-color: #C3D4E6; }}
  .fo-aviso {{ background: #FEF6E0; border: 1px solid #F5DC9A; border-left: 4px solid {AMARELO};
               border-radius: 8px; padding: .7rem 1rem; color: #5C4300; font-size: .9rem; margin-bottom: 1rem; }}

  /* Sidebar */
  section[data-testid="stSidebar"] {{ background: {CARD}; border-right: 1px solid {BORDA}; }}
  section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{ color: {AZUL}; }}
  .fo-side-titulo {{ font-weight: 700; color: {AZUL}; font-size: 1.05rem; margin-bottom: .2rem; }}
  .fo-side-sub {{ color: {TEXTO_SUAVE}; font-size: .8rem; margin-bottom: .6rem; }}

  /* Botões */
  .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
    background: {AZUL}; border-color: {AZUL}; font-weight: 600;
  }}
  .stButton > button[kind="primary"]:hover {{ background: #003A6B; border-color: #003A6B; }}
  .stLinkButton a {{ font-weight: 600; }}

  /* Abas */
  .stTabs [data-baseweb="tab-list"] {{ gap: .3rem; border-bottom: 1px solid {BORDA}; }}
  .stTabs [aria-selected="true"] {{ color: {AZUL} !important; }}
  div[data-testid="stDataFrame"] {{ border: 1px solid {BORDA}; border-radius: 8px; }}
</style>
"""


def cabecalho(titulo: str, subtitulo: str) -> str:
    return (f'<div class="fo-header"><div><h1>{html.escape(titulo)}</h1>'
            f'<p>{html.escape(subtitulo)}</p></div>'
            f'<div class="fo-faixa"><span></span><span></span><span></span></div></div>')


def kpis(itens: list[tuple[str, str, str, str]]) -> str:
    """itens = [(rótulo, valor, nota, cor)] com cor em {'', 'verde', 'amarelo'}."""
    cards = "".join(
        f'<div class="fo-kpi {cor}"><div class="rotulo">{html.escape(r)}</div>'
        f'<div class="valor">{html.escape(v)}</div><div class="nota">{html.escape(n)}</div></div>'
        for r, v, n, cor in itens)
    return f'<div class="fo-kpis">{cards}</div>'


def badge(texto: str, tipo: str = "info") -> str:
    return f'<span class="fo-badge {tipo}">{html.escape(texto)}</span>'
