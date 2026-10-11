import pytest

from calc import avaliar
from calc.analisador import analisar
from calc.arvore import Binario, Numero, Unario


def test_a_potencia_associa_a_direita():
    assert analisar("2 ^ 3 ^ 2") == Binario(
        "^", Numero(2), Binario("^", Numero(3), Numero(2))
    )


@pytest.mark.parametrize(
    ("programa", "valor"),
    [("2^3^2", 512), ("(2^3)^2", 64), ("2^3^2^0", 8), ("-2^2", -4), ("2 * 3 ^ 2", 18)],
)
def test_valores(programa, valor):
    assert avaliar(programa) == valor


def test_o_expoente_pode_ter_menos_unario():
    assert analisar("2 ^ -1") == Binario("^", Numero(2), Unario("-", Numero(1)))
