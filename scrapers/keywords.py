"""Filtro semântico por palavras-chave para escopos de Engenharia, Agronomia e Geociências.

Toda comparação é feita sobre texto normalizado (minúsculo, sem acentos), portanto
as palavras-chave abaixo devem ser escritas SEM acento.
"""
from __future__ import annotations

import re
import unicodedata

AREA_TODAS = "Todas"

# Área técnica -> palavras/expressões-chave (sem acento, minúsculas)
AREAS_TECNICAS: dict[str, list[str]] = {
    "Engenharia Civil/Obras": [
        "obra", "obras", "engenharia", "pavimentacao", "pavimento", "recapeamento",
        "asfalt", "tapa buraco", "tapa-buraco", "drenagem", "reforma", "ampliacao",
        "construcao", "edificacao", "terraplanagem", "terraplenagem", "ponte",
        "estrada", "rodovia", "vicinal", "cascalhamento", "meio-fio", "meio fio",
        "sarjeta", "galeria pluvial", "bueiro", "calcamento", "calcada",
        "manutencao predial", "alvenaria", "cobertura metalica", "estrutura metalica",
        "concreto", "muro de arrimo", "contencao", "urbanizacao", "revitalizacao",
        "quadra poliesportiva", "unidade basica de saude", "creche", "escola",
        "habitacional", "saneamento", "esgotamento sanitario", "abastecimento de agua",
        "rede de agua", "rede de esgoto", "estacao de tratamento",
    ],
    "Engenharia Elétrica/Mecânica": [
        "eletric", "iluminacao publica", "iluminacao", "luminaria", "led",
        "subestacao", "rede de distribuicao", "spda", "para-raios", "pararaios",
        "gerador", "fotovoltaic", "energia solar", "usina solar", "climatizacao",
        "ar condicionado", "ar-condicionado", "refrigeracao", "elevador",
        "mecanica", "caldeira", "bomba", "automacao", "cabeamento estruturado",
    ],
    "Agronomia/Meio Ambiente": [
        "agronom", "agricola", "agropecuari", "licenciamento ambiental",
        "ambiental", "recuperacao de area degradada", "prad", "reflorestamento",
        "arborizacao", "paisagismo", "poda", "supressao vegetal", "inventario florestal",
        "florestal", "manejo de solo", "conservacao de solo", "curva de nivel",
        "irrigacao", "patrulha mecanizada", "aterro sanitario", "residuos solidos",
        "coleta de lixo", "pgrs", "viveiro", "zootecn",
    ],
    "Geociências/Topografia": [
        "topograf", "georreferenc", "geodes", "geolog", "geotecn", "sondagem",
        "levantamento planialtimetrico", "planialtimetric", "cadastro tecnico",
        "aerofotogrametr", "aerolevantamento", "drone", "regularizacao fundiaria",
        "reurb", "cartograf", "poco artesiano", "pocos artesianos", "perfuracao de poco",
        "hidrogeolog", "batimetr", "mineracao", "cascalheira", "jazida",
    ],
    "Serviços Técnicos/Projetos": [
        "projeto", "projetos", "laudo", "pericia", "consultoria tecnica",
        "assessoria tecnica", "fiscalizacao de obra", "fiscalizacao de obras",
        "gerenciamento de obra", "supervisao de obra", "orcamento de obra",
        "anteprojeto", "projeto executivo", "projeto basico", "estudo de viabilidade",
        "vistoria tecnica", "avcb", "plano de prevencao", "ppci", "art ",
        "responsabilidade tecnica", "plano diretor", "plano de mobilidade",
        "plano municipal de saneamento",
    ],
}

# Termos que, sozinhos, geram falsos positivos (ex.: "projeto social"). Se o objeto
# contiver APENAS correspondências "fracas" e algum termo de exclusão, é descartado.
TERMOS_FRACOS = {"projeto", "projetos", "escola", "creche", "led", "bomba", "drone", "art "}
TERMOS_EXCLUSAO = [
    "genero alimenticio", "generos alimenticios", "merenda", "medicamento",
    "material de expediente", "material escolar", "uniforme", "transporte escolar",
    "combustivel", "projeto social", "projeto cultural", "show", "evento",
    "locacao de veiculo", "material de limpeza", "kit escolar",
]


def normalizar(texto: object) -> str:
    """Minúsculas, sem acentos, espaços colapsados."""
    if texto is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def _matches(texto_norm: str) -> dict[str, list[str]]:
    achados: dict[str, list[str]] = {}
    padded = f" {texto_norm} "
    for area, termos in AREAS_TECNICAS.items():
        hits = [t for t in termos if t in padded]
        if hits:
            achados[area] = hits
    return achados


def classificar_objeto(objeto: object) -> tuple[bool, list[str], list[str]]:
    """Retorna (é_engenharia, áreas_encontradas, termos_encontrados)."""
    txt = normalizar(objeto)
    if not txt:
        return False, [], []
    achados = _matches(txt)
    if not achados:
        return False, [], []
    termos = sorted({t.strip() for hits in achados.values() for t in hits})
    so_fracos = all(t in {f.strip() for f in TERMOS_FRACOS} for t in termos)
    if so_fracos and any(ex in txt for ex in TERMOS_EXCLUSAO):
        return False, [], []
    # ordena áreas pela quantidade de termos encontrados (área principal primeiro)
    areas = sorted(achados, key=lambda a: -len(achados[a]))
    return True, areas, termos


def pertence_area(areas: list[str] | str, area_filtro: str) -> bool:
    if area_filtro in (None, "", AREA_TODAS):
        return True
    if isinstance(areas, str):
        areas = [a.strip() for a in areas.split(";") if a.strip()]
    return area_filtro in areas
