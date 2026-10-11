import pytest

from calc.erros import ErroSintaxe
from calc.lexico import tokens


def _tipos_e_textos(programa):
    return [(t.tipo, t.texto) for t in tokens(programa)]


def test_separa_numeros_nomes_operadores_e_palavras_reservadas():
    assert _tipos_e_textos("let x = 2.5 in x * 10") == [
        ("let", "let"),
        ("nome", "x"),
        ("=", "="),
        ("numero", "2.5"),
        ("in", "in"),
        ("nome", "x"),
        ("*", "*"),
        ("numero", "10"),
        ("fim", ""),
    ]


def test_operadores_de_dois_caracteres():
    textos = [t.texto for t in tokens("a <= b => c == d != e >= f")]

    assert textos == ["a", "<=", "b", "=>", "c", "==", "d", "!=", "e", ">=", "f", ""]


def test_ignora_espacos_mudancas_de_linha_e_comentarios():
    textos = [t.texto for t in tokens("1 # um comentário\n  + 2")]

    assert textos == ["1", "+", "2", ""]


def test_cada_token_sabe_onde_comeca():
    assert [t.pos for t in tokens("ab + 12")] == [0, 3, 5, 7]


def test_um_caracter_que_nao_e_da_linguagem_e_erro_de_sintaxe():
    with pytest.raises(ErroSintaxe):
        tokens("1 $ 2")
