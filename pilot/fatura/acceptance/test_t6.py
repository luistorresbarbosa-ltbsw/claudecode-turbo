"""T6 · O cêntimo que falta: nota de crédito parcial da FT 2026/31.

Caso reportado: creditar 3 unidades da linha 2 (12,50 €, IVA normal 23 %).
  base 3 × 12.50 = 37.50; IVA 37.50 × 0.23 = 8.625 -> 8.63 (ROUND_HALF_UP); total 46.13.
  O módulo injetado dá 8.62 / 46.12: o float, e também o Decimal com HALF_EVEN, descem o .xx5.
Os outros casos dão o mesmo antes e depois da correção (não há .xx5 no IVA deles); servem para
apanhar correções que mudam o resto do comportamento. Contas à mão nos comentários.
"""

from decimal import Decimal
from pathlib import Path

import fatura
import pytest
from fatura.modelo import Fatura, Linha
from fatura.notas_credito import ler_fatura, nota_credito

RAIZ = Path(next(iter(fatura.__path__))).resolve().parent  # pasta do braço
EXEMPLO = RAIZ / "exemplos" / "ft-2026-31.json"


def _linha(descricao, quantidade, preco, taxa, desconto="0"):
    return Linha(
        descricao=descricao,
        quantidade=Decimal(quantidade),
        preco_unitario=Decimal(preco),
        taxa=taxa,
        desconto_pct=Decimal(desconto),
    )


# A mesma fatura que exemplos/ft-2026-31.json, escrita à mão.
FT_2026_31 = Fatura(
    numero="FT 2026/31",
    regiao="PT",
    linhas=[
        _linha("Café em grão, lote da casa (kg)", "20", "16.40", "NOR"),
        _linha("Chávena de café em porcelana", "24", "12.50", "NOR"),
        _linha("Açúcar em pacotes (caixa de 1000)", "6", "21.30", "RED", "12.5"),
        _linha("Vinho tinto do Douro (garrafa de 0,75 l)", "12", "7.85", "INT"),
    ],
)


def _resumo(nota):
    return {
        "por_taxa": {taxa: tuple(par) for taxa, par in nota.por_taxa.items()},
        "base": nota.base,
        "iva": nota.iva,
        "total": nota.total,
    }


def _esperado(por_taxa, base, iva, total):
    return {
        "por_taxa": {
            taxa: (Decimal(b), Decimal(i)) for taxa, (b, i) in por_taxa.items()
        },
        "base": Decimal(base),
        "iva": Decimal(iva),
        "total": Decimal(total),
    }


def test_caso_reportado_tem_o_centimo_certo():
    nota = nota_credito(ler_fatura(EXEMPLO), {2: Decimal(3)})

    assert nota.total == Decimal("46.13")
    assert _resumo(nota) == _esperado(
        {"NOR": ("37.50", "8.63")}, "37.50", "8.63", "46.13"
    )


def test_le_a_fatura_do_exemplo():
    lida = ler_fatura(EXEMPLO)

    def campos(l):
        return (l.descricao, l.quantidade, l.preco_unitario, l.taxa, l.desconto_pct)

    assert (lida.numero, lida.regiao) == (FT_2026_31.numero, FT_2026_31.regiao)
    assert [campos(l) for l in lida.linhas] == [campos(l) for l in FT_2026_31.linhas]


OUTROS_CASOS = [
    pytest.param(
        {1: "1"},
        # 16.40 × 0.23 = 3.772 -> 3.77
        _esperado({"NOR": ("16.40", "3.77")}, "16.40", "3.77", "20.17"),
        id="uma-unidade-da-linha-1",
    ),
    pytest.param(
        {3: "6"},
        # 6 × 21.30 × 0.875 = 111.825 -> 111.83; 111.83 × 0.06 = 6.7098 -> 6.71
        _esperado({"RED": ("111.83", "6.71")}, "111.83", "6.71", "118.54"),
        id="linha-3-inteira-com-desconto",
    ),
    pytest.param(
        {1: "3", 2: "1"},
        # 49.20 + 12.50 = 61.70; 61.70 × 0.23 = 14.191 -> 14.19 (por linha daria 11.32 + 2.88)
        _esperado({"NOR": ("61.70", "14.19")}, "61.70", "14.19", "75.89"),
        id="duas-linhas-da-mesma-taxa",
    ),
    pytest.param(
        {1: "1", 3: "2", 4: "1"},
        # NOR 16.40 -> 3.77; RED 2 × 21.30 × 0.875 = 37.275 -> 37.28, × 0.06 = 2.2368 -> 2.24;
        # INT 7.85 × 0.13 = 1.0205 -> 1.02
        _esperado(
            {
                "NOR": ("16.40", "3.77"),
                "RED": ("37.28", "2.24"),
                "INT": ("7.85", "1.02"),
            },
            "61.53",
            "7.03",
            "68.56",
        ),
        id="tres-taxas",
    ),
]


@pytest.mark.parametrize(("creditar", "esperado"), OUTROS_CASOS)
def test_outros_casos_nao_mudam(creditar, esperado):
    nota = nota_credito(
        FT_2026_31, {linha: Decimal(q) for linha, q in creditar.items()}
    )

    assert _resumo(nota) == esperado
    valores = [
        nota.base,
        nota.iva,
        nota.total,
        *(v for par in nota.por_taxa.values() for v in par),
    ]
    assert all(isinstance(v, Decimal) for v in valores)


def test_nao_credita_mais_do_que_foi_faturado():
    with pytest.raises(ValueError):
        nota_credito(FT_2026_31, {2: Decimal(25)})  # a linha 2 tem 24 unidades


@pytest.mark.parametrize("linha", [0, 5], ids=["linha-0", "linha-5"])
def test_nao_credita_linhas_que_nao_existem(linha):
    with pytest.raises(ValueError):
        nota_credito(FT_2026_31, {linha: Decimal(1)})
