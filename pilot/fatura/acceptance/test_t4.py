"""T4 · Totais da fatura: fatura.totais.calcular(f) contra 4 faturas calculadas à mão.

Regras do prompt: total de cada linha = quantidade × preço × (1 − desconto_pct/100), arredondado
a 2 casas (ROUND_HALF_UP) uma só vez; por taxa, base = soma das linhas e IVA = base × taxa da
região, arredondado a 2 casas; sem_iva = soma das bases; iva = soma dos IVAs; total = sem_iva + iva.

Cada fatura apanha um erro diferente:
- continente: .xx5 nas linhas (HALF_EVEN e float dão menos 1 cêntimo) e arredondar só no fim;
- desconto de 12,5 %: .xx5 depois do desconto, arredondar o valor do desconto à parte, 3 taxas;
- Açores: IVA por taxa ≠ soma do IVA por linha, e um .xx5 no IVA;
- Madeira: quantidades fracionadas, arredondamento duplo (antes e depois do desconto).
Nenhuma fatura usa a taxa normal da Madeira (o bug da T2), para a T4 não depender da T2.
"""

from decimal import Decimal

import pytest
from fatura.modelo import Fatura, Linha
from fatura.totais import calcular


def _linha(descricao, quantidade, preco, taxa, desconto="0"):
    return Linha(
        descricao=descricao,
        quantidade=Decimal(quantidade),
        preco_unitario=Decimal(preco),
        taxa=taxa,
        desconto_pct=Decimal(desconto),
    )


CASOS = [
    pytest.param(
        Fatura(
            numero="FT 2026/101",
            regiao="PT",
            linhas=[
                # 1.5 × 2.43 = 3.645 -> 3.65
                _linha("Farinha de trigo T65 (kg)", "1.5", "2.43", "RED"),
                _linha("Manteiga sem sal (kg)", "0.5", "4.13", "RED"),  # 2.065 -> 2.07
                _linha("Formas de papel (pack de 100)", "2", "3.75", "NOR"),  # 7.50
            ],
        ),
        {
            "linhas": ["3.65", "2.07", "7.50"],
            "por_taxa": {
                "RED": ("5.72", "0.34"),  # 5.72 × 0.06 = 0.3432
                "NOR": ("7.50", "1.73"),  # 7.50 × 0.23 = 1.725
            },
            "sem_iva": "13.22",
            "iva": "2.07",
            "total": "15.29",
        },
        id="continente-arredondamento-xx5",
    ),
    pytest.param(
        Fatura(
            numero="FT 2026/102",
            regiao="PT",
            linhas=[
                # 89.90 × 0.875 = 78.6625 -> 78.66
                _linha("Máquina de café (aluguer mensal)", "1", "89.90", "NOR", "12.5"),
                # 6 × 20.50 = 123.00; × 0.875 = 107.625 -> 107.63
                _linha("Café em grão (kg)", "6", "20.50", "NOR", "12.5"),
                _linha("Leite meio-gordo (l)", "24", "0.89", "RED"),  # 21.36
                _linha("Vinho do Porto (garrafa)", "2", "14.95", "INT"),  # 29.90
            ],
        ),
        {
            "linhas": ["78.66", "107.63", "21.36", "29.90"],
            "por_taxa": {
                "NOR": ("186.29", "42.85"),  # 186.29 × 0.23 = 42.8467
                "RED": ("21.36", "1.28"),  # 21.36 × 0.06 = 1.2816
                "INT": ("29.90", "3.89"),  # 29.90 × 0.13 = 3.887
            },
            "sem_iva": "237.55",
            "iva": "48.02",
            "total": "285.57",
        },
        id="continente-desconto-12.5-tres-taxas",
    ),
    pytest.param(
        Fatura(
            numero="FT 2026/103",
            regiao="PT-AC",
            linhas=[
                _linha("Bolo-rei (unidade)", "1", "14.10", "NOR"),  # 14.10
                _linha("Caixa de oferta", "3", "1.70", "NOR"),  # 5.10
                _linha("Menu do dia", "5", "2.50", "INT"),  # 12.50
                _linha("Pão de forma", "3", "1.85", "RED"),  # 5.55
            ],
        ),
        {
            "linhas": ["14.10", "5.10", "12.50", "5.55"],
            "por_taxa": {
                # 19.20 × 0.16 = 3.072; por linha daria 2.256 -> 2.26 e 0.816 -> 0.82, soma 3.08
                "NOR": ("19.20", "3.07"),
                "INT": ("12.50", "1.13"),  # 12.50 × 0.09 = 1.125
                "RED": ("5.55", "0.22"),  # 5.55 × 0.04 = 0.222
            },
            "sem_iva": "37.25",
            "iva": "4.42",
            "total": "41.67",
        },
        id="acores-iva-por-taxa",
    ),
    pytest.param(
        Fatura(
            numero="FT 2026/104",
            regiao="PT-MA",
            linhas=[
                # 2.5 × 8.45 = 21.125; × 0.875 = 18.484375 -> 18.48
                _linha("Fruta da época (kg)", "2.5", "8.45", "RED", "12.5"),
                _linha("Bolo de mel (unidade)", "4", "6.35", "INT"),  # 25.40
                _linha("Queijo fresco (kg)", "1.25", "3.94", "RED"),  # 4.925 -> 4.93
            ],
        ),
        {
            "linhas": ["18.48", "25.40", "4.93"],
            "por_taxa": {
                "RED": ("23.41", "0.94"),  # 23.41 × 0.04 = 0.9364
                "INT": ("25.40", "3.05"),  # 25.40 × 0.12 = 3.048
            },
            "sem_iva": "48.81",
            "iva": "3.99",
            "total": "52.80",
        },
        id="madeira-quantidades-fracionadas",
    ),
]


def _taxas_presentes(por_taxa):
    # Tolera entradas a zero para taxas que não aparecem na fatura, e (base, iva) em lista ou tuplo.
    return {
        taxa: tuple(par)
        for taxa, par in por_taxa.items()
        if any(valor != 0 for valor in par)
    }


@pytest.mark.parametrize(("fatura", "esperado"), CASOS)
def test_totais_calculados_a_mao(fatura, esperado):
    totais = calcular(fatura)

    assert list(totais.linhas) == [Decimal(v) for v in esperado["linhas"]]
    assert _taxas_presentes(totais.por_taxa) == {
        taxa: (Decimal(base), Decimal(iva))
        for taxa, (base, iva) in esperado["por_taxa"].items()
    }
    assert totais.sem_iva == Decimal(esperado["sem_iva"])
    assert totais.iva == Decimal(esperado["iva"])
    assert totais.total == Decimal(esperado["total"])


@pytest.mark.parametrize(("fatura", "esperado"), CASOS)
def test_todos_os_valores_sao_decimal(fatura, esperado):
    totais = calcular(fatura)

    valores = [
        *totais.linhas,
        *(valor for par in totais.por_taxa.values() for valor in par),
        totais.sem_iva,
        totais.iva,
        totais.total,
    ]
    assert [type(v).__name__ for v in valores if not isinstance(v, Decimal)] == []
