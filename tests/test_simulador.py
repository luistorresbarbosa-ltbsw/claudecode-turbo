"""Simulador das políticas nas mesmas condições: perfis médios dos braços e o oráculo."""
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "simular_politicas.py"
_spec = importlib.util.spec_from_file_location("simular_politicas", _PATH)
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def turn(model, *, output=1_000, seconds=10.0, read=20_000, write=1_000):
    return {"model": model, "seconds": seconds,
            "warm": {"requests": 2, "input": 10, "read": read, "write": write, "output": output}}


def test_mean_profiles_averages_the_arms_that_ran_the_turn_in_that_model():
    arms = {"a": [turn("sonnet", output=100, seconds=10.0)],
            "b": [turn("opus", output=500, seconds=40.0)],
            "c": [turn("sonnet", output=300, seconds=30.0)]}

    prof = S.mean_profiles(arms, 1)

    assert prof[(0, "sonnet")]["output"] == pytest.approx(200)
    assert prof[(0, "sonnet")]["seconds"] == pytest.approx(20.0)
    assert prof[(0, "opus")]["output"] == pytest.approx(500)
    assert not prof[(0, "sonnet")].get("synthetic")


def test_mean_profiles_synthesizes_a_model_no_arm_ran_with_its_measured_speed():
    arms = {"a": [turn("sonnet", output=1_000, seconds=10.0)], "b": [turn("sonnet", output=1_000, seconds=20.0)]}

    prof = S.mean_profiles(arms, 1)

    opus = prof[(0, "opus")]
    assert opus["synthetic"]
    assert opus["output"] == pytest.approx(1_000)
    # o mesmo trabalho, à velocidade do Opus: + 1k × (8,2 − 5,6) ms
    assert opus["seconds"] == pytest.approx(15.0 + 1_000 * (S.SECONDS_PER_TOKEN["opus"] - S.SECONDS_PER_TOKEN["sonnet"]))


def three_turns():
    arms = {"a": [turn("sonnet"), turn("sonnet"), turn("sonnet")],
            "b": [turn("opus"), turn("opus"), turn("opus")]}
    return S.mean_profiles(arms, 3), [30_000, 60_000, 90_000]


def test_the_oracle_is_never_worse_than_a_fixed_sequence():
    prof, contexts = three_turns()

    best = S.oracle(prof, contexts, required_opus=[False, False, False])

    for seq in (["sonnet"] * 3, ["opus"] * 3, ["sonnet", "opus", "sonnet"]):
        assert best["objective"] <= S.objective(S.replay(seq, prof, contexts)) + 1e-12
    assert best["models"] == ["sonnet"] * 3  # o Sonnet é mais barato e mais rápido em tudo


def test_the_oracle_keeps_the_opus_where_the_jev_asked_for_it():
    prof, contexts = three_turns()

    best = S.oracle(prof, contexts, required_opus=[False, True, False])

    assert best["models"][1] == "opus"
    assert best["objective"] >= S.oracle(prof, contexts, required_opus=[False] * 3)["objective"]
