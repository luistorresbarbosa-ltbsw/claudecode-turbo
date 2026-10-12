"""Piloto do JEV: o mesmo projeto corrido por dois braços, standard e JEV, tarefa a tarefa.

O registo é o contrato entre o harness (que escreve) e o dashboard (que lê): um ficheiro JSONL por
piloto em $JEV_HOME/pilots/<id>.jsonl, com três tipos de linha:

    meta  {pilot, started, tasks: [{id, title, kind}], max_usd_per_task, max_usd_total}
    task  {pilot, arm: standard|jev, task, title, kind, status: done|error|budget|timeout|skipped,
           cost_usd, wall_ms, models: {model_id: cost_usd}, jev: {decisions, decision_cost_usd} | null,
           acceptance: {ok, passed, failed}}
    judge {pilot, model, cost_usd, criteria: [{id, label, result: standard|jev|tie|both_bad|inconclusive,
           verdicts: [{a, winner, reason}]}], passes: [{a, ok, cost_usd, error}]}
          (o juiz às cegas, duas passagens com a ordem trocada; `passes` diz como correu cada uma)
    task_judge {pilot, panel, cost_usd, results: [{pair: [alvo, outro], task, models, criteria: [{id, label,
           votes, result}]}]}  (o juiz por tarefa: só onde o modelo principal difere; 3 de 4 votos)
    end   {pilot, finished, stopped: null | motivo}

O custo é o `total_cost_usd` que o próprio Claude Code reporta (preço de lista), mais, no braço JEV,
o custo das decisões do Jev. O tempo é o relógio real de cada `claude -p`, decisão do Jev incluída.
"""
from __future__ import annotations

import json
from pathlib import Path

from jev import ledger


def pilots_dir(home: str | Path | None = None) -> Path:
    return ledger.ledger_path(home).parent / "pilots"


def append(row: dict, home: str | Path | None = None) -> Path:
    path = pilots_dir(home) / f"{row['pilot']}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    return path


def _rows(path: Path) -> list[dict]:
    rows = []
    for raw in path.read_bytes().splitlines():
        try:
            row = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("v") == 1 and row.get("type") in ("meta", "task", "judge", "task_judge", "end"):
            rows.append(row)
    return rows


def read_all(home: str | Path | None = None) -> list[dict]:
    """Os pilotos, do mais recente para o mais antigo: {id, meta, tasks, judge, end}."""
    folder = pilots_dir(home)
    if not folder.is_dir():
        return []
    pilots = []
    for path in folder.glob("*.jsonl"):
        if not path.is_file():
            continue
        rows = _rows(path)
        meta = next((r for r in rows if r["type"] == "meta"), None)
        if meta is None:
            continue
        pilots.append({
            "id": meta["pilot"],
            "meta": meta,
            "tasks": [r for r in rows if r["type"] == "task"],
            "judge": next((r for r in reversed(rows) if r["type"] == "judge"), None),
            "task_judge": next((r for r in reversed(rows) if r["type"] == "task_judge"), None),
            "end": next((r for r in rows if r["type"] == "end"), None),
        })
    return sorted(pilots, key=lambda p: str(p["meta"].get("started", "")), reverse=True)
