"""Ledger do JEV: um registo JSONL por tarefa despachada.

É o contrato partilhado entre o núcleo (que escreve) e o dashboard (que lê).
Cada linha compara o custo do caminho JEV com o do Claude Code "standard":

    jev.cost_usd       custo total do caminho JEV (execução + decisão)
    standard.cost_usd  o que o Claude Code standard custou ("measured")
                       ou teria custado ("estimated")
    savings_usd        standard - jev; negativo quando o JEV saiu mais caro. Numa tarefa
                       falhada (jev.ok false) é -jev: o custo conta, mas o trabalho
                       continua por fazer e o standard "evitado" não conta.

Fallbacks (qualquer pedido que falhe cai para o standard Anthropic):

    decision.router_error  null, ou o erro do Jev; a decisão passou a ser o standard
    jev.fallback           null, ou {"from": modelo que falhou, "reason": erro} quando a
                           execução foi repetida no standard; jev.cost_usd soma as duas tentativas
    jev.ok                 false quando nem o fallback produziu resposta

Os custos são a preço de lista (o Claude Code reporta costBasis "list"). Numa subscrição
medem consumo de quota, não faturação.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MAX_TASK_CHARS = 280
BASELINE_KINDS = ("estimated", "measured")


def ledger_path(home: str | Path | None = None) -> Path:
    base = home or os.environ.get("JEV_HOME") or Path.home() / ".jev"
    return Path(base) / "ledger.jsonl"


def make_record(*, task: str, decision: dict, jev: dict, standard: dict,
                now: datetime | None = None) -> dict:
    if standard.get("kind") not in BASELINE_KINDS:
        raise ValueError(f"standard.kind tem de ser um de {BASELINE_KINDS}, veio {standard.get('kind')!r}")

    task = task.strip()
    if len(task) > MAX_TASK_CHARS:
        task = task[: MAX_TASK_CHARS - 1] + "…"

    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "v": SCHEMA_VERSION,
        "id": uuid.uuid4().hex[:12],
        "ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "task": task,
        "decision": decision,
        "jev": jev,
        "standard": standard,
        "savings_usd": round(_saved(jev, standard), 9),
    }


def _saved(jev: dict, standard: dict) -> float:
    if jev.get("ok") is False:
        return -jev["cost_usd"]
    return standard["cost_usd"] - jev["cost_usd"]


def append(record: dict, home: str | Path | None = None) -> Path:
    line = json.dumps(record, ensure_ascii=False, allow_nan=False)  # NaN partiria o JSON do dashboard
    path = ledger_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return path


def _is_valid(rec: object) -> bool:
    if not isinstance(rec, dict) or rec.get("v") != SCHEMA_VERSION:
        return False
    try:
        costs = [rec[side]["cost_usd"] for side in ("jev", "standard")]
        return all(isinstance(c, (int, float)) and math.isfinite(c) for c in costs)
    except (KeyError, TypeError):
        return False


def read_all(home: str | Path | None = None) -> list[dict]:
    """Lê o ledger inteiro, ignorando linhas corrompidas (ex.: escrita interrompida a meio
    de um carácter): uma linha estragada nunca esconde as outras."""
    path = ledger_path(home)
    if not path.exists():
        return []
    records = []
    for raw in path.read_bytes().splitlines():
        try:
            rec = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if _is_valid(rec):
            records.append(rec)
    return records


def summarize(records: list[dict]) -> dict:
    """O standard só conta tarefas concluídas; o JEV conta tudo o que gastou."""
    done = [r for r in records if r["jev"].get("ok") is not False]
    standard = sum(r["standard"]["cost_usd"] for r in done)
    jev = sum(r["jev"]["cost_usd"] for r in records)
    saved = standard - jev
    return {
        "tasks": len(records),
        "failed": len(records) - len(done),
        "standard_usd": round(standard, 9),
        "jev_usd": round(jev, 9),
        "saved_usd": round(saved, 9),
        "saved_pct": round(100 * saved / standard, 1) if standard > 0 else 0.0,
        "speed": _speed(records),
    }


def _median_ms(values: list) -> int | None:
    values = [v for v in values if isinstance(v, (int, float))]
    return int(statistics.median(values)) if values else None


def _speed(records: list[dict]) -> dict:
    """Tempo de espera por tarefa (mediana). O standard só tem tempo quando foi medido."""
    measured = [r["standard"].get("duration_ms") for r in records
                if r["standard"].get("kind") == "measured" and r["standard"].get("duration_ms")]
    return {
        "jev_median_ms": _median_ms([r["jev"].get("duration_ms") for r in records]),
        "standard_median_ms": _median_ms(measured),
        "standard_measured": len(measured),
    }
