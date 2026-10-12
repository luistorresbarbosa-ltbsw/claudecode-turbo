"""Política de modelo da sessão (`JEV_POLICY`): na v1, cada prompt corre no modelo que o Jev escolhe;
na v2, o modelo é da sessão; na v3 (por defeito), há uma faixa por tarefa (ver `_apply_v3`); a v4 é a v3,
com os seguimentos óbvios a correr na faixa sem perguntar ao Jev (ver `follow_up_without_jev`).

A cache do Claude é de cada modelo. Trocar de modelo a meio de uma sessão obriga a escrever a conversa
toda na cache do novo modelo (a 2× o preço de entrada), em vez de a ler (a 10%): numa sonda real
(2026-10-11, sessão retomada com `--resume`), Sonnet → Opus escreveu 14,6k tokens. Mudar o esforço
invalida a cache das mensagens (a do system e das ferramentas fica), segundo a documentação da API.
Por isso, na v2, com a cache quente:
- o modelo e o esforço mantêm-se e só sobem: um modelo maior, ou mais esforço no mesmo modelo, porque
  aí a qualidade paga a reescrita;
- com a cache fria (sessão nova, `/clear`, compactação, ou mais de uma hora parada), vale o Jev.
O standard (quando o Jev falha) e as respostas free passam como estão.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import time
from pathlib import Path

from jev import ledger

POLICIES = ("v1", "v2", "v3", "v4")
MODEL_RANK = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}

# v3: números medidos nos pilotos de 2026-10-11 (sessões contínuas, transcripts) e na sonda G2
CACHE_FIXED_TOKENS = 12_600  # o system prompt e as ferramentas: lidos da cache mesmo depois de uma troca
REWRITE_USD = {"haiku": 1.9e-6, "sonnet": 3.8e-6, "opus": 7.8e-6, "fable": 19.75e-6}  # escrita 1h − leitura, por token
OUTPUT_USD = {"haiku": 5e-6, "sonnet": 10e-6, "opus": 20e-6, "fable": 50e-6}
WRITE_USD = {"haiku": 2e-6, "sonnet": 4e-6, "opus": 8e-6, "fable": 20e-6}
SECONDS_PER_TOKEN = {"sonnet": 5.6e-3, "opus": 8.2e-3}  # saída medida; os outros sem medição
# Numa tarefa nova, até aqui segue-se o Jev (descer custa ≤ $0.11, subir ≤ $0.21): o simulador, sobre as sessões
# reais de 2026-10-11, deu 40k como o melhor custo + tempo (25k ficava igual à v2; 50k ou mais, pior)
FREE_SWITCH_CONTEXT = 40_000
QUALITY_USD = 1.5  # quanto vale, numa tarefa, a qualidade de um modelo maior (× big_model_gain)
TIME_USD_PER_S = 0.01  # o utilizador escolheu "equilibrado": 1 minuto vale ~$0.60
# Sondas G2 com sessões novas no Jev: seguimentos até 0,23, tarefas novas desde 0,24 (64 prompts rotulados)
TASK_CHANGED_NEW = 0.2
FOLLOW_UP_MAX_WORDS = 12
REGRET_K = 1.5
_FOLLOW_UP = re.compile(r"^(sim|não|nao|ok|continua|avança|agora|também|e |mas |corre|corrige|testa|repete|faz o mesmo|"
                        r"explica melhor|isso|yes|go|continue|now|also|run|fix|retry)\b", re.IGNORECASE)
_NEW_TASK = re.compile(r"^(acrescenta|adiciona|cria|escreve|implementa|explica|refatora|bug:|add|create|write|"
                       r"implement|explain|refactor)\b", re.IGNORECASE)
CACHE_TTL_S = 3600  # o Claude Code escreve a cache com a duração de 1 h
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def current() -> str:
    value = os.environ.get("JEV_POLICY", "").strip().lower()
    # a v3 é a defeito desde 2026-10-13: nas mesmas condições (perfis médios das corridas finais), custo + tempo
    # 27,19 contra 29,05 da v1 e 28,90 da v2, a 1,2% da melhor sequência que não contraria o Opus do Jev
    return value if value in POLICIES else "v3"


def apply(decision, state: dict | None, policy: str, *, now: float | None = None, prompt: str = "",
          context: int | None = None, regret_rule: bool = False):
    """A decisão a usar neste prompt, dada a sessão (`state`: o modelo que correu no prompt anterior)."""
    if policy in ("v3", "v4"):
        return _apply_v3(decision, state, now=now, prompt=prompt, context=context, regret_rule=regret_rule)
    if policy != "v2" or decision.is_standard or decision.runner != "anthropic" or not _warm(state, now):
        return decision
    held, held_effort = state.get("model"), state.get("effort")
    if held not in MODEL_RANK or decision.model not in MODEL_RANK:
        return decision
    if MODEL_RANK[decision.model] > MODEL_RANK[held]:
        return decision  # um modelo maior: a cache reescreve-se de qualquer maneira, vale a escolha toda do Jev
    if (MODEL_RANK[decision.model] == MODEL_RANK[held]
            and EFFORT_RANK.get(decision.effort, -1) >= EFFORT_RANK.get(held_effort, -1)):
        return decision  # o mesmo modelo, com o mesmo esforço ou mais
    return dataclasses.replace(decision, model=held, effort=held_effort,
                               rationale=f"{decision.rationale} · v2: mantém {held} · {held_effort} (cache)")


def _apply_v3(decision, state, *, now, prompt, context, regret_rule):
    """Uma faixa por tarefa. Mudar o esforço é grátis (medido); trocar de modelo reescreve a cache, por isso:
    R2 cache fria → o Jev; R3 a mesma tarefa → mantém o modelo; numa tarefa nova, R4 com pouco contexto → o
    Jev, R5 subir só se o ganho pagar a reescrita (ou se o Jev já não admitir o modelo atual), R6 descer só
    quando o arrependimento acumulado pagar a descida e uma volta provável. O standard e o free passam."""
    if decision.is_standard or decision.runner != "anthropic" or not _warm(state, now):
        return decision
    held = state.get("model")
    if held not in MODEL_RANK or decision.model not in MODEL_RANK or decision.model == held:
        return decision  # o mesmo modelo: o esforço segue o Jev (R1)
    signals = decision.signals or {}
    admitted = signals.get("admitted") or {}
    held_admitted = not admitted or held in admitted
    up = MODEL_RANK[decision.model] > MODEL_RANK[held]
    if not is_new_task(signals, prompt):  # R3
        if up and not held_admitted and int(state.get("followups") or 0) >= 1:
            return decision
        return _hold(decision, held, _effort_for(held, decision.effort, admitted), "mesma tarefa")
    ctx = context if context is not None else int(state.get("context") or 0)
    if ctx <= FREE_SWITCH_CONTEXT:  # R4
        return decision
    if up:  # R5
        if not held_admitted or (signals.get("gain") or 0.0) * QUALITY_USD >= rewrite_usd(decision.model, ctx):
            return decision
        effort = max(_effort_for(held, decision.effort, admitted), "high", key=lambda e: EFFORT_RANK.get(e, -1))
        return _hold(decision, held, effort, "subir não compensa")
    if regret_rule and float(state.get("regret") or 0.0) >= _down_threshold(decision.model, held, ctx, state):  # R6
        return decision
    return _hold(decision, held, _effort_for(held, decision.effort, admitted), "descer não compensa")


def is_new_task(signals: dict, prompt: str) -> bool:
    """O prompt começa uma tarefa nova? O `task_changed` do Jev quando há; senão uma heurística, que na dúvida
    diz "mesma tarefa" (o mais seguro para a cache)."""
    if is_lexical_follow_up(prompt):
        return False  # "corre os testes…", "sim, avança": o Jev chegou a dar 0,23 a isto depois de uma resposta longa
    changed = (signals or {}).get("task_changed")
    if changed is not None:
        return changed >= TASK_CHANGED_NEW
    text = (prompt or "").strip()
    return len(text.split()) >= 25 and bool(_NEW_TASK.match(text))


def is_lexical_follow_up(prompt: str) -> bool:
    """Um prompt curto que começa como seguimento ("corre os testes…", "sim, avança", "explica melhor")."""
    text = (prompt or "").strip()
    return bool(_FOLLOW_UP.match(text)) and len(text.split()) <= FOLLOW_UP_MAX_WORDS


def follow_up_without_jev(state: dict | None, prompt: str, policy: str, *, now: float | None = None):
    """Na v4, um seguimento óbvio corre na faixa sem perguntar ao Jev: a v3 manteria o modelo de qualquer maneira,
    e assim poupa-se a decisão (1 a 4 s e o custo dela). Só com a cache quente e se a troca anterior correu num
    modelo Anthropic (depois de uma resposta free, pergunta-se ao Jev). Sem isso, devolve None."""
    if (policy != "v4" or not _warm(state, now) or state.get("last_runner") != "anthropic"
            or state.get("model") not in MODEL_RANK or not is_lexical_follow_up(prompt)):
        return None
    from jev.router import Decision  # o router importa este módulo

    return Decision(runner="anthropic", model=state["model"], effort=state.get("effort"),
                    rationale=f"v4: seguimento, sem decisão do Jev ({state['model']} · {state.get('effort')})",
                    router_model="v4: seguimento", signals={"rule": "seguimento", "jev": "saltado"})


def rewrite_usd(model: str, context: int) -> float:
    """Quanto custa trocar para `model` com `context` tokens: reescrever tudo menos o system e as ferramentas."""
    return max(0, context - CACHE_FIXED_TOKENS) * REWRITE_USD.get(model, REWRITE_USD["opus"])


def _down_threshold(smaller: str, held: str, context: int, state: dict) -> float:
    n_new, n_new_big = int(state.get("n_new") or 0), int(state.get("n_new_opus") or 0)
    p_return = (n_new_big + 1) / (n_new + 2)  # quantas tarefas novas pediram o modelo maior
    return REGRET_K * rewrite_usd(smaller, context) + p_return * rewrite_usd(held, context)


def _effort_for(model: str, effort: str | None, admitted: dict) -> str | None:
    """O esforço do Jev, se ele o admite para `model`; senão o mais baixo admitido acima dele."""
    allowed = admitted.get(model) or []
    if not allowed or effort in allowed:
        return effort
    above = [e for e in allowed if EFFORT_RANK.get(e, -1) >= EFFORT_RANK.get(effort, -1)]
    return min(above or allowed, key=lambda e: EFFORT_RANK.get(e, 99))


def _hold(decision, model: str, effort: str | None, why: str):
    return dataclasses.replace(
        decision, model=model, effort=effort,
        rationale=f"{decision.rationale} · v3: mantém {model} · {effort} ({why})",
        signals={**(decision.signals or {}), "held_from": decision.model, "rule": why})


def next_state(decision, state: dict | None, *, now: float | None = None, new_task: bool | None = None) -> dict | None:
    """O estado da sessão depois deste prompt: o modelo que correu (uma resposta free não o muda) e, para a v3,
    os seguimentos da tarefa, as tarefas novas e o arrependimento."""
    if decision.runner != "anthropic":
        return state
    prev = state or {}
    new = True if new_task is None else new_task
    switched = prev.get("model") not in (None, decision.model)
    held_from = (decision.signals or {}).get("held_from")
    wanted = held_from or decision.model  # o que o Jev pediu (se mantive outro modelo, é o held_from)
    held_bigger = held_from is not None and MODEL_RANK.get(held_from, 9) < MODEL_RANK.get(decision.model, 0)
    return {
        **{k: prev[k] for k in ("context", "last_prompt", "last_answer") if k in prev},
        "model": decision.model, "effort": decision.effort, "updated": time.time() if now is None else now,
        "followups": 0 if new else int(prev.get("followups") or 0) + 1,
        "n_new": int(prev.get("n_new") or 0) + int(new),
        "n_new_opus": int(prev.get("n_new_opus") or 0) + int(new and MODEL_RANK.get(wanted, 0) >= MODEL_RANK["opus"]),
        # o arrependimento conta enquanto mantenho um modelo maior do que o Jev pede; volta a zero ao trocar
        "regret": float(prev.get("regret") or 0.0) if held_bigger and not switched else 0.0,
        "held_from": held_from if held_bigger else None,
    }


def add_regret(state: dict, *, output_tokens: int, write_tokens: int) -> dict:
    """Depois de um turno num modelo maior do que o Jev pedia: soma o que isso custou (saída, escrita e tempo)."""
    held, preferred = state.get("model"), state.get("held_from")
    if not preferred or held not in OUTPUT_USD or preferred not in OUTPUT_USD:
        return state
    extra = (output_tokens * (OUTPUT_USD[held] - OUTPUT_USD[preferred])
             + write_tokens * (WRITE_USD[held] - WRITE_USD[preferred])
             + TIME_USD_PER_S * output_tokens * (SECONDS_PER_TOKEN.get(held, 0) - SECONDS_PER_TOKEN.get(preferred, 0)))
    return {**state, "regret": float(state.get("regret") or 0.0) + max(0.0, extra)}


def _warm(state: dict | None, now: float | None) -> bool:
    if not state:
        return False
    now = time.time() if now is None else now
    return now - float(state.get("updated") or 0) <= CACHE_TTL_S


def _state_path(session: str, home) -> Path | None:
    if not isinstance(session, str) or not _SESSION_ID.fullmatch(session):
        return None  # nunca um caminho a partir de um id estranho
    return ledger.ledger_path(home).parent / "sessions" / f"{session}.json"


def load_state(session: str, home=None) -> dict | None:
    path = _state_path(session, home)
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(session: str, state: dict | None, home=None) -> None:
    path = _state_path(session, home)
    if path is None or state is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
