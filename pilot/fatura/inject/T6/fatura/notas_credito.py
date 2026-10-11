"""Notas de crédito parciais.

Uma nota de crédito anula, no todo ou em parte, linhas de uma fatura já emitida. Indica-se, por
número de linha (a primeira linha da fatura é a 1), quantas unidades se creditam.

As contas são as da fatura:

- a base de cada linha creditada é quantidade × preço unitário × (1 − desconto_pct/100),
  arredondada ao cêntimo;
- o IVA calcula-se por taxa, sobre a soma das bases dessa taxa, e arredonda-se ao cêntimo;
- o total é a base mais o IVA.
"""

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fatura.iva import TAXAS
from fatura.modelo import Fatura, Linha

CENTIMO = Decimal("0.01")
ZERO = Decimal(0)


@dataclass(frozen=True)
class NotaCredito:
    fatura: str  # número da fatura de origem
    por_taxa: dict[str, tuple[Decimal, Decimal]]  # código da taxa -> (base, IVA)
    base: Decimal
    iva: Decimal
    total: Decimal


def ler_fatura(caminho: str | Path) -> Fatura:
    """Lê uma fatura em JSON, com os valores decimais escritos como strings."""
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    linhas = [
        Linha(
            descricao=linha["descricao"],
            quantidade=Decimal(linha["quantidade"]),
            preco_unitario=Decimal(linha["preco_unitario"]),
            taxa=linha["taxa"],
            desconto_pct=Decimal(linha["desconto_pct"]),
        )
        for linha in dados["linhas"]
    ]
    return Fatura(numero=dados["numero"], regiao=dados["regiao"], linhas=linhas)


def nota_credito(fatura: Fatura, creditar: dict[int, Decimal]) -> NotaCredito:
    """Nota de crédito das quantidades em `creditar` (número da linha -> quantidade)."""
    if not creditar:
        raise ValueError("creditar: indica pelo menos uma linha")
    bases: dict[str, Decimal] = {}
    for numero, quantidade in creditar.items():
        linha = _linha(fatura, numero)
        if not ZERO < quantidade <= linha.quantidade:
            raise ValueError(
                f"linha {numero}: a quantidade a creditar tem de ser maior do que 0 "
                f"e no máximo {linha.quantidade}; recebi {quantidade}"
            )
        bases[linha.taxa] = bases.get(linha.taxa, ZERO) + _base(linha, quantidade)

    taxas = TAXAS[fatura.regiao]
    por_taxa = {taxa: (base, _iva(base, taxas[taxa])) for taxa, base in bases.items()}
    base = sum((b for b, _ in por_taxa.values()), ZERO)
    iva = sum((i for _, i in por_taxa.values()), ZERO)
    return NotaCredito(
        fatura=fatura.numero, por_taxa=por_taxa, base=base, iva=iva, total=base + iva
    )


def _linha(fatura: Fatura, numero: int) -> Linha:
    if not 1 <= numero <= len(fatura.linhas):
        raise ValueError(
            f"linha {numero}: a fatura {fatura.numero} tem {len(fatura.linhas)} linhas"
        )
    return fatura.linhas[numero - 1]


def _base(linha: Linha, quantidade: Decimal) -> Decimal:
    valor = quantidade * linha.preco_unitario * (1 - linha.desconto_pct / 100)
    return valor.quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _iva(base: Decimal, taxa: Decimal) -> Decimal:
    """IVA de uma base, ao cêntimo."""
    return Decimal(str(round(float(base * taxa), 2)))
