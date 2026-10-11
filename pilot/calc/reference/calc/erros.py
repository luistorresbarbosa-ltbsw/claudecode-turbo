"""Os erros da linguagem. Todos descendem de ErroCalc."""

from __future__ import annotations


class ErroCalc(Exception):
    """Um erro num programa calc."""


class ErroSintaxe(ErroCalc):
    """O programa está mal escrito. A mensagem diz onde e o que lá estava:

    linha 2, coluna 17: inesperado 'in'
    linha 1, coluna 7: inesperado fim do programa
    """

    def __init__(self, linha: int, coluna: int, inesperado: str | None):
        self.linha = linha
        self.coluna = coluna
        self.inesperado = inesperado  # o texto do token; None no fim do programa
        o_que = "fim do programa" if inesperado is None else f"'{inesperado}'"
        super().__init__(f"linha {linha}, coluna {coluna}: inesperado {o_que}")

    @classmethod
    def em(cls, programa: str, pos: int, inesperado: str | None) -> ErroSintaxe:
        """O erro no índice `pos` do programa; `len(programa)` é o fim. Linhas e colunas contam de 1."""
        linha = programa.count("\n", 0, pos) + 1
        coluna = pos - programa.rfind("\n", 0, pos)  # rfind dá -1 na primeira linha
        return cls(linha, coluna, inesperado)


class ErroExecucao(ErroCalc):
    """O programa está bem escrito, mas falhou a correr (divisão por zero, variável não definida...)."""
