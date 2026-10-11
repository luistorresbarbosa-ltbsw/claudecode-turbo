"""T8 · Email ao cliente: docs/email-aurora.md menciona as duas faturas, o montante e os 2 %.

Corre na pasta do braço e lê docs/email-aurora.md a partir dali (o harness grava lá a resposta).
Afirma factos, não forma. Contas do prompt: 634,86 × 0,98 = 622,16 e 612,40 + 622,16 = 1 234,56.
"""

import re
from pathlib import Path

SAIDA = Path("docs/email-aurora.md")


def _texto() -> str:
    assert SAIDA.is_file(), f"não existe {SAIDA} em {Path.cwd()}"
    return SAIDA.read_text(encoding="utf-8", errors="replace")


def test_menciona_a_fatura_ft_2026_14():
    assert re.search(r"FT\s*2026\s*/\s*14(?!\d)", _texto(), re.IGNORECASE)


def test_menciona_a_fatura_ft_2026_15():
    assert re.search(r"FT\s*2026\s*/\s*15(?!\d)", _texto(), re.IGNORECASE)


def test_menciona_o_montante_da_transferencia():
    # "1 234,56" (qualquer espaço, incluindo o inseparável), "1234,56" ou "1.234,56".
    assert re.search(r"(?<![\d.,])1[\s.]?234,56(?!\d)", _texto())


def test_menciona_o_desconto_de_2_por_cento():
    # "2%", "2 %", "2,0%", "2 por cento" ou "dois por cento"; "12%" e "0,2%" não contam.
    padrao = r"(?<![\d.,])2(?:[.,]0+)?\s*(?:%|por\s+cento)|\bdois\s+por\s+cento"
    assert re.search(padrao, _texto(), re.IGNORECASE)
