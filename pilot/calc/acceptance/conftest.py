"""Rede de segurança da aceitação: nenhum teste fica pendurado.

O harness corta o pytest aos 300 s e, se isso acontecer, o piloto inteiro para. Por isso cada teste
tem um limite (10 s, ou o da marca `tempo_maximo`) e o ficheiro todo tem 200 s: um ciclo infinito no
código do braço chumba esse teste, e só esse, em vez de pendurar a corrida. Os limites estão muito
acima do que uma solução correta precisa; não medem desempenho (isso é a T6, com os seus limites).
"""

import signal
import time

import pytest

LIMITE_POR_TESTE = 10  # segundos
LIMITE_DO_FICHEIRO = 200  # segundos, abaixo dos 300 s do harness
_INICIO = time.monotonic()


@pytest.fixture(autouse=True)
def _sem_ficar_pendurado(request):
    if not hasattr(signal, "setitimer"):  # sem SIGALRM (Windows): corre sem rede
        yield
        return
    marca = request.node.get_closest_marker("tempo_maximo")
    limite = marca.args[0] if marca else LIMITE_POR_TESTE
    restante = LIMITE_DO_FICHEIRO - (time.monotonic() - _INICIO)
    if restante < 1:
        pytest.fail(f"o ficheiro passou dos {LIMITE_DO_FICHEIRO} s", pytrace=False)
    limite = min(limite, restante)

    def esgotado(_sinal, _frame):
        pytest.fail(f"o teste passou dos {limite:.0f} s", pytrace=False)

    anterior = signal.signal(signal.SIGALRM, esgotado)
    signal.setitimer(signal.ITIMER_REAL, limite)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, anterior)
