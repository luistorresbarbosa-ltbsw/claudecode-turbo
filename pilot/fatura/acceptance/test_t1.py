"""T1 · Glossário de IVA: docs/IVA.md tem as 9 taxas em vigor e uma tabela em Markdown.

Corre na pasta do braço e lê docs/IVA.md a partir dali (o harness grava lá a resposta).
Afirma factos, não forma: cada taxa aparece escrita como percentagem ("23%", "23 %", "23,0%")
e há pelo menos uma tabela Markdown (cabeçalho, linha separadora, linha de dados).

Taxas em vigor em 2026: continente 23/13/6, Madeira 22/12/4, Açores 16/9/4. A reduzida da Madeira
é 4 % desde 1 de outubro de 2024 (Decreto Legislativo Regional n.º 6/2024/M, art. 21.º; Ofício
Circulado n.º 25045/2024 da AT); antes era 5 %. Como os Açores também têm 4 %, a presença de "4%"
não prova a da Madeira: por isso a tabela é lida e, se a reduzida da Madeira lá estiver como 5 % e
nunca como 4 %, chumba. Se a tabela não deixar perceber qual é a célula, não chumba.
O resto da associação região-taxa fica para o juiz.
"""

import re
from pathlib import Path

import pytest

SAIDA = Path("docs/IVA.md")

TAXAS_EM_VIGOR = [
    ("continente", "normal", 23),
    ("continente", "intermedia", 13),
    ("continente", "reduzida", 6),
    ("madeira", "normal", 22),
    ("madeira", "intermedia", 12),
    ("madeira", "reduzida", 4),
    ("acores", "normal", 16),
    ("acores", "intermedia", 9),
    ("acores", "reduzida", 4),
]

# Linha separadora de uma tabela Markdown: "|---|:---:|", "--- | ---", "| :-- | --: |" ...
SEPARADOR_DE_TABELA = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$")


def _texto() -> str:
    assert SAIDA.is_file(), f"não existe {SAIDA} em {Path.cwd()}"
    return SAIDA.read_text(encoding="utf-8", errors="replace")


def _tem_percentagem(texto: str, valor: int) -> bool:
    # O número não pode vir colado a outro dígito nem a uma casa decimal: "16%" não conta como 6 %,
    # nem "2,5%" como 5 %. Aceita "23%", "23 %" (qualquer espaço, incluindo o inseparável) e "23,0%".
    padrao = rf"(?<![\d.,]){valor}(?:[.,]0+)?\s*%"
    return re.search(padrao, texto) is not None


@pytest.mark.parametrize(
    ("regiao", "taxa", "valor"),
    TAXAS_EM_VIGOR,
    ids=[f"{regiao}-{taxa}-{valor}" for regiao, taxa, valor in TAXAS_EM_VIGOR],
)
def test_menciona_a_taxa_em_vigor(regiao, taxa, valor):
    assert _tem_percentagem(_texto(), valor), (
        f"falta a taxa {taxa} ({regiao}): {valor}%"
    )


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


MADEIRA = re.compile(r"madeira|pt-ma", re.IGNORECASE)
REDUZIDA = re.compile(r"reduzid|\bred\b", re.IGNORECASE)


def _celulas_madeira_reduzida(tabela: list[list[str]]):
    """Células que dizem a taxa reduzida da Madeira, nos três formatos habituais de tabela."""
    cabecalho, corpo = tabela[0], tabela[1:]
    colunas_madeira = [j for j, c in enumerate(cabecalho) if MADEIRA.search(c)]
    colunas_reduzida = [j for j, c in enumerate(cabecalho) if REDUZIDA.search(c)]
    anterior: list[str] = []
    for linha in corpo:
        # Célula vazia sem números por baixo de um rótulo: é o rótulo de cima ("célula fundida").
        linha = [
            anterior[j]
            if not c and j < len(anterior) and not re.search(r"\d", anterior[j])
            else c
            for j, c in enumerate(linha)
        ]
        anterior = linha
        texto_da_linha = " | ".join(linha)
        if REDUZIDA.search(texto_da_linha):  # regiões em colunas, taxas em linhas
            yield from (linha[j] for j in colunas_madeira if j < len(linha))
        if MADEIRA.search(texto_da_linha):  # taxas em colunas, regiões em linhas
            yield from (linha[j] for j in colunas_reduzida if j < len(linha))
        # Sem colunas com o nome da região nem da taxa: uma linha por (região, taxa).
        uma_linha_por_par = not colunas_madeira and not colunas_reduzida
        if (
            uma_linha_por_par
            and MADEIRA.search(texto_da_linha)
            and REDUZIDA.search(texto_da_linha)
        ):
            yield texto_da_linha


def test_tem_uma_tabela_markdown():
    assert _tabelas(_texto()), (
        "não há nenhuma tabela Markdown (cabeçalho, separador |---|, dados)"
    )


def test_reduzida_da_madeira_nao_e_a_de_antes_de_outubro_de_2024():
    celulas = [
        c for tabela in _tabelas(_texto()) for c in _celulas_madeira_reduzida(tabela)
    ]
    if any(_tem_percentagem(c, 4) for c in celulas):
        return
    assert not any(_tem_percentagem(c, 5) for c in celulas), (
        "a taxa reduzida da Madeira está como 5 %: é 4 % desde 1 de outubro de 2024"
    )
