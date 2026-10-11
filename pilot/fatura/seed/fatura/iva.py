"""Taxas de IVA por região, em fração: Decimal("0.23") quer dizer 23 %."""

from decimal import Decimal

TAXAS: dict[str, dict[str, Decimal]] = {
    # Continente
    "PT": {"NOR": Decimal("0.23"), "INT": Decimal("0.13"), "RED": Decimal("0.06")},
    # Região Autónoma da Madeira (taxa reduzida de 4 % desde 1 de outubro de 2024)
    "PT-MA": {"NOR": Decimal("0.32"), "INT": Decimal("0.12"), "RED": Decimal("0.04")},
    # Região Autónoma dos Açores
    "PT-AC": {"NOR": Decimal("0.16"), "INT": Decimal("0.09"), "RED": Decimal("0.04")},
}
