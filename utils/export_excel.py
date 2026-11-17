"""Exportação profissional (.xlsx) com xlsxwriter: moeda R$, datas e hiperlinks."""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd

AZUL, VERDE, AMARELO, BORDA = "#004B87", "#007A33", "#F2A900", "#DCE3EC"

_COLS_EXPORT = [
    "Região/Grupo", "Município", "Nº Contrato", "Data Assinatura", "Empresa Contratada", "CNPJ",
    "Objeto Completo", "Valor (R$)", "Pago (R$)", "Saldo (R$)", "Vigência", "Área Técnica", "Plataforma",
    "Processo", "Fiscal", "Fiscal CREA/ART", "Vínculo Pagamentos",
    "Link Contrato", "Link OS", "Link Empenho", "Portal Oficial",
]
_MOEDA = {"Valor (R$)", "Pago (R$)", "Saldo (R$)"}
_SEM_LINK = {"Link OS": "OS não publicada no portal",
             "Link Empenho": "Sem página própria — ver aba Pagamentos_Empenhos"}
_LARGURAS = {"Região/Grupo": 16, "Município": 22, "Nº Contrato": 14, "Data Assinatura": 14,
             "Empresa Contratada": 38, "CNPJ": 20, "Objeto Completo": 70, "Valor (R$)": 18,
             "Vigência": 24, "Área Técnica": 30, "Plataforma": 14, "Link Contrato": 16,
             "Pago (R$)": 18, "Saldo (R$)": 18, "Processo": 14, "Fiscal": 30, "Fiscal CREA/ART": 30,
             "Vínculo Pagamentos": 30,
             "Link OS": 16, "Link Empenho": 16, "Portal Oficial": 16}
_ROTULO_LINK = {"Link Contrato": "📄 Contrato", "Link OS": "📋 Ordem de Serviço",
                "Link Empenho": "💰 Empenho", "Portal Oficial": "🌐 Portal"}
_FMT_MOEDA = '"R$" #,##0.00'  # exibido como R$ #.##0,00 no Excel em pt-BR


def gerar_excel(df: pd.DataFrame, status: pd.DataFrame | None = None, exercicio: int | None = None) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        wb = writer.book
        f_tit = wb.add_format({"bold": True, "font_size": 14, "font_color": AZUL})
        f_sub = wb.add_format({"italic": True, "font_color": "#5A6B7D"})
        f_cab = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": AZUL, "border": 1,
                               "border_color": BORDA, "text_wrap": True, "valign": "vcenter"})
        f_txt = wb.add_format({"border": 1, "border_color": BORDA, "valign": "top"})
        f_wrap = wb.add_format({"border": 1, "border_color": BORDA, "valign": "top", "text_wrap": True})
        f_moeda = wb.add_format({"num_format": _FMT_MOEDA, "border": 1, "border_color": BORDA, "valign": "top"})
        f_data = wb.add_format({"num_format": "dd/mm/yyyy", "border": 1, "border_color": BORDA, "valign": "top"})
        f_link = wb.add_format({"font_color": AZUL, "underline": 1, "border": 1, "border_color": BORDA, "valign": "top"})
        f_na = wb.add_format({"font_color": "#9A6B00", "italic": True, "border": 1, "border_color": BORDA, "valign": "top"})
        f_tot = wb.add_format({"bold": True, "bg_color": "#E8F3EC", "font_color": VERDE, "border": 1,
                               "border_color": BORDA, "num_format": _FMT_MOEDA})
        f_tot_txt = wb.add_format({"bold": True, "bg_color": "#E8F3EC", "font_color": VERDE, "border": 1,
                                   "border_color": BORDA})

        # ---------------- Aba 1 ----------------
        ws = wb.add_worksheet("Contratos_Engenharia_MS")
        ws.write(0, 0, "FiscalizaObras-MS — Contratos de Engenharia, Agronomia e Geociências", f_tit)
        ws.write(1, 0, f"Exercício {exercicio or ''} · Gerado em {datetime.now():%d/%m/%Y %H:%M} · "
                       "Fonte: Portais da Transparência municipais", f_sub)
        lin0 = 3
        for j, col in enumerate(_COLS_EXPORT):
            ws.write(lin0, j, col, f_cab)
            ws.set_column(j, j, _LARGURAS.get(col, 15))
        ws.set_row(lin0, 30)
        for i, (_, row) in enumerate(df.iterrows(), start=lin0 + 1):
            for j, col in enumerate(_COLS_EXPORT):
                v = row.get(col)
                if col in _ROTULO_LINK:
                    if isinstance(v, str) and v.startswith("http"):
                        ws.write_url(i, j, v, f_link, string=_ROTULO_LINK[col], tip=v)
                    else:
                        ws.write(i, j, _SEM_LINK.get(col, "Não localizado no portal"), f_na)
                elif col in _MOEDA:
                    ws.write_number(i, j, float(v), f_moeda) if pd.notna(v) else ws.write_blank(i, j, None, f_txt)
                elif col == "Data Assinatura":
                    if pd.notna(v):
                        ws.write_datetime(i, j, pd.Timestamp(v).to_pydatetime(), f_data)
                    else:
                        ws.write_blank(i, j, None, f_txt)
                else:
                    ws.write(i, j, "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v),
                             f_wrap if col in ("Objeto Completo", "Empresa Contratada") else f_txt)
        ultima = lin0 + len(df)
        if len(df):
            jv = _COLS_EXPORT.index("Valor (R$)")
            ws.write(ultima + 1, jv - 1, "TOTAL", f_tot_txt)
            for k, col in enumerate(("Valor (R$)", "Pago (R$)", "Saldo (R$)")):
                letra = chr(ord("A") + jv + k)
                ws.write_formula(ultima + 1, jv + k, f"=SUM({letra}{lin0 + 2}:{letra}{ultima + 1})", f_tot,
                                 float(df[col].fillna(0).sum()))
        ws.autofilter(lin0, 0, max(ultima, lin0), len(_COLS_EXPORT) - 1)
        ws.freeze_panes(lin0 + 1, 2)

        # ---------------- Aba 2 ----------------
        ws2 = wb.add_worksheet("Resumo_por_Municipio")
        ws2.write(0, 0, "Resumo por Região/Grupo e Município", f_tit)
        cab2 = ["Região/Grupo", "Município", "Qtd. Contratos", "Valor Total (R$)", "Com Doc. Completa",
                "% Doc. Completa", "Status do Portal"]
        for j, c in enumerate(cab2):
            ws2.write(2, j, c, f_cab)
        ws2.set_column(0, 0, 18); ws2.set_column(1, 1, 26); ws2.set_column(2, 2, 14)
        ws2.set_column(3, 3, 20); ws2.set_column(4, 5, 16); ws2.set_column(6, 6, 34)
        f_pct = wb.add_format({"num_format": "0.0%", "border": 1, "border_color": BORDA})

        resumo = (df.groupby(["Região/Grupo", "Município"], dropna=False)
                    .agg(qtd=("ID", "count"), valor=("Valor (R$)", "sum"), doc=("Doc Completa", "sum"))
                    .reset_index()) if len(df) else pd.DataFrame(columns=["Região/Grupo", "Município", "qtd", "valor", "doc"])
        st_map = {}
        if status is not None and len(status):
            st_map = dict(zip(status["Município"], status["Status"]))
            faltam = status[~status["Município"].isin(resumo["Município"])]
            extra = pd.DataFrame({"Região/Grupo": faltam["Região/Grupo"], "Município": faltam["Município"],
                                  "qtd": 0, "valor": 0.0, "doc": 0})
            resumo = pd.concat([resumo, extra], ignore_index=True)
        resumo = resumo.sort_values(["Região/Grupo", "Município"]).reset_index(drop=True)

        lin = 3
        for grupo, bloco in resumo.groupby("Região/Grupo", sort=True, dropna=False):
            for _, r in bloco.iterrows():
                ws2.write(lin, 0, str(grupo), f_txt)
                ws2.write(lin, 1, r["Município"], f_txt)
                ws2.write_number(lin, 2, int(r["qtd"]), f_txt)
                ws2.write_number(lin, 3, float(r["valor"] or 0), f_moeda)
                ws2.write_number(lin, 4, int(r["doc"]), f_txt)
                ws2.write_number(lin, 5, (r["doc"] / r["qtd"]) if r["qtd"] else 0, f_pct)
                ws2.write(lin, 6, st_map.get(r["Município"], ""), f_txt)
                lin += 1
            ws2.write(lin, 0, f"Subtotal {grupo}", f_tot_txt)
            ws2.write(lin, 1, "", f_tot_txt)
            ws2.write_number(lin, 2, int(bloco["qtd"].sum()), f_tot_txt)
            ws2.write_number(lin, 3, float(bloco["valor"].fillna(0).sum()), f_tot)
            ws2.write_number(lin, 4, int(bloco["doc"].sum()), f_tot_txt)
            ws2.write(lin, 5, "", f_tot_txt); ws2.write(lin, 6, "", f_tot_txt)
            lin += 2
        ws2.write(lin, 0, "TOTAL GERAL", f_tot_txt)
        ws2.write(lin, 1, "", f_tot_txt)
        ws2.write_number(lin, 2, int(resumo["qtd"].sum()), f_tot_txt)
        ws2.write_number(lin, 3, float(resumo["valor"].fillna(0).sum()), f_tot)
        ws2.write_number(lin, 4, int(resumo["doc"].sum()), f_tot_txt)
        ws2.freeze_panes(3, 0)

        # ---------------- Aba 3 (pagamentos/empenhos) ----------------
        ws4 = wb.add_worksheet("Pagamentos_Empenhos")
        cab4 = ["Município", "Nº Contrato", "Empresa Contratada", "CNPJ", "Data", "Nº Empenho", "Liquidação",
                "Ordem de Pagamento", "Nota Fiscal", "Valor Pago (R$)", "Vínculo", "Histórico"]
        larg4 = [20, 12, 34, 20, 12, 12, 12, 14, 12, 16, 28, 90]
        for j, (c4, w4) in enumerate(zip(cab4, larg4)):
            ws4.write(0, j, c4, f_cab)
            ws4.set_column(j, j, w4)
        lin4 = 1
        for _, row in df.iterrows():
            for e in row.get("Empenhos") or []:
                dt = pd.to_datetime(e.get("data"), dayfirst=True, errors="coerce")
                vals = [row["Município"], row["Nº Contrato"], row["Empresa Contratada"], row["CNPJ"]]
                for j, v in enumerate(vals):
                    ws4.write(lin4, j, str(v or ""), f_txt)
                if pd.notna(dt):
                    ws4.write_datetime(lin4, 4, dt.to_pydatetime(), f_data)
                else:
                    ws4.write_blank(lin4, 4, None, f_txt)
                for j, k in ((5, "numero"), (6, "liquidacao"), (7, "ordem_pagamento"), (8, "nota_fiscal")):
                    v = e.get(k)
                    ws4.write(lin4, j, "" if v is None else str(v), f_txt)
                vp = e.get("valor_pago")
                if vp is not None:
                    ws4.write_number(lin4, 9, float(vp), f_moeda)
                else:
                    ws4.write_blank(lin4, 9, None, f_txt)
                ws4.write(lin4, 10, e.get("vinculo") or "", f_txt)
                ws4.write(lin4, 11, e.get("historico") or "", f_wrap)
                lin4 += 1
        ws4.autofilter(0, 0, max(lin4 - 1, 0), len(cab4) - 1)
        ws4.freeze_panes(1, 0)

        # ---------------- Aba 4 (diagnóstico) ----------------
        if status is not None and len(status):
            ws3 = wb.add_worksheet("Status_dos_Portais")
            cols3 = ["Região/Grupo", "Município", "Plataforma", "Status", "Detalhe",
                     "Acesso Manual (Contratos)", "Portal Oficial"]
            for j, c in enumerate(cols3):
                ws3.write(0, j, c, f_cab)
            ws3.set_column(0, 3, 20); ws3.set_column(4, 4, 60); ws3.set_column(5, 6, 22)
            for i, (_, r) in enumerate(status.iterrows(), start=1):
                for j, c in enumerate(cols3):
                    v = r.get(c)
                    if c in ("Acesso Manual (Contratos)", "Portal Oficial") and isinstance(v, str) and v.startswith("http"):
                        ws3.write_url(i, j, v, f_link, string="Abrir", tip=v)
                    else:
                        ws3.write(i, j, "" if v is None else str(v), f_txt)
    return buf.getvalue()
