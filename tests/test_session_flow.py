"""O fluxo dentro da sessão: o mod chama `jev route` ao enviar o prompt e `jev record` no fim do turno."""
import io
import json
import sys

import pytest

from jev import cli, ledger, pricing
from jev.dispatch import RunResult
from jev.router import Decision, standard
from tests.test_router import LAST_EXCHANGE

SONNET_LOW = Decision(runner="anthropic", model="sonnet", effort="low", rationale="Jev: code:repo_scan",
                      router_cost_usd=0.0002)
OPUS_HIGH = Decision(runner="anthropic", model="opus", effort="high", rationale="Jev: code:debugging",
                     router_cost_usd=0.0007)
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
    def run_free(task, decision, history=()):
        run_free.calls.append(task)
        run_free.histories.append(list(history))
        return RunResult(ok=True, model_id=decision.model, cost_usd=0.0, tokens={"input": 1000, "output": 500},
                         duration_ms=3000, text=text)
    run_free.calls, run_free.histories = [], []
    return run_free


def free_failing(task, decision, history=()):
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
    assert out["decision"]["effort"] == "high"  # o esforço do Jev mantém-se
    assert out["decision"]["rationale"].endswith(" · subagente: sonnet")


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


def test_route_json_gives_the_jev_the_prompt_and_the_last_exchange(capsys):
    seen = {}

    def decide(task, **kw):
        seen.update(task=task, **kw)
        return SONNET_LOW

    code = cli.main(["route", "--json"], decide=decide, run_free=free_ok(),
                    stdin=io.StringIO(json.dumps({"task": "sim, avança", "history": LAST_EXCHANGE})))

    assert code == 0 and seen == {"task": "sim, avança", "history": LAST_EXCHANGE}
    assert json.loads(capsys.readouterr().out)["decision"]["model"] == "sonnet"


def test_a_free_answer_gets_the_last_exchange_too(capsys):
    run_free = free_ok("A validação recusa campos a mais.")

    cli.main(["route", "--json"], decide=lambda t, **k: FREE, run_free=run_free,
             stdin=io.StringIO(json.dumps({"task": "explica melhor", "history": LAST_EXCHANGE})))

    assert run_free.calls == ["explica melhor"] and run_free.histories == [LAST_EXCHANGE]


# --- v2: o modelo é da sessão (a cache é de cada modelo) -----------------------------------------------

def routed(decision, *, session="s1", reset=False, capsys):
    payload = {"task": "x", "history": [], "session": session, "reset": reset}
    assert cli.main(["route", "--json"], decide=lambda t, **k: decision, run_free=free_ok(),
                    stdin=io.StringIO(json.dumps(payload))) == 0
    return json.loads(capsys.readouterr().out)


def test_route_v2_keeps_the_sessions_model_when_the_jev_asks_for_a_smaller_one(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v2")

    routed(OPUS_HIGH, capsys=capsys)
    out = routed(SONNET_LOW, capsys=capsys)

    assert out["decision"]["model"] == "opus" and out["decision"]["effort"] == "high"
    assert out["model_id"] == pricing.ALIASES["opus"]
    assert "v2: mantém opus · high" in out["decision"]["rationale"]


def test_route_v2_after_a_reset_follows_the_jev_again(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v2")

    routed(OPUS_HIGH, capsys=capsys)
    out = routed(SONNET_LOW, reset=True, capsys=capsys)  # /clear ou compactação: a cache ficou fria

    assert out["decision"]["model"] == "sonnet"


def test_route_v2_sessions_do_not_mix(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v2")

    routed(OPUS_HIGH, session="s1", capsys=capsys)
    out = routed(SONNET_LOW, session="s2", capsys=capsys)

    assert out["decision"]["model"] == "sonnet"


def test_route_v1_decides_each_prompt_on_its_own(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v1")

    routed(OPUS_HIGH, capsys=capsys)
    out = routed(SONNET_LOW, capsys=capsys)

    assert out["decision"]["model"] == "sonnet"


def test_route_says_which_policy_decided(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v2")

    assert routed(SONNET_LOW, capsys=capsys)["policy"] == "v2"


# --- v3 na CLI: o histórico sobrevive ao --resume, a faixa segue a tarefa, o arrependimento acumula -------

BOTH = {"sonnet": ["low", "medium", "high"], "opus": ["medium", "high"]}
OPUS_NEW = Decision(runner="anthropic", model="opus", effort="high", rationale="Jev: code:debugging",
                    signals={"task_changed": 0.4, "gain": 0.4, "admitted": BOTH})
SONNET_FOLLOW_UP = Decision(runner="anthropic", model="sonnet", effort="medium", rationale="Jev: code:debugging",
                            signals={"task_changed": 0.1, "gain": 0.2, "admitted": BOTH})
SONNET_NEW = Decision(runner="anthropic", model="sonnet", effort="medium", rationale="Jev: code:general_impl",
                      signals={"task_changed": 0.4, "gain": 0.2, "admitted": BOTH})


def turn_v3(decision, *, task="x", context=60_000, answer="feito", output=1000, writes=500, capsys, seen=None):
    def decide(t, **kw):
        if seen is not None:
            seen.append(kw.get("history"))
        return decision
    cli.main(["route", "--json"], decide=decide, run_free=free_ok(),
             stdin=io.StringIO(json.dumps({"task": task, "history": [], "session": "s1"})))
    out = json.loads(capsys.readouterr().out)
    usage = {"input_tokens": 2, "output_tokens": output, "cache_read_input_tokens": 30_000,
             "cache_creation_input_tokens": writes, "model": out["model_id"]}
    cli.main(["record"], stdin=io.StringIO(json.dumps({
        "task": task, "decision": out["decision"], "model_id": out["model_id"], "usage": usage, "duration_ms": 1000,
        "reason": "answer", "scope": "main", "session": "s1", "answer": answer, "context": context})))
    capsys.readouterr()
    return out


def test_route_uses_the_sessions_last_exchange_when_the_mod_sends_none(capsys):
    # cada `claude -p --resume` é um processo novo: a última troca tem de estar guardada no núcleo
    seen = []
    turn_v3(SONNET_NEW, task="acrescenta fatura/io.py", answer="Proponho validar os campos. Avanço?", capsys=capsys)
    turn_v3(SONNET_FOLLOW_UP, task="sim, avança", capsys=capsys, seen=seen)

    assert seen[-1] == [{"role": "user", "content": "acrescenta fatura/io.py"},
                        {"role": "assistant", "content": "Proponho validar os campos. Avanço?"}]


def test_route_v3_keeps_the_model_on_a_follow_up(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v3")

    turn_v3(OPUS_NEW, capsys=capsys)
    out = turn_v3(SONNET_FOLLOW_UP, capsys=capsys)

    assert out["decision"]["model"] == "opus" and "mesma tarefa" in out["decision"]["rationale"]


def test_route_v3_follows_the_jev_on_a_new_task_with_a_small_context(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v3")

    turn_v3(OPUS_NEW, context=20_000, capsys=capsys)
    out = turn_v3(SONNET_NEW, capsys=capsys)

    assert out["decision"]["model"] == "sonnet"


def test_record_adds_regret_when_v3_kept_a_bigger_model(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v3")

    turn_v3(OPUS_NEW, capsys=capsys)
    turn_v3(SONNET_NEW, output=10_000, writes=5_000, capsys=capsys)  # o Jev queria o Sonnet; ficou no Opus

    from jev import policy
    state = policy.load_state("s1")
    assert state["context"] == 60_000 and state["last_answer"] == "feito"
    assert state["regret"] == pytest.approx(0.10 + 0.02 + 0.26)


def test_a_free_answer_opens_a_session_without_breaking_the_route(capsys, monkeypatch):
    # com a v3 por defeito e o pool "all", o primeiro prompt de uma sessão pode ir para um free
    monkeypatch.setenv("JEV_POLICY", "v3")

    out = routed(FREE, capsys=capsys)

    assert out["free"]["ok"]
    from jev import policy
    assert policy.load_state("s1")["last_runner"] == "openrouter-free"


# --- v4: os seguimentos óbvios correm na faixa sem perguntar ao Jev --------------------------------------

FOLLOW_UP = "Corre os testes e corrige o que falhar."
TASK = "Os testes de IVA da Madeira falham. Descobre porquê."


def test_route_v4_a_follow_up_runs_on_the_lane_without_the_jev(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v4")
    seen = []

    first = turn_v3(OPUS_NEW, task=TASK, capsys=capsys)
    out = turn_v3(SONNET_FOLLOW_UP, task=FOLLOW_UP, capsys=capsys, seen=seen)

    assert seen == []  # o Jev não foi chamado
    lane = (first["decision"]["model"], first["decision"]["effort"])  # (o Opus de ganho 0,4 passou a sonnet · high)
    assert (out["decision"]["model"], out["decision"]["effort"]) == lane
    assert out["decide_ms"] == 0 and out["decision"]["router_cost_usd"] == 0.0
    rec = ledger.read_all()[-1]
    assert rec["decision"]["signals"]["jev"] == "saltado"
    from jev import policy
    assert policy.load_state("s1")["followups"] == 1


def test_route_v3_still_asks_the_jev_on_a_follow_up(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v3")
    seen = []

    turn_v3(OPUS_NEW, task=TASK, capsys=capsys)
    turn_v3(SONNET_FOLLOW_UP, task=FOLLOW_UP, capsys=capsys, seen=seen)

    assert len(seen) == 1


def test_route_v4_asks_the_jev_after_a_free_answer(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v4")
    seen = []

    turn_v3(OPUS_NEW, task=TASK, capsys=capsys)
    cli.main(["route", "--json"], decide=lambda t, **k: FREE, run_free=free_ok(),
             stdin=io.StringIO(json.dumps({"task": "o que é o IVA?", "history": [], "session": "s1"})))
    capsys.readouterr()
    turn_v3(SONNET_FOLLOW_UP, task="sim, explica melhor", capsys=capsys, seen=seen)

    assert len(seen) == 1


def test_route_v4_a_subagent_always_asks_the_jev(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v4")
    calls = []

    def decide(t, **kw):
        calls.append(t)
        return SONNET_LOW
    cli.main(["route", "--json", "--agent"], decide=decide, run_free=free_ok(),
             stdin=io.StringIO(json.dumps({"task": FOLLOW_UP, "history": [], "session": "s1"})))

    assert calls == [FOLLOW_UP]


def test_record_keeps_how_long_the_route_and_the_decision_took(capsys):
    _, out = record({"task": "x", "decision": SONNET_LOW.to_ledger(), "model_id": "claude-sonnet-5-5",
                     "usage": SONNET_USAGE, "duration_ms": 9000, "reason": "answer", "scope": "main",
                     "route_ms": 2400, "decide_ms": 1900}, capsys)

    assert (out["record"]["jev"]["route_ms"], out["record"]["jev"]["decide_ms"]) == (2400, 1900)


# --- o ledger para avaliar o JEV: a sessão, a versão e o contexto de cada turno ---------------------------

def test_record_keeps_the_session_the_policy_and_the_context(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v4")

    turn_v3(OPUS_NEW, task=TASK, context=61_000, capsys=capsys)

    rec = ledger.read_all()[-1]
    assert (rec["session"], rec["policy"], rec["context_tokens"]) == ("s1", "v4", 61_000)


def test_a_subagent_turn_keeps_its_session_too(capsys):
    _, out = record({"task": "x", "decision": SONNET_LOW.to_ledger(), "model_id": "claude-sonnet-5-5",
                     "usage": SONNET_USAGE, "duration_ms": 900, "reason": "answer", "scope": "agent",
                     "session": "s1"}, capsys)

    assert out["record"]["session"] == "s1" and "context_tokens" not in out["record"]


def test_a_free_answer_is_logged_with_its_session(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v3")

    routed(FREE, capsys=capsys)

    rec = ledger.read_all()[-1]
    assert (rec["session"], rec["policy"]) == ("s1", "v3")


def test_route_marks_the_turn_in_progress_and_record_clears_it(capsys, monkeypatch):
    monkeypatch.setenv("JEV_POLICY", "v3")

    cli.main(["route", "--json"], decide=lambda t, **k: OPUS_NEW, run_free=free_ok(),
             stdin=io.StringIO(json.dumps({"task": TASK, "history": [], "session": "s1"})))
    out = json.loads(capsys.readouterr().out)

    live = ledger.read_live()
    assert [(x["session"], x["task"], x["decision"]["model"], x["policy"]) for x in live] == [("s1", TASK, "opus", "v3")]

    record({"task": TASK, "decision": out["decision"], "model_id": out["model_id"], "usage": SONNET_USAGE,
            "duration_ms": 900, "reason": "aborted", "scope": "main", "session": "s1"}, capsys)
    assert ledger.read_live() == []  # mesmo um turno interrompido deixa de estar em curso


def test_a_turn_the_jev_did_not_change_saves_nothing(capsys):
    # um subagente que ficou com o modelo que declarou, ou uma sessão com o modelo fixado: sem o JEV era igual
    unrouted = {"runner": "anthropic", "model": "haiku", "effort": None, "rationale": "sem decisão do Jev: modelo declarado",
                "is_standard": False, "router_model": "sem decisão", "router_cost_usd": 0, "router_error": None,
                "signals": {"jev": "sem decisão", "rule": "modelo declarado"}}
    _, out = record({"task": "onde está o timeout?", "decision": unrouted, "model_id": "claude-sonnet-5-5",
                     "usage": SONNET_USAGE, "duration_ms": 3000, "reason": "answer", "scope": "agent",
                     "session": "s1", "baseline": "same"}, capsys)

    rec = out["record"]
    assert rec["standard"]["kind"] == "measured"
    assert rec["standard"]["cost_usd"] == pytest.approx(rec["jev"]["cost_usd"]) and rec["savings_usd"] == 0


# --- Windows: o stdin de um pipe vem na codificação do sistema (cp1252), e os acentos estragavam-se -------

def test_record_reads_utf8_even_when_the_platform_default_is_cp1252(monkeypatch):
    payload = {"task": "antes de avançar para alterações", "decision": SONNET_LOW.to_ledger(),
               "model_id": "claude-sonnet-5-5", "usage": SONNET_USAGE, "duration_ms": 900, "reason": "answer"}
    raw = io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(raw, encoding="cp1252"))
    out = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(out, encoding="cp1252"))

    cli.main(["record"])
    sys.stdout.flush()

    assert ledger.read_all()[-1]["task"] == "antes de avançar para alterações"
    out.getvalue().decode("utf-8")  # o que o mod lê também sai em UTF-8


def test_ledger_repair_fixes_text_garbled_on_windows(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JEV_HOME", str(tmp_path))
    ok, bad = _plain_record("SÃO PAULO e avançar"), _plain_record("antes de avanÃ§ar para alteraÃ§Ãµes")
    ledger.append(ok)
    ledger.append(bad)

    assert cli.main(["ledger", "--reparar"]) == 0

    assert [r["task"] for r in ledger.read_all()] == ["SÃO PAULO e avançar", "antes de avançar para alterações"]
    assert "1 registo" in capsys.readouterr().out
    assert (tmp_path / "ledger.jsonl.bak").exists()


def _plain_record(task):
    return ledger.make_record(task=task, decision=SONNET_LOW.to_ledger(),
                              jev={"model_id": "claude-sonnet-5-5", "cost_usd": 0.01, "tokens": None,
                                   "duration_ms": 10, "ok": True, "fallback": None},
                              standard={"kind": "estimated", "model_id": "claude-opus-5-5", "effort": "xhigh",
                                        "cost_usd": 0.02, "tokens": None, "duration_ms": None})
