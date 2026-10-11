"""Linha de comandos: `python -m fatura total ficheiro.json` imprime 'Total: 1 234,56 €'."""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from fatura.io import de_json
from fatura.totais import arredondar, calcular


def euros(valor: Decimal) -> str:
    """1234.56 -> '1 234,56 €': espaço nos milhares, vírgula decimal, sempre 2 casas."""
    com_virgulas = f"{arredondar(valor):,.2f}"  # '1,234.56'
    return com_virgulas.replace(",", " ").replace(".", ",") + " €"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fatura")
    comandos = parser.add_subparsers(dest="comando", required=True)
    total = comandos.add_parser(
        "total", help="imprime o total com IVA de uma fatura em JSON"
    )
    total.add_argument("ficheiro", type=Path)
    args = parser.parse_args(argv)

    try:
        fatura = de_json(args.ficheiro.read_text(encoding="utf-8"))
        totais = calcular(fatura)
    except (OSError, KeyError, ValueError) as erro:  # JSONDecodeError é um ValueError
        print(f"erro: {args.ficheiro}: {erro}", file=sys.stderr)
        return 1
    print(f"Total: {euros(totais.total)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
