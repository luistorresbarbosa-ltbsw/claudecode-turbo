"""T2 · Potência à direita: `2^3^2` é `2^(3^2)` = 512, e o resto da precedência não muda.

O ponto de partida associa `^` à esquerda: 2^3^2 = (2^3)^2 = 64. Cada caso de A_DIREITA dá outro
valor à esquerda (está no comentário). Os de NAO_MUDA já davam certo e apanham correções que
estragam o resto: pôr tudo a associar à direita, ou mudar a precedência do menos unário ou do
produto. Nenhum expoente é negativo sem parênteses (`2^-1`), que a T2 não pede.
"""

from fractions import Fraction

import pytest

from calc import avaliar

A_DIREITA = [
    ("2^3^2", 512),  # 2^9; à esquerda, (2^3)^2 = 64
    ("2 ^ 2 ^ 3", 256),  # 2^8; à esquerda, (2^2)^3 = 64
    ("2^3^2^0", 8),  # 2^(3^(2^0)) = 2^3; à esquerda, ((2^3)^2)^0 = 1
    ("10 ^ 2 ^ 0 ^ 5", 10),  # 10^(2^(0^5)) = 10^1; à esquerda, ((10^2)^0)^5 = 1
    ("3 ^ 1 ^ 2 * 2", 6),  # 3^(1^2) * 2; à esquerda, (3^1)^2 * 2 = 18
    ("(1 / 2) ^ 3 ^ 2", Fraction(1, 512)),  # (1/2)^9; à esquerda, (1/8)^2 = 1/64
]

NAO_MUDA = [
    ("(2^3)^2", 64),  # os parênteses continuam a mandar
    ("-2^2", -4),  # a potência vem antes do menos unário: -(2^2)
    ("2 * 3 ^ 2", 18),  # e antes do produto: 2 * 9
    ("2 ^ 3 * 2", 16),  # (2^3) * 2, e não 2^(3*2) = 64
    ("100 - 20 - 5", 75),  # a subtração continua à esquerda (à direita daria 85)
    ("64 / 4 / 2", 8),  # e a divisão também (à direita daria 32)
    ("1 - 2 + 3", 2),  # (1 - 2) + 3 (à direita daria -4)
]


@pytest.mark.parametrize(("programa", "valor"), A_DIREITA, ids=[p for p, _ in A_DIREITA])
def test_a_potencia_associa_a_direita(programa, valor):
    assert avaliar(programa) == valor


@pytest.mark.parametrize(("programa", "valor"), NAO_MUDA, ids=[p for p, _ in NAO_MUDA])
def test_o_resto_da_precedencia_nao_muda(programa, valor):
    assert avaliar(programa) == valor
