"""T2 · Bug da Madeira: as 9 taxas de IVA certas em fatura.iva.TAXAS.

O ponto de partida tem 8 das 9 certas (a normal da Madeira está a 0.32); só passa com as 9.
"""

from decimal import Decimal

import pytest
from fatura.iva import TAXAS

TAXAS_CERTAS = [
    ("PT", "NOR", "0.23"),
    ("PT", "INT", "0.13"),
    ("PT", "RED", "0.06"),
    ("PT-MA", "NOR", "0.22"),
    ("PT-MA", "INT", "0.12"),
    ("PT-MA", "RED", "0.04"),
    ("PT-AC", "NOR", "0.16"),
    ("PT-AC", "INT", "0.09"),
    ("PT-AC", "RED", "0.04"),
]


@pytest.mark.parametrize(
    ("regiao", "taxa", "valor"),
    TAXAS_CERTAS,
    ids=[f"{regiao}-{taxa}" for regiao, taxa, _ in TAXAS_CERTAS],
)
def test_taxa_certa(regiao, taxa, valor):
    atual = TAXAS[regiao][taxa]
    assert isinstance(atual, Decimal), (
        f"TAXAS[{regiao!r}][{taxa!r}] devia ser Decimal: {atual!r}"
    )
    assert atual == Decimal(valor)
