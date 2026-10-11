import pytest

from calc.tipos import ErroTipo, inferir


@pytest.mark.parametrize(
    ("programa", "tipo"),
    [
        ("1 + 2", "num"),
        ("fn x => x", "a -> a"),
        ("fn f => fn x => f(x)", "(a -> b) -> a -> b"),
        ("fn x => fn y => x == y", "a -> a -> bool"),
        ("let id = fn x => x in if id(true) then id(1) else 0", "num"),
        ("fn x => let f = fn y => x in if f(1) then f(true) else false", "bool -> bool"),
        ("fn x => let g = fn y => x(y) in g", "(a -> b) -> a -> b"),
        (
            (
                "let rec repetir = fn f => fn n => fn x =>"
                " if n == 0 then x else repetir(f)(n - 1)(f(x)) in repetir"
            ),
            "(a -> a) -> num -> a -> a",
        ),
    ],
)
def test_tipos(programa, tipo):
    assert inferir(programa) == tipo


def test_tipos_que_nao_casam():
    with pytest.raises(ErroTipo, match="num e bool|bool e num"):
        inferir("if true then 1 else false")


def test_o_parametro_nao_e_polimorfico():
    with pytest.raises(ErroTipo):
        inferir("fn f => if f(true) then f(1) else 0")


def test_tipo_infinito():
    with pytest.raises(ErroTipo, match="infinito: a = a -> b"):
        inferir("fn x => x(x)")


def test_variavel_nao_definida():
    with pytest.raises(ErroTipo, match="'y'"):
        inferir("y + 1")
