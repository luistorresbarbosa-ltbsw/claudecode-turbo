"""Router do JEV: o Jev da TypeSafe (`typesafe/jev-router`, via OpenRouter) decide o modelo e o
esforço de cada tarefa.

O Jev lê a tarefa, classifica o tipo e a dificuldade e escolhe o candidato mais barato que chega,
com o esforço de raciocínio. Lê também a troca anterior (o último pedido e a resposta): sem ela, um
seguimento como "sim, avança" parece conversa e ia para um free. Não tem modo "só decidir": executa sempre no modelo escolhido. Por isso
pedimos-lhe 1 token. A decisão (o modelo e o esforço) vem nos metadados do OpenRouter, e o custo dela
é o custo do Jev, que entra no caminho JEV.

O Jev decide entre Anthropic e free:
- escolhe um modelo Anthropic: a tarefa corre pela subscrição (`claude -p`) com o modelo e o esforço dele;
- escolhe um dos modelos baratos (o pool dele não tem modelos free; os baratos são a forma de dizer
  "isto não precisa da Anthropic"): a tarefa corre num modelo free, para poupar;
- escolhe barato numa tarefa que mexe em ficheiros: um free não tem ferramentas, por isso corre no
  Sonnet, com o esforço do Jev (no piloto de 2026-10-11, o Haiku nesse papel falhou 2 de 3 tarefas).
Com JEV_POOL=anthropic o pool do Jev fica só com os modelos Anthropic: não há respostas free.
Os modelos free nunca decidem nada: só executam.

Qualquer falha (erro, metadados em falta, um modelo fora da lista permitida, um esforço
desconhecido) cai para o standard Anthropic.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatchcase

from jev import policy

# Sem litellm aqui: importá-lo custa ~1,1 s, e a decisão está no caminho de cada prompt.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
JEV_MODEL = "typesafe/jev-router"
ROUTER_TIMEOUT_S = 15  # o Jev decide em 1-4 s; se não responder, standard já
EFFORTS = ("low", "medium", "high", "xhigh", "max")
_EFFORT_ALIASES = {"minimal": "low", "none": "low"}

# Anthropic: o que o Jev escolher aqui corre pela subscrição
ANTHROPIC_MODELS = {
    "anthropic/claude-haiku-4.5": "haiku",
    "anthropic/claude-sonnet-5.5": "sonnet",
    "anthropic/claude-opus-5.5": "opus",
    "anthropic/claude-fable-5.1": "fable",
}
# Os modelos baratos do pool do Jev: quando ele escolhe um destes, a tarefa é simples e corre num free
CHEAP_SIGNALS = ("openai/gpt-6-luna*", "google/gemini-*flash*", "deepseek/*flash*")
FREE_EXECUTOR = "nvidia/nemotron-3-ultra-550b-a55b:free"  # o free mais bem cotado (550B)
JEV_POOL = (*ANTHROPIC_MODELS, *CHEAP_SIGNALS)


def _pool() -> tuple[str, ...]:
    """O pool pedido ao Jev. JEV_POOL=anthropic deixa de fora os baratos que fazem de free, e
    JEV_POOL=all mete-os. Sem JEV_POOL, a v1 mete-os e a v2 não (nos pilotos, os free falharam no código)."""
    choice = os.environ.get("JEV_POOL", "").strip().lower() or ("anthropic" if policy.current() == "v2" else "all")
    return tuple(ANTHROPIC_MODELS) if choice == "anthropic" else JEV_POOL
# Tarefas que precisam de ferramentas (ler/editar o repo, correr comandos): um free não as consegue fazer
_TOOL_TASK_PREFIXES = ("code:", "agent:")
_TOOL_TASKS = {"devops", "security_audit"}
# Da troca anterior, cada mensagem vai aparada: o início do pedido e o fim da resposta, onde costuma
# estar a pergunta ou a proposta a que o prompt seguinte responde
HISTORY_CHARS = 2000


@dataclass(frozen=True)
class Decision:
    runner: str
    model: str
    effort: str | None
    rationale: str
    est_output_tokens: int = 0
    is_standard: bool = False
    router_model: str = JEV_MODEL
    router_cost_usd: float = 0.0
    router_error: str | None = None
    # O que o Jev disse da tarefa, para a política da sessão (v3): task_changed, difficulty, gain e,
    # por modelo, os esforços em que o Jev o admite
    signals: dict = field(default_factory=dict)

    def to_ledger(self) -> dict:
        return asdict(self)


def standard(router_error: str | None = None, router_cost_usd: float = 0.0) -> Decision:
    """O que o Claude Code usaria sem o JEV (por defeito: opus com o effortLevel xhigh das settings)."""
    return Decision(
        runner="anthropic",
        model=os.environ.get("JEV_STANDARD_MODEL", "opus"),
        effort=os.environ.get("JEV_STANDARD_EFFORT", "xhigh"),
        rationale="fallback: o Jev não decidiu dentro das regras, uso o standard" if router_error else "standard",
        is_standard=True,
        router_cost_usd=router_cost_usd,
        router_error=router_error,
    )


def _undated(slug: str) -> str:
    """'anthropic/claude-sonnet-5.5-20260928' -> 'anthropic/claude-sonnet-5.5' (mantém o ':free')."""
    return re.sub(r"-\d{8}(?=(:free)?$)", "", slug)


def _effort(value: str | None) -> str:
    effort = _EFFORT_ALIASES.get(value, value)
    if effort not in EFFORTS:
        raise ValueError(f"esforço desconhecido do Jev: {value!r}")
    return effort


def _is_cheap(slug: str) -> bool:
    return any(fnmatchcase(slug, pattern) for pattern in CHEAP_SIGNALS)


def _needs_tools(task_type: str) -> bool:
    return task_type.startswith(_TOOL_TASK_PREFIXES) or task_type in _TOOL_TASKS


def _why(data: dict) -> str:
    answers = data.get("answers") or {}
    task = (answers.get("task") or {}).get("choice", "?")
    probs = (answers.get("difficulty") or {}).get("probabilities") or {}
    difficulty = max(probs, key=probs.get) if probs else "?"
    gain = (answers.get("big_model_gain") or {}).get("noul")
    parts = [f"Jev: {task}", f"dificuldade {difficulty}/4"]
    if gain is not None:
        parts.append(f"ganho de um modelo maior {gain:.2f}")
    return " · ".join(parts)


def history_messages(history) -> list[dict]:
    """A troca anterior em mensagens para o Jev (e para o free), aparadas; vazias e outros papéis ficam de fora."""
    out = []
    for message in history or ():
        role, content = message.get("role"), (message.get("content") or "").strip()
        if role == "user" and content:
            out.append({"role": "user", "content": content[:HISTORY_CHARS]})
        elif role == "assistant" and content:
            out.append({"role": "assistant", "content": content[-HISTORY_CHARS:]})
    return out


def _signals(data: dict) -> dict:
    answers = data.get("answers") or {}

    def score(name):
        probs = (answers.get(name) or {}).get("probabilities") or {}
        return int(max(probs, key=probs.get)) if probs else None

    admitted: dict[str, list[str]] = {}
    for e in data.get("evaluations") or []:
        alias = ANTHROPIC_MODELS.get(_undated(e.get("model") or ""))
        if alias and e.get("admitted") and e.get("effort"):
            admitted.setdefault(alias, []).append(e["effort"])
    return {"task": (answers.get("task") or {}).get("choice"),
            "task_changed": (answers.get("task_changed") or {}).get("noul"),
            "difficulty": score("difficulty"), "gain": (answers.get("big_model_gain") or {}).get("noul"),
            "admitted": admitted}


def _post(body: dict, headers: dict) -> dict:
    req = urllib.request.Request(OPENROUTER_URL, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=ROUTER_TIMEOUT_S) as r:
        return json.loads(r.read())


def decide(task: str, *, history=(), post=_post) -> Decision:
    cost = 0.0
    try:
        resp = post(
            {"model": JEV_MODEL, "messages": [*history_messages(history), {"role": "user", "content": task}],
             "max_tokens": 1,
             # uma sessão nova em cada decisão: sem ela, o Jev guarda um incumbente por chave da API e uma
             # sessão (ou um braço do piloto) herdava o modelo de outra; com ela, dá sempre a opinião fresca
             "session_id": f"jev-{uuid.uuid4().hex}",
             "plugins": [{"id": "jev-router", "allowed_models": list(_pool())}]},
            {"X-OpenRouter-Metadata": "enabled"},
        )
        cost = float((resp.get("usage") or {}).get("cost") or 0.0)
        meta = resp.get("openrouter_metadata") or {}
        data = next((p.get("data") or {} for p in meta.get("pipeline") or [] if p.get("name") == "jev-router"), None)
        if not data:
            raise ValueError("a resposta não traz a decisão do Jev (metadados em falta)")
        # Com vários candidatos vem `selection_probabilities`; com um só, apenas `candidates`
        ranked = data.get("selection_probabilities") or data.get("candidates") or []
        top = max(ranked, key=lambda c: c.get("probability") or 0, default=None)
        if not top:
            raise ValueError(f"o Jev não admitiu nenhum modelo permitido (serviu {resp.get('model')})")
        slug, effort = _undated(top["model"]), _effort(top.get("effort"))
        task_type = ((data.get("answers") or {}).get("task") or {}).get("choice") or ""
        why = _why(data)
        cheap_allowed = _pool() != tuple(ANTHROPIC_MODELS)
        if slug in ANTHROPIC_MODELS:
            runner, model = "anthropic", ANTHROPIC_MODELS[slug]
        elif not (_is_cheap(slug) and cheap_allowed):
            raise ValueError(f"o Jev escolheu {slug}, fora dos modelos permitidos")
        elif _needs_tools(task_type):
            runner, model = "anthropic", "sonnet"
            why += " · barato, mas mexe em ficheiros: sonnet"
        else:
            runner, model = "openrouter-free", FREE_EXECUTOR
            why += " · barato: corre num free"
        return Decision(
            runner=runner, model=model, effort=effort, rationale=why,
            est_output_tokens=int(data.get("estimated_output_tokens") or 0),
            router_cost_usd=cost, signals=_signals(data),
        )
    except Exception as exc:  # regra do utilizador: qualquer falha cai para o standard
        return standard(f"{type(exc).__name__}: {str(exc)[:160]}", router_cost_usd=cost)
