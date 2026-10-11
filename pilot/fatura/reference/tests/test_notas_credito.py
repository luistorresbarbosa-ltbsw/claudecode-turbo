from decimal import Decimal
from pathlib import Path

import pytest
from fatura.notas_credito import ler_fatura, nota_credito

FT_2026_31 = ler_fatura(Path(__file__).parent.parent / "exemplos" / "ft-2026-31.json")


def test_tres_chavenas_da_ft_2026_31():
    # Caso reportado: 3 × 12.50 = 37.50; IVA 37.50 × 0.23 = 8.625 -> 8.63 (com float dava 8.62)
    nota = nota_credito(FT_2026_31, {2: Decimal(3)})

    assert nota.por_taxa == {"NOR": (Decimal("37.50"), Decimal("8.63"))}
    assert nota.total == Decimal("46.13")


def test_iva_por_taxa_sobre_a_soma_das_bases():
    # 65.60 + 12.50 = 78.10; IVA 78.10 × 0.23 = 17.963 -> 17.96
    # (linha a linha daria 15.088 -> 15.09 mais 2.875 -> 2.88, ou seja 17.97)
    nota = nota_credito(FT_2026_31, {1: Decimal(4), 2: Decimal(1)})

    assert nota.por_taxa == {"NOR": (Decimal("78.10"), Decimal("17.96"))}
    assert nota.total == Decimal("96.06")


def test_nao_credita_mais_do_que_foi_faturado():
    with pytest.raises(ValueError, match="linha 2"):
        nota_credito(FT_2026_31, {2: Decimal(25)})
