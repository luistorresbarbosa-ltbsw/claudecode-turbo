import pytest
from fatura.nif import digito_de_controlo, valido


@pytest.mark.parametrize(
    ("oito", "controlo"),
    [
        ("12345678", 9),  # soma 156, resto 2 -> 11 - 2 = 9
        ("29999999", 8),  # soma 333, resto 3 -> 8
        ("12345677", 0),  # soma 154, resto 0 -> 11, que vale 0
        ("50000000", 0),  # soma 45, resto 1 -> 10, que vale 0
    ],
)
def test_digito_de_controlo(oito, controlo):
    assert digito_de_controlo(oito) == controlo


@pytest.mark.parametrize(
    "nif", ["123456789", "299999998", "500000000", "100000002", "123 456 789"]
)
def test_aceita_nifs_validos(nif):
    assert valido(nif) is True


@pytest.mark.parametrize(
    "nif",
    [
        "123456788",  # controlo errado
        "12345678",  # 8 dígitos
        "1234567890",  # 10 dígitos
        "12345678X",  # letra
        "",
        "023456787",  # prefixo 0, controlo certo
        "423456784",  # prefixo 42, controlo certo
    ],
)
def test_recusa_nifs_invalidos(nif):
    assert valido(nif) is False
