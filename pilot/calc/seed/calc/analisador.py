"""Analisador sintático: dos tokens à árvore do programa.

Gramática, da precedência mais fraca para a mais forte:

    expressao  := "let" NOME "=" expressao "in" expressao
                | "let" "rec" NOME "=" funcao "in" expressao
                | "if" expressao "then" expressao "else" expressao
                | funcao
                | comparacao
    funcao     := "fn" NOME "=>" expressao
    comparacao := soma [("==" | "!=" | "<" | "<=" | ">" | ">=") soma]
    soma       := produto (("+" | "-") produto)*
    produto    := unario (("*" | "/") unario)*
    unario     := "-" unario | potencia
    potencia   := chamada ["^" unario]
    chamada    := atomo ("(" expressao ")")*
    atomo      := NUMERO | "true" | "false" | NOME | "(" expressao ")"

`+ - * /` associam à esquerda; `^` associa à direita; as comparações não se encadeiam.
"""

from fractions import Fraction

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
from calc.erros import ErroSintaxe
from calc.lexico import Token, tokens

COMPARACOES = ("==", "!=", "<", "<=", ">", ">=")


def analisar(programa: str) -> No:
    """A árvore do programa. Lança ErroSintaxe se o programa estiver mal escrito."""
    return _Analisador(tokens(programa)).programa()


class _Analisador:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._i = 0

    def programa(self) -> No:
        arvore = self._expressao()
        self._espera("fim", "o fim do programa")
        return arvore

    # --- regras da gramática ---------------------------------------------------------------

    def _expressao(self) -> No:
        if self._aceita("let"):
            return self._seja()
        if self._aceita("if"):
            condicao = self._expressao()
            self._espera("then", "'then'")
            entao = self._expressao()
            self._espera("else", "'else'")
            return Se(condicao, entao, self._expressao())
        if self._ve("fn"):
            return self._funcao()
        return self._comparacao()

    def _seja(self) -> No:
        recursivo = self._aceita("rec")
        nome = self._espera("nome", "um nome").texto
        self._espera("=", "'='")
        valor = self._funcao() if recursivo else self._expressao()
        self._espera("in", "'in'")
        corpo = self._expressao()
        return SejaRec(nome, valor, corpo) if recursivo else Seja(nome, valor, corpo)

    def _funcao(self) -> Fn:
        self._espera("fn", "'fn'")
        parametro = self._espera("nome", "um nome").texto
        self._espera("=>", "'=>'")
        return Fn(parametro, self._expressao())

    def _comparacao(self) -> No:
        esquerda = self._soma()
        if self._ve(*COMPARACOES):
            op = self._avanca().tipo
            return Binario(op, esquerda, self._soma())
        return esquerda

    def _soma(self) -> No:
        esquerda = self._produto()
        while self._ve("+", "-"):
            op = self._avanca().tipo
            esquerda = Binario(op, esquerda, self._produto())
        return esquerda

    def _produto(self) -> No:
        esquerda = self._unario()
        while self._ve("*", "/"):
            op = self._avanca().tipo
            esquerda = Binario(op, esquerda, self._unario())
        return esquerda

    def _unario(self) -> No:
        if self._aceita("-"):
            return Unario("-", self._unario())
        return self._potencia()

    def _potencia(self) -> No:
        base = self._chamada()
        while self._ve("^"):
            self._avanca()
            base = Binario("^", base, self._chamada())
        return base

    def _chamada(self) -> No:
        funcao = self._atomo()
        while self._aceita("("):
            argumento = self._expressao()
            self._espera(")", "')'")
            funcao = Chamada(funcao, argumento)
        return funcao

    def _atomo(self) -> No:
        token = self._atual
        if self._aceita("numero"):
            return Numero(Fraction(token.texto))
        if self._aceita("true") or self._aceita("false"):
            return Booleano(token.tipo == "true")
        if self._aceita("nome"):
            return Variavel(token.texto)
        if self._aceita("("):
            dentro = self._expressao()
            self._espera(")", "')'")
            return dentro
        raise self._erro("uma expressão")

    # --- tokens --------------------------------------------------------------------------------

    @property
    def _atual(self) -> Token:
        return self._tokens[self._i]

    def _ve(self, *tipos: str) -> bool:
        return self._atual.tipo in tipos

    def _avanca(self) -> Token:
        token = self._atual
        if token.tipo != "fim":
            self._i += 1
        return token

    def _aceita(self, tipo: str) -> bool:
        if self._ve(tipo):
            self._avanca()
            return True
        return False

    def _espera(self, tipo: str, o_que: str) -> Token:
        if not self._ve(tipo):
            raise self._erro(o_que)
        return self._avanca()

    def _erro(self, o_que: str) -> ErroSintaxe:
        token = self._atual
        encontrei = "o fim do programa" if token.tipo == "fim" else repr(token.texto)
        return ErroSintaxe(f"esperava {o_que}, mas encontrei {encontrei}")
