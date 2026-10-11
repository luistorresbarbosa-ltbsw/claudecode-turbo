"""T3 · Erros com posição: `linha L, coluna C: inesperado 'T'`, ou `inesperado fim do programa`.

Regras do prompt: L e C contam de 1 e são a posição do primeiro carácter do token onde o analisador
deu pelo erro; T é o texto do token tal como está no programa; no fim do programa a posição é a do
carácter a seguir ao último; um carácter fora da linguagem também é erro de sintaxe.

Cada caso foi escolhido para ter um só token culpado em qualquer analisador razoável (descida
recursiva ou Pratt, léxico de uma vez ou a pedido): o erro está no primeiro token que não pode
continuar o programa. Nenhum programa acaba em espaços, para "a seguir ao último carácter" e "a
seguir ao último token" darem o mesmo. As colunas estão contadas à mão nos comentários.
"""

import pytest

from calc import avaliar
from calc.erros import ErroSintaxe

CASOS = [
    pytest.param("1 + * 2", "linha 1, coluna 5: inesperado '*'", id="operador-sem-operando"),
    pytest.param("(1 + 2", "linha 1, coluna 7: inesperado fim do programa", id="parentese-por-fechar"),
    pytest.param("if 1 < 2 then 3", "linha 1, coluna 16: inesperado fim do programa", id="if-sem-else"),
    # "let x = 1 x + 2": o segundo x está na coluna 11, onde devia estar o 'in'
    pytest.param("let x = 1 x + 2", "linha 1, coluna 11: inesperado 'x'", id="let-sem-in"),
    pytest.param("let in = 2 in 3", "linha 1, coluna 5: inesperado 'in'", id="palavra-reservada-como-nome"),
    pytest.param("fn => 1", "linha 1, coluna 4: inesperado '=>'", id="fn-sem-parametro"),
    pytest.param("1 2", "linha 1, coluna 3: inesperado '2'", id="sobra-um-numero"),
    # o texto do token é o do programa: "3.50", e não 3.5 nem 7/2
    pytest.param("1 + 2 3.50", "linha 1, coluna 7: inesperado '3.50'", id="texto-do-token"),
    pytest.param("1 + $", "linha 1, coluna 5: inesperado '$'", id="caracter-fora-da-linguagem"),
    # linha 2 "let y = dobro(4 in": o 'in' começa na coluna 17, onde devia estar o ')'
    pytest.param(
        "let dobro = fn x => x * 2 in\nlet y = dobro(4 in\ny + 1",
        "linha 2, coluna 17: inesperado 'in'",
        id="segunda-linha",
    ),
    # linha 2 "  a ? 2": o '?' está na coluna 5
    pytest.param("let a = 1 in\n  a ? 2", "linha 2, coluna 5: inesperado '?'", id="caracter-na-segunda-linha"),
    # o comentário ocupa a linha 1; linha 3 "  )": o ')' está na coluna 3
    pytest.param("# um comentário\n1 +\n  )", "linha 3, coluna 3: inesperado ')'", id="depois-de-um-comentario"),
    pytest.param("1 +\n\n*", "linha 3, coluna 1: inesperado '*'", id="linha-em-branco"),
    # linha 2 "let y = 2 in" tem 12 caracteres: o fim está na coluna 13
    pytest.param(
        "let x = 1 in\nlet y = 2 in",
        "linha 2, coluna 13: inesperado fim do programa",
        id="fim-na-segunda-linha",
    ),
]


@pytest.mark.parametrize(("programa", "mensagem"), CASOS)
def test_a_mensagem_diz_onde_e_o_que(programa, mensagem):
    with pytest.raises(ErroSintaxe) as erro:
        avaliar(programa)

    assert str(erro.value) == mensagem


@pytest.mark.parametrize(
    ("programa", "valor"),
    [("let x = 2 in x * 3", 6), ("# comentário\n(1 + 2) *\n  3", 9)],
    ids=["let", "varias-linhas"],
)
def test_os_programas_bem_escritos_continuam_a_correr(programa, valor):
    assert avaliar(programa) == valor
