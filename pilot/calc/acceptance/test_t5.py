"""T5 · Âmbito léxico: uma função vê as variáveis do sítio onde foi definida, não as de quem a chama.

O ponto de partida tem âmbito dinâmico: o corpo de uma função corre no ambiente de quem a chama.
Cada caso diz no comentário o que dá com âmbito dinâmico (um valor errado ou "variável não
definida"). Os de recursão apanham as correções que estragam o `let rec` (a função não se vê a si
própria) ou o `let` simples (que não é recursivo: `let f = ... f ...` vê o f de fora).
Só há recursão pouco funda e nenhum `^`, para a T5 não depender da T2 nem da T6.
"""

import pytest

from calc import avaliar

CASOS = [
    pytest.param(
        "let x = 1 in let f = fn y => x + y in let x = 100 in f(10)",
        11,  # dinâmico: 100 + 10 = 110
        id="caso-do-bug",
    ),
    pytest.param(
        "let somar = fn a => fn b => a + b in somar(2)(3)",
        5,  # dinâmico: 'a' não definida
        id="funcao-que-devolve-funcao",
    ),
    pytest.param(
        "let vezes = fn n => fn x => x * n in"
        " let dobro = vezes(2) in let triplo = vezes(3) in dobro(10) + triplo(10)",
        50,  # 20 + 30; dinâmico: 'n' não definida
        id="cada-funcao-guarda-o-seu-n",
    ),
    pytest.param(
        "let y = 5 in let f = fn x => x + y in let g = fn y => f(y) in g(100)",
        105,  # f usa o y = 5 de fora; dinâmico: o y = 100 de g, 200
        id="parametro-de-quem-chama-com-o-mesmo-nome",
    ),
    pytest.param(
        "let f = let k = 7 in fn x => x * k in f(6)",
        42,  # dinâmico: 'k' não definida
        id="variavel-que-so-existe-onde-a-funcao-nasceu",
    ),
    pytest.param(
        "let duas_vezes = fn f => fn x => f(f(x)) in"
        " let mais3 = fn x => x + 3 in duas_vezes(mais3)(10)",
        16,  # dinâmico: 'f' não definida
        id="funcao-de-ordem-superior",
    ),
    pytest.param(
        "let x = 10 in let soma_x = fn y => y + x in let usar = fn x => soma_x(x) in usar(1)",
        11,  # 1 + 10; dinâmico: 1 + 1 = 2
        id="argumento-com-o-nome-de-uma-variavel-livre",
    ),
]

RECURSAO = [
    pytest.param(
        "let rec fact = fn n => if n == 0 then 1 else n * fact(n - 1) in fact(10)",
        3628800,  # já dava certo: a correção não pode estragar o let rec
        id="let-rec-continua-a-funcionar",
    ),
    pytest.param(
        "let passo = 2 in"
        " let rec contar = fn n => if n <= 0 then 0 else 1 + contar(n - passo) in"
        " let passo = 1 in contar(10)",
        5,  # 10, 8, 6, 4, 2 com o passo = 2 da definição; dinâmico: passo = 1, 10
        id="let-rec-ve-o-ambiente-da-definicao",
    ),
    pytest.param(
        "let rec potencia = fn b => fn e => if e == 0 then 1 else b * potencia(b)(e - 1) in"
        " potencia(2)(10)",
        1024,  # dinâmico: 'b' não definida
        id="let-rec-que-devolve-funcao",
    ),
    pytest.param(
        "let rec somatorio = fn n => if n == 0 then fn x => x else fn x => n + somatorio(n - 1)(x) in"
        " somatorio(4)(0)",
        10,  # 4 + 3 + 2 + 1 + 0: cada fecho guarda o seu n; dinâmico: 'n' não definida
        id="cada-nivel-guarda-o-seu-n",
    ),
    pytest.param(
        "let f = fn x => x + 1 in let f = fn x => f(x) * 2 in f(3)",
        8,  # o f de dentro chama o f de fora: (3 + 1) × 2; dinâmico: chama-se a si próprio sem fim
        id="let-simples-nao-e-recursivo",
    ),
]


@pytest.mark.parametrize(("programa", "valor"), CASOS)
def test_as_funcoes_veem_o_ambiente_onde_foram_definidas(programa, valor):
    assert avaliar(programa) == valor


@pytest.mark.parametrize(("programa", "valor"), RECURSAO)
def test_a_recursao_continua_a_funcionar(programa, valor):
    assert avaliar(programa) == valor
