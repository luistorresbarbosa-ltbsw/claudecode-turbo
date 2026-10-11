"""Router: decide com um modelo free; qualquer falha cai para o standard Anthropic."""
import functools
import json

import litellm
import pytest

from jev import router

NEMOTRON_ULTRA = "nvidia/nemotron-3-ultra-550b-a55b:free"


def answering(payload):
    """Fronteira externa falsa: um litellm.completion real que devolve `payload` sem rede."""
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return functools.partial(litellm.completion, mock_response=content)


def failing(exc):
    def complete(**kwargs):
        raise exc
    return complete


def test_free_runner_decision_is_taken_as_is():
    d = router.decide("o que é um monad?", complete=answering(
        {"runner": "openrouter-free", "model": NEMOTRON_ULTRA, "effort": None,
         "rationale": "pergunta conceptual, não toca no repo", "est_output_tokens": 400}))

    assert (d.runner, d.model, d.effort, d.is_standard, d.router_error) == (
        "openrouter-free", NEMOTRON_ULTRA, None, False, None)
    assert d.est_output_tokens == 400


def test_anthropic_decision_keeps_model_and_effort():
    d = router.decide("corrige o typo no README", complete=answering(
        {"runner": "anthropic", "model": "haiku", "effort": "low",
         "rationale": "edição trivial", "est_output_tokens": 120}))

    assert (d.runner, d.model, d.effort, d.is_standard) == ("anthropic", "haiku", "low", False)


def test_router_calls_the_free_model_with_the_task_and_a_json_schema():
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return answering({"runner": "anthropic", "model": "haiku", "effort": "low",
                          "rationale": "r", "est_output_tokens": 1})(**kwargs)

    router.decide("renomeia a função foo", complete=spy)

    assert seen["model"] == "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
    assert seen["model"].endswith(":free")
    assert "renomeia a função foo" in seen["messages"][-1]["content"]
    assert seen["response_format"]["type"] == "json_schema"


def test_rate_limit_on_the_free_model_falls_back_to_standard():
    exc = litellm.RateLimitError(message="429", llm_provider="openrouter", model="nemotron")

    d = router.decide("qualquer coisa", complete=failing(exc))

    assert d.is_standard
    assert (d.runner, d.model, d.effort) == ("anthropic", "opus", "xhigh")
    assert "RateLimitError" in d.router_error


def test_garbage_reply_falls_back_to_standard():
    d = router.decide("qualquer coisa", complete=answering("não sei, talvez o sonnet?"))

    assert d.is_standard
    assert d.router_error


@pytest.mark.parametrize("bad", [
    # um modelo Anthropic via OpenRouter: proibido, os Anthropic vêm da subscrição
    {"runner": "openrouter-free", "model": "haiku", "effort": None},
    {"runner": "anthropic", "model": NEMOTRON_ULTRA, "effort": "low"},
    {"runner": "anthropic", "model": "sonnet", "effort": None},
    {"runner": "anthropic", "model": "sonnet", "effort": "ultra"},
    {"runner": "openrouter-free", "model": "some/unrated-model:free", "effort": None},
    {"runner": "anthropic", "model": "gpt-5", "effort": "low"},
])
def test_inconsistent_decisions_fall_back_to_standard(bad):
    d = router.decide("x", complete=answering({**bad, "rationale": "r", "est_output_tokens": 10}))

    assert d.is_standard
    assert d.router_error


def test_standard_follows_the_env_overrides(monkeypatch):
    monkeypatch.setenv("JEV_STANDARD_MODEL", "sonnet")
    monkeypatch.setenv("JEV_STANDARD_EFFORT", "high")

    d = router.decide("x", complete=answering("lixo"))

    assert (d.model, d.effort) == ("sonnet", "high")


def test_decision_serialises_for_the_ledger():
    d = router.decide("x", complete=answering("lixo"))

    rec = d.to_ledger()

    assert rec["runner"] == "anthropic" and rec["router_error"] and rec["router_cost_usd"] == 0.0
    assert json.loads(json.dumps(rec)) == rec
