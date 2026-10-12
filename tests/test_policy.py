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
    state = policy.next_state(dec("opus", effort="low"), None, now=NOW)
    assert {k: state[k] for k in ("model", "effort", "updated")} == {"model": "opus", "effort": "low", "updated": NOW}
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


# --- v3: uma faixa por tarefa ----------------------------------------------------------------------------

ADMITS_BOTH = {"sonnet": ["low", "medium", "high"], "opus": ["medium", "high"]}


def dec3(model, effort="medium", *, tc=0.1, gain=0.3, admitted=None):
    signals = {"task_changed": tc, "gain": gain, "admitted": ADMITS_BOTH if admitted is None else admitted}
    return Decision(runner="anthropic", model=model, effort=effort, rationale="Jev: x", signals=signals)


def lane(model, effort="high", *, context=60_000, followups=0, age_s=60, **extra):
    return {"model": model, "effort": effort, "updated": NOW - age_s, "context": context, "followups": followups, **extra}


def v3(decision, state, **kw):
    return policy.apply(decision, state, "v3", now=NOW, **kw)


def test_v3_effort_follows_the_jev_even_downwards():
    # Medido nos pilotos: mudar o esforço nunca reescreveu a cache (7 casos)
    d = dec3("opus", effort="low", admitted={"opus": ["low", "medium", "high"]})

    assert v3(d, lane("opus", "high")) is d


def test_v3_follows_the_jev_when_the_cache_is_cold():
    d = dec3("sonnet", tc=0.1)

    assert v3(d, None) is d
    assert v3(d, lane("opus", age_s=policy.CACHE_TTL_S + 1)) is d


def test_v3_a_follow_up_keeps_the_model_both_ways():
    up = v3(dec3("opus", "high", tc=0.1), lane("sonnet", "medium"))
    down = v3(dec3("sonnet", "low", tc=0.1), lane("opus", "high"))

    assert (up.model, up.effort) == ("sonnet", "high")  # o esforço segue o Jev; o modelo é o da tarefa
    # o Jev não admite o Opus em low (ADMITS_BOTH): fica o mais baixo que admite (R1)
    assert (down.model, down.effort) == ("opus", "medium") and "mesma tarefa" in down.rationale


def test_v3_a_follow_up_keeps_the_model_even_with_a_small_context():
    assert v3(dec3("opus", tc=0.1), lane("sonnet", context=20_000)).model == "sonnet"


def test_v3_the_second_follow_up_moves_up_when_the_jev_no_longer_admits_the_model():
    only_opus = dec3("opus", "high", tc=0.1, admitted={"opus": ["medium", "high"]})

    assert v3(only_opus, lane("sonnet", followups=0)).model == "sonnet"  # 1.º seguimento: ainda mantém
    assert v3(only_opus, lane("sonnet", followups=1)).model == "opus"


def test_v3_a_new_task_with_a_small_context_follows_the_jev():
    d = dec3("sonnet", tc=0.4)

    assert v3(d, lane("opus", context=20_000)) is d


def test_v3_a_new_task_moves_up_when_the_gain_pays_the_rewrite():
    # U(C) = (C − 12,6k) × $7,8/M; com ganho 0,26 × $1,5, sobe até ~62,6k de contexto
    assert v3(dec3("opus", tc=0.4, gain=0.26), lane("sonnet", context=62_000)).model == "opus"
    held = v3(dec3("opus", "medium", tc=0.4, gain=0.26), lane("sonnet", "low", context=64_000))
    assert (held.model, held.effort) == ("sonnet", "high")  # não sobe, mas com esforço pelo menos high


def test_v3_a_new_task_moves_up_when_the_jev_does_not_admit_the_current_model():
    d = dec3("opus", tc=0.4, gain=0.1, admitted={"opus": ["medium", "high"]})

    assert v3(d, lane("sonnet", context=150_000)) is d


def test_v3_a_new_task_does_not_move_down_on_a_large_warm_cache():
    d = v3(dec3("sonnet", "medium", tc=0.4), lane("opus", "high", context=60_000))

    assert (d.model, d.effort) == ("opus", "medium") and "descer não compensa" in d.rationale


def test_v3_moves_down_once_the_regret_pays_the_rewrite_and_a_likely_return():
    # 1,5·D(60k) + p·U(60k), com p = (1 + 1)/(4 + 2): ≈ $0.39
    state = lane("opus", context=60_000, regret=1.0, n_new=4, n_new_opus=1)
    d = dec3("sonnet", tc=0.4)

    assert v3(d, state, regret_rule=True) is d
    assert v3(d, state).model == "opus"  # sem a regra do arrependimento, mantém
    assert v3(d, {**state, "regret": 0.2}, regret_rule=True).model == "opus"


@pytest.mark.parametrize(("tc", "new"), [(0.24, True), (0.6, True), (0.19, False), (0.07, False)])
def test_a_new_task_is_what_the_jevs_task_changed_says(tc, new):
    # Sondas G2 com sessões novas: seguimentos até 0,23, tarefas novas desde 0,24
    assert policy.is_new_task({"task_changed": tc}, "Os testes de IVA da Madeira falham. Descobre porquê.") is new


@pytest.mark.parametrize("prompt", ["Corre os testes e corrige o que falhar.", "sim, avança", "Isso não cobre a linha 2."])
def test_a_short_continuation_is_a_follow_up_whatever_task_changed_says(prompt):
    # depois de uma resposta longa, o Jev chegou a dar 0,23 a um "Corre os testes…"
    assert policy.is_new_task({"task_changed": 0.23}, prompt) is False


@pytest.mark.parametrize(("prompt", "new"), [
    ("Corre os testes e corrige o que falhar.", False),
    ("sim, avança", False),
    ("Explica melhor isso.", False),
    ("Acrescenta fatura/clientes.py com uma função que agrupa as faturas pelo NIF do cliente, soma os totais com IVA e "
     "devolve uma lista ordenada. Escreve testes.", True),
])
def test_without_the_jevs_signal_a_heuristic_decides(prompt, new):
    assert policy.is_new_task({}, prompt) is new


def test_v3_state_counts_follow_ups_and_new_tasks():
    s1 = policy.next_state(dec3("opus", tc=0.4), None, now=NOW, new_task=True)
    s2 = policy.next_state(dec3("opus", tc=0.1), s1, now=NOW, new_task=False)
    s3 = policy.next_state(dec3("sonnet", tc=0.4), s2, now=NOW, new_task=True)

    assert (s2["followups"], s2["n_new"], s2["n_new_opus"]) == (1, 1, 1)
    assert (s3["followups"], s3["n_new"], s3["n_new_opus"]) == (0, 2, 1)


def test_the_regret_grows_with_what_holding_the_bigger_model_cost():
    state = policy.add_regret(lane("opus", regret=0.0, held_from="sonnet"), output_tokens=10_000, write_tokens=5_000)

    # 10k × ($20 − $10)/M + 5k × ($8 − $4)/M + $0,01/s × 10k × (8,2 − 5,6) ms
    assert state["regret"] == pytest.approx(0.10 + 0.02 + 0.26)
    assert policy.add_regret(lane("opus", regret=0.3), output_tokens=10_000, write_tokens=0)["regret"] == 0.3


def test_holding_opus_against_the_jevs_sonnet_is_not_a_task_that_wanted_opus():
    # o "p" da volta provável conta as tarefas novas em que o Jev pediu o modelo maior, não as que eu segurei
    held = policy.apply(dec3("sonnet", tc=0.4), lane("opus", context=60_000), "v3", now=NOW)
    state = policy.next_state(held, lane("opus", context=60_000, n_new=1, n_new_opus=1), now=NOW, new_task=True)

    assert state["held_from"] == "sonnet" and (state["n_new"], state["n_new_opus"]) == (2, 1)
