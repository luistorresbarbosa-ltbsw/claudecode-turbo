import sys

import pytest

from calc import avaliar


@pytest.fixture
def pilha_curta():
    """Um limite de recursão baixo: só passa se as chamadas em cauda não usarem a pilha."""
    anterior = sys.getrecursionlimit()
    sys.setrecursionlimit(400)
    yield
    sys.setrecursionlimit(anterior)


def test_recursao_em_cauda_funda(pilha_curta):
    programa = "let rec contar = fn n => if n == 0 then 0 else contar(n - 1) in contar(100000)"

    assert avaliar(programa) == 0


def test_cauda_dentro_de_let_e_entre_duas_funcoes(pilha_curta):
    programa = (
        "let rec ping = fn n =>"
        " let pong = fn m => if m == 0 then 7 else ping(m - 1) in pong(n) in"
        " ping(20000)"
    )

    assert avaliar(programa) == 7


def test_a_recursao_que_nao_e_em_cauda_da_o_mesmo():
    programa = "let rec fact = fn n => if n == 0 then 1 else n * fact(n - 1) in fact(20)"

    assert avaliar(programa) == 2432902008176640000
