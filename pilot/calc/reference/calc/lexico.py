"""Analisador léxico: parte o texto de um programa em tokens."""

import re
from dataclasses import dataclass

from calc.erros import ErroSintaxe

PALAVRAS_RESERVADAS = frozenset(
    {"let", "rec", "in", "if", "then", "else", "fn", "true", "false"}
)
# Os de dois caracteres vêm primeiro, para "<=" não ser lido como "<" seguido de "=",
# nem "//" como duas divisões.
OPERADORES = (
    "==", "!=", "<=", ">=", "=>", "//",
    "+", "-", "*", "/", "%", "^", "(", ")", "<", ">", "=",
)  # fmt: skip

_NUMERO = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_NOME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESPACOS_E_COMENTARIOS = re.compile(r"(?:\s+|#[^\n]*)+")


@dataclass(frozen=True)
class Token:
    tipo: str  # "numero", "nome", "fim", ou o próprio texto nos operadores e palavras reservadas
    texto: str  # tal como está no programa ("" no fim)
    pos: int  # índice do primeiro carácter no programa (len(programa) no fim)


def tokens(programa: str) -> list[Token]:
    """Os tokens do programa, acabados num token "fim". Ignora espaços e comentários (# ...)."""
    resultado = []
    pos = 0
    while True:
        if espacos := _ESPACOS_E_COMENTARIOS.match(programa, pos):
            pos = espacos.end()
        if pos == len(programa):
            resultado.append(Token("fim", "", pos))
            return resultado
        token = _token(programa, pos)
        resultado.append(token)
        pos += len(token.texto)


def _token(programa: str, pos: int) -> Token:
    if numero := _NUMERO.match(programa, pos):
        return Token("numero", numero.group(), pos)
    if nome := _NOME.match(programa, pos):
        texto = nome.group()
        return Token(texto if texto in PALAVRAS_RESERVADAS else "nome", texto, pos)
    for operador in OPERADORES:
        if programa.startswith(operador, pos):
            return Token(operador, operador, pos)
    raise ErroSintaxe.em(programa, pos, programa[pos])
