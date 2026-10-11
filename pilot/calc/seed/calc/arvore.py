"""A árvore de um programa: um nó por construção da linguagem."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Numero:
    valor: Fraction


@dataclass(frozen=True)
class Booleano:
    valor: bool


@dataclass(frozen=True)
class Variavel:
    nome: str


@dataclass(frozen=True)
class Unario:
    """`-operando`: o único operador unário é o menos."""

    op: str
    operando: No


@dataclass(frozen=True)
class Binario:
    """`esquerda op direita`: + - * / ^ e as comparações."""

    op: str
    esquerda: No
    direita: No


@dataclass(frozen=True)
class Se:
    """`if condicao then entao else senao`"""

    condicao: No
    entao: No
    senao: No


@dataclass(frozen=True)
class Seja:
    """`let nome = valor in corpo`"""

    nome: str
    valor: No
    corpo: No


@dataclass(frozen=True)
class SejaRec:
    """`let rec nome = funcao in corpo`: a função pode chamar-se a si própria."""

    nome: str
    funcao: Fn
    corpo: No


@dataclass(frozen=True)
class Fn:
    """`fn parametro => corpo`"""

    parametro: str
    corpo: No


@dataclass(frozen=True)
class Chamada:
    """`funcao(argumento)`"""

    funcao: No
    argumento: No


No = Numero | Booleano | Variavel | Unario | Binario | Se | Seja | SejaRec | Fn | Chamada
