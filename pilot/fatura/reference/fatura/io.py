"""Faturas em JSON. Os valores decimais vão como strings, para nunca passarem por float.

{"numero": "FT 2026/7", "regiao": "PT",
 "linhas": [{"descricao": "Pastel de nata", "quantidade": "12", "preco_unitario": "1.10",
             "taxa": "RED", "desconto_pct": "0"}]}
"""

import json
from decimal import Decimal, InvalidOperation

from fatura.modelo import Fatura, Linha


def para_json(f: Fatura) -> str:
    dados = {
        "numero": f.numero,
        "regiao": f.regiao,
        "linhas": [
            {
                "descricao": linha.descricao,
                "quantidade": str(linha.quantidade),
                "preco_unitario": str(linha.preco_unitario),
                "taxa": linha.taxa,
                "desconto_pct": str(linha.desconto_pct),
            }
            for linha in f.linhas
        ],
    }
    return json.dumps(dados, ensure_ascii=False, indent=2)


def de_json(texto: str) -> Fatura:
    dados = json.loads(texto)
    linhas = [_linha(d, f"linhas[{i}]") for i, d in enumerate(dados["linhas"], start=1)]
    return Fatura(numero=dados["numero"], regiao=dados["regiao"], linhas=linhas)


def _linha(dados: dict, onde: str) -> Linha:
    return Linha(
        descricao=dados["descricao"],
        quantidade=_decimal(dados["quantidade"], f"{onde}.quantidade"),
        preco_unitario=_decimal(dados["preco_unitario"], f"{onde}.preco_unitario"),
        taxa=dados["taxa"],
        desconto_pct=_decimal(dados["desconto_pct"], f"{onde}.desconto_pct"),
    )


def _decimal(valor: object, campo: str) -> Decimal:
    """Um número escrito como string JSON; um número JSON já teria passado por float."""
    try:
        numero = Decimal(valor) if isinstance(valor, str) else None
    except InvalidOperation:
        numero = None
    if numero is None or not numero.is_finite():
        raise ValueError(
            f'{campo}: tem de ser uma string com um número, como "12.50"; recebi {valor!r}'
        )
    return numero
