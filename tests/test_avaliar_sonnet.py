"""A porta de ganho da experiência "o Sonnet onde o Jev pede Opus" (critério 3 de scripts/avaliar_sonnet.py)."""
import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "avaliar_sonnet.py"
_spec = importlib.util.spec_from_file_location("avaliar_sonnet", _PATH)
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


def tasks(*pairs):
    return {f"T{i}": {"gain": g, "holds": h} for i, (g, h) in enumerate(pairs)}


def test_without_failures_the_gate_is_the_largest_measured_gain():
    assert A.gate(tasks((0.28, True), (0.42, True), (0.55, True))) == 0.55


def test_no_gate_when_the_sonnet_fails_the_lowest_gain_task():
    assert A.gate(tasks((0.28, False), (0.42, True))) is None


def test_held_tasks_above_a_failure_do_not_widen_the_gate():
    assert A.gate(tasks((0.28, True), (0.33, True), (0.42, False), (0.5, True))) == 0.33


def test_no_tasks_no_gate():
    assert A.gate({}) is None
