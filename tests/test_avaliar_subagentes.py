"""A regra de decisão da avaliação dos subagentes (scripts/avaliar_subagentes.py): fixada antes de correr."""
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("avaliar_subagentes", _ROOT / "scripts" / "avaliar_subagentes.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)

CLEAN = {"sem_decisao_abaixo_de_opus": [], "route_lento": []}


def numbers(**over):
    out = {"subagentes": {"jev-v4": 10, "jev-v4-antes": 9}, "tarefas_perdidas": [], "juiz": {"jev-v4": 6, "jev-v4-antes": 4},
           "auditoria": {"jev-v4": dict(CLEAN), "jev-v4-antes": dict(CLEAN)}, "pares_com_antes": 5,
           "real": {"standard": {"custo + tempo": 18.0}, "jev-v4-antes": {"custo + tempo": 6.7}, "jev-v4": {"custo + tempo": 8.2}},
           "mesmas_condições": {"standard": 30.0, "jev-v4-antes": 20.0, "jev-v4": 21.0}}
    out.update(over)
    return out


def record(model, rule=None, route_ms=1500, scope="agent"):
    return {"id": "r1", "decision": {"scope": scope, "model": model, "signals": {"rule": rule} if rule else {}},
            "jev": {"route_ms": route_ms}}


def test_everything_in_order_recommends_the_new_mod():
    v = A.verdict(numbers())
    assert v["válida"] and v["recomendado"] is True


def test_too_few_subagents_gives_no_verdict_instead_of_a_failure():
    v = A.verdict(numbers(subagentes={"jev-v4": 3, "jev-v4-antes": 9}))
    assert v == {"válida": False, "critérios": {}, "recomendado": None}


def test_losing_a_task_the_old_mod_or_standard_passes_fails_criterion_1():
    assert A.verdict(numbers(tarefas_perdidas=["calc-subagentes:T3 (perdeu para standard)"]))["recomendado"] is False


def test_the_judge_preferring_the_old_mod_fails_criterion_2_but_a_tie_passes():
    assert A.verdict(numbers(juiz={"jev-v4": 3, "jev-v4-antes": 5}))["critérios"]["2 juiz"] is False
    assert A.verdict(numbers(juiz={"jev-v4": 4, "jev-v4-antes": 4}))["critérios"]["2 juiz"] is True


def test_cost_up_to_ten_percent_over_the_old_mod_passes_but_more_fails():
    ok = numbers(mesmas_condições={"standard": 30.0, "jev-v4-antes": 20.0, "jev-v4": 22.0})
    bad = numbers(mesmas_condições={"standard": 30.0, "jev-v4-antes": 20.0, "jev-v4": 22.5})
    assert A.verdict(ok)["critérios"]["4a custo contra o antes"] is True
    assert A.verdict(bad)["critérios"]["4a custo contra o antes"] is False


def test_costing_more_than_standard_in_real_cost_and_time_fails_criterion_4b():
    v = A.verdict(numbers(real={"standard": {"custo + tempo": 8.0}, "jev-v4-antes": {"custo + tempo": 6.7},
                                "jev-v4": {"custo + tempo": 8.2}}))
    assert v["critérios"]["4b custo contra o standard"] is False and v["recomendado"] is False


def test_without_the_target_against_old_pair_judged_there_is_no_verdict_on_criterion_2():
    v = A.verdict(numbers(pares_com_antes=0))
    assert v["recomendado"] is None and "2 juiz" in v["sem_medição"]


def test_a_subagent_without_a_decision_running_below_opus_is_caught():
    audit = A.agent_audit([record("sonnet", rule="Jev sem resposta"), record("opus", rule="núcleo em falta"),
                           record("haiku"), record("sonnet", scope="main", rule="Jev sem resposta")])
    assert audit["subagentes"] == 3
    assert audit["sem_decisao_abaixo_de_opus"] == ["r1"]


def test_a_slow_route_over_thirty_seconds_is_caught():
    assert A.agent_audit([record("sonnet", route_ms=30_001)])["route_lento"] == ["r1"]
    assert A.agent_audit([record("sonnet", route_ms=30_000)])["route_lento"] == []
