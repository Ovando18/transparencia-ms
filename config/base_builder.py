"""Construção da base de municípios a partir dos arquivos oficiais:

* ``Transparências MS completo.xlsx`` – 79 municípios e URLs dos portais;
* ``REGIÕES 2026.pdf``                 – 18 Regiões de Fiscalização.

O resultado é gravado em ``data/municipios_ms.json`` e consumido por
``config/municipios_ms.py``. Não há dados inventados: o que não for encontrado
nos arquivos é reportado em ``pendencias``.
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.plataformas import detectar_plataforma
from scrapers.keywords import normalizar

RAIZ = Path(__file__).resolve().parent.parent
JSON_PATH = RAIZ / "data" / "municipios_ms.json"

# Lista oficial IBGE dos 79 municípios de MS (nomes canônicos com acentuação)
MUNICIPIOS_MS: list[str] = [
    "Água Clara", "Alcinópolis", "Amambai", "Anastácio", "Anaurilândia", "Angélica",
    "Antônio João", "Aparecida do Taboado", "Aquidauana", "Aral Moreira", "Bandeirantes",
    "Bataguassu", "Batayporã", "Bela Vista", "Bodoquena", "Bonito", "Brasilândia",
    "Caarapó", "Camapuã", "Campo Grande", "Caracol", "Cassilândia", "Chapadão do Sul",
    "Corguinho", "Coronel Sapucaia", "Corumbá", "Costa Rica", "Coxim", "Deodápolis",
    "Dois Irmãos do Buriti", "Douradina", "Dourados", "Eldorado", "Fátima do Sul",
    "Figueirão", "Glória de Dourados", "Guia Lopes da Laguna", "Iguatemi", "Inocência",
    "Itaporã", "Itaquiraí", "Ivinhema", "Japorã", "Jaraguari", "Jardim", "Jateí", "Juti",
    "Ladário", "Laguna Carapã", "Maracaju", "Miranda", "Mundo Novo", "Naviraí", "Nioaque",
    "Nova Alvorada do Sul", "Nova Andradina", "Novo Horizonte do Sul", "Paraíso das Águas",
    "Paranaíba", "Paranhos", "Pedro Gomes", "Ponta Porã", "Porto Murtinho",
    "Ribas do Rio Pardo", "Rio Brilhante", "Rio Negro", "Rio Verde de Mato Grosso",
    "Rochedo", "Santa Rita do Pardo", "São Gabriel do Oeste", "Selvíria", "Sete Quedas",
    "Sidrolândia", "Sonora", "Tacuru", "Taquarussu", "Terenos", "Três Lagoas", "Vicentina",
]
FISCAIS_FIXOS: list[str] = ["Campo Grande", "Dourados", "Paranaíba", "Três Lagoas"]

# Grafias alternativas comuns -> nome canônico
_ALIASES = {
    "bataipora": "Batayporã",
    "rio verde": "Rio Verde de Mato Grosso",
    "rio verde de mt": "Rio Verde de Mato Grosso",
    "sao gabriel": "São Gabriel do Oeste",
    "dois irmaos": "Dois Irmaos do Buriti",
    "taquarusu": "Taquarussu",
    "guia lopes": "Guia Lopes da Laguna",
    "ribas": "Ribas do Rio Pardo",
}

_CANON = {normalizar(m): m for m in MUNICIPIOS_MS}
for _alias, _nome in _ALIASES.items():
    _CANON.setdefault(_alias, _CANON.get(normalizar(_nome), _nome))
# nomes mais longos primeiro (evita "Rio Verde" casar antes de "Rio Verde de Mato Grosso")
_CANON_ORDENADO = sorted(_CANON.items(), key=lambda kv: -len(kv[0]))


def nome_canonico(texto: object) -> str | None:
    t = normalizar(texto)
    t = re.sub(r"^(prefeitura( municipal)?( de| do| da)?|municipio( de| do| da)?)\s+", "", t)
    t = re.sub(r"\s*[-/(]\s*ms\)?$", "", t).strip(" .-")
    if t in _CANON:
        return _CANON[t]
    return None


def encontrar_municipios_em_texto(texto: str) -> list[str]:
    """Localiza (em ordem de aparição) nomes de municípios dentro de um texto livre."""
    t = f" {normalizar(texto)} "
    achados: list[tuple[int, str]] = []
    ocupados: list[tuple[int, int]] = []
    for chave, nome in _CANON_ORDENADO:
        for m in re.finditer(rf"(?<![a-z]){re.escape(chave)}(?![a-z])", t):
            a, b = m.span()
            if any(a < y and b > x for x, y in ocupados):
                continue
            ocupados.append((a, b))
            achados.append((a, nome))
    vistos, saida = set(), []
    for _, nome in sorted(achados):
        if nome not in vistos:
            vistos.add(nome)
            saida.append(nome)
    return saida


# ---------------------------------------------------------------------------
# Planilha
# ---------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


def ler_planilha(fonte: str | Path | bytes) -> dict[str, dict]:
    """Retorna {municipio_canonico: {url, fornecedor_planilha}}."""
    dado = io.BytesIO(fonte) if isinstance(fonte, (bytes, bytearray)) else fonte
    folhas = pd.read_excel(dado, sheet_name=None, header=None, dtype=str)
    resultado: dict[str, dict] = {}
    for _, df in folhas.items():
        df = df.fillna("")
        if df.empty:
            continue
        # coluna de municípios = a que mais casa com nomes canônicos
        cont_mun = {c: df[c].map(lambda v: nome_canonico(v) is not None).sum() for c in df.columns}
        col_mun = max(cont_mun, key=cont_mun.get)
        if cont_mun[col_mun] == 0:
            continue
        cont_url = {c: df[c].str.contains(r"https?://|www\.", case=False, regex=True).sum()
                    for c in df.columns}
        col_url = max(cont_url, key=cont_url.get) if cont_url else None
        # coluna de sistema/fornecedor (opcional)
        padrao_forn = r"betha|fiorilli|scpi|quality|megasoft|cr2|sistema|e-gov|cloud"
        cont_forn = {c: df[c].str.contains(padrao_forn, case=False, regex=True).sum()
                     for c in df.columns if c not in (col_mun, col_url)}
        col_forn = max(cont_forn, key=cont_forn.get) if cont_forn and max(cont_forn.values()) > 0 else None

        for _, row in df.iterrows():
            nome = nome_canonico(row[col_mun])
            if not nome:
                continue
            url = ""
            celulas = [row[col_url]] if col_url is not None else []
            celulas += [row[c] for c in df.columns if c not in (col_url,)]
            for cel in celulas:
                m = _URL_RE.search(str(cel)) or re.search(r"www\.[^\s]+", str(cel), re.I)
                if m:
                    url = m.group(0).rstrip(".,;)")
                    if url.lower().startswith("www."):
                        url = "http://" + url
                    break
            forn = str(row[col_forn]).strip() if col_forn is not None else ""
            if nome not in resultado or (url and not resultado[nome]["url"]):
                resultado[nome] = {"url": url, "fornecedor_planilha": forn}
    return resultado


# ---------------------------------------------------------------------------
# PDF das regiões
# ---------------------------------------------------------------------------
_REGIAO_RE = re.compile(r"regi[aã]o\s*(?:de\s+fiscaliza[cç][aã]o\s*)?(?:n[ºo°.]*\s*)?(\d{1,2})", re.I)


def _texto_pdf(fonte: str | Path | bytes) -> list[str]:
    dado = io.BytesIO(fonte) if isinstance(fonte, (bytes, bytearray)) else fonte
    try:
        import pdfplumber
        with pdfplumber.open(dado) as pdf:
            return [(p.extract_text() or "") for p in pdf.pages]
    except Exception:
        from pypdf import PdfReader
        if isinstance(dado, io.BytesIO):
            dado.seek(0)
        return [(p.extract_text() or "") for p in PdfReader(dado).pages]


def _regioes_por_texto(paginas: list[str]) -> dict[int, list[str]]:
    texto = "\n".join(paginas)
    marcas = [(m.start(), m.end(), int(m.group(1))) for m in _REGIAO_RE.finditer(texto)]
    regioes: dict[int, list[str]] = {}
    for i, (_, fim, num) in enumerate(marcas):
        if not 1 <= num <= 18:
            continue
        trecho = texto[fim: marcas[i + 1][0] if i + 1 < len(marcas) else len(texto)]
        for nome in encontrar_municipios_em_texto(trecho):
            regioes.setdefault(num, [])
            if nome not in regioes[num]:
                regioes[num].append(nome)
    return regioes


_LINHA_REGIAO_RE = re.compile(r"^\s*(?:regi[aã]o\s*)?(\d{1,2})\s*[-–:.)]?\s+(.+?)(?:\s+(\d{1,2}))?\s*$", re.I)


def _regioes_por_linhas(paginas: list[str]) -> dict[int, list[str]]:
    """Layout 'tabela em texto': cada linha = '<nº região> MUN1, MUN2 E MUN3 <qtd>'.
    Linhas sem número que contenham municípios continuam a região anterior."""
    regioes: dict[int, list[str]] = {}
    atual: int | None = None
    for linha in "\n".join(paginas).splitlines():
        m = _LINHA_REGIAO_RE.match(linha)
        if m and 1 <= int(m.group(1)) <= 18 and encontrar_municipios_em_texto(m.group(2)):
            atual = int(m.group(1))
            trecho = m.group(2)
        elif atual is not None:
            trecho = linha
        else:
            continue
        for nome in encontrar_municipios_em_texto(trecho):
            lst = regioes.setdefault(atual, [])
            if nome not in lst:
                lst.append(nome)
    return regioes


def _regioes_por_tabela(fonte: str | Path | bytes) -> dict[int, list[str]]:
    """Para PDFs em formato de tabela (colunas 'Região' / 'Município')."""
    regioes: dict[int, list[str]] = {}
    try:
        import pdfplumber
        dado = io.BytesIO(fonte) if isinstance(fonte, (bytes, bytearray)) else fonte
        with pdfplumber.open(dado) as pdf:
            for pagina in pdf.pages:
                for tabela in pagina.extract_tables() or []:
                    regiao_atual = None
                    # tabela com cabeçalhos de região por coluna
                    cab = tabela[0] if tabela else []
                    cols_reg = {j: int(m.group(1)) for j, c in enumerate(cab)
                                if c and (m := _REGIAO_RE.search(str(c)))}
                    if cols_reg:
                        for linha in tabela[1:]:
                            for j, num in cols_reg.items():
                                if j < len(linha) and linha[j]:
                                    for nome in encontrar_municipios_em_texto(linha[j]):
                                        regioes.setdefault(num, []).append(nome)
                        continue
                    for linha in tabela:
                        txt = " | ".join(str(c) for c in linha if c)
                        m = _REGIAO_RE.search(txt)
                        if m:
                            regiao_atual = int(m.group(1))
                        else:
                            m2 = re.match(r"^\s*(\d{1,2})\s*$", str(linha[0] or ""))
                            if m2:
                                regiao_atual = int(m2.group(1))
                        if regiao_atual and 1 <= regiao_atual <= 18:
                            for nome in encontrar_municipios_em_texto(txt):
                                lst = regioes.setdefault(regiao_atual, [])
                                if nome not in lst:
                                    lst.append(nome)
    except Exception:
        return {}
    return regioes


def ler_regioes_pdf(fonte: str | Path | bytes) -> dict[int, list[str]]:
    if isinstance(fonte, (str, Path)):
        fonte = Path(fonte).read_bytes()
    paginas = _texto_pdf(fonte)
    candidatos = [_regioes_por_linhas(paginas), _regioes_por_texto(paginas), _regioes_por_tabela(fonte)]

    def cobertura(r):
        return len({m for v in r.values() for m in v if m not in FISCAIS_FIXOS})

    escolhido = max(candidatos, key=cobertura)  # em empate, prevalece a leitura por linhas
    # cada município pertence a uma única região (primeira ocorrência) e fixos saem
    vistos: set[str] = set()
    limpo: dict[int, list[str]] = {}
    for num in sorted(escolhido):
        for nome in escolhido[num]:
            if nome in FISCAIS_FIXOS or nome in vistos:
                continue
            vistos.add(nome)
            limpo.setdefault(num, []).append(nome)
    return limpo


# ---------------------------------------------------------------------------
# Montagem e gravação
# ---------------------------------------------------------------------------
def _registro(nome: str, planilha: dict, grupo: str) -> dict:
    info = planilha.get(nome, {})
    url = info.get("url", "")
    forn = info.get("fornecedor_planilha", "")
    return {
        "nome": nome,
        "grupo": grupo,
        "url": url,
        "fornecedor_planilha": forn,
        "plataforma": detectar_plataforma(url, forn),
    }


def construir_base(planilha_fonte, pdf_fonte, nome_planilha="", nome_pdf="") -> dict:
    planilha = ler_planilha(planilha_fonte)
    regioes = ler_regioes_pdf(pdf_fonte)

    base = {
        "oficial": True,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "fontes": {"planilha": nome_planilha, "pdf": nome_pdf},
        "fiscais_fixos": [_registro(n, planilha, "Fiscais Fixos") for n in FISCAIS_FIXOS],
        "regioes": {},
        "nao_mapeados": [],
        "pendencias": [],
    }
    mapeados = set(FISCAIS_FIXOS)
    for num in range(1, 19):
        nomes = regioes.get(num, [])
        rotulo = f"Região {num}"
        base["regioes"][str(num)] = {
            "nome": rotulo,
            "municipios": [_registro(n, planilha, rotulo) for n in nomes],
        }
        mapeados.update(nomes)
        if not nomes:
            base["pendencias"].append(f"{rotulo}: nenhum município localizado no PDF.")

    faltantes = [m for m in MUNICIPIOS_MS if m not in mapeados]
    base["nao_mapeados"] = [_registro(n, planilha, "Sem região") for n in faltantes]
    if faltantes:
        base["pendencias"].append(
            f"{len(faltantes)} município(s) não localizados no PDF de regiões: " + ", ".join(faltantes))
    sem_url = [m for m in MUNICIPIOS_MS if not planilha.get(m, {}).get("url")]
    if sem_url:
        base["pendencias"].append(
            f"{len(sem_url)} município(s) sem URL na planilha: " + ", ".join(sem_url))
    for nome in MUNICIPIOS_MS:
        u = planilha.get(nome, {}).get("url", "").lower()
        if ".leg.br" in u or "camara" in u:
            base["pendencias"].append(f"{nome}: a URL da planilha aponta para a Câmara Municipal, não para a Prefeitura ({u}).")
        elif "e-gov.betha" in u and "mun=" not in u:
            base["pendencias"].append(f"{nome}: URL Betha e-Gov sem o parâmetro '?mun=' (identificação do município).")
    total_reg = sum(len(r["municipios"]) for r in base["regioes"].values())
    base["resumo"] = {
        "fiscais_fixos": len(FISCAIS_FIXOS),
        "municipios_em_regioes": total_reg,
        "com_url": len(MUNICIPIOS_MS) - len(sem_url),
        "total": len(MUNICIPIOS_MS),
    }
    return base


def salvar_base(base: dict, caminho: Path = JSON_PATH) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def localizar_arquivos_fonte(pasta: Path = RAIZ) -> tuple[Path | None, Path | None]:
    xlsx = next((p for p in sorted(pasta.glob("*.xlsx")) if "transpar" in normalizar(p.name)), None)
    pdf = next((p for p in sorted(pasta.glob("*.pdf")) if "regi" in normalizar(p.name)), None)
    return xlsx, pdf
