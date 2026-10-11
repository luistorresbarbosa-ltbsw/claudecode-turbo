"""Inferência de tipos Hindley–Milner, com polimorfismo no let.

`inferir(programa)` devolve o tipo do programa sem o correr, na forma canónica: `num`, `bool`,
`A -> B` (à direita, com parênteses só quando o lado esquerdo é uma função) e variáveis `a`, `b`,
`c`, ... pela ordem em que aparecem. Um programa sem tipo lança ErroTipo.

É o algoritmo W, com a substituição guardada num dicionário (variável -> tipo) que só cresce:
unificar liga variáveis e `resolver` aplica as ligações. Um `let` generaliza as variáveis do tipo
que não estão livres no contexto (depois de aplicada a substituição); cada uso instancia-as de novo.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count

from calc.analisador import analisar
from calc.arvore import (
    Binario,
    Booleano,
    Chamada,
    Fn,
    No,
    Numero,
    Se,
    Seja,
    SejaRec,
    Unario,
    Variavel,
)
from calc.erros import ErroCalc


class ErroTipo(ErroCalc):
    """O programa está bem escrito, mas não tem tipo."""


@dataclass(frozen=True)
class TVar:
    id: int


@dataclass(frozen=True)
class TBase:
    nome: str  # "num" ou "bool"


@dataclass(frozen=True)
class TFun:
    argumento: Tipo
    resultado: Tipo


Tipo = TVar | TBase | TFun
NUM, BOOL = TBase("num"), TBase("bool")
ARITMETICA = ("+", "-", "*", "/", "//", "%", "^")
ORDEM = ("<", "<=", ">", ">=")
IGUALDADE = ("==", "!=")


@dataclass(frozen=True)
class Esquema:
    """∀ variaveis . tipo: o tipo de um nome dado por um let, já generalizado."""

    variaveis: frozenset[int]
    tipo: Tipo


Contexto = dict[str, Esquema]


def inferir(programa: str) -> str:
    """O tipo do programa, na forma canónica. Lança ErroTipo (ou ErroSintaxe)."""
    inferidor = _Inferidor()
    return mostrar(inferidor.resolver(inferidor.tipo(analisar(programa), {})))


def mostrar(tipo: Tipo) -> str:
    """O tipo na forma canónica."""
    return _mostrar(tipo, {})


def _mostrar_juntos(*tipos: Tipo) -> list[str]:
    """Vários tipos na forma canónica, com os mesmos nomes para as mesmas variáveis."""
    nomes: dict[int, str] = {}
    return [_mostrar(tipo, nomes) for tipo in tipos]


def _mostrar(tipo: Tipo, nomes: dict[int, str]) -> str:
    match tipo:
        case TBase(nome):
            return nome
        case TVar(id):
            if id not in nomes:
                n = len(nomes)
                nomes[id] = "abcdefghijklmnopqrstuvwxyz"[n % 26] + (str(n // 26) if n >= 26 else "")
            return nomes[id]
        case TFun(argumento, resultado):
            esquerda = _mostrar(argumento, nomes)
            if isinstance(argumento, TFun):
                esquerda = f"({esquerda})"
            return f"{esquerda} -> {_mostrar(resultado, nomes)}"
    raise TypeError(f"tipo desconhecido: {tipo!r}")


class _Inferidor:
    def __init__(self):
        self._ligacoes: dict[int, Tipo] = {}
        self._ids = count()

    # --- inferência ----------------------------------------------------------------------------

    def tipo(self, no: No, contexto: Contexto) -> Tipo:
        match no:
            case Numero():
                return NUM
            case Booleano():
                return BOOL
            case Variavel(nome):
                if nome not in contexto:
                    raise ErroTipo(f"variável '{nome}' não definida")
                return self._instanciar(contexto[nome])
            case Unario("-", operando):
                self._unificar(self.tipo(operando, contexto), NUM)
                return NUM
            case Binario(op, esquerda, direita):
                a, b = self.tipo(esquerda, contexto), self.tipo(direita, contexto)
                if op in IGUALDADE:
                    self._unificar(a, b)
                    return BOOL
                self._unificar(a, NUM)
                self._unificar(b, NUM)
                return BOOL if op in ORDEM else NUM
            case Se(condicao, entao, senao):
                self._unificar(self.tipo(condicao, contexto), BOOL)
                resultado = self.tipo(entao, contexto)
                self._unificar(resultado, self.tipo(senao, contexto))
                return resultado
            case Fn(parametro, corpo):
                argumento = self._nova()
                dentro = {**contexto, parametro: Esquema(frozenset(), argumento)}
                return TFun(argumento, self.tipo(corpo, dentro))
            case Chamada(funcao, argumento):
                tipo_funcao = self.tipo(funcao, contexto)
                tipo_argumento = self.tipo(argumento, contexto)
                resultado = self._nova()
                self._unificar(tipo_funcao, TFun(tipo_argumento, resultado))
                return resultado
            case Seja(nome, valor, corpo):
                esquema = self._generalizar(self.tipo(valor, contexto), contexto)
                return self.tipo(corpo, {**contexto, nome: esquema})
            case SejaRec(nome, funcao, corpo):
                propria = self._nova()  # monomórfica dentro da própria definição
                dentro = {**contexto, nome: Esquema(frozenset(), propria)}
                self._unificar(propria, self.tipo(funcao, dentro))
                esquema = self._generalizar(propria, contexto)
                return self.tipo(corpo, {**contexto, nome: esquema})
        raise TypeError(f"nó desconhecido: {no!r}")

    # --- substituição e unificação -------------------------------------------------------------

    def _nova(self) -> TVar:
        return TVar(next(self._ids))

    def resolver(self, tipo: Tipo) -> Tipo:
        """O tipo com todas as ligações aplicadas."""
        match tipo:
            case TVar(id) if id in self._ligacoes:
                return self.resolver(self._ligacoes[id])
            case TFun(argumento, resultado):
                return TFun(self.resolver(argumento), self.resolver(resultado))
        return tipo

    def _raso(self, tipo: Tipo) -> Tipo:
        while isinstance(tipo, TVar) and tipo.id in self._ligacoes:
            tipo = self._ligacoes[tipo.id]
        return tipo

    def _unificar(self, a: Tipo, b: Tipo) -> None:
        a, b = self._raso(a), self._raso(b)
        if a == b:
            return
        if isinstance(a, TVar) or isinstance(b, TVar):
            variavel, outro = (a, b) if isinstance(a, TVar) else (b, a)
            if variavel.id in self._livres(outro):
                nome, tipo = _mostrar_juntos(variavel, self.resolver(outro))
                raise ErroTipo(f"o tipo seria infinito: {nome} = {tipo}")
            self._ligacoes[variavel.id] = outro
            return
        if isinstance(a, TFun) and isinstance(b, TFun):
            self._unificar(a.argumento, b.argumento)
            self._unificar(a.resultado, b.resultado)
            return
        um, outro = _mostrar_juntos(self.resolver(a), self.resolver(b))
        raise ErroTipo(f"os tipos não casam: {um} e {outro}")

    # --- generalização e instanciação ----------------------------------------------------------

    def _livres(self, tipo: Tipo) -> set[int]:
        match self._raso(tipo):
            case TVar(id):
                return {id}
            case TFun(argumento, resultado):
                return self._livres(argumento) | self._livres(resultado)
        return set()

    def _generalizar(self, tipo: Tipo, contexto: Contexto) -> Esquema:
        presas = set().union(
            *(self._livres(e.tipo) - e.variaveis for e in contexto.values())
        )
        return Esquema(frozenset(self._livres(tipo) - presas), self.resolver(tipo))

    def _instanciar(self, esquema: Esquema) -> Tipo:
        novas = {id: self._nova() for id in esquema.variaveis}
        return self._trocar(self.resolver(esquema.tipo), novas)

    def _trocar(self, tipo: Tipo, novas: dict[int, TVar]) -> Tipo:
        match tipo:
            case TVar(id):
                return novas.get(id, tipo)
            case TFun(argumento, resultado):
                return TFun(self._trocar(argumento, novas), self._trocar(resultado, novas))
        return tipo
