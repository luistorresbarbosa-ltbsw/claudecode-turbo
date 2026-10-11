"""Totais de uma fatura: total de cada linha, base e IVA por taxa, e totais gerais."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from fatura.iva import TAXAS
from fatura.modelo import Fatura, Linha

CENTIMO = Decimal("0.01")
ZERO = Decimal(0)


@dataclass(frozen=True)
class Totais:
    linhas: list[Decimal]  # total sem IVA de cada linha, pela ordem da fatura
    por_taxa: dict[str, tuple[Decimal, Decimal]]  # código da taxa -> (base, IVA)
    sem_iva: Decimal
    iva: Decimal
    total: Decimal


def arredondar(valor: Decimal) -> Decimal:
    """Ao cêntimo, com ROUND_HALF_UP (2.675 -> 2.68)."""
    return valor.quantize(CENTIMO, rounding=ROUND_HALF_UP)


def total_da_linha(linha: Linha) -> Decimal:
    """quantidade × preço × (1 − desconto_pct/100), arredondado uma só vez."""
    return arredondar(
        linha.quantidade * linha.preco_unitario * (1 - linha.desconto_pct / 100)
    )


def calcular(f: Fatura) -> Totais:
    taxas = _taxas_da_regiao(f)
    linhas = [total_da_linha(linha) for linha in f.linhas]

    bases: dict[str, Decimal] = {}
    for numero, (linha, valor) in enumerate(zip(f.linhas, linhas), start=1):
        if linha.taxa not in taxas:
            raise ValueError(
                f"linhas[{numero}].taxa: {linha.taxa!r} não é NOR, INT nem RED"
            )
        bases[linha.taxa] = bases.get(linha.taxa, ZERO) + valor

    por_taxa = {
        taxa: (base, arredondar(base * taxas[taxa])) for taxa, base in bases.items()
    }
    sem_iva = sum((base for base, _ in por_taxa.values()), ZERO)
    iva = sum((valor for _, valor in por_taxa.values()), ZERO)
    return Totais(
        linhas=linhas, por_taxa=por_taxa, sem_iva=sem_iva, iva=iva, total=sem_iva + iva
    )


def _taxas_da_regiao(f: Fatura) -> dict[str, Decimal]:
    try:
        return TAXAS[f.regiao]
    except KeyError:
        raise ValueError(f"regiao: {f.regiao!r} não é PT, PT-MA nem PT-AC") from None
