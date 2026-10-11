from fractions import Fraction

import pytest

from calc import avaliar
from calc.erros import ErroExecucao


@pytest.mark.parametrize(
    ("programa", "valor"),
    [
        ("7 // 2", 3),
        ("-7 // 2", -4),
        ("7.5 // 2", 3),
        ("-7 % 2", 1),
        ("7 % -2", -1),
        ("7.5 % 2", Fraction(3, 2)),
        ("1 / 3 % (1 / 4)", Fraction(1, 12)),
    ],
)
def test_arredonda_para_baixo_e_o_resto_tem_o_sinal_do_divisor(programa, valor):
    assert avaliar(programa) == valor


@pytest.mark.parametrize(
    ("programa", "valor"),
    [("1 + 7 % 4", 4), ("2 * 7 % 4", 2), ("100 // 7 // 2", 7), ("-7 % 3", 2)],
)
def test_mesma_precedencia_que_o_produto(programa, valor):
    assert avaliar(programa) == valor


@pytest.mark.parametrize("programa", ["1 // 0", "1 % 0"])
def test_dividir_por_zero(programa):
    with pytest.raises(ErroExecucao, match="divisão por zero"):
        avaliar(programa)
