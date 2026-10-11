"""Avaliador: calcula o valor de um programa percorrendo a sua árvore.

Os valores são números (Fraction), booleanos (bool) e funções (Funcao).

- Âmbito léxico: uma função guarda o ambiente onde foi criada e o corpo corre nesse ambiente,
  mais o parâmetro. Quem a chama não lhe empresta variáveis.
- Chamadas em cauda: `avaliar_no` é um ciclo. O que está em posição de cauda (os ramos de um `if`,
  o corpo de um `let` e o corpo da função chamada) não se avalia com outra chamada de Python: passa
  a ser o nó da volta seguinte do ciclo. Assim, uma recursão em cauda não faz crescer a pilha do
  Python; a que não é em cauda continua limitada por ela.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

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
from calc.erros import ErroExecucao


@dataclass(frozen=True, eq=False)
class Funcao:
    """O valor de `fn parametro => corpo`: guarda o ambiente onde foi criada."""

    parametro: str
    corpo: No
    ambiente: Ambiente


Valor = Fraction | bool | Funcao


class Ambiente:
    """Os nomes visíveis num ponto do programa e os seus valores."""

    def __init__(self, valores: dict[str, Valor] | None = None):
        self._valores = dict(valores or {})

    def com(self, nome: str, valor: Valor) -> Ambiente:
        """Um ambiente novo: este, mais `nome` (que tapa outro que tenha o mesmo nome)."""
        return Ambiente({**self._valores, nome: valor})

    def com_recursiva(self, nome: str, funcao: Fn) -> Ambiente:
        """Um ambiente novo em que `nome` é uma função criada nele próprio: vê-se a si mesma."""
        novo = Ambiente(self._valores)
        novo._valores[nome] = Funcao(funcao.parametro, funcao.corpo, novo)
        return novo

    def valor(self, nome: str) -> Valor:
        try:
            return self._valores[nome]
        except KeyError:
            raise ErroExecucao(f"variável '{nome}' não definida") from None


def avaliar(programa: str) -> Valor:
    """O valor do programa. Lança ErroSintaxe ou ErroExecucao."""
    return avaliar_no(analisar(programa), Ambiente())


def avaliar_no(no: No, ambiente: Ambiente) -> Valor:
    while True:  # cada volta avalia o nó que está em posição de cauda do anterior
        match no:
            case Se(condicao, entao, senao):
                no = entao if _condicao(avaliar_no(condicao, ambiente)) else senao
            case Seja(nome, valor, corpo):
                ambiente = ambiente.com(nome, avaliar_no(valor, ambiente))
                no = corpo
            case SejaRec(nome, funcao, corpo):
                ambiente = ambiente.com_recursiva(nome, funcao)
                no = corpo
            case Chamada(funcao, argumento):
                chamada = avaliar_no(funcao, ambiente)
                if not isinstance(chamada, Funcao):
                    raise ErroExecucao("só se podem chamar funções")
                valor = avaliar_no(argumento, ambiente)
                ambiente = chamada.ambiente.com(chamada.parametro, valor)
                no = chamada.corpo
            case _:
                return _avaliar_folha(no, ambiente)


def _avaliar_folha(no: No, ambiente: Ambiente) -> Valor:
    """Os nós sem posição de cauda: o valor sai logo, sem passar o controlo a outro nó."""
    match no:
        case Numero(valor) | Booleano(valor):
            return valor
        case Variavel(nome):
            return ambiente.valor(nome)
        case Unario("-", operando):
            return -_numero(avaliar_no(operando, ambiente), "-")
        case Binario(op, esquerda, direita):
            return _binario(
                op, avaliar_no(esquerda, ambiente), avaliar_no(direita, ambiente)
            )
        case Fn(parametro, corpo):
            return Funcao(parametro, corpo, ambiente)
    raise TypeError(f"nó desconhecido: {no!r}")


def _binario(op: str, a: Valor, b: Valor) -> Valor:
    if op in ("==", "!="):
        return _iguais(a, b) == (op == "==")
    a, b = _numero(a, op), _numero(b, op)
    match op:
        case "+":
            return a + b
        case "-":
            return a - b
        case "*":
            return a * b
        case "/":
            return a / _divisor(b)
        case "//":
            # o maior inteiro <= a/b: também arredonda para baixo nos negativos (-7 // 2 = -4)
            return Fraction(a // _divisor(b))
        case "%":
            return a % _divisor(b)  # a − b × (a // b): tem o sinal de b
        case "^":
            return _potencia(a, b)
        case "<":
            return a < b
        case "<=":
            return a <= b
        case ">":
            return a > b
        case ">=":
            return a >= b
    raise TypeError(f"operador desconhecido: {op!r}")


def _divisor(b: Fraction) -> Fraction:
    if b == 0:
        raise ErroExecucao("divisão por zero")
    return b


def _potencia(base: Fraction, expoente: Fraction) -> Fraction:
    if expoente.denominator != 1:
        raise ErroExecucao(f"o expoente de '^' tem de ser inteiro: {expoente}")
    if base == 0 and expoente < 0:
        raise ErroExecucao("divisão por zero")
    return base**expoente.numerator


def _iguais(a: Valor, b: Valor) -> bool:
    numeros = isinstance(a, Fraction) and isinstance(b, Fraction)
    booleanos = isinstance(a, bool) and isinstance(b, bool)
    if not (numeros or booleanos):
        raise ErroExecucao(
            "'==' e '!=' só comparam números com números e booleanos com booleanos"
        )
    return a == b


def _numero(valor: Valor, op: str) -> Fraction:
    if not isinstance(valor, Fraction):
        raise ErroExecucao(f"'{op}' só funciona com números")
    return valor


def _condicao(valor: Valor) -> bool:
    if not isinstance(valor, bool):
        raise ErroExecucao("a condição de um if tem de ser true ou false")
    return valor
