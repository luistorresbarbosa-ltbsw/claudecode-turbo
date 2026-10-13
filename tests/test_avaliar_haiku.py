"""A regra de decisão do teste dirigido (scripts/avaliar_haiku.py): fixada antes de correr."""
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("avaliar_haiku", _ROOT / "scripts" / "avaliar_haiku.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


def numbers(**over):
    out = {"subagentes": {"jev-v4-antes": {"haiku": 4}, "jev-v4": {"sonnet": 4}}, "tarefas_perdidas": [],
           "mesmas_condições": {"jev-v4-antes": 10.0, "jev-v4": 10.5}}
    out.update(over)
    return out


def test_haiku_kept_before_and_lifted_after_confirms_the_change():
    assert A.verdict(numbers()) == {"válida": True, "confirmado": True, "critérios": {
        "M2 novo sem haiku": True, "Q1 tarefas": True, "Q2 custo + tempo": True}}


def test_no_haiku_subagent_in_the_old_arm_means_the_path_was_not_forced_so_no_verdict():
    v = A.verdict(numbers(subagentes={"jev-v4-antes": {"sonnet": 4}, "jev-v4": {"sonnet": 4}}))
    assert v["válida"] is False and v["confirmado"] is None


def test_too_few_subagents_gives_no_verdict():
    assert A.verdict(numbers(subagentes={"jev-v4-antes": {"haiku": 2}, "jev-v4": {"sonnet": 2}}))["válida"] is False


def test_a_haiku_subagent_left_in_the_new_arm_fails_m2():
    v = A.verdict(numbers(subagentes={"jev-v4-antes": {"haiku": 4}, "jev-v4": {"haiku": 1, "sonnet": 3}}))
    assert v["critérios"]["M2 novo sem haiku"] is False and v["confirmado"] is False


def test_losing_a_task_fails_q1_and_costing_over_ten_percent_fails_q2():
    assert A.verdict(numbers(tarefas_perdidas=["T3"]))["critérios"]["Q1 tarefas"] is False
    assert A.verdict(numbers(mesmas_condições={"jev-v4-antes": 10.0, "jev-v4": 11.1}))["critérios"]["Q2 custo + tempo"] is False
    assert A.verdict(numbers(mesmas_condições={"jev-v4-antes": 10.0, "jev-v4": 11.0}))["critérios"]["Q2 custo + tempo"] is True
