# 🏗️ FiscalizaObras-MS

Painel web em **Streamlit** para a equipe de fiscalização do **Crea-MS**. Serve para pesquisar, auditar e extrair contratos públicos de obras e serviços de **Engenharia, Agronomia e Geociências** diretamente nos **Portais da Transparência das 79 prefeituras de Mato Grosso do Sul**, sem usar a API do PNCP.

---

## Funcionalidades

- **Dois modos de pesquisa:** por Região de Fiscalização (1 a 18) ou pelos Municípios com Fiscais Fixos (Campo Grande, Dourados, Paranaíba e Três Lagoas).
- **Coleta paralela** (`ThreadPoolExecutor`) com cache (`st.cache_data`, 6 h) e progresso em tempo real (`st.status` + `st.progress`).
- **Filtro semântico** por palavras-chave em 5 áreas técnicas (`scrapers/keywords.py`).
- **Filtros de auditoria:** exercício, área técnica, busca livre (objeto, nº, CNPJ, empresa), faixa de valor e documentação completa.
- **Tabela interativa** com links clicáveis para Contrato 📄, Ordem de Serviço 📋, Empenho 💰 e Portal 🌐.
- **Ficha Técnica de Fiscalização** de cada contrato, com o histórico de empenhos e botões de ação.
- **Diagnóstico dos portais:** `Online - Coletado`, `Online - Sem contratos de engenharia`, `Instável / Timeout`, `Bloqueado (SSL / Firewall)`, `Consulta Manual` e `URL não cadastrada`, sempre com o link direto para consulta manual.
- **Exportação .xlsx** com as abas `Contratos_Engenharia_MS`, `Resumo_por_Municipio` e `Status_dos_Portais`. Valores em moeda R$, datas `dd/mm/aaaa` e hiperlinks clicáveis.

## Arquitetura

```
app.py                         # interface Streamlit (sidebar, KPIs, abas, exportação)
config/
  municipios_ms.py             # API da base: regiões, fiscais fixos, URLs, plataformas
  base_builder.py              # leitura da planilha .xlsx e do PDF de regiões -> JSON
  plataformas.py               # detecção da plataforma pela URL + links diretos
data/municipios_ms.json        # base gerada a partir dos arquivos oficiais (versionar!)
scrapers/
  collector.py                 # roteamento por plataforma, paralelismo, cache, resiliência
  parsers.py                   # normalização de JSON/HTML -> esquema único de contrato
  keywords.py                  # áreas técnicas e filtro semântico
utils/
  dados.py                     # DataFrame, filtros e formatação R$
  export_excel.py              # planilha profissional (xlsxwriter)
  styles.py                    # CSS institucional (paleta MS)
scripts/gerar_base_municipios.py
tests/test_smoke.py            # testes offline (portal HTTP simulado)
.streamlit/config.toml         # tema: #004B87 / #007A33 / #F2A900 / #F4F6F9
```

### Fluxo de coleta, por município

1. Lê a **plataforma** detectada pela URL: `SCPI` (Fiorilli), `Betha Cloud`, `Betha e-Gov`, `Quality`, `Megasoft`, `CR2` ou `Outros`.
2. Tenta os **endpoints JSON internos** da plataforma, que ficam em `ENDPOINTS_JSON`, em `scrapers/collector.py`.
3. Se não houver JSON, faz **scraping das tabelas HTML** de contratos. Para isso, segue os links de menu “Contratos/Licitações”.
4. Filtra pelo **exercício** e pelo **escopo técnico**. Os links de Contrato, OS e Empenho vêm de cada linha.
5. Qualquer falha vira um **status de diagnóstico** e não interrompe a pesquisa. O fiscal recebe o link direto para a área de contratos do portal.

### Situação por plataforma (validada nos portais reais em nov/2026)

| Plataforma | Municípios | Coleta | Como funciona |
|---|---|---|---|
| **Fiorilli SCPI** | 35 | ✅ Automática | `scrapers/plataforma_scpi.py`: sessão ASP.NET, troca de exercício e botão **Exportar JSON** da página `InformacoesContratos.aspx` (todos os contratos do ano). Testado em Corumbá: 394 contratos de 2026, 22 de engenharia. |
| **Quality Sistemas** | 9 | ✅ Automática | `scrapers/plataforma_quality.py`: API `/api/v1/contratos/{entidade}/{ano}?mes=0` com cookie de sessão. Filtra só `CONTRATO PRINCIPAL`. Link direto por contrato. Testado: 7 de 9 coletados. Camapuã e Caracol estavam fora do ar na integração da própria Quality. |
| **Betha Cloud** | 13 | 🔜 Consulta Manual | API `api.transparencia.betha.cloud` com token OAuth anônimo e Dados Abertos assíncronos. Integração em desenvolvimento. |
| **Betha e-Gov** | 3 | ⚠️ Tentativa HTML | O servidor recusa conexões de IPs fora do Brasil. |
| **Megasoft / CR2 / sites próprios** | 19 | ⚠️ Tentativa HTML | Leitor genérico de tabelas HTML; cai em Consulta Manual quando a listagem é dinâmica. |

> ⚠️ **Rede:** muitos portais SCPI são servidores das prefeituras em IP próprio e porta 8079. Alguns podem recusar acessos vindos de fora do Brasil, como os servidores do Streamlit Cloud. A aba **Status dos Portais** mostra o diagnóstico de cada um. Rodar o painel localmente, numa rede brasileira, maximiza a coleta.

## Base de municípios (arquivos oficiais)

A divisão em regiões e as URLs vêm **exclusivamente** dos arquivos oficiais. O sistema não inventa nenhum dado:

| Arquivo | Conteúdo |
|---|---|
| `Transparências MS completo.xlsx` | 79 municípios + URL do Portal da Transparência (+ sistema, se houver) |
| `REGIÕES 2026.pdf` | 18 Regiões de Fiscalização (75 municípios) |

Há três formas de carregar a base:

1. Coloque os dois arquivos na raiz do projeto e execute o script abaixo. Ele gera `data/municipios_ms.json` e mostra a conferência: 75 municípios em regiões, 79 URLs e as pendências.

   ```bash
   python scripts/gerar_base_municipios.py
   ```

2. Ou apenas inicie o app com os arquivos na raiz. O JSON é gerado automaticamente.
3. Ou envie os dois arquivos em **“📂 Base oficial de municípios”**, na barra lateral do painel.

Revise e **versione `data/municipios_ms.json`**. No Streamlit Cloud, arquivos gravados em tempo de execução não são permanentes. O JSON pode ser corrigido manualmente, se necessário.

## Execução local

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

Testes (offline):

```bash
python tests/test_smoke.py
```

## Publicação no GitHub

```bash
git init
```

```bash
git add .
```

```bash
git commit -m "FiscalizaObras-MS: painel de fiscalização de contratos de engenharia"
```

```bash
git branch -M main
```

```bash
git remote add origin https://github.com/<seu-usuario>/fiscalizaobras-ms.git
```

```bash
git push -u origin main
```

## Deploy no Streamlit Community Cloud

1. Acesse **https://share.streamlit.io** e entre com sua conta do GitHub.
2. Clique em **Create app** → **Deploy a public app from GitHub**.
3. Selecione o repositório `fiscalizaobras-ms`, a branch `main` e o arquivo principal `app.py`.
4. Em *Advanced settings*, escolha **Python 3.11 ou superior**.
5. Clique em **Deploy**. As dependências de `requirements.txt` são instaladas automaticamente.

Observações:

- O projeto não usa Playwright, então **não precisa de `packages.txt`**.
- Alguns portais municipais bloqueiam IPs de nuvem estrangeiros. Nesses casos, o status mostrará `Bloqueado` ou `Timeout` com o link para consulta manual. Rodar o painel localmente, numa rede brasileira, costuma aumentar a taxa de coleta automática.
- Para portais com certificado SSL vencido, há a opção *Aceitar portais com certificado SSL inválido*, em ⚙️ **Opções avançadas**, desligada por padrão.

## Ajustes comuns

| Necessidade | Onde |
|---|---|
| Incluir ou remover palavras-chave | `scrapers/keywords.py` → `AREAS_TECNICAS`, `TERMOS_EXCLUSAO` |
| Ajustar endpoint de uma plataforma | `scrapers/collector.py` → `ENDPOINTS_JSON` |
| Nova regra de detecção de plataforma | `config/plataformas.py` → `_REGRAS_URL` |
| Link direto da aba de contratos | `config/plataformas.py` → `link_contratos()` |
| Tempo de cache / timeout | `scrapers/collector.py` → `st.cache_data(ttl=...)`, `TIMEOUT` |
