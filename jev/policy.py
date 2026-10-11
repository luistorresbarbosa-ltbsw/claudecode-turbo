"""Política de modelo da sessão (`JEV_POLICY`): na v1, cada prompt corre no modelo que o Jev escolhe;
na v2, o modelo é da sessão.

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

POLICIES = ("v1", "v2")
MODEL_RANK = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}
CACHE_TTL_S = 3600  # o Claude Code escreve a cache com a duração de 1 h
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def current() -> str:
    value = os.environ.get("JEV_POLICY", "").strip().lower()
    return value if value in POLICIES else "v1"


def apply(decision, state: dict | None, policy: str, *, now: float | None = None):
    """A decisão a usar neste prompt, dada a sessão (`state`: o modelo que correu no prompt anterior)."""
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


def next_state(decision, state: dict | None, *, now: float | None = None) -> dict | None:
    """O estado da sessão depois deste prompt: o modelo que correu (uma resposta free não o muda)."""
    if decision.runner != "anthropic":
        return state
    return {"model": decision.model, "effort": decision.effort, "updated": time.time() if now is None else now}


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
