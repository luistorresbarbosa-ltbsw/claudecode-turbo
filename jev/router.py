"""Router do JEV: um modelo free decide onde corre cada tarefa, com que modelo e esforço.

Qualquer falha (rate limit, timeout, JSON inválido, decisão incoerente) cai para o standard
Anthropic, ou seja, o que o Claude Code usaria sem o JEV. Os modelos Anthropic correm sempre
pela subscrição (`claude -p`); o OpenRouter só serve modelos free.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

import litellm

litellm.suppress_debug_info = True  # senão imprime avisos no stdout, que o mod lê como JSON
ROUTER_MODEL = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
ROUTER_TIMEOUT_S = 60
ANTHROPIC_MODELS = ("haiku", "sonnet", "opus", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Executores free: só os bem cotados (maiores, de fornecedores sólidos)
FREE_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
)

SYSTEM_PROMPT = """You are JEV, the router of a Claude Code setup. For each task you choose WHERE it runs, \
aiming for the cheapest option that will still do the job well. You never do the task yourself.

## Options

A) runner "openrouter-free": cost $0. A free model with NO tools: it cannot read files, see the \
repository, run commands or browse. Use it ONLY for self-contained text work where everything needed \
is in the task text: general or conceptual questions, explaining a concept, translating, rewriting or \
drafting text given in full.
   model: "nvidia/nemotron-3-ultra-550b-a55b:free" (best quality, the default),
          "nvidia/nemotron-3-super-120b-a12b:free" (faster),
          "google/gemma-4-31b-it:free" (short, simple text).
   effort: null.

B) runner "anthropic": Claude Code with tools (reads the repo, searches, edits files when allowed). \
Every run first pays ~23k tokens of fixed context (about $0.02 on haiku, $0.10 on opus). \
List price per 1M tokens, input/output:
   - "haiku"  $1/$5: small, well-defined jobs. Typos, one-line fixes, finding where something is, explaining one file.
   - "sonnet" $2/$10: everyday coding. Features or refactors across a few files, writing tests, debugging with a clear lead.
   - "opus"   $4/$20: hard reasoning. Architecture, subtle or cross-cutting bugs, large multi-file changes, security-sensitive work.
   - "fable"  $10/$50: only for the hardest long-horizon problems that opus would likely fail.
   effort (thinking depth; higher means more output tokens and more cost): "low" | "medium" | "high" | "xhigh" | "max".
   Typical pairs: haiku+low, sonnet+medium, opus+high. Use xhigh or max only when the task clearly needs deep reasoning.

## Rules
1. If the task refers to files, code, this project or repo, paths, the codebase, errors on the user's \
machine, or anything that must be looked up: runner "anthropic".
2. Otherwise, if the task is self-contained text: runner "openrouter-free". Use \
"nvidia/nemotron-3-ultra-550b-a55b:free" for any answer longer than a line or two; \
"google/gemma-4-31b-it:free" only for very short replies such as a one-line translation.
3. Minimums. Never go below these, whatever else the task looks like:
   - writing or changing tests: at least "sonnet" with "medium";
   - investigating a bug whose cause is unknown: at least "sonnet" with "medium";
   - any design, redesign or architecture work: at least "opus" with "high".
4. Above the minimums, pick the cheapest model and the lowest effort that will clearly succeed. The \
user's default is opus at xhigh; matching that is only right for genuinely hard tasks.
5. est_output_tokens: your estimate of how many tokens the work will produce.
6. rationale: one short sentence in European Portuguese (pt-PT) explaining the choice.

## Examples
- "qual a diferença entre TCP e UDP?" -> openrouter-free, nvidia/nemotron-3-ultra-550b-a55b:free, null
- "corrige o typo 'recieve' no README.md" -> anthropic, haiku, low
- "escreve testes para o módulo de pagamentos" -> anthropic, sonnet, medium
- "descobre porque é que o login falha só em produção" -> anthropic, opus, high
- "traduz para inglês: 'bom dia a todos'" -> openrouter-free, google/gemma-4-31b-it:free, null

Reply with the JSON object only."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["runner", "model", "effort", "rationale", "est_output_tokens"],
    "properties": {
        "runner": {"type": "string", "enum": ["anthropic", "openrouter-free"]},
        "model": {"type": "string", "enum": [*ANTHROPIC_MODELS, *FREE_MODELS]},
        "effort": {"type": ["string", "null"], "enum": [*EFFORTS, None]},
        "rationale": {"type": "string"},
        "est_output_tokens": {"type": "integer"},
    },
}


@dataclass(frozen=True)
class Decision:
    runner: str
    model: str
    effort: str | None
    rationale: str
    est_output_tokens: int = 0
    is_standard: bool = False
    router_model: str = ROUTER_MODEL
    router_cost_usd: float = 0.0
    router_error: str | None = None

    def to_ledger(self) -> dict:
        return asdict(self)


def standard(router_error: str | None = None) -> Decision:
    """O que o Claude Code usaria sem o JEV (por defeito: opus com o effortLevel xhigh das settings)."""
    return Decision(
        runner="anthropic",
        model=os.environ.get("JEV_STANDARD_MODEL", "opus"),
        effort=os.environ.get("JEV_STANDARD_EFFORT", "xhigh"),
        rationale="fallback: o cérebro free falhou, uso o standard" if router_error else "standard",
        is_standard=True,
        router_error=router_error,
    )


def _check(raw: dict) -> None:
    runner, model, effort = raw["runner"], raw["model"], raw.get("effort")
    if runner == "anthropic":
        if model not in ANTHROPIC_MODELS:
            raise ValueError(f"modelo Anthropic desconhecido: {model!r}")
        if effort not in EFFORTS:
            raise ValueError(f"esforço inválido: {effort!r}")
    elif runner == "openrouter-free":
        if model not in FREE_MODELS:
            raise ValueError(f"modelo free fora da lista: {model!r}")
    else:
        raise ValueError(f"runner desconhecido: {runner!r}")


def decide(task: str, *, complete=litellm.completion) -> Decision:
    try:
        resp = complete(
            model=ROUTER_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Task:\n{task}"},
            ],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "jev_decision", "strict": True, "schema": SCHEMA}},
            timeout=ROUTER_TIMEOUT_S,
        )
        raw = json.loads(resp.choices[0].message.content)
        _check(raw)
        free = raw["runner"] == "openrouter-free"
        return Decision(
            runner=raw["runner"],
            model=raw["model"],
            effort=None if free else raw["effort"],
            rationale=str(raw.get("rationale", ""))[:300],
            est_output_tokens=max(0, int(raw.get("est_output_tokens") or 0)),
            router_cost_usd=float((getattr(resp, "_hidden_params", None) or {}).get("response_cost") or 0.0),
        )
    except Exception as exc:  # regra do utilizador: qualquer falha do cérebro free cai para o standard
        return standard(f"{type(exc).__name__}: {str(exc)[:160]}")
