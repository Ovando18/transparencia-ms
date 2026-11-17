"""Normalização de registros de contratos vindos de APIs JSON e de tabelas HTML.

Cada plataforma usa nomes de campos diferentes; aqui eles são mapeados por
heurística para o esquema único do painel (ver ``CAMPOS``).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.keywords import normalizar

CAMPOS = [
    "numero", "data_assinatura", "fornecedor", "cnpj", "objeto", "valor",
    "vigencia_inicio", "vigencia_fim", "link_contrato", "link_os", "link_empenho",
    "empenhos",
]

# campo -> padrões (sobre a chave normalizada); a ordem indica prioridade
_PADROES_CHAVE: dict[str, list[str]] = {
    "numero": [r"^(n|nr|num|numero)?\s*_?\s*contrato$", r"numero.*contrato", r"contrato.*(numero|nr|n)$",
               r"^numero$", r"^n[ºo°]?$", r"^nr$", r"^contrato$", r"numerocontrato", r"^codigo$"],
    "objeto": [r"objeto", r"ementa", r"historico", r"descricao", r"finalidade", r"especificacao"],
    "fornecedor": [r"fornecedor", r"contratad[oa]", r"credor", r"razao\s*social", r"empresa",
                   r"favorecido", r"beneficiario", r"^nome$"],
    "cnpj": [r"cnpj", r"cpf", r"documento", r"inscricao"],
    "valor": [r"valor\s*(global|total|contratado|do contrato|inicial)?$", r"^valor", r"vl_?total",
              r"montante", r"valor"],
    "data_assinatura": [r"assinatura", r"data\s*(do)?\s*contrato", r"dt_?contrato", r"celebra",
                        r"^data$", r"emissao", r"^dt"],
    "vigencia_inicio": [r"inicio\s*(da)?\s*vigencia", r"vigencia\s*inicio", r"dt_?inicio", r"^inicio"],
    "vigencia_fim": [r"(fim|termino|final)\s*(da)?\s*vigencia", r"vigencia\s*(fim|final|termino)",
                     r"dt_?(fim|termino|vencimento)", r"vencimento", r"^vigencia$", r"^fim", r"termino"],
}

_CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_CPF_MASC_RE = re.compile(r"\b\*{3}\.?\d{3}\.?\d{3}-?\*{2}\b|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")


# ---------------------------------------------------------------------------
# Conversores
# ---------------------------------------------------------------------------
def parse_valor(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s or s in {"-", ".", ","}:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_data(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    m = re.search(r"/Date\((\-?\d+)", s)  # formato .NET
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000).date()
    if re.fullmatch(r"\d{12,13}", s):  # epoch em ms
        return datetime.fromtimestamp(int(s) / 1000).date()
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
    if m:
        d, mth, y = map(int, m.groups())
        try:
            return date(y, mth, d)
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(*map(int, m.groups()))
        except ValueError:
            return None
    return None


def formatar_cnpj(s) -> str:
    d = re.sub(r"\D", "", str(s or ""))
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return str(s or "").strip()


# ---------------------------------------------------------------------------
# Mapeamento de chaves
# ---------------------------------------------------------------------------
def _chave_norm(k: str) -> str:
    k = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(k))  # camelCase -> camel Case
    return normalizar(k).replace("_", " ").strip()


def mapear_campos(chaves: list[str]) -> dict[str, str]:
    """{campo_padrao: chave_original}"""
    normas = {k: _chave_norm(k) for k in chaves}
    usado: set[str] = set()
    mapa: dict[str, str] = {}
    for campo, padroes in _PADROES_CHAVE.items():
        for pad in padroes:
            achou = next((k for k, n in normas.items() if k not in usado and re.search(pad, n)), None)
            if achou:
                mapa[campo] = achou
                usado.add(achou)
                break
    return mapa


def _achatar(d: dict, prefixo: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        chave = f"{prefixo}{k}"
        if isinstance(v, dict):
            out.update(_achatar(v, chave + " "))
        else:
            out[chave] = v
    return out


def classificar_link(texto: str, href: str) -> str | None:
    t = normalizar(f"{texto} {href}")
    if re.search(r"empenho|liquidac|pagamento|nota de empenho|despesa", t):
        return "link_empenho"
    if re.search(r"ordem de servico|ordem servico|\bos\b|ordemservico|inicio de obra", t):
        return "link_os"
    if re.search(r"contrato|\.pdf|anexo|documento|arquivo|download|visualizar|integra", t):
        return "link_contrato"
    return None


def normalizar_registro(raw: dict, base_url: str = "") -> dict:
    plano = _achatar(raw)
    mapa = mapear_campos(list(plano.keys()))
    reg = {c: None for c in CAMPOS}
    for campo, chave in mapa.items():
        reg[campo] = plano.get(chave)

    # links presentes em qualquer campo
    for k, v in plano.items():
        if isinstance(v, str) and re.match(r"^(https?:)?/|^https?://", v.strip()) and len(v) < 600:
            tipo = classificar_link(k, v)
            if tipo and not reg[tipo]:
                reg[tipo] = urljoin(base_url, v.strip())

    # CNPJ procurado em todos os valores se não houver campo próprio
    if not reg["cnpj"]:
        for v in plano.values():
            m = _CNPJ_RE.search(str(v or ""))
            if m:
                reg["cnpj"] = m.group(0)
                break
    # empenhos aninhados
    for k, v in raw.items():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "empenho" in normalizar(k):
            reg["empenhos"] = [normalizar_empenho(e) for e in v]

    return finalizar(reg)


def normalizar_empenho(e: dict) -> dict:
    plano = _achatar(e)
    def pick(*pads):
        for k, v in plano.items():
            n = _chave_norm(k)
            if any(re.search(p, n) for p in pads):
                return v
        return None
    return {
        "numero": pick(r"numero|^n", r"empenho"),
        "data": parse_data(pick(r"data|emissao")),
        "valor_empenhado": parse_valor(pick(r"empenhad", r"valor")),
        "valor_pago": parse_valor(pick(r"pago|pagamento")),
        "link": pick(r"link|url|href"),
    }


def finalizar(reg: dict) -> dict:
    reg["valor"] = parse_valor(reg.get("valor"))
    reg["data_assinatura"] = parse_data(reg.get("data_assinatura"))
    reg["vigencia_inicio"] = parse_data(reg.get("vigencia_inicio"))
    vf = reg.get("vigencia_fim")
    if vf and isinstance(vf, str) and re.search(r"\d.*(a|ate|-).*\d", normalizar(vf)):
        datas = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", vf)
        if len(datas) >= 2:
            reg["vigencia_inicio"] = reg["vigencia_inicio"] or parse_data(datas[0])
            vf = datas[-1]
    reg["vigencia_fim"] = parse_data(vf)
    for c in ("numero", "objeto", "fornecedor"):
        if reg.get(c) is not None:
            reg[c] = re.sub(r"\s+", " ", str(reg[c])).strip()
    forn = reg.get("fornecedor") or ""
    if not reg.get("cnpj"):
        m = _CNPJ_RE.search(forn)
        if m:
            reg["cnpj"] = m.group(0)
    if reg.get("cnpj"):
        reg["cnpj"] = formatar_cnpj(reg["cnpj"])
        reg["fornecedor"] = re.sub(re.escape(reg["cnpj"]) + r"\s*[-–]?\s*", "", forn).strip() or forn
    reg["empenhos"] = reg.get("empenhos") or []
    return reg


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def extrair_lista_json(dado) -> list[dict]:
    """Localiza a maior lista de dicionários dentro de uma resposta JSON qualquer."""
    melhores: list[list[dict]] = []

    def visitar(x, prof=0):
        if prof > 5:
            return
        if isinstance(x, list):
            if x and all(isinstance(i, dict) for i in x[:5]):
                melhores.append(x)
            for i in x[:3]:
                visitar(i, prof + 1)
        elif isinstance(x, dict):
            for v in x.values():
                visitar(v, prof + 1)

    visitar(dado)
    return max(melhores, key=len) if melhores else []


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
_PISTAS_CABECALHO = ("contrat", "objeto", "fornecedor", "valor", "vigencia", "credor", "assinatura")


def tabelas_de_contratos(html: str, base_url: str = "") -> list[dict]:
    """Converte tabelas HTML com cara de 'contratos' em registros normalizados."""
    soup = BeautifulSoup(html, "lxml")
    registros: list[dict] = []
    for tabela in soup.find_all("table"):
        linhas = tabela.find_all("tr")
        if len(linhas) < 2:
            continue
        cab_cells = linhas[0].find_all(["th", "td"])
        cabecalho = [c.get_text(" ", strip=True) for c in cab_cells]
        cab_norm = " ".join(normalizar(c) for c in cabecalho)
        if sum(p in cab_norm for p in _PISTAS_CABECALHO) < 2:
            continue
        for tr in linhas[1:]:
            celulas = tr.find_all(["td", "th"])
            if len(celulas) < 2:
                continue
            raw = {}
            for i, td in enumerate(celulas):
                chave = cabecalho[i] if i < len(cabecalho) and cabecalho[i] else f"col{i}"
                raw[chave] = td.get_text(" ", strip=True)
            reg = normalizar_registro(raw, base_url)
            for a in tr.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith(("javascript:", "#")) or not href:
                    continue
                tipo = classificar_link(a.get_text(" ", strip=True) + " " + (a.get("title") or ""), href)
                if tipo and not reg.get(tipo):
                    reg[tipo] = urljoin(base_url, href)
            if reg.get("objeto") or reg.get("numero"):
                registros.append(reg)
    return registros


def links_para_contratos(html: str, base_url: str) -> list[str]:
    """Links de menu que levam à área de contratos/licitações do portal."""
    soup = BeautifulSoup(html, "lxml")
    achados: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        t = normalizar(a.get_text(" ", strip=True) + " " + href)
        if "contrato" in t:
            achados.append((0, urljoin(base_url, href)))
        elif "licitac" in t:
            achados.append((1, urljoin(base_url, href)))
    vistos, saida = set(), []
    for _, u in sorted(achados):
        if u not in vistos:
            vistos.add(u)
            saida.append(u)
    return saida[:4]
