"""Filtro semântico por palavras-chave para escopos de Engenharia, Agronomia e Geociências.

Regras (calibradas com os contratos reais do portal de Corumbá/SCPI):

* comparação sobre texto normalizado (minúsculo, sem acento);
* cada termo casa como PALAVRA INTEIRA; termos terminados em ``*`` são radicais
  (``eletric*`` casa "elétrica", "elétricos"...);
* termos FORTES bastam para classificar o contrato;
* termos FRACOS (ex.: "projeto", "laudo", "ar condicionado") só contam quando o
  objeto também traz um verbo de serviço técnico (execução, instalação,
  manutenção, elaboração...), evitando "projetos esportivos", "exames/laudos";
* termos de EXCLUSÃO (locação de imóvel, passagens, exames...) descartam o
  contrato quando não há termo forte.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

AREA_TODAS = "Todas"

# Área técnica -> termos FORTES (sem acento, minúsculas; "*" = radical)
AREAS_TECNICAS: dict[str, list[str]] = {
    "Engenharia Civil/Obras": [
        "obra", "obras", "engenharia", "pavimentacao", "pavimento", "recapeamento",
        "asfalt*", "tapa buraco", "tapa-buraco", "drenagem", "reforma", "reformas",
        "construcao", "construcoes", "edificacao", "edificacoes",
        "terraplanagem", "terraplenagem", "ponte", "pontes", "estrada", "estradas",
        "rodovia", "rodovias", "vicinal", "vicinais", "cascalhamento", "encascalhamento",
        "meio-fio", "meio fio", "sarjeta", "sarjetas", "galeria pluvial", "galerias pluviais",
        "aguas pluviais", "bueiro", "bueiros", "calcamento", "manutencao predial",
        "alvenaria", "estrutura metalica", "cobertura metalica", "muro de arrimo",
        "urbanizacao", "revitalizacao", "restauracao", "saneamento", "esgotamento sanitario",
        "rede de esgoto", "rede de agua", "estacao de tratamento", "lajota", "lajotas",
        "bloquete", "bloquetes", "patrolamento", "passarela", "viaduto",
    ],
    "Engenharia Elétrica/Mecânica": [
        "engenharia eletrica", "iluminacao publica", "subestacao", "rede de distribuicao",
        "spda", "para-raios", "pararaios", "fotovoltaic*", "energia solar", "usina solar",
        "instalacoes eletricas", "instalacao eletrica", "rede eletrica", "eletrificacao",
        "climatizacao", "cabeamento estruturado", "grupo gerador",
    ],
    "Agronomia/Meio Ambiente": [
        "agronom*", "agricola", "agropecuari*", "licenciamento ambiental",
        "recuperacao de area degradada", "prad", "reflorestamento", "arborizacao",
        "supressao vegetal", "inventario florestal", "manejo florestal",
        "conservacao de solo", "conservacao do solo", "curva de nivel", "curvas de nivel",
        "patrulha mecanizada", "aterro sanitario", "residuos solidos", "pgrs",
        "plano de manejo", "estudo de impacto ambiental", "eia/rima",
    ],
    "Geociências/Topografia": [
        "topograf*", "georreferenc*", "geodes*", "geolog*", "geotecn*", "sondagem",
        "sondagens", "planialtimetric*", "cadastro tecnico", "aerofotogrametr*",
        "aerolevantamento", "regularizacao fundiaria", "reurb", "cartograf*",
        "poco artesiano", "pocos artesianos", "perfuracao de poco", "perfuracao de pocos",
        "hidrogeolog*", "batimetr*", "cascalheira", "jazida",
    ],
    "Serviços Técnicos/Projetos": [
        "projeto executivo", "projetos executivos", "projeto basico", "projetos basicos",
        "anteprojeto", "projeto arquitetonico", "projetos arquitetonicos",
        "projeto estrutural", "projetos complementares", "projeto de engenharia",
        "fiscalizacao de obra", "fiscalizacao de obras", "gerenciamento de obra",
        "gerenciamento de obras", "supervisao de obra", "supervisao de obras",
        "laudo tecnico", "laudos tecnicos", "laudo estrutural", "vistoria tecnica",
        "avcb", "ppci", "plano de prevencao e protecao contra incendio",
        "anotacao de responsabilidade tecnica", "plano diretor", "plano de mobilidade",
        "plano municipal de saneamento", "estudo de viabilidade tecnica",
    ],
}

# Termos FRACOS: só contam com um verbo de serviço técnico no objeto
TERMOS_FRACOS: dict[str, list[str]] = {
    "Engenharia Civil/Obras": ["ampliacao", "escola", "creche", "quadra", "pintura", "contencao",
                               "calcada", "calcadas"],
    "Engenharia Elétrica/Mecânica": [
        "eletric*", "iluminacao", "luminaria*", "gerador", "geradores", "ar condicionado",
        "ar-condicionado", "refrigeracao", "elevador", "elevadores", "bomba", "bombas",
        "caldeira*", "mecanica",
    ],
    "Agronomia/Meio Ambiente": ["poda", "paisagismo", "irrigacao", "viveiro", "ambiental"],
    "Geociências/Topografia": ["drone"],
    "Serviços Técnicos/Projetos": [
        "projeto", "projetos", "laudo", "laudos", "pericia",
    ],
}

VERBOS_TECNICOS = [
    "execucao", "executar", "instalacao", "instalacoes", "manutencao", "elaboracao",
    "implantacao", "recuperacao", "adequacao", "construcao", "montagem", "substituicao",
    "servicos de engenharia", "servico de engenharia",
]

TERMOS_EXCLUSAO = [
    "locacao de imovel", "locacao do imovel", "passagens", "passagem rodoviaria",
    "exame*", "consulta medica", "consultas medicas", "genero* alimenticio*", "merenda",
    "medicamento*", "material de expediente", "material escolar", "uniforme*",
    "transporte escolar", "combustive*", "trofeu*", "medalha*", "show*", "evento*",
    "apresentacoes artisticas", "seguro", "material de limpeza", "kit escolar",
    "assessoria juridica", "direito", "parlamentar", "credenciamento de agentes culturais",
    "iluminacao natalina", "decoracao natalina", "zero rodovia", "zero km", "frota",
]

# Exclusão ABSOLUTA: descarta mesmo com termo forte (ex.: "obras didáticas", "gêneros ... engenharia")
TERMOS_EXCLUSAO_ABSOLUTA = [
    "livro*", "isbn", "paradidatic*", "didatic*", "literari*", "protetor solar", "uniforme*",
    "genero* alimenticio*", "medicamento*", "servicos medicos", "servico medico",
    "credenciamento para contratacao pessoa fisica", "desinsetizacao", "desratizacao",
    "dedetizacao", "assessoria estrategica", "transferencias voluntarias", "captacao de recursos",
]

# Expressões removidas do texto antes da análise (falsos gatilhos)
EXPRESSOES_NEUTRAS = [
    r"mao[\s-]+de[\s-]+obra", r"engenharia de trafego",
    r"secretaria\s+(?:municipal\s+)?de\s+obras(?:\s*(?:,|e)\s*[a-z]+(?:\s+[a-z]+){0,3})?",
    r"secretaria\s+(?:municipal\s+)?de\s+infraestrutura(?:\s+[a-z]+){0,4}",
]

# Compra de material/equipamento SEM serviço de engenharia associado não é escopo Crea
_RE_COMPRA = re.compile(r"\b(aquisicao|fornecimento|compra)\b")
_RE_SERVICO = re.compile(r"\b(execucao|instalacao|instalar|implantacao|obras? de|servicos? de engenharia|"
                         r"construcao de|reforma d|elaboracao|manutencao (?:preventiva|corretiva))")

# Objetos de pura aquisição: termos fracos não bastam (salvo se houver instalação/execução)
INICIO_AQUISICAO = ("aquisicao", "compra", "fornecimento", "registro de precos para aquisicao")


def normalizar(texto: object) -> str:
    """Minúsculas, sem acentos, espaços colapsados."""
    if texto is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


@lru_cache(maxsize=4096)
def _regex(termo: str) -> re.Pattern:
    radical = termo.endswith("*")
    base = re.escape(termo.rstrip("*")).replace(r"\ ", r"\s+")
    fim = r"[a-z]*" if radical else r"(?![a-z])"
    return re.compile(rf"(?<![a-z]){base}{fim}")


def _achados(texto: str, termos_por_area: dict[str, list[str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for area, termos in termos_por_area.items():
        hits = [t.rstrip("*") for t in termos if _regex(t).search(texto)]
        if hits:
            out[area] = hits
    return out


def _tem(texto: str, termos: list[str]) -> bool:
    return any(_regex(t).search(texto) for t in termos)


def classificar_objeto(objeto: object) -> tuple[bool, list[str], list[str]]:
    """Retorna (é_escopo_técnico, áreas_encontradas, termos_encontrados)."""
    txt = normalizar(objeto)
    for exp in EXPRESSOES_NEUTRAS:
        txt = re.sub(exp, " ", txt)
    txt = re.sub(r"^[\d.\s]+", "", txt).strip()  # remove numeração "1.1." do início
    if not txt:
        return False, [], []
    fortes = _achados(txt, AREAS_TECNICAS)
    fracos = _achados(txt, TERMOS_FRACOS)
    excluido = _tem(txt, TERMOS_EXCLUSAO)

    if _tem(txt, TERMOS_EXCLUSAO_ABSOLUTA):
        return False, [], []
    compra = _RE_COMPRA.search(txt[:160])
    if compra and not _RE_SERVICO.search(txt):
        return False, [], []

    if fortes:
        # termo forte isolado + exclusão (ex.: "passagens rodoviárias") -> descarta,
        # exceto se houver obra/engenharia explícita
        if excluido and not _tem(txt, ["obra", "obras", "engenharia"]):
            return False, [], []
        achados = fortes
        for area, hits in fracos.items():
            achados.setdefault(area, []).extend(hits)
    elif (fracos and _tem(txt, VERBOS_TECNICOS) and not excluido
          and not (txt.startswith(INICIO_AQUISICAO) and not _tem(txt, ["instalacao", "execucao"]))):
        achados = fracos
    else:
        return False, [], []

    termos = sorted({t for hits in achados.values() for t in hits})
    areas = sorted(achados, key=lambda a: (-len(fortes.get(a, [])), -len(achados[a])))
    return True, areas, termos


def pertence_area(areas: list[str] | str, area_filtro: str) -> bool:
    if area_filtro in (None, "", AREA_TODAS):
        return True
    if isinstance(areas, str):
        areas = [a.strip() for a in areas.split(";") if a.strip()]
    return area_filtro in areas
