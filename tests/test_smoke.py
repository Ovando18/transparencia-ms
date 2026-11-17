"""Testes rápidos (sem acesso à internet): python -m pytest -q  ou  python tests/test_smoke.py"""
from __future__ import annotations

import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402
import pandas as pd  # noqa: E402

from config.base_builder import MUNICIPIOS_MS, FISCAIS_FIXOS, encontrar_municipios_em_texto, ler_planilha  # noqa: E402
from config.plataformas import detectar_plataforma, link_contratos  # noqa: E402
from scrapers.collector import ST_COLETADO, ST_SEM_URL, coletar_varios  # noqa: E402
from scrapers.keywords import classificar_objeto  # noqa: E402
from scrapers.parsers import parse_data, parse_valor, tabelas_de_contratos  # noqa: E402
from utils.dados import aplicar_filtros, resultados_para_df, status_para_df  # noqa: E402
from utils.export_excel import gerar_excel  # noqa: E402

HTML = """<html><body><table>
<tr><th>Nº Contrato</th><th>Data Assinatura</th><th>Fornecedor</th><th>Objeto</th><th>Valor</th><th>Vigência</th><th>Docs</th></tr>
<tr><td>012/2026</td><td>10/02/2026</td><td>12.345.678/0001-90 - CONSTRUTORA ALFA LTDA</td>
<td>Contratação de empresa para execução de obra de pavimentação asfáltica e drenagem</td>
<td>R$ 1.234.567,89</td><td>10/02/2026 a 10/02/2027</td>
<td><a href="/docs/contrato12.pdf">Contrato</a> <a href="/docs/os12.pdf">Ordem de Serviço</a>
<a href="/despesas/empenho?id=12">Empenho</a></td></tr>
<tr><td>013/2026</td><td>11/02/2026</td><td>MERCADO BETA</td><td>Aquisição de gêneros alimentícios para merenda</td>
<td>R$ 50.000,00</td><td></td><td></td></tr>
<tr><td>099/2025</td><td>11/02/2025</td><td>GEO LTDA</td><td>Serviço de topografia</td><td>10.000,00</td><td></td><td></td></tr>
</table></body></html>"""


class _Portal(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def log_message(self, *a):
        pass


def test_base():
    assert len(MUNICIPIOS_MS) == 79 and len(set(MUNICIPIOS_MS)) == 79
    assert len(FISCAIS_FIXOS) == 4
    assert encontrar_municipios_em_texto("REGIÃO 5: Rio Verde de Mato Grosso, Rio Brilhante e Coxim") == [
        "Rio Verde de Mato Grosso", "Rio Brilhante", "Coxim"]


def test_planilha_sintetica():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["MUNICÍPIO", "SISTEMA", "LINK"])
    ws.append(["Campo Grande", "Outro", "https://transparencia.campogrande.ms.gov.br"])
    ws.append(["COXIM", "Fiorilli SCPI 9.0", "http://177.1.2.3:8079/transparencia/"])
    buf = io.BytesIO(); wb.save(buf)
    p = ler_planilha(buf.getvalue())
    assert p["Coxim"]["url"].startswith("http://177") and p["Campo Grande"]["url"]
    assert detectar_plataforma(p["Coxim"]["url"], p["Coxim"]["fornecedor_planilha"]) == "SCPI"


def test_plataformas():
    assert detectar_plataforma("https://transparencia.betha.cloud/#/abc") == "Betha Cloud"
    assert detectar_plataforma("https://e-gov.betha.com.br/transparencia/01037-001/recursos.faces?mun=x") == "Betha e-Gov"
    assert "con_contratos.faces" in link_contratos(
        "https://e-gov.betha.com.br/transparencia/01037-001/recursos.faces?mun=x", "Betha e-Gov")


def test_parsers_e_keywords():
    assert parse_valor("R$ 1.234.567,89") == 1234567.89
    assert parse_data("10/02/2026").isoformat() == "2026-02-10"
    assert classificar_objeto("obra de pavimentação asfáltica")[0]
    assert not classificar_objeto("aquisição de gêneros alimentícios")[0]
    regs = tabelas_de_contratos(HTML, "http://x")
    assert regs[0]["cnpj"] == "12.345.678/0001-90" and regs[0]["link_os"].endswith("os12.pdf")


def test_coleta_filtros_export():
    srv = HTTPServer(("127.0.0.1", 0), _Portal)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/portal"
    muns = [{"nome": "Coxim", "grupo": "Região 1", "url": url, "plataforma": "Outros"},
            {"nome": "Sonora", "grupo": "Região 1", "url": "", "plataforma": "Outros"}]
    res = coletar_varios(muns, 2026)
    srv.shutdown()
    st = {r["municipio"]: r for r in res}
    assert st["Coxim"]["status"] == ST_COLETADO and len(st["Coxim"]["contratos"]) == 1
    assert st["Sonora"]["status"] == ST_SEM_URL
    df = resultados_para_df(res)
    assert bool(df.loc[0, "Doc Completa"]) and df.loc[0, "Valor (R$)"] == 1234567.89
    assert len(aplicar_filtros(df, texto="12345678")) == 1
    assert len(aplicar_filtros(df, valor_max=1000)) == 0
    assert len(aplicar_filtros(df, area="Agronomia/Meio Ambiente")) == 0
    xlsx = gerar_excel(df, status_para_df(res), 2026)
    wb = openpyxl.load_workbook(io.BytesIO(xlsx))
    assert wb.sheetnames[:3] == ["Contratos_Engenharia_MS", "Resumo_por_Municipio", "Pagamentos_Empenhos"]
    ws = wb["Contratos_Engenharia_MS"]
    cab = {ws.cell(4, j).value: j for j in range(1, ws.max_column + 1)}
    assert ws.cell(5, cab["Valor (R$)"]).number_format.startswith('"R$"')
    assert ws.cell(5, cab["Link Contrato"]).hyperlink is not None
    assert ws.cell(5, cab["Link Empenho"]).hyperlink is not None


def test_filtro_falsos_positivos():
    """Casos reais do portal de Corumbá que NÃO são do escopo Crea."""
    for txt in ["Contratação de serviços terceirizados de limpeza, asseio e conservação, com mão de obra",
                "Aquisição de veículo tipo passeio, modelo hatch, zero rodovia",
                "Credenciamento de agentes culturais para apresentações artísticas",
                "Aquisição de capacete para motocicleta visando ampliação da frota",
                "Confecção de troféus e medalhas para os projetos esportivos",
                "Agenciamento de passagens rodoviárias intermunicipais",
                "Credenciamento para contratação pessoa física e jurídica para a prestação de serviços médicos "
                "destinados à manutenção e ampliação da rede",
                "Fornecimento de livros paradidáticos, detentora de exclusividade de comercialização das obras",
                "Manutenção de roçadeiras para atender a Secretaria Municipal de Obras",
                "Fornecimento de massa asfáltica para aplicação a frio",
                "Aquisição de insumos e materiais de construção",
                "Contratação de empresa para aquisição de materiais de construção civil, destinadas à manutenção preventiva",
                "Aquisição de insumos e materiais para pintura em geral, destinados à execução de serviços",
                "locação do lmovel em alvenaria, situado na Avenida",
                "Concessão onerosa de direito real de uso de bem público. Solicitação da Gerência de Obras de Naviraí/MS",
                "Registro de preços objetivando a aquisição futura de materiais empregados em tapa buracos e obras de "
                "manutenção de vias"]:
        assert not classificar_objeto(txt)[0], txt
    for txt in ["Execução de obra de pavimentação asfáltica e drenagem",
                "Serviços de manutenção preventiva e corretiva de elevadores",
                "Contratação de empresa de topografia para cadastramento do perímetro",
                "Elaboração de projeto executivo da estrutura de contenção",
                "Aquisição e instalação de 10 estufas agrícolas tipo túnel",
                "Serviços técnicos de manutenção preventiva e corretiva de elevador, com fornecimento de material"]:
        assert classificar_objeto(txt)[0], txt


def test_normalizadores_plataformas():
    from scrapers.plataforma_quality import entidade_da_url, link_contrato
    from scrapers.plataforma_scpi import normalizar_scpi
    r = normalizar_scpi({"CODIGO": "0935/26", "ANO": 2026, "FORNECEDOR": "MARSOU ENGENHARIA LTDA",
                         "VALCON": 6129800.0, "VIGENI": "2026-10-20T00:00:00", "INSMF": "01.278.335/0001-39",
                         "VENCIMENTO_ATUAL": "2027-12-19T00:00:00", "OBJETO_COMPLETO": "Obra de drenagem"})
    assert r["valor"] == 6129800.0 and r["data_assinatura"].isoformat() == "2026-10-20"
    assert r["vigencia_fim"].isoformat() == "2027-12-19" and r["cnpj"] == "01.278.335/0001-39"
    ent = entidade_da_url("https://web.qualitysistemas.com.br/portal/transparencia_publica/prefeitura_municipal_de_terenos")
    assert ent == "prefeitura_municipal_de_terenos"
    assert link_contrato(ent, "12/2026", "1").endswith("/contratos/prefeitura_municipal_de_terenos/contrato/12_2026_1")


def test_arquivos_oficiais():
    """Valida a base gerada dos arquivos oficiais (se estiverem na raiz)."""
    from config.base_builder import construir_base, localizar_arquivos_fonte
    xlsx, pdf = localizar_arquivos_fonte()
    if not (xlsx and pdf):
        return
    b = construir_base(xlsx, pdf)
    qtd = {int(k): len(v["municipios"]) for k, v in b["regioes"].items()}
    # quantidades conforme a coluna "MUNICÍPIOS" do REGIÕES 2026.pdf
    assert qtd == {1: 4, 2: 4, 3: 4, 4: 4, 5: 3, 6: 4, 7: 5, 8: 4, 9: 4, 10: 4, 11: 4, 12: 5,
                   13: 4, 14: 5, 15: 5, 16: 4, 17: 4, 18: 4}
    assert b["resumo"]["municipios_em_regioes"] == 75 and b["resumo"]["com_url"] == 79
    assert not b["nao_mapeados"]


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_"):
            fn(); print("OK", nome)
