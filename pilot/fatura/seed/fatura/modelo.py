"""Modelo de dados: uma fatura e as suas linhas."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Taxa = Literal["NOR", "INT", "RED"]  # normal, intermédia, reduzida
Regiao = Literal["PT", "PT-MA", "PT-AC"]  # continente, Madeira, Açores


@dataclass
class Linha:
    descricao: str
    quantidade: Decimal
    preco_unitario: Decimal  # sem IVA
    taxa: Taxa
    desconto_pct: Decimal = Decimal(0)  # percentagem: Decimal("12.5") = 12,5 %


@dataclass
class Fatura:
    numero: str
    regiao: Regiao
    linhas: list[Linha]
