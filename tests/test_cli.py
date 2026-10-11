"""CLI: decide, executa, compara com o standard e regista no ledger."""
import io
import json

import pytest

from jev import cli, ledger, pricing
from jev.dispatch import Outcome, RunResult
from jev.router import Decision, standard

from tests.test_pricing import HAIKU_PROBE_USAGE

HAIKU_LOW = Decision(runner="anthropic", model="haiku", effort="low", rationale="edição trivial", est_output_tokens=200)
FREE = Decision(runner="openrouter-free", model="nvidia/nemotron-3-ultra-550b-a55b:free", effort=None,
                rationale="pergunta conceptual", est_output_tokens=500)
HAIKU_TOKENS = pricing.tokens_from_claude_usage(HAIKU_PROBE_USAGE)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_HOME", str(tmp_path))
    for var in ("JEV_DEPTH", "JEV_STANDARD_MODEL", "JEV_STANDARD_EFFORT", "JEV_MAX_USD"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def result(model_id, cost, *, ok=True, tokens=None, is_standard=False, text="feito", error=None):
    return RunResult(ok=ok, model_id=model_id, cost_usd=cost, tokens=tokens, duration_ms=100,
                     text=text, error=error, is_standard=is_standard)


class FakeExecute:
    """Fronteira do dispatch: devolve resultados por ordem e regista as decisões recebidas."""

    def __init__(self, *outcomes):
        self.outcomes, self.decisions = list(outcomes), []

    def __call__(self, task, decision, **kw):
        self.decisions.append(decision)
        return self.outcomes.pop(0)


def run(args, *, decision=HAIKU_LOW, execute=None, stdin=""):
    execute = execute or FakeExecute()
    code = cli.main(args, decide=lambda task, **kw: decision, execute=execute, stdin=io.StringIO(stdin))
    return code, execute


def last_record():
    return ledger.read_all()[-1]


def test_run_compares_jev_with_an_estimated_standard():
    code, _ = run(["run", "corrige o typo"], execute=FakeExecute(
        Outcome(final=result("claude-haiku-4-5-20251001", 0.0227163, tokens=HAIKU_TOKENS))))

    rec = last_record()
    assert code == 0
    assert rec["jev"]["cost_usd"] == pytest.approx(0.0227163)
    assert rec["standard"]["kind"] == "estimated"
    # os mesmos tokens a preço Opus 5.5: 10×$4 + 392×$20 + 13803×$0.20 + 9683×$8, por milhão
    assert rec["standard"]["cost_usd"] == pytest.approx(0.0881046)
    assert rec["savings_usd"] == pytest.approx(0.0653883)


def test_free_run_estimate_includes_claude_codes_fixed_context():
    run(["run", "tcp vs udp?"], decision=FREE, execute=FakeExecute(
        Outcome(final=result(FREE.model, 0.0, tokens={"input": 1000, "output": 500}))))

    assert last_record()["standard"]["cost_usd"] == pytest.approx(0.0942246)


def test_execution_fallback_is_compared_with_the_standard_that_actually_ran():
    run(["run", "x"], execute=FakeExecute(Outcome(
        final=result("claude-opus-5-5", 0.10, tokens={"output": 1}, is_standard=True),
        failed=result("claude-haiku-4-5", 0.02, ok=False, error="error_max_budget_usd: budget_exhausted"))))

    rec = last_record()
    assert rec["standard"]["kind"] == "measured"
    assert rec["standard"]["cost_usd"] == pytest.approx(0.10)
    assert rec["jev"]["cost_usd"] == pytest.approx(0.12)
    assert rec["savings_usd"] == pytest.approx(-0.02)
    assert rec["jev"]["fallback"] == {"from": "claude-haiku-4-5", "reason": "error_max_budget_usd: budget_exhausted"}


def test_router_fallback_shows_no_savings():
    run(["run", "x"], decision=standard("RateLimitError: 429"), execute=FakeExecute(
        Outcome(final=result("claude-opus-5-5", 0.10, tokens={"output": 1}, is_standard=True))))

    rec = last_record()
    assert rec["savings_usd"] == 0.0
    assert rec["standard"]["kind"] == "measured"
    assert rec["decision"]["router_error"] == "RateLimitError: 429"


def test_ab_measures_the_standard_with_a_real_run():
    execute = FakeExecute(
        Outcome(final=result("claude-haiku-4-5", 0.02, tokens=HAIKU_TOKENS)),
        Outcome(final=result("claude-opus-5-5", 0.31, tokens={"output": 900}, is_standard=True)))

    run(["run", "--ab", "x"], execute=execute)

    assert [d.is_standard for d in execute.decisions] == [False, True]
    rec = last_record()
    assert rec["standard"]["kind"] == "measured"
    assert rec["standard"]["cost_usd"] == pytest.approx(0.31)


def test_ab_refuses_edits_because_they_would_be_applied_twice():
    code, execute = run(["run", "--ab", "--edits", "x"])

    assert code == 2 and execute.decisions == [] and ledger.read_all() == []


def test_dry_run_decides_but_neither_runs_nor_records(capsys):
    code, execute = run(["run", "--dry", "--json", "x"])

    out = json.loads(capsys.readouterr().out)
    assert code == 0 and execute.decisions == [] and ledger.read_all() == []
    assert out["decision"]["model"] == "haiku"
    assert out["estimate"]["standard_usd"] > out["estimate"]["jev_usd"] > 0


def test_refuses_to_run_inside_a_jev_child(monkeypatch):
    monkeypatch.setenv("JEV_DEPTH", "1")
    decided = []

    code = cli.main(["run", "x"], decide=lambda t, **k: decided.append(t), execute=FakeExecute(),
                    stdin=io.StringIO())

    assert code == 2 and decided == []


def test_task_can_come_from_stdin():
    seen = []

    cli.main(["run"], decide=lambda t, **k: seen.append(t) or HAIKU_LOW,
             execute=FakeExecute(Outcome(final=result("claude-haiku-4-5", 0.01, tokens=HAIKU_TOKENS))),
             stdin=io.StringIO("  tarefa vinda do stdin \n"))

    assert seen == ["tarefa vinda do stdin"]


def test_empty_task_is_an_error():
    code, execute = run(["run"], stdin="   ")

    assert code == 2 and execute.decisions == []


def test_failed_task_exits_nonzero_but_is_still_recorded():
    code, _ = run(["run", "x"], decision=standard("timeout"), execute=FakeExecute(
        Outcome(final=result("claude-opus-5-5", 0.05, ok=False, is_standard=True, error="rede"))))

    assert code == 1
    assert last_record()["jev"]["ok"] is False


def test_json_output_has_the_answer_report_and_running_total(capsys):
    run(["run", "--json", "x"], execute=FakeExecute(
        Outcome(final=result("claude-haiku-4-5-20251001", 0.0227163, tokens=HAIKU_TOKENS, text="Corrigido."))))

    out = json.loads(capsys.readouterr().out)
    assert out["answer"] == "Corrigido."
    assert out["summary"]["tasks"] == 1
    assert "haiku" in out["report"] and "0.0654" in out["report"]


def test_ledger_command_prints_the_totals(capsys):
    for cost in (0.02, 0.03):
        run(["run", "x"], execute=FakeExecute(Outcome(final=result("claude-haiku-4-5", cost, tokens=HAIKU_TOKENS))))
    capsys.readouterr()

    assert cli.main(["ledger", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tasks"] == 2


def test_json_stdout_stays_parseable_even_when_litellm_runs(capsys):
    # o mod lê o stdout inteiro como JSON, e o litellm gosta de imprimir avisos no stdout
    import functools
    from jev import router
    from tests.test_router import jev_reply
    decide = functools.partial(router.decide, post=jev_reply("jev_decision_simple"))

    cli.main(["run", "--dry", "--json", "x"], decide=decide, execute=FakeExecute(), stdin=io.StringIO())

    assert json.loads(capsys.readouterr().out)["decision"]["model"] == "sonnet"


def test_jevs_decision_cost_is_part_of_the_jev_path():
    paid = Decision(runner="anthropic", model="haiku", effort="low", rationale="r", router_cost_usd=0.002)

    run(["run", "x"], decision=paid, execute=FakeExecute(
        Outcome(final=result("claude-haiku-4-5-20251001", 0.0227163, tokens=HAIKU_TOKENS))))

    rec = last_record()
    assert rec["jev"]["cost_usd"] == pytest.approx(0.0247163)
    assert rec["savings_usd"] == pytest.approx(0.0881046 - 0.0247163)


def test_dry_run_estimate_includes_jevs_decision_cost(capsys):
    paid = Decision(runner="anthropic", model="haiku", effort="low", rationale="r", est_output_tokens=200,
                    router_cost_usd=0.002)

    run(["run", "--dry", "--json", "x"], decision=paid)

    est = json.loads(capsys.readouterr().out)["estimate"]
    # 200×$5 + 13803×$0.10 + 9683×$2 (Haiku, por milhão) = 0.0217463, mais a decisão do Jev
    assert est["jev_usd"] == pytest.approx(0.0217463 + 0.002)


def test_pilot_refuses_a_project_that_does_not_exist(capsys):
    assert cli.main(["pilot", "run", "--project", "nao-existe"]) == 2
    assert "nao-existe" in capsys.readouterr().err
