"""CLI do JEV.

    jev run <tarefa> [--edits] [--ab] [--dry] [--json]   (a tarefa também pode vir do stdin)
    jev ledger [--json]

`run` decide com o Jev, executa, compara com o standard e regista no ledger.
O standard é "medido" quando correu de facto (--ab, ou um fallback) e "estimado" quando são
os mesmos tokens ao preço do modelo standard. A estimativa é conservadora: não conta o
thinking extra que o standard (xhigh) faria nem o tokenizer maior do Opus.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

from jev import dispatch, ledger, policy, pricing, router

REPO_ENV = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_MAX_USD = 0.50


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jev", description="O JEV escolhe o modelo e o esforço para cada tarefa.")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="decide, corre a tarefa e regista o custo")
    run.add_argument("task", nargs="*", help="a tarefa; se faltar, lê do stdin")
    run.add_argument("--edits", action="store_true", help="deixa editar ficheiros (por defeito só lê)")
    run.add_argument("--ab", action="store_true", help="corre também o standard, para medir a diferença")
    run.add_argument("--dry", action="store_true", help="só decide e estima: não corre nem regista (paga só a decisão do Jev)")
    run.add_argument("--json", action="store_true")
    led = sub.add_parser("ledger", help="totais acumulados")
    led.add_argument("--json", action="store_true")
    led.add_argument("--reparar", action="store_true",
                     help="repara o texto com acentos que o Windows estragou (avanÃ§ar em vez de avançar), com cópia em ledger.jsonl.bak")
    route = sub.add_parser("route", help="para o mod: o Jev decide o prompt do stdin (JSON na saída)")
    route.add_argument("--agent", action="store_true", help="a tarefa é de um subagente (nunca vai para um free)")
    route.add_argument("--json", action="store_true",
                       help='o stdin é {"task", "history"}: o prompt e a troca anterior da sessão')
    sub.add_parser("record", help="para o mod: regista um turno (JSON no stdin)")
    pil = sub.add_parser("pilot", help="o piloto: standard vs JEV no projeto fatura").add_subparsers(dest="pilot_cmd", required=True)
    prun = pil.add_parser("run", help="corre os dois braços, tarefa a tarefa, e no fim o juiz")
    prun.add_argument("--project", default="fatura", help="a pasta do projeto em pilot/ (por defeito, fatura)")
    prun.add_argument("--tasks", help="ids separados por vírgulas (por defeito, todas)")
    prun.add_argument("--max-min", type=float, default=10, help="envelope de tempo de cada braço, em minutos")
    prun.add_argument("--max-usd-task", type=float, default=1.0)
    prun.add_argument("--max-usd-total", type=float, default=9.0)
    prun.add_argument("--no-judge", action="store_true")
    prun.add_argument("--anthropic-only", action="store_true",
                      help="o pool do Jev só com modelos Anthropic (sem respostas free)")
    prun.add_argument("--arms", default="standard,jev",
                      help="os dois braços a comparar, separados por vírgula: standard, jev, jev-v1, jev-v2")
    prun.add_argument("--judge-target", help="o braço a comparar com cada um dos outros no juiz por tarefa "
                                              "(painel Opus e Sonnet); obrigatório com 3 braços")
    prun.add_argument("--session", action="store_true",
                      help="cada braço corre todas as tarefas numa só sessão, com um seguimento nas de código")
    prun.add_argument("--claude-md", action="store_true",
                      help="dá aos dois braços um CLAUDE.md, feito de pilot/<projeto>/regras.md")
    return p


def _usd(x: float) -> str:
    return f"${x:.4f}"


def _label(d: router.Decision) -> str:
    return f"{d.model} · {d.effort}" if d.effort else f"{d.model} (free)"


def _estimate(decision: router.Decision, task: str) -> dict:
    tokens = pricing.with_cc_overhead({"input": len(task) // 4, "output": decision.est_output_tokens})
    run = 0.0 if decision.runner == "openrouter-free" else pricing.cost_of(decision.model, tokens)
    jev = run + decision.router_cost_usd  # a decisão do Jev paga-se mesmo num --dry
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
        lines.append(f"⚠ o Jev falhou ({decision.router_error}); fui pelo standard")
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


def _estimated_standard(tokens: dict) -> dict:
    std = router.standard()
    return {"kind": "estimated", "model_id": pricing.ALIASES.get(std.model, std.model), "effort": std.effort,
            "cost_usd": round(pricing.cost_of(std.model, tokens), 9), "tokens": None, "duration_ms": None}


def _route(task: str, *, history=(), session: str | None = None, reset: bool = False, agent: bool,
           decide, run_free, context: int | None = None) -> dict:
    # A sessão (o modelo da faixa, o contexto e a última troca): um subagente começa sem contexto
    state = None if (agent or not session or reset) else policy.load_state(session)
    if not history and state and state.get("last_prompt") and state.get("last_answer"):
        # cada `claude -p --resume` é um processo novo e o mod perde a troca anterior: vem do núcleo
        history = [{"role": "user", "content": state["last_prompt"]},
                   {"role": "assistant", "content": state["last_answer"]}]
    # v4: um seguimento óbvio corre na faixa sem perguntar ao Jev (a v3 manteria o modelo de qualquer maneira)
    skipped = None if agent else policy.follow_up_without_jev(state, task, policy.current())
    started = time.monotonic()
    decision = skipped or decide(task, history=history)
    decide_ms = 0 if skipped else int((time.monotonic() - started) * 1000)
    if agent and decision.runner == "openrouter-free":  # um subagente usa ferramentas: um free não serve
        decision = dataclasses.replace(decision, runner="anthropic", model="sonnet",
                                       rationale=decision.rationale + " · subagente: sonnet")
    if not agent and session:
        new_task = policy.is_new_task(decision.signals, task) if state else True
        decision = policy.apply(decision, state, policy.current(), prompt=task, context=context)
        # uma resposta free não muda a faixa (e numa sessão nova ainda não há faixa nenhuma)
        policy.save_state(session, {**(policy.next_state(decision, state, new_task=new_task) or {}),
                                    "last_prompt": task[:2000], "last_answer": "", "last_runner": decision.runner})
        if decision.runner == "anthropic":  # um free responde já e regista-se já: não fica em curso
            ledger.set_live(session, {"task": task[:ledger.MAX_TASK_CHARS], "decision": decision.to_ledger(),
                                      "policy": policy.current()})
    out = {"decision": decision.to_ledger(), "decide_ms": decide_ms, "free": None, "policy": policy.current(),
           "model_id": None if decision.is_standard else pricing.ALIASES.get(decision.model, decision.model)}
    if decision.runner != "openrouter-free":
        return out

    res = run_free(task, decision, history=history)
    out["free"] = {"ok": res.ok, "text": res.text, "model_id": res.model_id, "duration_ms": res.duration_ms,
                   "error": res.error}
    if not res.ok:  # regra do utilizador: qualquer falha cai para o standard (a sessão segue sem mudanças)
        fallback = router.standard(f"o free falhou: {res.error}", router_cost_usd=decision.router_cost_usd)
        out.update(decision=fallback.to_ledger(), model_id=None)
        if session and not agent:  # a sessão vai correr no standard
            policy.save_state(session, {**policy.next_state(fallback, state), "last_prompt": task[:2000],
                                        "last_answer": "", "last_runner": fallback.runner})
        return out
    if session and not agent:  # a resposta free é a troca que o próximo prompt vai ver
        saved = policy.load_state(session)
        if saved:
            policy.save_state(session, {**saved, "last_answer": res.text[-2000:]})
    # este prompt não vai ter turno Anthropic: regista-se já
    ledger.append(ledger.make_record(
        task=task, decision=decision.to_ledger(),
        jev={"model_id": res.model_id, "cost_usd": decision.router_cost_usd, "tokens": res.tokens,
             "duration_ms": decide_ms + (res.duration_ms or 0), "ok": True, "fallback": None, "decide_ms": decide_ms},
        standard=_estimated_standard(pricing.with_cc_overhead(res.tokens or {})),
        session=session, policy=policy.current(),
    ))
    out["summary"] = ledger.summarize(ledger.read_all())
    return out


def _record(payload: dict) -> dict:
    if payload.get("session") and payload.get("scope") != "agent":
        ledger.clear_live(payload["session"])  # o turno acabou (bem ou não): deixa de estar em curso
    decision = dict(payload["decision"])
    if payload.get("scope"):
        decision["scope"] = payload["scope"]
    usage = payload.get("usage") or {}
    tokens = pricing.tokens_from_claude_usage(usage)
    model_id = usage.get("model") or payload.get("model_id") or pricing.ALIASES[router.standard().model]
    run_cost = pricing.cost_of(model_id, tokens)
    duration = payload.get("duration_ms")
    if decision.get("is_standard"):  # o standard correu de facto: é uma medição real dele
        std = router.standard()
        standard = {"kind": "measured", "model_id": model_id, "effort": std.effort, "cost_usd": run_cost,
                    "tokens": tokens, "duration_ms": duration}
    elif payload.get("baseline") == "same":  # o JEV não mudou este turno: sem ele corria igual, nada a atribuir
        standard = {"kind": "measured", "model_id": model_id, "effort": decision.get("effort"), "cost_usd": run_cost,
                    "tokens": tokens, "duration_ms": duration}
    else:
        standard = _estimated_standard(tokens)
    rec = ledger.make_record(
        task=payload.get("task") or "",
        decision=decision,
        jev={"model_id": model_id, "cost_usd": run_cost + (decision.get("router_cost_usd") or 0.0),
             "tokens": tokens, "duration_ms": duration, "ok": payload.get("reason") == "answer", "fallback": None,
             # o que se esperou antes do turno: o `jev route` inteiro (medido no mod) e, dentro dele, a decisão
             "route_ms": payload.get("route_ms"), "decide_ms": payload.get("decide_ms")},
        standard=standard,
        session=payload.get("session"), policy=policy.current(),
        context_tokens=int(payload["context"]) if payload.get("context") is not None else None,
    )
    ledger.append(rec)
    _remember_turn(payload, usage)
    return {"record": rec, "summary": ledger.summarize(ledger.read_all())}


def _remember_turn(payload: dict, usage: dict) -> None:
    """Guarda na sessão o que o turno deixou: a resposta (o histórico do próximo prompt), o contexto e a hora do
    último pedido; e, se a v3 manteve um modelo maior do que o Jev pedia, o que isso custou (o arrependimento)."""
    session = payload.get("session")
    if not session or payload.get("scope") == "agent":
        return
    state = policy.load_state(session)
    if not state:
        return
    state = {**state, "last_answer": (payload.get("answer") or "")[-2000:], "updated": time.time()}
    if payload.get("context") is not None:
        state["context"] = int(payload["context"])
    if state.get("held_from"):
        state = policy.add_regret(state, output_tokens=int(usage.get("output_tokens") or 0),
                                  write_tokens=int(usage.get("cache_creation_input_tokens") or 0))
    policy.save_state(session, state)


def _pilot(args) -> int:
    from datetime import datetime

    from jev import pilot_run

    root = pilot_run.REPO / "pilot" / args.project
    if not (root / "tasks.json").is_file():
        return _fail(f"não há piloto '{args.project}' em pilot/ (falta pilot/{args.project}/tasks.json)")
    tasks = json.loads((root / "tasks.json").read_text(encoding="utf-8"))
    if args.tasks:
        wanted = [t.strip() for t in args.tasks.split(",")]
        tasks = [t for t in tasks if t["id"] in wanted]
    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    unknown = [a for a in arms if a not in pilot_run.KNOWN_ARMS]
    if unknown or len(arms) not in (2, 3) or len(set(arms)) != len(arms):
        return _fail(f"--arms: quero dois ou três braços diferentes de {', '.join(pilot_run.KNOWN_ARMS)} "
                     f"(veio {args.arms})")
    if (args.judge_target and args.judge_target not in arms) or (len(arms) == 3 and not args.judge_target
                                                                  and not args.no_judge):
        return _fail(f"--judge-target: com 3 braços, diz qual comparar com os outros (um de {', '.join(arms)})")
    # no repo não se chama CLAUDE.md, senão a sessão que mexe em pilot/ também o carregava
    claude_md = root / "regras.md" if args.claude_md else None
    if claude_md and not claude_md.is_file():
        return _fail(f"--claude-md: falta pilot/{args.project}/regras.md")
    judge_file = root / "juiz.json"  # o que o juiz avalia neste projeto (sem ele, o do fatura)
    judge_spec = json.loads(judge_file.read_text(encoding="utf-8")) if judge_file.is_file() else None
    variant = "anthropic" if args.anthropic_only else "anthropic+free"
    arms_tag = "" if arms == pilot_run.ARMS else "-".join(a.removeprefix("jev-") for a in arms) + "-"
    pilot_id = (f"{args.project}-{'anthropic-' if args.anthropic_only else ''}{'claudemd-' if claude_md else ''}"
                f"{'sessao-' if args.session else ''}{arms_tag}" + datetime.now().strftime("%Y%m%d-%H%M"))
    print(f"piloto {pilot_id}: {len(tasks)} tarefas · {args.max_min:g} min por braço · "
          f"${args.max_usd_task:g}/tarefa · ${args.max_usd_total:g} no total · pool do Jev: {variant}"
          f"{' · CLAUDE.md nos dois braços' if claude_md else ''} · braços: {' vs '.join(arms)}"
          f"{' · uma sessão por braço' if args.session else ''}", flush=True)
    pilot_run.run_pilot(tasks, pilot_id=pilot_id, seed=root / "seed", inject_root=root / "inject",
                        acceptance_root=root / "acceptance", max_min_arm=args.max_min,
                        max_usd_task=args.max_usd_task, max_usd_total=args.max_usd_total,
                        judge=not args.no_judge, log=lambda msg: print(msg, flush=True),
                        jev_env={"JEV_POOL": "anthropic" if args.anthropic_only else "all"}, variant=variant,
                        claude_md=claude_md, judge_spec=judge_spec, arms=arms, session=args.session,
                        judge_target=args.judge_target)
    return 0


def _fail(msg: str) -> int:
    print(f"jev: {msg}", file=sys.stderr)
    return 2


def _utf8_stdio() -> None:
    """O mod fala com o núcleo em UTF-8. No Windows, um pipe vem na codificação do sistema (cp1252) e os acentos
    estragavam-se (avançar → avanÃ§ar); por isso o stdin e o stdout são sempre UTF-8."""
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass  # um stream que não se reconfigura (nos testes, ou já lido) fica como está


def main(argv: list[str] | None = None, *, decide=None, execute=None, run_free=None, stdin=None) -> int:
    _utf8_stdio()
    args = _parser().parse_args(argv)
    if args.cmd in ("route", "record"):
        text = (stdin or sys.stdin).read()
        if args.cmd == "record":
            print(json.dumps(_record(json.loads(text)), ensure_ascii=False))
            return 0
        if decide is None:
            from dotenv import load_dotenv
            load_dotenv(REPO_ENV)
            decide = router.decide
        task, history, session, reset, context = text.strip(), [], None, False, None
        if args.json:
            payload = json.loads(text)
            task, history = payload["task"].strip(), payload.get("history") or []
            session, reset = payload.get("session"), bool(payload.get("reset"))
            context = payload.get("context")
        out = _route(task, history=history, session=session, reset=reset, agent=args.agent, decide=decide,
                     run_free=run_free or dispatch.run_free, context=context)
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if args.cmd == "pilot":
        return _pilot(args)
    if args.cmd == "ledger" and args.reparar:
        fixed = ledger.repair_text()
        print(f"{fixed} registo{'s' if fixed != 1 else ''} reparado{'s' if fixed != 1 else ''}"
              + (f"; o original ficou em {ledger.ledger_path()}.bak" if fixed else ""))
        return 0
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
        jev={"model_id": final.model_id, "cost_usd": outcome.cost_usd + decision.router_cost_usd,
             "tokens": final.tokens,
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
