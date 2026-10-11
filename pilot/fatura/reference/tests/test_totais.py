from decimal import Decimal

import pytest
from fatura.modelo import Fatura, Linha
from fatura.totais import calcular


def linha(quantidade, preco, taxa, desconto="0"):
    return Linha("artigo", Decimal(quantidade), Decimal(preco), taxa, Decimal(desconto))


def test_linha_xx5_arredonda_para_cima():
    # 0.5 × 5.37 = 2.685 -> 2.69 (HALF_EVEN daria 2.68); IVA 2.69 × 0.23 = 0.6187 -> 0.62
    t = calcular(Fatura("FT 1", "PT", [linha("0.5", "5.37", "NOR")]))

    assert t.linhas == [Decimal("2.69")]
    assert (t.sem_iva, t.iva, t.total) == (
        Decimal("2.69"),
        Decimal("0.62"),
        Decimal("3.31"),
    )


def test_desconto_e_uma_percentagem():
    # 25.00 × (1 − 12.5/100) = 21.875 -> 21.88; IVA 21.88 × 0.06 = 1.3128 -> 1.31
    t = calcular(Fatura("FT 2", "PT", [linha("1", "25.00", "RED", "12.5")]))

    assert t.por_taxa == {"RED": (Decimal("21.88"), Decimal("1.31"))}
    assert t.total == Decimal("23.19")


def test_iva_calcula_se_sobre_a_base_de_cada_taxa():
    # 20.20 × 0.16 = 3.232 -> 3.23; linha a linha daria 1.616 -> 1.62 duas vezes, 3.24
    t = calcular(
        Fatura(
            "FT 3", "PT-AC", [linha("1", "10.10", "NOR"), linha("1", "10.10", "NOR")]
        )
    )

    assert t.por_taxa == {"NOR": (Decimal("20.20"), Decimal("3.23"))}
    assert t.total == Decimal("23.43")


def test_varias_taxas_somam_se_no_fim():
    # NOR 10.00 -> 2.30; INT 10.00 -> 1.30; sem IVA 20.00, IVA 3.60
    t = calcular(
        Fatura("FT 4", "PT", [linha("2", "5.00", "NOR"), linha("4", "2.50", "INT")])
    )

    assert t.por_taxa == {
        "NOR": (Decimal("10.00"), Decimal("2.30")),
        "INT": (Decimal("10.00"), Decimal("1.30")),
    }
    assert (t.sem_iva, t.iva, t.total) == (
        Decimal("20.00"),
        Decimal("3.60"),
        Decimal("23.60"),
    )


def test_regiao_desconhecida_diz_o_campo():
    with pytest.raises(ValueError, match="regiao"):
        calcular(Fatura("FT 5", "ES", [linha("1", "1.00", "NOR")]))


def test_taxa_desconhecida_diz_a_linha():
    with pytest.raises(ValueError, match=r"linhas\[2\]\.taxa"):
        calcular(
            Fatura(
                "FT 6", "PT", [linha("1", "1.00", "NOR"), linha("1", "1.00", "ZERO")]
            )
        )
