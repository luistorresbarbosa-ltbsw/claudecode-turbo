import json
from decimal import Decimal

import pytest
from fatura.__main__ import euros, main
from fatura.io import de_json, para_json
from fatura.modelo import Fatura, Linha

FATURA = Fatura(
    "FT 2026/9",
    "PT-MA",
    [
        Linha("Bolo de mel", Decimal(2), Decimal("6.35"), "INT"),
        Linha(
            "Queijo fresco (kg)",
            Decimal("1.250"),
            Decimal("3.94"),
            "RED",
            Decimal("12.5"),
        ),
    ],
)


def test_ida_e_volta():
    assert de_json(para_json(FATURA)) == FATURA


def test_decimais_vao_como_strings():
    linha = json.loads(para_json(FATURA))["linhas"][1]

    assert linha == {
        "descricao": "Queijo fresco (kg)",
        "quantidade": "1.250",
        "preco_unitario": "3.94",
        "taxa": "RED",
        "desconto_pct": "12.5",
    }


def test_recusa_decimais_escritos_como_numeros_json():
    texto = para_json(FATURA).replace('"6.35"', "6.35")

    with pytest.raises(ValueError, match=r"linhas\[1\]\.preco_unitario"):
        de_json(texto)


@pytest.mark.parametrize(
    ("valor", "texto"),
    [
        ("0", "0,00 €"),
        ("98.4", "98,40 €"),
        ("1000", "1 000,00 €"),
        ("1234567.89", "1 234 567,89 €"),
    ],
)
def test_euros(valor, texto):
    assert euros(Decimal(valor)) == texto


def test_comando_total(tmp_path, capsys):
    # 1003.71 + IVA 23 % (230.8533 -> 230.85) = 1234.56
    ficheiro = tmp_path / "fatura.json"
    ficheiro.write_text(
        para_json(
            Fatura(
                "FT 2026/10",
                "PT",
                [Linha("Forno", Decimal(1), Decimal("1003.71"), "NOR")],
            )
        ),
        encoding="utf-8",
    )

    assert main(["total", str(ficheiro)]) == 0
    assert capsys.readouterr().out == "Total: 1 234,56 €\n"


def test_comando_total_com_ficheiro_que_nao_existe(tmp_path, capsys):
    assert main(["total", str(tmp_path / "nao-existe.json")]) == 1
    assert "nao-existe.json" in capsys.readouterr().err
