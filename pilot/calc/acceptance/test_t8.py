"""T8 · Léxico vs dinâmico: docs/ambito.md dá 15 com âmbito léxico e 35 com dinâmico, e tem tabela.

Corre na pasta do braço e lê docs/ambito.md a partir dali (o harness grava lá a resposta).
O exemplo do prompt: custo(n) = n × taxa foi definida onde taxa = 3; faturar tem uma taxa local = 7
e chama custo(5). Léxico: a taxa de onde custo foi definida, 5 × 3 = 15. Dinâmico: a taxa de quem
chama, 5 × 7 = 35. Nenhum dos dois números aparece no prompt.

Afirma factos, não forma: os dois resultados aparecem, há uma tabela Markdown e a tabela não os
troca. A troca só chumba quando é clara: uma linha (ou coluna) da tabela que fala só de um dos
âmbitos e tem só o resultado do outro. Se a tabela não se deixar ler assim, não chumba; o resto da
explicação fica para o juiz.
"""

import re
from pathlib import Path

SAIDA = Path("docs/ambito.md")

# Linha separadora de uma tabela Markdown: "|---|:---:|", "--- | ---", "| :-- | --: |" ...
SEPARADOR_DE_TABELA = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$")
LEXICO = re.compile(r"l[ée]xic|est[áa]tic", re.IGNORECASE)
DINAMICO = re.compile(r"din[âa]mic", re.IGNORECASE)


def _texto() -> str:
    assert SAIDA.is_file(), f"não existe {SAIDA} em {Path.cwd()}"
    return SAIDA.read_text(encoding="utf-8", errors="replace")


def _tem_numero(texto: str, numero: str) -> bool:
    # sozinho: sem algarismos colados nem casas decimais ("150" e "1,35" não contam)
    return re.search(rf"(?<![\d.,]){numero}(?![\d]|[.,]\d)", texto) is not None


def _celulas(linha: str) -> list[str]:
    celulas = [c.strip() for c in linha.strip().split("|")]
    if celulas and not celulas[0]:
        celulas = celulas[1:]
    if celulas and not celulas[-1]:
        celulas = celulas[:-1]
    return celulas


def _tabelas(texto: str) -> list[list[list[str]]]:
    """Cada tabela Markdown como [cabeçalho, linha de dados, ...], cada uma uma lista de células."""
    linhas = texto.splitlines()
    tabelas, i = [], 1
    while i < len(linhas) - 1:
        if (
            SEPARADOR_DE_TABELA.match(linhas[i])
            and "|" in linhas[i - 1]
            and "|" in linhas[i + 1]
        ):
            fim = i + 1
            while fim < len(linhas) and "|" in linhas[fim]:
                fim += 1
            tabelas.append(
                [_celulas(linhas[i - 1])] + [_celulas(l) for l in linhas[i + 1 : fim]]
            )
            i = fim
        else:
            i += 1
    return tabelas


def _resultados_por_ambito(tabela: list[list[str]]):
    """(âmbito, texto) para cada linha ou coluna da tabela que fala só de um dos dois âmbitos."""
    cabecalho, corpo = tabela[0], tabela[1:]
    colunas = {
        "lexico": [j for j, c in enumerate(cabecalho) if LEXICO.search(c) and not DINAMICO.search(c)],
        "dinamico": [j for j, c in enumerate(cabecalho) if DINAMICO.search(c) and not LEXICO.search(c)],
    }
    for linha in corpo:
        for ambito, indices in colunas.items():  # âmbitos em colunas
            yield from ((ambito, linha[j]) for j in indices if j < len(linha))
        texto = " | ".join(linha)  # âmbitos em linhas
        if LEXICO.search(texto) and not DINAMICO.search(texto):
            yield "lexico", texto
        if DINAMICO.search(texto) and not LEXICO.search(texto):
            yield "dinamico", texto


def test_tem_uma_tabela_markdown():
    assert _tabelas(_texto()), "não há nenhuma tabela Markdown (cabeçalho, separador |---|, dados)"


def test_com_ambito_lexico_da_15():
    assert _tem_numero(_texto(), "15"), "falta o resultado com âmbito léxico: 5 × 3 = 15"


def test_com_ambito_dinamico_da_35():
    assert _tem_numero(_texto(), "35"), "falta o resultado com âmbito dinâmico: 5 × 7 = 35"


def test_a_tabela_nao_troca_os_resultados():
    trocados = [
        (ambito, texto)
        for tabela in _tabelas(_texto())
        for ambito, texto in _resultados_por_ambito(tabela)
        if (ambito == "lexico" and _tem_numero(texto, "35") and not _tem_numero(texto, "15"))
        or (ambito == "dinamico" and _tem_numero(texto, "15") and not _tem_numero(texto, "35"))
    ]
    assert not trocados, f"a tabela troca os resultados (léxico 15, dinâmico 35): {trocados}"
