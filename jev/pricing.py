"""Preços a lista, por token, com o litellm como fonte e duas correções verificadas.

As correções foram confirmadas contra o `total_cost_usd` que o próprio Claude Code reporta
(ver tests/test_pricing.py, que usa execuções reais):

- O Claude Code escreve a cache com TTL de 1h, que custa 2× o input. O campo do litellm
  `cache_creation_input_token_cost` é o preço da cache de 5 min (1.25×).
- O litellm 1.104 tem o cache read do Sonnet 5.5 a $0.10/M; o oficial é $0.20/M.
"""
from __future__ import annotations

import litellm

ALIASES = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
    "fable": "claude-fable-5-1",
}

_OVERRIDES = {
    "claude-sonnet-5-5": {"cache_read": 0.20e-6},
}

# Contexto fixo que o Claude Code carrega em cada `claude -p` (system prompt, ferramentas...).
# Medido a 2026-10-11 com o claude 2.1.287. Serve para estimar o standard de tarefas que
# o JEV correu fora do Claude Code (modelos free), que nunca pagaram este contexto.
CLAUDE_CODE_OVERHEAD = {"cache_read": 13803, "cache_write_1h": 9683}

TOKEN_KINDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def _per_token(model: str) -> dict[str, float]:
    model_id = ALIASES.get(model, model)
    info = litellm.model_cost[model_id]  # KeyError de propósito: modelo desconhecido não é grátis
    price = {
        "input": info["input_cost_per_token"],
        "output": info["output_cost_per_token"],
        "cache_read": info.get("cache_read_input_token_cost") or 0.0,
        "cache_write_5m": info.get("cache_creation_input_token_cost") or 0.0,
        "cache_write_1h": 2 * info["input_cost_per_token"],
    }
    price.update(_OVERRIDES.get(model_id, {}))
    return price


def cost_of(model: str, tokens: dict) -> float:
    """Custo a preço de lista, em USD. Os thinking tokens já vêm contados em `output`."""
    if model.endswith(":free"):
        return 0.0
    price = _per_token(model)
    return sum(price[kind] * (tokens.get(kind) or 0) for kind in TOKEN_KINDS)


def tokens_from_claude_usage(usage: dict) -> dict:
    """Converte o `usage` do `claude -p --output-format json` para os nossos tipos de token."""
    split = usage.get("cache_creation")
    if split:
        write_5m = split.get("ephemeral_5m_input_tokens", 0)
        write_1h = split.get("ephemeral_1h_input_tokens", 0)
    else:  # sem detalhe por TTL, assume o do Claude Code (1h)
        write_5m, write_1h = 0, usage.get("cache_creation_input_tokens", 0)
    return {
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "cache_write_5m": write_5m,
        "cache_write_1h": write_1h,
    }


def with_cc_overhead(tokens: dict) -> dict:
    out = dict(tokens)
    for kind, n in CLAUDE_CODE_OVERHEAD.items():
        out[kind] = (out.get(kind) or 0) + n
    return out
