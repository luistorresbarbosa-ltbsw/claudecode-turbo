"""T4 · Divisão inteira: `a // b` arredonda para baixo e `a % b` = a − b × (a // b).

Regras do prompt: // é o maior inteiro ≤ a/b (também nos negativos); % tem o sinal de b; ambos
funcionam com não inteiros, com resultados exatos; mesma precedência de * e /, à esquerda; dividir
por zero é ErroExecucao. Nenhum caso usa `^`, para a T4 não depender da T2.

Contas à mão nos comentários. Os erros que cada grupo apanha:
- truncar em vez de arredondar para baixo (int(a / b), math.fmod): os negativos;
- passar por float: 1/3 % (1/4) = 1/12 exato (em float dá 0.08333333333333331);
- precedência ou associatividade erradas: os casos de PRECEDENCIA, cada um com o valor errado ao lado;
- deixar escapar ZeroDivisionError: os erros têm de ser ErroExecucao.
"""

from fractions import Fraction

import pytest

from calc import avaliar
from calc.erros import ErroExecucao

DIVISAO_INTEIRA = [
    ("7 // 2", 3),
    ("-7 // 2", -4),  # -3.5 arredonda para baixo; truncar daria -3
    ("7 // -2", -4),
    ("-7 // -2", 3),
    ("6 // 3", 2),
    ("7.5 // 2", 3),
    ("-7.5 // 2", -4),  # -3.75 -> -4
    ("1 / 3 // (1 / 4)", 1),  # 4/3 -> 1
    ("0 // 5", 0),
]

RESTO = [
    ("7 % 3", 1),
    ("-7 % 2", 1),  # -7 − 2 × (-4); com o sinal de a (fmod) daria -1
    ("7 % -2", -1),  # 7 − (-2) × (-4)
    ("-7 % -2", -1),  # -7 − (-2) × 3
    ("6 % 3", 0),
    ("7.5 % 2", Fraction(3, 2)),
    ("-7.5 % 2", Fraction(1, 2)),  # -7.5 − 2 × (-4)
    ("1 / 3 % (1 / 4)", Fraction(1, 12)),  # 1/3 − 1/4 × 1
    ("0.3 % 0.1", 0),  # exato: 3/10 − 1/10 × 3; em float daria 0.09999999999999998
]

PRECEDENCIA = [
    ("1 + 7 % 4", 4),  # 1 + 3; se % viesse depois do +, (1 + 7) % 4 = 0
    ("2 * 7 % 4", 2),  # (2 * 7) % 4; se % viesse antes do *, 2 * 3 = 6
    ("7 % 4 * 2", 6),  # (7 % 4) * 2; se * viesse antes do %, 7 % 8 = 7
    ("100 // 7 // 2", 7),  # (100 // 7) // 2 = 14 // 2; à direita, 100 // 3 = 33
    ("20 // 6 / 3", 1),  # (20 // 6) / 3 = 3 / 3; se / viesse antes, 20 // 2 = 10
    ("20 / 6 // 3", 1),  # (20 / 6) // 3 = (10/3) // 3; se // viesse antes, 20 / 2 = 10
    ("-7 % 3", 2),  # (-7) % 3: o menos unário vem antes; -(7 % 3) daria -1
    ("10 - 7 // 2", 7),  # 10 − 3; se // viesse depois do −, 3 // 2 = 1
    ("7 // 2 * 2 + 7 % 2", 7),  # 3 × 2 + 1: a = b × (a // b) + a % b
]


def _ids(casos):
    return [programa for programa, _ in casos]


@pytest.mark.parametrize(("programa", "valor"), DIVISAO_INTEIRA, ids=_ids(DIVISAO_INTEIRA))
def test_divisao_inteira_arredonda_para_baixo(programa, valor):
    assert avaliar(programa) == valor


@pytest.mark.parametrize(("programa", "valor"), RESTO, ids=_ids(RESTO))
def test_resto_tem_o_sinal_do_divisor(programa, valor):
    assert avaliar(programa) == valor


@pytest.mark.parametrize(("programa", "valor"), PRECEDENCIA, ids=_ids(PRECEDENCIA))
def test_mesma_precedencia_do_produto_e_a_esquerda(programa, valor):
    assert avaliar(programa) == valor


@pytest.mark.parametrize(
    ("programa", "valor"),
    [("10 // 3 / 7", Fraction(3, 7)), ("10 % 4 / 7", Fraction(2, 7))],
    ids=["divisao-inteira", "resto"],
)
def test_os_resultados_continuam_exatos(programa, valor):
    # 3/7 e 2/7 não cabem num float: só dá igual se // e % devolveram números exatos
    assert avaliar(programa) == valor


@pytest.mark.parametrize("programa", ["1 // 0", "1 % 0", "5 % (2 - 2)", "0.5 // 0"])
def test_dividir_por_zero_e_erro_de_execucao(programa):
    with pytest.raises(ErroExecucao):
        avaliar(programa)
