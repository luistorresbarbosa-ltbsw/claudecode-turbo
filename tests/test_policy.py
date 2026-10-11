"""Política de modelo da sessão: na v2, o modelo é da sessão; na v1, de cada prompt."""
import pytest

from jev import policy
from jev.router import Decision, standard

NOW = 1_000_000.0


def dec(model, effort="medium", runner="anthropic"):
    return Decision(runner=runner, model=model, effort=effort, rationale="Jev: x")


def warm(model, effort="high", *, age_s=60):
    return {"model": model, "effort": effort, "updated": NOW - age_s}


def test_v1_always_follows_the_jev():
    d = dec("sonnet")

    assert policy.apply(d, warm("opus"), "v1", now=NOW) is d


def test_v2_keeps_the_sessions_model_and_effort_when_the_jev_asks_for_a_smaller_model():
    # Sonda real (2026-10-11): trocar de modelo a meio da sessão escreveu 14,6k tokens na cache
    d = policy.apply(dec("sonnet", effort="low"), warm("opus", "high"), "v2", now=NOW)

    assert (d.model, d.effort) == ("opus", "high")
    assert "v2: mantém opus · high" in d.rationale


def test_v2_keeps_the_effort_when_the_jev_asks_for_less_on_the_same_model():
    # A documentação da API: mudar o esforço invalida a cache das mensagens (a do system e das ferramentas fica)
    d = policy.apply(dec("sonnet", effort="low"), warm("sonnet", "high"), "v2", now=NOW)

    assert (d.model, d.effort) == ("sonnet", "high")


def test_v2_raises_the_effort_when_the_jev_asks_for_more_on_the_same_model():
    d = dec("sonnet", effort="high")

    assert policy.apply(d, warm("sonnet", "medium"), "v2", now=NOW) is d  # mais esforço: a qualidade paga a cache


def test_v2_moves_up_when_the_jev_asks_for_a_bigger_model():
    d = dec("opus", effort="high")

    assert policy.apply(d, warm("sonnet"), "v2", now=NOW) is d


def test_v2_follows_the_jev_when_the_cache_is_cold():
    d = dec("sonnet")

    assert policy.apply(d, None, "v2", now=NOW) is d  # sessão nova, /clear ou compactação
    assert policy.apply(d, warm("opus", age_s=policy.CACHE_TTL_S + 1), "v2", now=NOW) is d  # a cache expirou


def test_v2_leaves_the_standard_fallback_and_free_answers_alone():
    fallback = standard("TimeoutError")
    free = dec("nvidia/nemotron-3-ultra-550b-a55b:free", runner="openrouter-free")

    assert policy.apply(fallback, warm("sonnet"), "v2", now=NOW) is fallback  # regra: falhou, standard
    assert policy.apply(free, warm("opus"), "v2", now=NOW) is free  # um free não usa a cache da sessão


def test_the_state_after_a_turn_is_the_model_that_ran():
    assert policy.next_state(dec("opus", effort="low"), None, now=NOW) == {"model": "opus", "effort": "low",
                                                                             "updated": NOW}
    free = dec("nvidia/nemotron-3-ultra-550b-a55b:free", runner="openrouter-free")
    assert policy.next_state(free, warm("sonnet"), now=NOW) == warm("sonnet")  # a sessão não correu


@pytest.mark.parametrize(("env", "want"), [(None, "v1"), ("v2", "v2"), (" V2 ", "v2"), ("v9", "v1")])
def test_the_policy_comes_from_jev_policy(monkeypatch, env, want):
    if env is None:
        monkeypatch.delenv("JEV_POLICY", raising=False)
    else:
        monkeypatch.setenv("JEV_POLICY", env)

    assert policy.current() == want


def test_the_session_state_survives_between_processes(tmp_path):
    policy.save_state("00b3744d-acd8-47ed-b677-b8d10b3b6c80", warm("opus"), home=tmp_path)

    assert policy.load_state("00b3744d-acd8-47ed-b677-b8d10b3b6c80", home=tmp_path) == warm("opus")
    assert policy.load_state("outra-sessao", home=tmp_path) is None


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a/b", "", "x" * 200])
def test_a_strange_session_id_never_touches_the_disk(tmp_path, bad):
    policy.save_state(bad, warm("opus"), home=tmp_path)

    assert policy.load_state(bad, home=tmp_path) is None
    assert not any(tmp_path.rglob("*.json"))
