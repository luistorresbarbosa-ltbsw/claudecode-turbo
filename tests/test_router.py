"""Router: o Jev (typesafe/jev-router) decide o modelo e o esforço; qualquer falha cai para o standard."""
import copy
import json
import urllib.error
from pathlib import Path

import pytest

from jev import router

FIX = Path(__file__).parent / "fixtures"


def _fixture(name):
    return json.loads((FIX / f"{name}.json").read_text())


def answering(data):
    """Fronteira externa falsa: o JSON real que o OpenRouter devolveu (fixture)."""
    def post(body, headers):
        return copy.deepcopy(data)
    return post


def jev_reply(name, **top_choice):
    """A resposta real `name`, com a escolha de topo do Jev opcionalmente alterada."""
    data = _fixture(name)
    if top_choice:
        jev = next(p for p in data["openrouter_metadata"]["pipeline"] if p["name"] == "jev-router")
        jev["data"]["selection_probabilities"][0].update(top_choice)
    return answering(data)


def failing(exc):
    def post(body, headers):
        raise exc
    return post


def test_simple_question_takes_jevs_top_choice():
    d = router.decide("explica em duas frases o que é uma closure", post=jev_reply("jev_decision_simple"))

    assert (d.runner, d.model, d.effort, d.is_standard, d.router_error) == ("anthropic", "sonnet", "high", False, None)
    assert d.router_cost_usd == pytest.approx(5.4e-05)
    assert "qa_knowledge" in d.rationale


def test_hard_task_runs_the_model_jev_decided_not_the_executor_it_paired():
    # A decisão real foi Opus·medium (probabilidade 1), servida como par Sonnet·low + Opus conselheiro.
    # O claude -p não faz pares, por isso corre o modelo decidido.
    d = router.decide("x", post=jev_reply("jev_decision_hard"))

    assert (d.model, d.effort) == ("opus", "medium")
    assert d.router_cost_usd == pytest.approx(0.0018305)


def test_jev_is_only_asked_to_decide_within_the_allowed_models():
    seen = {}

    def spy(body, headers):
        seen.update(body=body, headers=headers)
        return jev_reply("jev_decision_simple")(body, headers)

    router.decide("renomeia a função foo", post=spy)

    body = seen["body"]
    assert body["model"] == "typesafe/jev-router"
    assert body["max_tokens"] == 1  # o Jev executa sempre; só a decisão é paga lá, o resto corre pela subscrição
    plugin = body["plugins"][0]
    assert plugin["id"] == "jev-router"
    # o pool do Jev: Anthropic + os baratos que fazem de "free" (os free não estão no pool do Jev)
    assert set(plugin["allowed_models"]) == {
        "anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-5.5",
        "anthropic/claude-opus-5.5", "anthropic/claude-fable-5.1",
        "openai/gpt-6-luna*", "google/gemini-*flash*", "deepseek/*flash*",
    }
    assert seen["headers"]["X-OpenRouter-Metadata"] == "enabled"
    assert "renomeia a função foo" in body["messages"][-1]["content"]


def test_a_top_choice_outside_the_allowed_list_falls_back_to_standard():
    d = router.decide("x", post=jev_reply("jev_decision_simple", model="openai/gpt-6.1-sol-20260929"))

    assert d.is_standard and d.router_error


def test_jev_saying_cheap_on_a_text_task_runs_it_on_a_free_model():
    # Resposta real (só com `candidates`): qa_knowledge -> google/gemini-3.8-flash. Barato = free.
    d = router.decide("explica em duas frases o que é uma closure", post=jev_reply("jev_cheap_text"))

    assert (d.runner, d.model, d.is_standard) == ("openrouter-free", "nvidia/nemotron-3-ultra-550b-a55b:free", False)


def test_jev_saying_cheap_on_a_file_task_runs_it_on_sonnet():
    # Resposta real: code:file_read_write -> gpt-6-luna·low. Um free não tem ferramentas para mexer em
    # ficheiros. No piloto, o Haiku nesse papel falhou 2 de 3 tarefas: vai para o Sonnet, com o esforço do Jev.
    d = router.decide("corrige o typo 'recieve' no README.md", post=jev_reply("jev_cheap_file_task"))

    assert (d.runner, d.model, d.effort) == ("anthropic", "sonnet", "low")
    assert d.router_cost_usd == pytest.approx(9.7e-06)


def test_jev_choosing_anthropic_from_its_candidates_list():
    # Resposta real sem `selection_probabilities` (um só candidato): a decisão vem em `candidates`.
    d = router.decide("x", post=jev_reply("jev_anthropic_hard"))

    assert (d.runner, d.model, d.effort, d.is_standard) == ("anthropic", "opus", "medium", False)


@pytest.mark.parametrize("jev_effort, want", [("minimal", "low"), ("low", "low"), ("xhigh", "xhigh"), ("max", "max")])
def test_jev_effort_maps_onto_claude_code_levels(jev_effort, want):
    assert router.decide("x", post=jev_reply("jev_decision_simple", effort=jev_effort)).effort == want


def test_an_unknown_effort_falls_back_to_standard():
    assert router.decide("x", post=jev_reply("jev_decision_simple", effort="turbo")).is_standard


@pytest.mark.parametrize("exc", [
    urllib.error.HTTPError("https://openrouter.ai", 429, "Too Many Requests", None, None),
    urllib.error.HTTPError("https://openrouter.ai", 404, "No model left", None, None),
    TimeoutError("o Jev não respondeu a tempo"),
])
def test_jev_failures_fall_back_to_standard(exc):
    d = router.decide("x", post=failing(exc))

    assert d.is_standard
    assert (d.runner, d.model, d.effort) == ("anthropic", "opus", "xhigh")
    assert type(exc).__name__ in d.router_error


def test_a_reply_without_jevs_decision_falls_back_to_standard():
    d = router.decide("x", post=answering({"model": "openai/gpt-6-luna", "usage": {"cost": 1e-06},
                                            "choices": [{"message": {"content": "ok"}}]}))

    assert d.is_standard and d.router_error


def test_standard_follows_the_env_overrides(monkeypatch):
    monkeypatch.setenv("JEV_STANDARD_MODEL", "sonnet")
    monkeypatch.setenv("JEV_STANDARD_EFFORT", "high")

    d = router.decide("x", post=failing(RuntimeError("rede")))

    assert (d.model, d.effort) == ("sonnet", "high")


def test_decision_serialises_for_the_ledger():
    rec = router.decide("x", post=jev_reply("jev_decision_simple")).to_ledger()

    assert rec["router_model"] == "typesafe/jev-router" and rec["router_cost_usd"] > 0
    assert json.loads(json.dumps(rec)) == rec


def test_the_anthropic_only_pool_leaves_out_the_cheap_free_stand_ins(monkeypatch):
    monkeypatch.setenv("JEV_POOL", "anthropic")
    seen = {}

    def spy(body, headers):
        seen.update(body=body)
        return jev_reply("jev_decision_simple")(body, headers)

    router.decide("x", post=spy)

    assert set(seen["body"]["plugins"][0]["allowed_models"]) == {
        "anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-5.5",
        "anthropic/claude-opus-5.5", "anthropic/claude-fable-5.1",
    }


def test_in_the_anthropic_only_pool_a_cheap_answer_is_not_turned_into_a_free_run(monkeypatch):
    # Se o Jev ignorar a lista e servir um barato, isso é um modelo fora do pool: standard.
    monkeypatch.setenv("JEV_POOL", "anthropic")

    d = router.decide("x", post=jev_reply("jev_cheap_text"))

    assert d.is_standard and d.router_error


# --- a troca anterior: sem ela, "sim, avança" parece conversa e ia para um free (sonda real, 2026-10-11)

LAST_EXCHANGE = [{"role": "user", "content": "acrescenta fatura/io.py com de_json"},
                 {"role": "assistant", "content": "Proponho validar os campos e a região. Avanço?"}]


def _spying():
    sent = {}

    def spy(body, headers):
        sent.update(body)
        return jev_reply("jev_decision_simple")(body, headers)
    return sent, spy


def test_the_jev_reads_the_last_exchange_before_the_prompt():
    sent, spy = _spying()

    router.decide("sim, avança", history=LAST_EXCHANGE, post=spy)

    assert sent["messages"] == [*LAST_EXCHANGE, {"role": "user", "content": "sim, avança"}]


def test_a_long_exchange_reaches_the_jev_by_the_start_of_the_prompt_and_the_end_of_the_answer():
    sent, spy = _spying()
    prompt = "PEDIDO " + "x" * router.HISTORY_CHARS * 2
    answer = "y" * router.HISTORY_CHARS * 2 + " Avanço?"

    router.decide("sim", history=[{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}],
                  post=spy)

    user, assistant, _ = sent["messages"]
    assert len(user["content"]) == router.HISTORY_CHARS and user["content"].startswith("PEDIDO")
    assert len(assistant["content"]) == router.HISTORY_CHARS and assistant["content"].endswith("Avanço?")


def test_an_empty_answer_or_another_role_never_reaches_the_jev():
    sent, spy = _spying()

    router.decide("continua", history=[{"role": "user", "content": "x"}, {"role": "assistant", "content": "  "},
                                       {"role": "system", "content": "outra coisa"}], post=spy)

    assert sent["messages"] == [{"role": "user", "content": "x"}, {"role": "user", "content": "continua"}]


# --- o pool por defeito depende da versão: a v2 fica só com Anthropic (os free falharam no código) -----

def _pool_sent(monkeypatch, *, policy_env, pool_env):
    for var, value in (("JEV_POLICY", policy_env), ("JEV_POOL", pool_env)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)
    sent, spy = _spying()
    router.decide("x", post=spy)
    return set(sent["plugins"][0]["allowed_models"])


def test_the_v2_pool_is_anthropic_only_by_default(monkeypatch):
    assert _pool_sent(monkeypatch, policy_env="v2", pool_env=None) == set(router.ANTHROPIC_MODELS)


def test_the_v1_pool_keeps_the_cheap_stand_ins_by_default(monkeypatch):
    assert _pool_sent(monkeypatch, policy_env=None, pool_env=None) == set(router.JEV_POOL)


def test_jev_pool_all_brings_the_cheap_stand_ins_back_in_v2(monkeypatch):
    assert _pool_sent(monkeypatch, policy_env="v2", pool_env="all") == set(router.JEV_POOL)
