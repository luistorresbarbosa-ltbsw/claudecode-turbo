"""Valida o avaliador do piloto `fatura` antes de gastar: NULO 0/7 e ORÁCULO 7/7.

- NULO: o ponto de partida (seed/) com os ficheiros injetados (inject/<id>/). Não pode passar
  nenhuma tarefa.
- ORÁCULO: o mesmo, com a referência (reference/) por cima. Tem de passar todas.

Cada tarefa corre a sua aceitação escondida como o harness a corre, na pasta do braço:

    cd <braço> && PYTHONPATH=<braço> <repo>/.venv/bin/python -m pytest \\
        <repo>/pilot/fatura/acceptance/test_<id>.py -q -p no:cacheprovider

Uma tarefa só passa se o ficheiro inteiro passar (código 0, nenhum teste falhado, com erro ou
saltado). As pastas dos braços são temporárias e apagam-se no fim (--manter para as guardar).

Uso, com o Python da venv do repositório:

    .venv/bin/python pilot/fatura/validate.py [--manter]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parents[1]
PYTHON = REPO / ".venv" / "bin" / "python"
IGNORAR = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", ".venv", "uv.lock"
)
CONTAGEM = re.compile(
    r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b"
)


@dataclass
class Resultado:
    passou: bool
    resumo: str
    saida: str


def carregar_tarefas() -> list[dict]:
    return json.loads((AQUI / "tasks.json").read_text(encoding="utf-8"))


def montar_braco(destino: Path, tarefas: list[dict], com_referencia: bool) -> Path:
    shutil.copytree(AQUI / "seed", destino, ignore=IGNORAR)
    for tarefa in tarefas:
        for relativo in tarefa["inject"]:
            alvo = destino / relativo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(AQUI / "inject" / tarefa["id"] / relativo, alvo)
    if com_referencia:
        shutil.copytree(AQUI / "reference", destino, ignore=IGNORAR, dirs_exist_ok=True)
    return destino


def correr_pytest(braco: Path, alvo: str) -> Resultado:
    ambiente = {**os.environ, "PYTHONPATH": str(braco), "PYTHONDONTWRITEBYTECODE": "1"}
    processo = subprocess.run(
        [str(PYTHON), "-m", "pytest", alvo, "-q", "-p", "no:cacheprovider"],
        check=False,
        cwd=braco,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=300,
    )
    saida = processo.stdout + processo.stderr
    linhas = [linha for linha in processo.stdout.splitlines() if linha.strip()]
    contagens: dict[str, int] = {}
    for numero, tipo in CONTAGEM.findall(linhas[-1] if linhas else ""):
        tipo = "error" if tipo.startswith("error") else tipo
        contagens[tipo] = contagens.get(tipo, 0) + int(numero)
    maus = sum(
        contagens.get(t, 0)
        for t in ("failed", "error", "skipped", "xfailed", "xpassed")
    )
    passou = processo.returncode == 0 and contagens.get("passed", 0) > 0 and maus == 0
    resumo = (
        ", ".join(f"{n} {t}" for t, n in contagens.items())
        or f"código {processo.returncode}"
    )
    return Resultado(passou=passou, resumo=resumo, saida=saida)


def aceitacao(braco: Path, tarefa: dict) -> Resultado:
    ficheiro = AQUI / "acceptance" / f"test_{tarefa['id'].lower()}.py"
    return correr_pytest(braco, str(ficheiro))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--manter", action="store_true", help="não apaga as pastas dos braços"
    )
    args = parser.parse_args()

    if not PYTHON.exists():
        print(f"falta o Python da venv do repositório: {PYTHON}", file=sys.stderr)
        return 2

    tarefas = carregar_tarefas()
    base = Path(tempfile.mkdtemp(prefix="piloto-fatura-"))
    try:
        nulo = montar_braco(base / "nulo", tarefas, com_referencia=False)
        oraculo = montar_braco(base / "oraculo", tarefas, com_referencia=True)

        linhas, inesperados = [], []
        for tarefa in tarefas:
            r_nulo, r_oraculo = aceitacao(nulo, tarefa), aceitacao(oraculo, tarefa)
            linhas.append((tarefa, r_nulo, r_oraculo))
            if r_nulo.passou:
                inesperados.append((f"{tarefa['id']} passou no NULO", r_nulo))
            if not r_oraculo.passou:
                inesperados.append((f"{tarefa['id']} falhou no ORÁCULO", r_oraculo))

        def celula(r: Resultado) -> str:
            return f"{'✓' if r.passou else '✗'} {r.resumo}"

        total_nulo = sum(r.passou for _, r, _ in linhas)
        total_oraculo = sum(r.passou for _, _, r in linhas)
        n = len(tarefas)

        print(
            f"{'tarefa':<7}{'título':<22}{'NULO (seed + injeções)':<34}ORÁCULO (+ referência)"
        )
        print("-" * 92)
        for tarefa, r_nulo, r_oraculo in linhas:
            print(
                f"{tarefa['id']:<7}{tarefa['title']:<22}{celula(r_nulo):<34}{celula(r_oraculo)}"
            )
        print("-" * 92)
        print(f"{'total':<29}{f'{total_nulo}/{n}':<34}{total_oraculo}/{n}")

        proprios_nulo, proprios_oraculo = (
            correr_pytest(nulo, "tests"),
            correr_pytest(oraculo, "tests"),
        )
        print(
            f"\ntestes do próprio projeto (tests/): NULO {proprios_nulo.resumo}; "
            f"ORÁCULO {proprios_oraculo.resumo}"
        )

        for motivo, resultado in inesperados:
            print(f"\n=== {motivo} ===\n{resultado.saida}")

        ok = total_nulo == 0 and total_oraculo == n
        print(
            f"\n{'OK' if ok else 'FALHOU'}: NULO {total_nulo}/{n}, ORÁCULO {total_oraculo}/{n}"
        )
        if args.manter:
            print(f"pastas dos braços: {nulo} e {oraculo}")
        return 0 if ok else 1
    finally:
        if not args.manter:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
