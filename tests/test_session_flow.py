"""O fluxo dentro da sessão: o mod chama `jev route` ao enviar o prompt e `jev record` no fim do turno."""
import io
import json

import pytest

from jev import cli, ledger, pricing
from jev.dispatch import RunResult
from jev.router import Decision, standard

SONNET_LOW = Decision(runner="anthropic", model="sonnet", effort="low", rationale="Jev: code:repo_scan",
                      router_cost_usd=0.0002)
FREE = Decision(runner="openrouter-free", model="nvidia/nemotron-3-ultra-550b-a55b:free", effort="high",
                rationale="Jev: qa_knowledge · barato: corre num free", router_cost_usd=0.0)
# uso de um turno real de sonnet (o formato do turn.complete: as quatro contagens como a API as escreve)
SONNET_USAGE = {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 10738,
                "cache_creation_input_tokens": 14262, "model": "claude-sonnet-5-5"}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_HOME", str(tmp_path))
    for var in ("JEV_DEPTH", "JEV_STANDARD_MODEL", "JEV_STANDARD_EFFORT"):
        monkeypatch.delenv(var, raising=False)


def free_ok(text="Uma closure é…"):
    def run_free(task, decision):
        run_free.calls.append(task)
        return RunResult(ok=True, model_id=decision.model, cost_usd=0.0, tokens={"input": 1000, "output": 500},
                         duration_ms=3000, text=text)
    run_free.calls = []
    return run_free


def free_failing(task, decision):
    return RunResult(ok=False, model_id=decision.model, cost_usd=0.0, tokens=None, duration_ms=500, text="",
                     error="RateLimitError: 429")


def route(task, decision, *, run_free=None, agent=False, capsys):
    args = ["route"] + (["--agent"] if agent else [])
    code = cli.main(args, decide=lambda t, **k: decision, run_free=run_free or free_ok(), stdin=io.StringIO(task))
    return code, json.loads(capsys.readouterr().out)


def record(payload, capsys):
    code = cli.main(["record"], stdin=io.StringIO(json.dumps(payload)))
    return code, json.loads(capsys.readouterr().out)


# --- route -------------------------------------------------------------------

def test_route_gives_the_mod_the_anthropic_model_id_and_effort(capsys):
    code, out = route("onde está o timeout?", SONNET_LOW, capsys=capsys)

    assert code == 0
    assert (out["model_id"], out["decision"]["effort"]) == ("claude-sonnet-5-5", "low")
    assert out["free"] is None and out["decide_ms"] >= 0
    assert ledger.read_all() == []  # o turno Anthropic regista-se no fim, com o uso real


def test_route_answers_a_free_decision_and_records_it_at_once(capsys):
    run_free = free_ok("Uma closure é uma função que lembra o seu âmbito.")

    code, out = route("o que é uma closure?", FREE, run_free=run_free, capsys=capsys)

    assert run_free.calls == ["o que é uma closure?"]
    assert out["free"]["ok"] and out["free"]["text"].startswith("Uma closure")
    rec = ledger.read_all()[-1]
    assert rec["jev"]["cost_usd"] == 0.0 and rec["jev"]["duration_ms"] >= 3000
    # standard estimado: os mesmos tokens + o contexto fixo do Claude Code, a preço Opus
    assert rec["standard"]["cost_usd"] == pytest.approx(0.0942246)
    assert out["summary"]["tasks"] == 1


def test_route_falls_back_to_standard_when_the_free_model_fails(capsys):
    code, out = route("x", FREE, run_free=free_failing, capsys=capsys)

    assert out["decision"]["is_standard"] and "429" in out["decision"]["router_error"]
    assert out["model_id"] is None  # o mod não mexe no modelo: a sessão segue com o standard
    assert ledger.read_all() == []


def test_route_for_a_subagent_never_uses_a_free_model(capsys):
    run_free = free_ok()

    code, out = route("analisa o módulo de faturação", FREE, run_free=run_free, agent=True, capsys=capsys)

    assert run_free.calls == []  # um subagente usa ferramentas: um free não serve
    assert (out["decision"]["model"], out["model_id"]) == ("sonnet", "claude-sonnet-5-5")


# --- record ------------------------------------------------------------------

def test_record_prices_the_real_turn_and_estimates_the_standard(capsys):
    code, out = record({"task": "onde está o timeout?", "decision": SONNET_LOW.to_ledger(),
                        "model_id": "claude-sonnet-5-5", "usage": SONNET_USAGE, "duration_ms": 9000,
                        "reason": "answer"}, capsys)

    rec = ledger.read_all()[-1]
    # turno real de sonnet ($0.0592396, confirmado contra o Claude Code) + a decisão do Jev
    assert rec["jev"]["cost_usd"] == pytest.approx(0.0592396 + 0.0002)
    assert rec["jev"]["duration_ms"] == 9000 and rec["jev"]["ok"] is True
    # os mesmos tokens a preço Opus: 2×$4 + 4×$20 + 10738×$0.20 + 14262×$8, por milhão
    assert rec["standard"]["kind"] == "estimated"
    assert rec["standard"]["cost_usd"] == pytest.approx(0.1163316)
    assert out["summary"]["tasks"] == 1


def test_record_of_a_standard_turn_is_a_real_standard_measurement(capsys):
    record({"task": "x", "decision": standard("TimeoutError", router_cost_usd=0.0001).to_ledger(), "model_id": None,
            "usage": {**SONNET_USAGE, "model": "claude-opus-5-5"}, "duration_ms": 41000, "reason": "answer"}, capsys)

    rec = ledger.read_all()[-1]
    assert rec["standard"]["kind"] == "measured" and rec["standard"]["duration_ms"] == 41000
    assert rec["savings_usd"] == pytest.approx(-0.0001)  # só a decisão falhada do Jev


def test_record_of_an_interrupted_turn_saves_nothing(capsys):
    record({"task": "x", "decision": SONNET_LOW.to_ledger(), "model_id": "claude-sonnet-5-5",
            "usage": SONNET_USAGE, "duration_ms": 2000, "reason": "aborted"}, capsys)

    rec = ledger.read_all()[-1]
    assert rec["jev"]["ok"] is False and rec["savings_usd"] < 0


def test_record_marks_subagent_turns(capsys):
    record({"task": "analisa o módulo", "decision": SONNET_LOW.to_ledger(), "model_id": "claude-sonnet-5-5",
            "usage": SONNET_USAGE, "duration_ms": 5000, "reason": "answer", "scope": "agent"}, capsys)

    assert ledger.read_all()[-1]["decision"]["scope"] == "agent"
