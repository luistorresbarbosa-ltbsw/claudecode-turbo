"""Os erros da linguagem. Todos descendem de ErroCalc."""


class ErroCalc(Exception):
    """Um erro num programa calc."""


class ErroSintaxe(ErroCalc):
    """O programa está mal escrito: o analisador não o consegue ler."""


class ErroExecucao(ErroCalc):
    """O programa está bem escrito, mas falhou a correr (divisão por zero, variável não definida...)."""
