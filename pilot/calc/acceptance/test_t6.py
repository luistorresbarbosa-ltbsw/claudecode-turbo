"""T6 · Chamadas em cauda: 100 000 chamadas em cauda correm a tempo e a pilha do Python não cresce.

Os programas fundos correm num processo à parte, com um limite de tempo: uma solução que rebenta a
pilha (ou o processo) chumba esse teste sem levar a aceitação atrás. O tempo é o de `avaliar`, medido
lá dentro. O exemplo do prompt (`contar(100000)`) tem os 10 s que o prompt promete; os outros dois têm
o mesmo número de chamadas, mais trabalho por volta (~1,25× na referência), e por isso 15 s. A
referência faz cada um em ~0,3 s.

"Não fazer crescer a pilha do Python" mede-se diretamente: com um sys.setprofile (e
threading.setprofile, para quem avalie noutra thread) conta-se a profundidade máxima da pilha do
Python com 1 000 e com 20 000 chamadas em cauda. Tem de ser a mesma, com folga para ruído. Aumentar o
limite de recursão (o prompt diz que não resolve) deixa a profundidade crescer com o número de
chamadas, e chumba aqui.

Para a T6 não depender da T5, nenhum programa depende da regra de âmbito: não há funções que devolvem
funções com variáveis livres, nem nomes tapados entre a definição e a chamada. Dão o mesmo com âmbito
dinâmico (o ponto de partida) e léxico. A recursão que não é em cauda só vai até 20 níveis.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import calc
from calc import avaliar
from calc.erros import ErroExecucao

RAIZ = Path(next(iter(calc.__path__))).resolve().parent  # pasta do braço
ESPERA = 30  # segundos até matar o processo à parte

CONTAR = "let rec contar = fn n => if n == 0 then 0 else contar(n - 1) in contar(NIVEIS)"
# a chamada em cauda está no ramo then de um if que é o corpo de um let; descer(3k + 1) dá 1
DESCER = (
    "let rec descer = fn n => let m = n - 3 in if m >= 0 then descer(m) else n in"
    " descer(NIVEIS)"
)
# ping chama pong e pong chama ping, sempre em cauda: nenhuma se chama a si própria
PING_PONG = (
    "let rec ping = fn n =>"
    " let pong = fn m => if m == 0 then 7 else ping(m - 1) in pong(n) in"
    " ping(NIVEIS)"
)

CORRER = r"""
import json, sys, time
from calc import avaliar
programa = sys.stdin.read()
inicio = time.perf_counter()
valor = avaliar(programa)
print(json.dumps({"valor": str(valor), "segundos": time.perf_counter() - inicio}))
"""

PROFUNDIDADE = r"""
import json, sys, threading
from calc import avaliar

atual, maxima = {}, 0

def perfil(_frame, evento, _arg):
    global maxima
    if evento == "call":
        fio = threading.get_ident()
        atual[fio] = atual.get(fio, 0) + 1
        maxima = max(maxima, atual[fio])
    elif evento == "return":
        fio = threading.get_ident()
        atual[fio] = atual.get(fio, 0) - 1

def medir(programa):
    global maxima
    atual.clear()
    maxima = 0
    threading.setprofile(perfil)
    sys.setprofile(perfil)
    try:
        valor = avaliar(programa)
    finally:
        sys.setprofile(None)
        threading.setprofile(None)
    return {"valor": str(valor), "profundidade": maxima}

modelo = sys.stdin.read()
print(json.dumps([medir(modelo.replace("NIVEIS", n)) for n in ("1000", "20000")]))
"""


def _a_parte(script: str, entrada: str) -> object:
    """Corre `script` noutro processo, na pasta do braço, e devolve o JSON da última linha."""
    try:
        processo = subprocess.run(
            [sys.executable, "-c", script],
            input=entrada,
            cwd=RAIZ,
            env={**os.environ, "PYTHONPATH": str(RAIZ), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=ESPERA,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"não acabou em {ESPERA} s", pytrace=False)
    assert processo.returncode == 0, processo.stderr[-3000:]
    return json.loads(processo.stdout.strip().splitlines()[-1])


FUNDOS = [  # programa, níveis, valor, limite em segundos
    pytest.param(CONTAR, "100000", "0", 10, id="exemplo-do-prompt"),  # o que o prompt promete
    pytest.param(DESCER, "300001", "1", 15, id="then-dentro-de-um-let"),  # 100 000 chamadas
    pytest.param(PING_PONG, "50000", "7", 15, id="ping-pong"),  # 50 001 + 50 001 chamadas
]


@pytest.mark.tempo_maximo(ESPERA + 5)
@pytest.mark.parametrize(("modelo", "niveis", "valor", "limite"), FUNDOS)
def test_100000_chamadas_em_cauda_a_tempo(modelo, niveis, valor, limite):
    resultado = _a_parte(CORRER, modelo.replace("NIVEIS", niveis))

    assert resultado["valor"] == valor
    assert resultado["segundos"] < limite, f"demorou {resultado['segundos']:.1f} s"


@pytest.mark.tempo_maximo(ESPERA + 5)
@pytest.mark.parametrize(
    ("modelo", "valor"),
    [(CONTAR, "0"), (PING_PONG, "7")],
    ids=["contar", "ping-pong"],
)
def test_a_pilha_do_python_nao_cresce_com_as_chamadas_em_cauda(modelo, valor):
    mil, vinte_mil = _a_parte(PROFUNDIDADE, modelo)

    assert (mil["valor"], vinte_mil["valor"]) == (valor, valor)
    assert vinte_mil["profundidade"] <= mil["profundidade"] + 50, (
        f"a pilha cresceu: {mil['profundidade']} quadros com 1 000 chamadas, "
        f"{vinte_mil['profundidade']} com 20 000"
    )


RESULTADOS = [
    ("let rec fact = fn n => if n == 0 then 1 else n * fact(n - 1) in fact(20)", 2432902008176640000),
    ("let rec fib = fn n => if n < 2 then n else fib(n - 1) + fib(n - 2) in fib(15)", 610),
    ("let rec soma = fn n => if n == 0 then 0 else n + soma(n - 1) in soma(20)", 210),
    ("let rec contar = fn n => if n == 0 then 0 else contar(n - 1) in contar(10)", 0),
    ("let rec f = fn n => if n == 0 then fn x => x + 1 else f(n - 1) in f(10)(5)", 6),
    ("let dobro = fn x => x * 2 in let rec f = fn n => if n == 0 then 0 else f(dobro(n) - n - 1) in f(30)", 0),
    ("let rec par = fn n => if n == 0 then true else if n == 1 then false else par(n - 2) in par(11)", False),
    ("let escolher = fn c => if c then 1 else 2 in escolher(1 < 2) * 10 + escolher(2 < 1)", 12),
    ("1 + (if 1 < 2 then 2 else 3)", 3),
    ("(let a = 2 in a * 3) + 1", 7),
    ("(fn x => x * x)((fn y => y + 1)(2))", 9),
]


@pytest.mark.parametrize(("programa", "valor"), RESULTADOS, ids=[p[:50] for p, _ in RESULTADOS])
def test_os_resultados_nao_mudam(programa, valor):
    resultado = avaliar(programa)

    assert resultado == valor
    assert isinstance(resultado, bool) == isinstance(valor, bool)  # False não é 0


@pytest.mark.parametrize(
    "programa",
    [
        "let rec f = fn n => if n == 0 then y else f(n - 1) in f(3)",  # y não está definida
        "let rec f = fn n => if n == 0 then 1(2) else f(n - 1) in f(3)",  # 1 não é uma função
        "let rec f = fn n => if n == 0 then 1 / 0 else f(n - 1) in f(3)",
    ],
    ids=["variavel-nao-definida", "chamar-um-numero", "divisao-por-zero"],
)
def test_os_erros_na_cauda_continuam_a_ser_erros(programa):
    with pytest.raises(ErroExecucao):
        avaliar(programa)
