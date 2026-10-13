"""Contrato do ledger: o núcleo escreve, o dashboard lê."""
import json
from datetime import datetime, timezone

import pytest

from jev import ledger


def _rec(task="t", std=0.30, jev=0.05, kind="estimated", ok=True):
    return ledger.make_record(
        task=task,
        decision={"runner": "anthropic", "model": "haiku", "effort": "low",
                  "rationale": "trivial", "router_model": "heuristic", "router_cost_usd": 0.0},
        jev={"model_id": "claude-haiku-4-5", "cost_usd": jev, "tokens": None,
             "duration_ms": 100, "ok": ok},
        standard={"kind": kind, "model_id": "claude-opus-5-5", "effort": "high",
                  "cost_usd": std, "tokens": None, "duration_ms": None},
    )


def test_append_then_read_keeps_every_record_in_order(tmp_path):
    ledger.append(_rec(task="primeira"), home=tmp_path)
    ledger.append(_rec(task="segunda"), home=tmp_path)

    assert [r["task"] for r in ledger.read_all(home=tmp_path)] == ["primeira", "segunda"]


def test_append_creates_missing_home_dir(tmp_path):
    home = tmp_path / "nao" / "existe"

    ledger.append(_rec(), home=home)

    assert (home / "ledger.jsonl").exists()


def test_jev_home_env_var_redirects_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_HOME", str(tmp_path))

    ledger.append(_rec(task="via env"))

    assert ledger.read_all()[0]["task"] == "via env"
    assert (tmp_path / "ledger.jsonl").exists()


def test_read_all_on_missing_ledger_is_empty(tmp_path):
    assert ledger.read_all(home=tmp_path) == []


def test_read_all_skips_corrupt_and_incomplete_lines(tmp_path):
    good = json.dumps(_rec(task="boa"))
    (tmp_path / "ledger.jsonl").write_text(
        "\n".join([
            good,
            "{nao e json",                      # escrita interrompida a meio
            '{"v": 1, "task": "sem custos"}',   # registo incompleto
            "",
            '["lista", "nao", "dict"]',
            good,
        ]),
        encoding="utf-8",
    )

    assert [r["task"] for r in ledger.read_all(home=tmp_path)] == ["boa", "boa"]


@pytest.mark.parametrize("std, jev, want", [
    (0.30, 0.05, 0.25),    # JEV poupou
    (0.10, 0.40, -0.30),   # JEV escolheu algo mais caro: poupança negativa, não abs()
    (0.02, 0.02, 0.0),
])
def test_savings_is_standard_minus_jev(std, jev, want):
    assert _rec(std=std, jev=jev)["savings_usd"] == pytest.approx(want)


def test_unknown_baseline_kind_is_rejected():
    with pytest.raises(ValueError):
        _rec(kind="palpite")


def test_long_task_text_is_capped_but_short_text_is_untouched():
    assert len(_rec(task="x" * 5000)["task"]) <= 280
    assert _rec(task="  explica o ficheiro  ")["task"] == "explica o ficheiro"


def test_timestamp_is_utc_iso_with_z_suffix():
    rec = ledger.make_record(
        task="t",
        decision={}, jev={"cost_usd": 0.0}, standard={"kind": "measured", "cost_usd": 0.0},
        now=datetime(2026, 10, 11, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert rec["ts"] == "2026-10-11T10:00:00.000Z"


def test_summarize_totals_including_net_loss():
    recs = [_rec(std=0.30, jev=0.05), _rec(std=0.10, jev=0.40)]

    assert ledger.summarize(recs) == {
        "tasks": 2,
        "failed": 0,
        "standard_usd": pytest.approx(0.40),
        "jev_usd": pytest.approx(0.45),
        "saved_usd": pytest.approx(-0.05),
        "saved_pct": pytest.approx(-12.5),
        "speed": {"jev_median_ms": 100, "standard_median_ms": None, "standard_measured": 0},
    }


def test_summarize_empty_ledger_does_not_divide_by_zero():
    assert ledger.summarize([]) == {
        "tasks": 0, "failed": 0, "standard_usd": 0.0, "jev_usd": 0.0, "saved_usd": 0.0, "saved_pct": 0.0,
        "speed": {"jev_median_ms": None, "standard_median_ms": None, "standard_measured": 0},
    }


def test_a_failed_task_costs_what_it_spent_and_saves_nothing():
    # o trabalho continua por fazer, por isso o standard que "evitou" não conta
    assert _rec(std=0.10, jev=0.03, ok=False)["savings_usd"] == pytest.approx(-0.03)


def test_summarize_counts_failed_tasks_on_the_jev_side_only():
    recs = [_rec(std=0.30, jev=0.05), _rec(std=0.10, jev=0.03, ok=False)]

    assert ledger.summarize(recs) == {
        "tasks": 2,
        "failed": 1,
        "standard_usd": pytest.approx(0.30),
        "jev_usd": pytest.approx(0.08),
        "saved_usd": pytest.approx(0.22),
        "saved_pct": pytest.approx(73.3),
        "speed": {"jev_median_ms": 100, "standard_median_ms": None, "standard_measured": 0},
    }


def test_an_invalid_utf8_line_does_not_hide_the_rest_of_the_ledger(tmp_path):
    good = json.dumps(_rec(task="boa")).encode()
    (tmp_path / "ledger.jsonl").write_bytes(good + b"\n" + b'{"v": 1, "task": "cortad\xc3' + b"\n" + good + b"\n")

    assert [r["task"] for r in ledger.read_all(home=tmp_path)] == ["boa", "boa"]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_costs_are_skipped(tmp_path, bad):
    line = json.dumps(_rec(task="boa"))
    broken = line.replace('"cost_usd": 0.05', f'"cost_usd": {bad}')
    assert broken != line
    (tmp_path / "ledger.jsonl").write_text(broken + "\n" + line + "\n", encoding="utf-8")

    assert len(ledger.read_all(home=tmp_path)) == 1


def test_append_refuses_to_write_a_non_finite_cost(tmp_path):
    with pytest.raises(ValueError):
        ledger.append(_rec(jev=float("nan")), home=tmp_path)


def _timed(jev_ms, std_ms=None, kind="estimated"):
    rec = _rec(kind=kind)
    rec["jev"]["duration_ms"] = jev_ms
    rec["standard"]["duration_ms"] = std_ms
    return rec


def test_summarize_reports_speed_as_medians():
    recs = [_timed(4000), _timed(10000), _timed(8000, 41000, "measured"), _timed(6000, 30000, "measured")]

    speed = ledger.summarize(recs)["speed"]

    assert speed == {"jev_median_ms": 7000, "standard_median_ms": 35500, "standard_measured": 2}


def test_summarize_speed_without_measured_standard_has_no_comparison():
    assert ledger.summarize([_timed(5000)])["speed"] == {
        "jev_median_ms": 5000, "standard_median_ms": None, "standard_measured": 0,
    }


# --- o turno em curso: o que o Jev decidiu e ainda não acabou (para o dashboard o mostrar já) -------------

def test_a_turn_in_progress_is_kept_per_session_until_cleared(tmp_path):
    ledger.set_live("s1", {"task": "corre os testes", "decision": {"model": "sonnet", "effort": "high"}}, home=tmp_path)
    ledger.set_live("s2", {"task": "outra", "decision": {"model": "opus", "effort": "medium"}}, home=tmp_path)

    live = ledger.read_live(home=tmp_path)
    assert sorted(x["session"] for x in live) == ["s1", "s2"] and all("ts" in x for x in live)

    ledger.clear_live("s1", home=tmp_path)
    assert [x["session"] for x in ledger.read_live(home=tmp_path)] == ["s2"]


def test_a_stale_turn_in_progress_is_ignored(tmp_path):
    ledger.set_live("s1", {"task": "x"}, home=tmp_path, now=ledger.datetime(2026, 10, 13, 9, 0, tzinfo=ledger.timezone.utc))

    assert ledger.read_live(home=tmp_path, now=ledger.datetime(2026, 10, 13, 10, 0, tzinfo=ledger.timezone.utc)) == []


def test_a_strange_session_id_never_becomes_a_path(tmp_path):
    ledger.set_live("../../fora", {"task": "x"}, home=tmp_path)
    ledger.clear_live("../../fora", home=tmp_path)

    assert not list(tmp_path.parent.rglob("fora*"))
