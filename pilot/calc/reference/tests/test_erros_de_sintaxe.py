import pytest

from calc import analisar
from calc.erros import ErroSintaxe


@pytest.mark.parametrize(
    ("programa", "mensagem"),
    [
        ("1 + * 2", "linha 1, coluna 5: inesperado '*'"),
        ("(1 + 2", "linha 1, coluna 7: inesperado fim do programa"),
        ("let x = 1 x", "linha 1, coluna 11: inesperado 'x'"),
        ("1 + 2.50 3", "linha 1, coluna 10: inesperado '3'"),
        ("let a = 1 in\n  a $ 2", "linha 2, coluna 5: inesperado '$'"),
        ("# nota\nlet y = 2 in", "linha 2, coluna 13: inesperado fim do programa"),
        ("let rec f = 1 in f", "linha 1, coluna 13: inesperado '1'"),
    ],
)
def test_a_mensagem_diz_linha_coluna_e_token(programa, mensagem):
    with pytest.raises(ErroSintaxe) as erro:
        analisar(programa)

    assert str(erro.value) == mensagem


def test_o_erro_guarda_a_posicao_e_o_token():
    with pytest.raises(ErroSintaxe) as erro:
        analisar("1 +\n  )")

    assert (erro.value.linha, erro.value.coluna, erro.value.inesperado) == (2, 3, ")")
