"""T5 · JSON + CLI: fatura.io.para_json/de_json e `python -m fatura total ficheiro.json`.

O formato JSON é o do prompt: chaves com os nomes dos campos e decimais como strings.
As faturas do CLI não precisam de arredondamento nenhum (todas as linhas e todos os IVAs dão
cêntimos exatos), para a T5 não depender de como a T4 arredonda: só conta a leitura do JSON,
o desconto, as taxas da região e o formato "Total: 1 234,56 €".
"""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import fatura
import pytest
from fatura.io import de_json, para_json
from fatura.modelo import Fatura, Linha

RAIZ = Path(next(iter(fatura.__path__))).resolve().parent  # pasta do braço
CAMPOS_DECIMAIS = ("quantidade", "preco_unitario", "desconto_pct")

TEXTO = """{
  "numero": "FT 2026/7",
  "regiao": "PT-MA",
  "linhas": [
    {
      "descricao": "Bolo de mel (unidade)",
      "quantidade": "2",
      "preco_unitario": "6.35",
      "taxa": "INT",
      "desconto_pct": "0"
    },
    {
      "descricao": "Queijo fresco (kg)",
      "quantidade": "1.250",
      "preco_unitario": "0.10",
      "taxa": "RED",
      "desconto_pct": "12.5"
    }
  ]
}"""

FATURA = Fatura(
    numero="FT 2026/12",
    regiao="PT-AC",
    linhas=[
        Linha(
            descricao="Pastéis de nata (caixa de 6)",
            quantidade=Decimal(3),
            preco_unitario=Decimal("7.20"),
            taxa="RED",
            desconto_pct=Decimal(0),
        ),
        Linha(
            descricao="Café «Aurora», lote especial (kg)",
            quantidade=Decimal("1.250"),
            preco_unitario=Decimal("18.90"),
            taxa="NOR",
            desconto_pct=Decimal("12.5"),
        ),
    ],
)


def _campos(f):
    return (
        f.numero,
        f.regiao,
        [
            (l.descricao, l.quantidade, l.preco_unitario, l.taxa, l.desconto_pct)
            for l in f.linhas
        ],
    )


def _decimais_nao_decimal(f):
    return [
        (i, campo, type(getattr(l, campo)).__name__)
        for i, l in enumerate(f.linhas, start=1)
        for campo in CAMPOS_DECIMAIS
        if not isinstance(getattr(l, campo), Decimal)
    ]


def test_de_json_le_o_formato_do_prompt():
    f = de_json(TEXTO)

    assert _campos(f) == (
        "FT 2026/7",
        "PT-MA",
        [
            ("Bolo de mel (unidade)", Decimal(2), Decimal("6.35"), "INT", Decimal(0)),
            # "0.10" lido por float daria 0.1000000000000000055511151231257827...
            (
                "Queijo fresco (kg)",
                Decimal("1.250"),
                Decimal("0.10"),
                "RED",
                Decimal("12.5"),
            ),
        ],
    )
    assert _decimais_nao_decimal(f) == []


def test_para_json_escreve_os_decimais_como_strings():
    dados = json.loads(para_json(FATURA))

    assert (dados["numero"], dados["regiao"]) == ("FT 2026/12", "PT-AC")
    assert len(dados["linhas"]) == len(FATURA.linhas)
    for escrita, linha in zip(dados["linhas"], FATURA.linhas):
        assert (escrita["descricao"], escrita["taxa"]) == (linha.descricao, linha.taxa)
        for campo in CAMPOS_DECIMAIS:
            assert isinstance(escrita[campo], str), (
                f"{campo} devia ser string: {escrita[campo]!r}"
            )
            assert Decimal(escrita[campo]) == getattr(linha, campo)


def test_ida_e_volta_devolve_a_mesma_fatura():
    volta = de_json(para_json(FATURA))

    assert _campos(volta) == _campos(FATURA)
    assert _decimais_nao_decimal(volta) == []


def test_ida_e_volta_nao_passa_por_float():
    # Mais algarismos significativos do que um float guarda (~17): só sobrevivem sem float.
    f = Fatura(
        numero="FT 2026/13",
        regiao="PT",
        linhas=[
            Linha(
                descricao="Massa folhada (kg)",
                quantidade=Decimal("0.333333333333333333"),
                preco_unitario=Decimal("1234567890.123456789"),
                taxa="RED",
                desconto_pct=Decimal(0),
            )
        ],
    )

    volta = de_json(para_json(f))

    assert volta.linhas[0].quantidade == Decimal("0.333333333333333333")
    assert volta.linhas[0].preco_unitario == Decimal("1234567890.123456789")


CLI = [
    pytest.param(
        "PT",
        [
            ("Revisão da máquina de café", "1", "195.00", "NOR", "0"),  # 195.00
            ("Moinho de café profissional", "1", "450.00", "NOR", "10"),  # 405.00
            ("Vinho tinto (caixa de 6)", "7", "41.00", "INT", "0"),  # 287.00
            ("Farinha T65 (saco de 25 kg)", "5", "32.50", "RED", "0"),  # 162.50
        ],
        # NOR 600.00 + 138.00; INT 287.00 + 37.31; RED 162.50 + 9.75 = 1234.56
        "Total: 1 234,56 €",
        id="milhares-com-desconto",
    ),
    pytest.param(
        "PT-AC",
        [
            ("Bolo-rei (unidade)", "2", "15.00", "NOR", "0"),  # 30.00 + 16 % = 34.80
            ("Menu do dia", "3", "8.00", "INT", "0"),  # 24.00 + 9 % = 26.16
            ("Pão de forma", "24", "1.50", "RED", "0"),  # 36.00 + 4 % = 37.44
        ],
        # com as taxas do continente daria 102,18
        "Total: 98,40 €",
        id="acores-sem-milhares",
    ),
    pytest.param(
        "PT",
        [
            # 1000000.00 + 230000.00; 5.00 + 0.65; 160 × 26.90 = 4304.00 + 258.24
            ("Linha de produção (instalação)", "1", "1000000.00", "NOR", "0"),
            ("Garrafa de vinho do Porto", "1", "5.00", "INT", "0"),
            ("Farinha T65 (saco de 25 kg)", "160", "26.90", "RED", "0"),
        ],
        # 1230000.00 + 5.65 + 4562.24 = 1234567.89
        "Total: 1 234 567,89 €",
        id="milhoes",
    ),
]


@pytest.mark.parametrize(("regiao", "linhas", "esperado"), CLI)
def test_cli_imprime_o_total(tmp_path, regiao, linhas, esperado):
    ficheiro = tmp_path / "fatura.json"
    dados = {
        "numero": "FT 2026/50",
        "regiao": regiao,
        "linhas": [
            {
                "descricao": descricao,
                "quantidade": quantidade,
                "preco_unitario": preco,
                "taxa": taxa,
                "desconto_pct": desconto,
            }
            for descricao, quantidade, preco, taxa, desconto in linhas
        ],
    }
    ficheiro.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ambiente = {
        **os.environ,
        "PYTHONPATH": str(RAIZ),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }

    resultado = subprocess.run(
        [sys.executable, "-m", "fatura", "total", str(ficheiro)],
        check=False,
        cwd=RAIZ,
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == esperado
