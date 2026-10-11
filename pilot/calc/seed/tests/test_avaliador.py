from fractions import Fraction

import pytest

from calc import avaliar
from calc.erros import ErroExecucao, ErroSintaxe


@pytest.mark.parametrize(
    ("programa", "valor"),
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("10 - 4 - 3", 3),
        ("7 / 2", Fraction(7, 2)),
        ("1 / 3 + 1 / 6", Fraction(1, 2)),
        ("0.1 + 0.2", Fraction(3, 10)),
        ("2 ^ 10", 1024),
        ("2 ^ (0 - 2)", Fraction(1, 4)),
        ("-2 ^ 2", -4),
        ("- -5", 5),
        ("let x = 5 in x * x", 25),
        ("let x = 1 in let x = x + 1 in x", 2),
        ("if 1 < 2 then 10 else 20", 10),
        ("if true then 1 else 2", 1),
        ("let dobro = fn x => x * 2 in dobro(21)", 42),
        ("(fn x => x + 1)(2)", 3),
        ("let rec fact = fn n => if n == 0 then 1 else n * fact(n - 1) in fact(5)", 120),
        ("# a resposta\nlet a = 6 in\n  a * 7", 42),
    ],
)
def test_valor_do_programa(programa, valor):
    assert avaliar(programa) == valor


def test_os_numeros_sao_fracoes():
    assert type(avaliar("4 / 2")) is Fraction


@pytest.mark.parametrize(
    ("programa", "valor"),
    [
        ("1 < 2", True),
        ("2 <= 1", False),
        ("3 > 3", False),
        ("3 >= 3", True),
        ("1 / 2 == 0.5", True),
        ("1 != 1", False),
        ("true == false", False),
        ("true != false", True),
    ],
)
def test_as_comparacoes_dao_booleanos(programa, valor):
    assert avaliar(programa) is valor


@pytest.mark.parametrize(
    "programa",
    [
        "1 / 0",
        "x + 1",
        "1 + true",
        "-true",
        "if 1 then 2 else 3",
        "1(2)",
        "2 ^ 0.5",
        "0 ^ (0 - 1)",
        "true < false",
        "1 == true",
        "(fn x => x) == (fn x => x)",
    ],
)
def test_erros_de_execucao(programa):
    with pytest.raises(ErroExecucao):
        avaliar(programa)


def test_programa_mal_escrito_e_erro_de_sintaxe():
    with pytest.raises(ErroSintaxe):
        avaliar("1 + * 2")
