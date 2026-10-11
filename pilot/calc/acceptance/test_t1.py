"""T1 · Tabela de precedência: docs/precedencia.md tem uma tabela e os três resultados certos.

Corre na pasta do braço e lê docs/precedencia.md a partir dali (o harness grava lá a resposta).
Afirma factos, não forma:
- 2^3^2 = 512 (a potência associa à direita: 2^(3^2); à esquerda daria 64);
- −2^2 = −4 (a potência aplica-se antes do menos unário: −(2^2));
- 100 − 20 − 5 = 75 (a subtração associa à esquerda; à direita daria 85);
- há uma tabela Markdown e o texto diz que a potência associa à direita.
Um número conta se aparecer escrito sozinho ("512", "−4", "-4", "menos 4"), em qualquer sítio.
A tabela só chumba a resposta se a linha da potência disser claramente que associa à esquerda e
nenhuma disser à direita; se a linha não se deixar ler, não chumba. O resto fica para o juiz.
"""

import re
from pathlib import Path

SAIDA = Path("docs/precedencia.md")

# Linha separadora de uma tabela Markdown: "|---|:---:|", "--- | ---", "| :-- | --: |" ...
SEPARADOR_DE_TABELA = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$")
MENOS = "-−–"  # hífen, sinal de menos (U+2212) e travessão curto


def _texto() -> str:
    assert SAIDA.is_file(), f"não existe {SAIDA} em {Path.cwd()}"
    return SAIDA.read_text(encoding="utf-8", errors="replace")


def _tem_numero(texto: str, numero: str) -> bool:
    # sozinho: sem algarismos colados nem casas decimais ("1512", "5120" e "0,512" não contam)
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


POTENCIA = re.compile(r"\^|pot[êe]nc|expon", re.IGNORECASE)
# Linhas que mencionam a potência num exemplo, mas são de outro operador: não contam.
OUTRO_OPERADOR = re.compile(
    r"un[áa]ri|sim[ée]tric|nega[çc]|sinal|\*|×|·|/|÷|\+|multiplic|divis|soma|subtra",
    re.IGNORECASE,
)
SETA = re.compile(r"\s*(?:→|->|⟶|=>)\s*")


def _sentido(texto: str) -> str | None:
    """"direita", "esquerda" ou None: "da esquerda para a direita" é associar à esquerda."""
    t = SETA.sub(" para a ", texto.lower())
    esquerda_para_direita = re.search(r"esquerda\W+(?:\w+\W+){0,3}?direita", t)
    direita_para_esquerda = re.search(r"direita\W+(?:\w+\W+){0,3}?esquerda", t)
    if esquerda_para_direita or direita_para_esquerda:
        if esquerda_para_direita and direita_para_esquerda:
            return None
        return "esquerda" if esquerda_para_direita else "direita"
    direita, esquerda = "direit" in t, "esquerd" in t
    if direita != esquerda:
        return "direita" if direita else "esquerda"
    return None


def test_tem_uma_tabela_markdown():
    assert _tabelas(_texto()), "não há nenhuma tabela Markdown (cabeçalho, separador |---|, dados)"


def test_2_elevado_a_3_elevado_a_2_da_512():
    assert _tem_numero(_texto(), "512"), "falta 2^3^2 = 512 (a potência associa à direita)"


def test_menos_2_ao_quadrado_da_menos_4():
    texto = _texto()
    escrito = re.search(rf"[{MENOS}]\s?4(?![\d]|[.,]\d)", texto)
    por_extenso = re.search(r"\bmenos\s+(?:4|quatro)\b", texto, re.IGNORECASE)
    assert escrito or por_extenso, "falta −2^2 = −4 (a potência vem antes do menos unário)"


def test_100_menos_20_menos_5_da_75():
    assert _tem_numero(_texto(), "75"), "falta 100 − 20 − 5 = 75 (a subtração associa à esquerda)"


def test_a_potencia_associa_a_direita():
    texto = _texto()
    assert "direit" in texto.lower(), "o texto nunca diz que a potência associa à direita"
    linhas = [" | ".join(linha) for tabela in _tabelas(texto) for linha in tabela[1:]]
    linhas_da_potencia = [
        linha for linha in linhas if POTENCIA.search(linha) and not OUTRO_OPERADOR.search(linha)
    ]
    sentidos = {_sentido(linha) for linha in linhas_da_potencia}
    assert not ("esquerda" in sentidos and "direita" not in sentidos), (
        f"na tabela, a potência associa à esquerda: {linhas_da_potencia}"
    )
