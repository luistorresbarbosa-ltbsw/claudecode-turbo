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
import re
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
                now: datetime | None = None, session: str | None = None, policy: str | None = None,
                context_tokens: int | None = None) -> dict:
    if standard.get("kind") not in BASELINE_KINDS:
        raise ValueError(f"standard.kind tem de ser um de {BASELINE_KINDS}, veio {standard.get('kind')!r}")

    task = task.strip()
    if len(task) > MAX_TASK_CHARS:
        task = task[: MAX_TASK_CHARS - 1] + "…"

    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    record = {
        "v": SCHEMA_VERSION,
        "id": uuid.uuid4().hex[:12],
        "ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "task": task,
        "decision": decision,
        "jev": jev,
        "standard": standard,
        "savings_usd": round(_saved(jev, standard), 9),
    }
    # Para avaliar o comportamento: a sessão do Claude Code, a versão da política e o contexto do turno
    extra = {"session": session, "policy": policy, "context_tokens": context_tokens}
    return {**record, **{k: v for k, v in extra.items() if v is not None}}


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


# --- o turno em curso -------------------------------------------------------------------------------------
# O ledger só ganha um registo no fim do turno; para o dashboard mostrar logo o que o Jev decidiu, o `jev route`
# guarda o turno em curso num ficheiro por sessão, que o `jev record` apaga. Um que ficou esquecido (o Claude
# Code fechado a meio) deixa de contar ao fim de LIVE_MAX_AGE_S.
LIVE_MAX_AGE_S = 1800
_LIVE_SESSION = re.compile(r"[A-Za-z0-9_-]{1,128}")


def live_dir(home: str | Path | None = None) -> Path:
    return ledger_path(home).parent / "live"


def _live_path(session: str, home) -> Path | None:
    if not isinstance(session, str) or not _LIVE_SESSION.fullmatch(session):
        return None  # nunca um caminho a partir de um id estranho
    return live_dir(home) / f"{session}.json"


def set_live(session: str, entry: dict, home: str | Path | None = None, now: datetime | None = None) -> None:
    path = _live_path(session, home)
    if path is None:
        return
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    record = {**entry, "session": session, "ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # quem lê nunca vê meio ficheiro


def clear_live(session: str, home: str | Path | None = None) -> None:
    path = _live_path(session, home)
    if path is not None:
        path.unlink(missing_ok=True)


def read_live(home: str | Path | None = None, now: datetime | None = None) -> list[dict]:
    """Os turnos em curso, do mais antigo para o mais recente; os esquecidos ficam de fora."""
    folder = live_dir(home)
    if not folder.is_dir():
        return []
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out = []
    for path in folder.glob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(str(entry["ts"]).replace("Z", "+00:00"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if (now - started).total_seconds() <= LIVE_MAX_AGE_S:
            out.append(entry)
    return sorted(out, key=lambda e: e["ts"])


def _unmangle(text: str) -> str:
    """Desfaz o texto UTF-8 lido como cp1252 (avanÃ§ar → avançar); o que não for isso fica como está."""
    if not isinstance(text, str) or ("Ã" not in text and "Â" not in text):
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text  # "SÃO PAULO" é texto a sério: não passa na volta


def repair_text(home: str | Path | None = None) -> int:
    """Repara as tarefas que o Windows estragou, guardando o ledger original em ledger.jsonl.bak; devolve quantas."""
    path = ledger_path(home)
    if not path.exists():
        return 0
    lines, fixed = path.read_bytes().splitlines(), 0
    out = []
    for raw in lines:
        try:
            rec = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            out.append(raw.decode("utf-8", errors="replace"))
            continue
        task = rec.get("task") if isinstance(rec, dict) else None
        good = _unmangle(task) if isinstance(task, str) else task
        if good != task:
            rec["task"], fixed = good, fixed + 1
            out.append(json.dumps(rec, ensure_ascii=False, allow_nan=False))
        else:
            out.append(raw.decode("utf-8", errors="replace"))
    if fixed:
        path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return fixed
