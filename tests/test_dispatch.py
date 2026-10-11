"""Dispatch: corre a tarefa onde o JEV decidiu; se falhar, corre no standard e paga as duas."""
import functools
import subprocess
from pathlib import Path

import litellm
import pytest

from jev import dispatch
from jev.router import Decision, standard

FIX = Path(__file__).parent / "fixtures"
SUCCESS = (FIX / "claude_p_success.json").read_text()        # execução real, sonnet
BUDGET_ERROR = (FIX / "claude_p_budget_error.json").read_text()  # execução real, teto estourado
HAIKU_LOW = Decision(runner="anthropic", model="haiku", effort="low", rationale="r")
FREE = Decision(runner="openrouter-free", model="nvidia/nemotron-3-ultra-550b-a55b:free", effort=None, rationale="r")


def flag(argv, name):
    return argv[argv.index(name) + 1]


def fake_run(stdout, returncode=0, stderr=""):
    def run(argv, **kw):
        run.calls.append({"argv": argv, **kw})
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)
    run.calls = []
    return run


# --- a linha de comando do claude -p -----------------------------------------

def test_jev_choice_runs_with_its_model_and_effort():
    argv = dispatch.claude_argv(HAIKU_LOW, edits=False, max_usd=0.5)

    assert argv[:2] == ["claude", "-p"]
    assert (flag(argv, "--model"), flag(argv, "--effort")) == ("haiku", "low")
    assert flag(argv, "--output-format") == "json"


def test_standard_runs_with_the_users_own_defaults():
    argv = dispatch.claude_argv(standard(), edits=False, max_usd=0.5)

    assert "--model" not in argv and "--effort" not in argv


def test_read_only_unless_edits_are_asked_for():
    # --tools limita as ferramentas que EXISTEM; o dontAsk deixou correr Bash num probe real
    ro = dispatch.claude_argv(HAIKU_LOW, edits=False, max_usd=0.5)
    rw = dispatch.claude_argv(HAIKU_LOW, edits=True, max_usd=0.5)

    assert set(flag(ro, "--tools").split(",")) == {"Read", "Grep", "Glob"}
    assert set(flag(rw, "--tools").split(",")) == {"Read", "Grep", "Glob", "Edit", "Write"}
    assert flag(rw, "--permission-mode") == "acceptEdits"
    for argv in (ro, rw):
        assert "--strict-mcp-config" in argv           # sem ferramentas de MCP servers
        assert flag(argv, "--permission-prompts") == "none"  # o que pediria confirmação é negado
        assert "dontAsk" not in argv and "bypassPermissions" not in argv


def test_every_claude_run_has_a_budget_cap():
    assert flag(dispatch.claude_argv(HAIKU_LOW, edits=False, max_usd=0.5), "--max-budget-usd") == "0.5"


# --- correr o claude -p ------------------------------------------------------

def test_claude_success_is_read_from_the_real_json():
    r = dispatch.run_claude("responde so: ok", HAIKU_LOW, edits=False, max_usd=0.5, run=fake_run(SUCCESS))

    assert r.ok and r.text == "ok" and not r.is_standard
    assert r.model_id == "claude-sonnet-5-5"  # o modelo que correu de facto (modelUsage), não o pedido
    assert r.cost_usd == pytest.approx(0.0592396)
    assert r.tokens == {"input": 2, "output": 4, "cache_read": 10738, "cache_write_5m": 0, "cache_write_1h": 14262}
    assert r.duration_ms == 1492


def test_task_goes_through_stdin_never_argv():
    run = fake_run(SUCCESS)

    dispatch.run_claude("--help me", HAIKU_LOW, edits=False, max_usd=0.5, run=run)

    assert run.calls[0]["input"] == "--help me"
    assert "--help me" not in run.calls[0]["argv"]


def test_child_run_is_marked_so_jev_cannot_recurse():
    run = fake_run(SUCCESS)

    dispatch.run_claude("x", HAIKU_LOW, edits=False, max_usd=0.5, run=run)

    assert run.calls[0]["env"]["JEV_DEPTH"] == "1"


def test_standard_run_is_flagged_as_standard():
    assert dispatch.run_claude("x", standard(), edits=False, max_usd=0.5, run=fake_run(SUCCESS)).is_standard


def test_budget_error_is_a_failure_that_still_costs():
    r = dispatch.run_claude("x", HAIKU_LOW, edits=False, max_usd=0.001, run=fake_run(BUDGET_ERROR, returncode=1))

    assert not r.ok
    assert r.cost_usd == pytest.approx(0.0219195)
    assert "error_max_budget_usd" in r.error


def test_crash_without_json_is_a_failure():
    r = dispatch.run_claude("x", HAIKU_LOW, edits=False, max_usd=0.5,
                            run=fake_run("", returncode=2, stderr="boom"))

    assert not r.ok and r.cost_usd == 0.0 and "boom" in r.error


def test_timeout_is_a_failure():
    def run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)

    r = dispatch.run_claude("x", HAIKU_LOW, edits=False, max_usd=0.5, run=run)

    assert not r.ok and "Timeout" in r.error


# --- correr num modelo free --------------------------------------------------

def test_free_run_returns_the_answer_at_zero_cost():
    seen = {}

    def complete(**kw):
        seen.update(kw)
        return litellm.completion(**kw, mock_response="TCP garante a entrega; UDP não.")

    r = dispatch.run_free("tcp vs udp?", FREE, complete=complete)

    assert r.ok and r.text.startswith("TCP") and r.cost_usd == 0.0
    assert seen["model"] == "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
    assert "tcp vs udp?" in seen["messages"][-1]["content"]
    assert r.tokens["output"] > 0



def test_a_free_run_reads_the_last_exchange_before_the_prompt():
    from tests.test_router import LAST_EXCHANGE
    seen = {}

    def complete(**kw):
        seen.update(kw)
        return litellm.completion(**kw, mock_response="A validação recusa campos a mais.")

    dispatch.run_free("explica melhor", FREE, history=LAST_EXCHANGE, complete=complete)

    assert seen["messages"][0]["role"] == "system"
    assert seen["messages"][1:] == [*LAST_EXCHANGE, {"role": "user", "content": "explica melhor"}]

def test_free_run_with_an_empty_reply_is_a_failure():
    # mock_response="" não serve: o litellm trata-o como "sem mock" e vai à rede
    def complete(**kw):
        return litellm.ModelResponse(
            choices=[{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": ""}}],
            usage={"prompt_tokens": 12, "completion_tokens": 0, "total_tokens": 12},
        )

    r = dispatch.run_free("x", FREE, complete=complete)

    assert not r.ok and "vazia" in r.error


def test_free_run_exception_is_a_failure():
    def complete(**kw):
        raise litellm.Timeout(message="lento", model="m", llm_provider="openrouter")

    r = dispatch.run_free("x", FREE, complete=complete)

    assert not r.ok and "Timeout" in r.error


# --- orquestração com fallback para o standard -------------------------------

def ok(model_id, cost, is_standard=False):
    return dispatch.RunResult(ok=True, model_id=model_id, cost_usd=cost, tokens={"output": 10},
                              duration_ms=5, text="feito", is_standard=is_standard)


def failed(model_id, cost, reason="boom"):
    return dispatch.RunResult(ok=False, model_id=model_id, cost_usd=cost, tokens=None,
                              duration_ms=5, text="", error=reason)


class Runner:
    """Executor falso: devolve resultados por ordem e regista as decisões que recebeu."""

    def __init__(self, *results):
        self.results, self.seen = list(results), []

    def __call__(self, task, decision, **kw):
        self.seen.append(decision)
        return self.results.pop(0)


def run_execute(decision, claude, free):
    return dispatch.execute("x", decision, edits=False, max_usd=0.5, run_claude=claude, run_free=free)


def test_successful_choice_needs_no_fallback():
    out = run_execute(HAIKU_LOW, Runner(ok("claude-haiku-4-5", 0.02)), Runner())

    assert out.final.ok and out.failed is None and out.fallback is None
    assert out.cost_usd == pytest.approx(0.02)


def test_failed_free_run_falls_back_to_standard():
    claude = Runner(ok("claude-opus-5-5", 0.10, is_standard=True))

    out = run_execute(FREE, claude, Runner(failed(FREE.model, 0.0, "resposta vazia")))

    assert claude.seen[0].is_standard
    assert out.final.ok and out.fallback == {"from": FREE.model, "reason": "resposta vazia"}
    assert out.cost_usd == pytest.approx(0.10)


def test_failed_anthropic_choice_falls_back_and_both_attempts_are_paid():
    claude = Runner(failed("claude-haiku-4-5", 0.02), ok("claude-opus-5-5", 0.10, is_standard=True))

    out = run_execute(HAIKU_LOW, claude, Runner())

    assert [d.is_standard for d in claude.seen] == [False, True]
    assert out.cost_usd == pytest.approx(0.12)


def test_standard_decision_is_never_retried():
    claude = Runner(failed("claude-opus-5-5", 0.05))

    out = run_execute(standard("RateLimitError"), claude, Runner())

    assert len(claude.seen) == 1
    assert not out.final.ok and out.fallback is None


def test_when_the_fallback_also_fails_the_outcome_is_not_ok():
    out = run_execute(FREE, Runner(failed("claude-opus-5-5", 0.07, "rede")), Runner(failed(FREE.model, 0.0, "429")))

    assert not out.final.ok
    assert out.fallback["reason"] == "429"
    assert out.cost_usd == pytest.approx(0.07)
