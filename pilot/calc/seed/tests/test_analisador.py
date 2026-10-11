from fractions import Fraction

import pytest

from calc.analisador import analisar
from calc.arvore import (
    Binario,
    Booleano,
    Chamada,
    Fn,
    Numero,
    Se,
    Seja,
    SejaRec,
    Unario,
    Variavel,
)
from calc.erros import ErroSintaxe


def test_o_produto_vem_antes_da_soma():
    assert analisar("1 + 2 * 3") == Binario(
        "+", Numero(1), Binario("*", Numero(2), Numero(3))
    )


def test_a_subtracao_associa_a_esquerda():
    assert analisar("10 - 4 - 3") == Binario(
        "-", Binario("-", Numero(10), Numero(4)), Numero(3)
    )


def test_o_menos_unario_vem_antes_do_produto():
    assert analisar("-2 * 3") == Binario("*", Unario("-", Numero(2)), Numero(3))


def test_a_potencia_vem_antes_do_produto():
    assert analisar("2 * 3 ^ 2") == Binario(
        "*", Numero(2), Binario("^", Numero(3), Numero(2))
    )


def test_os_parenteses_mudam_a_ordem():
    assert analisar("(1 + 2) * 3") == Binario(
        "*", Binario("+", Numero(1), Numero(2)), Numero(3)
    )


def test_numeros_com_casas_decimais_sao_exatos():
    assert analisar("0.1") == Numero(Fraction(1, 10))


def test_let_if_fn_e_chamada():
    assert analisar("let f = fn x => if x < 0 then -x else x in f(-3)") == Seja(
        "f",
        Fn(
            "x",
            Se(
                Binario("<", Variavel("x"), Numero(0)),
                Unario("-", Variavel("x")),
                Variavel("x"),
            ),
        ),
        Chamada(Variavel("f"), Unario("-", Numero(3))),
    )


def test_let_rec():
    assert analisar("let rec f = fn n => f(n) in f(true)") == SejaRec(
        "f",
        Fn("n", Chamada(Variavel("f"), Variavel("n"))),
        Chamada(Variavel("f"), Booleano(True)),
    )


@pytest.mark.parametrize(
    "programa",
    [
        "1 +",
        "(1",
        "1 2",
        "let x = 1",
        "let rec f = 1 in f",
        "if true then 1",
        "fn => 1",
    ],
)
def test_erros_de_sintaxe(programa):
    with pytest.raises(ErroSintaxe):
        analisar(programa)
