"""Gera data/municipios_ms.json a partir dos arquivos oficiais da raiz do projeto.

Uso:
    python scripts/gerar_base_municipios.py
    python scripts/gerar_base_municipios.py --planilha "Transparências MS completo.xlsx" --pdf "REGIÕES 2026.pdf"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.base_builder import construir_base, localizar_arquivos_fonte, salvar_base  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--planilha", type=Path)
    ap.add_argument("--pdf", type=Path)
    args = ap.parse_args()

    xlsx_auto, pdf_auto = localizar_arquivos_fonte()
    xlsx, pdf = args.planilha or xlsx_auto, args.pdf or pdf_auto
    if not xlsx or not xlsx.exists() or not pdf or not pdf.exists():
        print("ERRO: não encontrei a planilha de transparências e/ou o PDF de regiões.")
        print(f"  planilha: {xlsx}\n  pdf:      {pdf}")
        return 1

    base = construir_base(xlsx, pdf, xlsx.name, pdf.name)
    destino = salvar_base(base)
    r = base["resumo"]
    print(f"Base gravada em {destino}")
    print(f"  Fiscais fixos:          {r['fiscais_fixos']}")
    print(f"  Municípios em regiões:  {r['municipios_em_regioes']} (esperado: 75)")
    print(f"  Municípios com URL:     {r['com_url']} de {r['total']}")
    for num, reg in base["regioes"].items():
        nomes = ", ".join(m["nome"] for m in reg["municipios"])
        print(f"  Região {num:>2} ({len(reg['municipios'])}): {nomes}")
    if base["pendencias"]:
        print("\nPENDÊNCIAS (revise o JSON gerado):")
        for p in base["pendencias"]:
            print("  -", p)
    ok = r["municipios_em_regioes"] == 75 and r["com_url"] == 79
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
