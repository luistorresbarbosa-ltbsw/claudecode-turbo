"""Dispatch do JEV: corre a tarefa onde o router decidiu.

- runner "anthropic": `claude -p` pela subscrição do utilizador, com ferramentas restritas
  e teto de custo.
- runner "openrouter-free": uma completion via litellm, sem ferramentas, a $0.

Se a tentativa escolhida falhar, a tarefa corre no standard Anthropic e os custos das duas
tentativas somam-se: uma execução falhada também se paga (ver tests/fixtures).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass

from jev import pricing, router

READ_ONLY_TOOLS = ("Read", "Grep", "Glob")
EDIT_TOOLS = ("Edit", "Write")
CLAUDE_TIMEOUT_S = 590  # o $.process.run do mod corta aos 600 s
FREE_TIMEOUT_S = 120
FREE_SYSTEM_PROMPT = "Responde na língua da pergunta, de forma clara e concisa."
# Os modelos Anthropic correm pela subscrição (o login do claude), nunca por uma API key
SUBSCRIPTION_ONLY_STRIP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@dataclass(frozen=True)
class RunResult:
    ok: bool
    model_id: str
    cost_usd: float
    tokens: dict | None
    duration_ms: int | None
    text: str
    error: str | None = None
    is_standard: bool = False


@dataclass(frozen=True)
class Outcome:
    final: RunResult
    failed: RunResult | None = None  # a tentativa do JEV que falhou antes do fallback

    @property
    def cost_usd(self) -> float:
        return self.final.cost_usd + (self.failed.cost_usd if self.failed else 0.0)

    @property
    def duration_ms(self) -> int:
        return sum(run.duration_ms or 0 for run in (self.final, self.failed) if run)

    @property
    def fallback(self) -> dict | None:
        if self.failed is None:
            return None
        return {"from": self.failed.model_id, "reason": self.failed.error}


def claude_argv(decision: router.Decision, *, edits: bool, max_usd: float) -> list[str]:
    # --tools define as ferramentas que existem: sem Bash nem MCP, nada corre comandos.
    # (O --permission-mode dontAsk deixou correr Bash num probe real; não serve.)
    tools = READ_ONLY_TOOLS + (EDIT_TOOLS if edits else ())
    argv = ["claude", "-p", "--output-format", "json",
            "--max-budget-usd", str(max_usd),
            "--tools", ",".join(tools),
            "--strict-mcp-config",
            "--permission-prompts", "none"]
    if edits:
        argv += ["--permission-mode", "acceptEdits"]
    if not decision.is_standard:  # o standard corre com o modelo e o effortLevel das settings
        argv += ["--model", decision.model, "--effort", decision.effort]
    return argv


def _child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in SUBSCRIPTION_ONLY_STRIP}
    env["JEV_DEPTH"] = "1"  # o cli recusa correr dentro de uma execução do próprio JEV
    return env


def _main_model(model_usage: dict, default: str) -> str:
    if not model_usage:
        return default
    return max(model_usage, key=lambda m: model_usage[m].get("costUSD") or 0.0)


def run_claude(task: str, decision: router.Decision, *, edits: bool, max_usd: float,
               cwd: str | None = None, run=subprocess.run) -> RunResult:
    requested = pricing.ALIASES.get(decision.model, decision.model)
    started = time.monotonic()

    def failure(error: str, cost: float = 0.0) -> RunResult:
        return RunResult(ok=False, model_id=requested, cost_usd=cost, tokens=None,
                         duration_ms=int((time.monotonic() - started) * 1000), text="",
                         error=error, is_standard=decision.is_standard)

    try:
        proc = run(claude_argv(decision, edits=edits, max_usd=max_usd),
                   input=task, capture_output=True, text=True, cwd=cwd,
                   env=_child_env(), timeout=CLAUDE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return failure(f"Timeout: o claude -p passou de {CLAUDE_TIMEOUT_S}s (custo desconhecido)")
    try:
        data = json.loads(proc.stdout)  # mesmo a falhar (exit 1) o claude -p escreve o JSON
    except json.JSONDecodeError:
        return failure(f"o claude -p saiu com {proc.returncode} sem JSON: {proc.stderr.strip()[:200]}")

    ok = proc.returncode == 0 and not data.get("is_error")
    return RunResult(
        ok=ok,
        model_id=_main_model(data.get("modelUsage") or {}, requested),
        cost_usd=float(data.get("total_cost_usd") or 0.0),
        tokens=pricing.tokens_from_claude_usage(data.get("usage") or {}),
        duration_ms=data.get("duration_ms"),
        text=data.get("result") or "",
        error=None if ok else f"{data.get('subtype')}: {data.get('terminal_reason')}",
        is_standard=decision.is_standard,
    )


def _litellm_completion(**kwargs):
    import litellm  # aqui e não no topo: importá-lo custa ~1 s, e só os free precisam dele

    litellm.suppress_debug_info = True  # senão imprime avisos no stdout, que o mod lê como JSON
    return litellm.completion(**kwargs)


def run_free(task: str, decision: router.Decision, *, complete=_litellm_completion) -> RunResult:
    started = time.monotonic()

    def result(ok: bool, text: str = "", tokens: dict | None = None, error: str | None = None) -> RunResult:
        return RunResult(ok=ok, model_id=decision.model, cost_usd=0.0, tokens=tokens,
                         duration_ms=int((time.monotonic() - started) * 1000), text=text, error=error)

    try:
        resp = complete(model=f"openrouter/{decision.model}",
                        messages=[{"role": "system", "content": FREE_SYSTEM_PROMPT},
                                  {"role": "user", "content": task}],
                        timeout=FREE_TIMEOUT_S)
        text = (resp.choices[0].message.content or "").strip()
        tokens = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens}
    except Exception as exc:  # qualquer falha do modelo free leva ao fallback
        return result(False, error=f"{type(exc).__name__}: {str(exc)[:160]}")
    if not text:
        return result(False, tokens=tokens, error="resposta vazia")
    return result(True, text=text, tokens=tokens)


def execute(task: str, decision: router.Decision, *, edits: bool, max_usd: float,
            cwd: str | None = None, run_claude=run_claude, run_free=run_free) -> Outcome:
    if decision.runner == "openrouter-free":
        first = run_free(task, decision)
    else:
        first = run_claude(task, decision, edits=edits, max_usd=max_usd, cwd=cwd)
    if first.ok or decision.is_standard:
        return Outcome(final=first)
    retry = run_claude(task, router.standard(), edits=edits, max_usd=max_usd, cwd=cwd)
    return Outcome(final=retry, failed=first)
