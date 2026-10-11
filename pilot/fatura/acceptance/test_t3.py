"""T3 · Validar NIF: fatura.nif.valido(nif) aceita NIFs certos e recusa os errados.

Dígitos de controlo calculados à mão: pesos 9, 8, ..., 2 sobre os 8 primeiros dígitos;
controlo = 11 − (soma mod 11), e 0 quando isso dá 10 ou 11.
Só se usam prefixos sem ambiguidade: válidos 1, 2 e 5; inválidos 0 e 4 (fora do 45).
Os NIFs com prefixo inválido têm o dígito de controlo certo, para ser o prefixo a recusá-los.
"""

import pytest
from fatura.nif import valido

VALIDOS = [
    ("123456789", "soma 156, resto 2, controlo 9"),
    ("212345672", "prefixo 2: soma 130, resto 9, controlo 2"),
    ("512345678", "prefixo 5: soma 157, resto 3, controlo 8"),
    ("123456770", "soma 154, resto 0: 11 − 0 = 11, controlo 0"),
    ("123456720", "soma 144, resto 1: 11 − 1 = 10, controlo 0"),
    ("123 456 789", "espaços entre os dígitos"),
    ("512 345 678", "espaços entre os dígitos, prefixo 5"),
]

INVALIDOS = [
    ("123456780", "controlo errado: devia ser 9"),
    ("123456771", "resto 0 dá controlo 0, não 1"),
    ("12345678", "8 dígitos"),
    ("1234567890", "10 dígitos"),
    ("12345678A", "letra no lugar do controlo"),
    ("1234S6789", "letra no meio"),
    ("ABCDEFGHI", "só letras"),
    ("", "vazio"),
    ("012345679", "prefixo 0, controlo certo: soma 112, resto 2, controlo 9"),
    ("000000000", "prefixo 0, controlo certo: soma 0, controlo 0"),
    ("412345676", "prefixo 41, controlo certo: soma 148, resto 5, controlo 6"),
    ("401234568", "prefixo 40, controlo certo: soma 113, resto 3, controlo 8"),
]


@pytest.mark.parametrize(("nif", "porque"), VALIDOS, ids=[nif for nif, _ in VALIDOS])
def test_aceita_nif_valido(nif, porque):
    assert valido(nif) is True, porque  # -> bool: True, não só "verdadeiro"


@pytest.mark.parametrize(
    ("nif", "porque"), INVALIDOS, ids=[nif or "vazio" for nif, _ in INVALIDOS]
)
def test_recusa_nif_invalido(nif, porque):
    assert valido(nif) is False, porque  # -> bool: False, não None
