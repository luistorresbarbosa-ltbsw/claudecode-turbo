from decimal import Decimal

import pytest
from fatura.iva import TAXAS


@pytest.mark.parametrize(
    ("regiao", "esperado"),
    [
        ("PT", {"NOR": "0.23", "INT": "0.13", "RED": "0.06"}),
        ("PT-MA", {"NOR": "0.22", "INT": "0.12", "RED": "0.04"}),
        ("PT-AC", {"NOR": "0.16", "INT": "0.09", "RED": "0.04"}),
    ],
    ids=["continente", "madeira", "acores"],
)
def test_taxas_da_regiao(regiao, esperado):
    assert TAXAS[regiao] == {taxa: Decimal(valor) for taxa, valor in esperado.items()}


def test_as_taxas_sao_decimal():
    for regiao, taxas in TAXAS.items():
        for codigo, valor in taxas.items():
            assert isinstance(valor, Decimal), f"{regiao} {codigo}"
