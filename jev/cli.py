"""CLI do JEV.

    jev run <tarefa> [--edits] [--ab] [--dry] [--json]   (a tarefa também pode vir do stdin)
    jev ledger [--json]

`run` decide com o cérebro free, executa, compara com o standard e regista no ledger.
O standard é "medido" quando correu de facto (--ab, ou um fallback) e "estimado" quando são
os mesmos tokens ao preço do modelo standard. A estimativa é conservadora: não conta o
thinking extra que o standard (xhigh) faria nem o tokenizer maior do Opus.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from jev import dispatch, ledger, pricing, router

REPO_ENV = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_MAX_USD = 0.50


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jev", description="O JEV escolhe o modelo e o esforço para cada tarefa.")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="decide, corre a tarefa e regista o custo")
    run.add_argument("task", nargs="*", help="a tarefa; se faltar, lê do stdin")
    run.add_argument("--edits", action="store_true", help="deixa editar ficheiros (por defeito só lê)")
    run.add_argument("--ab", action="store_true", help="corre também o standard, para medir a diferença")
    run.add_argument("--dry", action="store_true", help="só decide e estima: não corre nem regista")
    run.add_argument("--json", action="store_true")
    led = sub.add_parser("ledger", help="totais acumulados")
    led.add_argument("--json", action="store_true")
    return p


def _usd(x: float) -> str:
    return f"${x:.4f}"


def _label(d: router.Decision) -> str:
    return f"{d.model} · {d.effort}" if d.effort else f"{d.model} (free)"


def _estimate(decision: router.Decision, task: str) -> dict:
    tokens = pricing.with_cc_overhead({"input": len(task) // 4, "output": decision.est_output_tokens})
    jev = 0.0 if decision.runner == "openrouter-free" else pricing.cost_of(decision.model, tokens)
    return {"jev_usd": round(jev, 9), "standard_usd": round(pricing.cost_of(router.standard().model, tokens), 9)}


def _measured(run: dispatch.RunResult, cost: float) -> dict:
    return {"kind": "measured", "model_id": run.model_id, "effort": router.standard().effort,
            "cost_usd": cost, "tokens": run.tokens, "duration_ms": run.duration_ms}


def _baseline(decision: router.Decision, outcome: dispatch.Outcome, ab: dispatch.Outcome | None) -> dict:
    std = router.standard()
    if ab is not None:
        return _measured(ab.final, ab.cost_usd)
    if outcome.final.is_standard:  # o standard correu de facto: decisão standard ou fallback
        return _measured(outcome.final, outcome.final.cost_usd)
    tokens = outcome.final.tokens or {}
    if decision.runner == "openrouter-free":  # fora do Claude Code não se pagou o contexto fixo
        tokens = pricing.with_cc_overhead(tokens)
    return {"kind": "estimated", "model_id": pricing.ALIASES.get(std.model, std.model), "effort": std.effort,
            "cost_usd": round(pricing.cost_of(std.model, tokens), 9), "tokens": None, "duration_ms": None}


def _report(decision: router.Decision, outcome: dispatch.Outcome, rec: dict, summary: dict, ab_usd: float) -> str:
    std, saved = rec["standard"], rec["savings_usd"]
    lines = []
    if decision.router_error:
        lines.append(f"⚠ o cérebro free falhou ({decision.router_error}); fui pelo standard")
    lines.append(f"JEV → {_label(decision)} · {decision.rationale}")
    if outcome.fallback:
        lines.append(f"⚠ {outcome.fallback['from']} falhou ({outcome.fallback['reason']}); repetido no standard")
    lines += ["", outcome.final.text if outcome.final.ok else f"✗ a tarefa falhou: {outcome.final.error}", ""]
    kind = "medido" if std["kind"] == "measured" else "estimado"
    verdict = f"poupaste {_usd(saved)}" if saved >= 0 else f"gastaste mais {_usd(-saved)}"
    lines.append(f"custo JEV {_usd(rec['jev']['cost_usd'])} · standard {_label(router.standard())} "
                 f"{_usd(std['cost_usd'])} ({kind}) · {verdict}")
    if ab_usd:
        lines.append(f"(o --ab gastou mais {_usd(ab_usd)} para medir o standard)")
    lines.append(f"total: {summary['tasks']} tarefa{'' if summary['tasks'] == 1 else 's'} · poupado {_usd(summary['saved_usd'])} "
                 f"({summary['saved_pct']}%) · preço de lista = quota da subscrição")
    return "\n".join(lines)


def _ledger_text(s: dict) -> str:
    return (f"{s['tasks']} tarefas · standard {_usd(s['standard_usd'])} · JEV {_usd(s['jev_usd'])} · "
            f"poupado {_usd(s['saved_usd'])} ({s['saved_pct']}%)")


def _fail(msg: str) -> int:
    print(f"jev: {msg}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None, *, decide=None, execute=None, stdin=None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "ledger":
        summary = ledger.summarize(ledger.read_all())
        print(json.dumps(summary) if args.json else _ledger_text(summary))
        return 0

    if os.environ.get("JEV_DEPTH"):
        return _fail("recuso correr dentro de uma execução do próprio JEV")
    task = " ".join(args.task).strip() or (stdin or sys.stdin).read().strip()
    if not task:
        return _fail("falta a tarefa (como argumento ou pelo stdin)")
    if args.ab and args.edits:
        return _fail("--ab com --edits aplicaria as edições duas vezes")

    if decide is None:  # só a execução real precisa da chave do OpenRouter
        from dotenv import load_dotenv
        load_dotenv(REPO_ENV)
        decide = router.decide
    execute = execute or dispatch.execute

    decision = decide(task)
    if args.dry:
        est = _estimate(decision, task)
        report = (f"JEV → {_label(decision)} · {decision.rationale}\n"
                  f"estimativa: JEV {_usd(est['jev_usd'])} · standard {_usd(est['standard_usd'])} (não correu)")
        print(json.dumps({"decision": decision.to_ledger(), "estimate": est, "report": report},
                         ensure_ascii=False) if args.json else report)
        return 0

    run_kw = {"edits": args.edits, "max_usd": float(os.environ.get("JEV_MAX_USD", DEFAULT_MAX_USD)),
              "cwd": os.getcwd()}
    outcome = execute(task, decision, **run_kw)
    ab = execute(task, router.standard(), **run_kw) if args.ab and not outcome.final.is_standard else None

    final = outcome.final
    rec = ledger.make_record(
        task=task,
        decision=decision.to_ledger(),
        jev={"model_id": final.model_id, "cost_usd": outcome.cost_usd, "tokens": final.tokens,
             "duration_ms": outcome.duration_ms,
             "ok": final.ok, "fallback": outcome.fallback},
        standard=_baseline(decision, outcome, ab),
    )
    ledger.append(rec)
    summary = ledger.summarize(ledger.read_all())
    report = _report(decision, outcome, rec, summary, ab.cost_usd if ab else 0.0)

    if args.json:
        print(json.dumps({"ok": final.ok, "answer": final.text, "report": report, "summary": summary, **rec},
                         ensure_ascii=False))
    else:
        print(report)
    return 0 if final.ok else 1
