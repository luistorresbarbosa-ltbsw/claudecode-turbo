import pytest

from calc import avaliar


@pytest.mark.parametrize(
    ("programa", "valor"),
    [
        ("let x = 1 in let f = fn y => x + y in let x = 100 in f(10)", 11),
        ("let somar = fn a => fn b => a + b in somar(2)(3)", 5),
        ("let f = let k = 7 in fn x => x * k in f(6)", 42),
        ("let y = 5 in let f = fn x => x + y in let g = fn y => f(y) in g(100)", 105),
    ],
)
def test_as_funcoes_veem_o_sitio_onde_foram_definidas(programa, valor):
    assert avaliar(programa) == valor


def test_let_rec_ve_se_a_si_propria_e_ao_ambiente_da_definicao():
    programa = (
        "let passo = 2 in"
        " let rec contar = fn n => if n <= 0 then 0 else 1 + contar(n - passo) in"
        " let passo = 1 in contar(10)"
    )

    assert avaliar(programa) == 5


def test_let_simples_nao_e_recursivo():
    assert avaliar("let f = fn x => x + 1 in let f = fn x => f(x) * 2 in f(3)") == 8
