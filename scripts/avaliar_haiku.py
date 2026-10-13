"""Teste dirigido dos subagentes com modelo declarado (critérios fixados antes de correr, a 2026-10-13).

Porquê: nas duas repetições de `calc-subagentes` nenhum subagente declarou modelo e o Jev nunca falhou, por isso o mod
novo e o `jev-v4-antes` correram igual nos subagentes e o piloto não mediu a mudança (o juiz deu 13 contra 8 numa
comparação sem diferença real: é o ruído do juiz com 2 repetições). Aqui obriga-se o caminho: o Claude é mandado
lançar os dois subagentes com `model: "haiku"`. O Jev só tem modelos maiores no pool, por isso o antes mantém o haiku
declarado e o novo sobe para o do Jev. O caminho "Jev falha" não se consegue forçar sem falhar também o turno
principal (cairia em opus nos dois braços): fica coberto só pelos testes do mod.

Piloto `calc-subagentes-haiku`: T2 (como está) e T3 e T4 do calc com a instrução acima. Braços `jev-v4-antes` e
`jev-v4` (sem standard: já está medido), 1 repetição, sessão contínua, mesmo CLAUDE.md, pool só Anthropic.

O mod novo confirma a mudança se cumprir os quatro critérios:
M1. (validade) O braço antes lança pelo menos 3 subagentes e pelo menos 1 corre em haiku (senão o caminho não foi
    forçado e não há veredito).
M2. No braço novo, nenhum subagente corre em haiku.
Q1. O novo não chumba nenhuma tarefa que o antes passe.
Q2. Custo + tempo ($0.01/s) nas mesmas condições: o novo custa no máximo 10% mais do que o antes.
O juiz por tarefa (par novo contra antes) corre e vai no relatório, mas **não decide**: com 3 tarefas e uma repetição o
ruído (13 contra 8 numa comparação sem diferença) é maior do que qualquer efeito que se queira detetar.

Se M2 ou Q1 falharem, a mudança reverte-se. Se só falhar o Q2, decide o utilizador com os números.

Uso: avaliar_haiku.py <piloto>   (imprime o relatório e grava avaliacao_haiku.json ao lado)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from jev import ledger, pilot  # noqa: E402

BASE, TARGET = "jev-v4-antes", "jev-v4"
MIN_SUBAGENTES = 3
COST_MARGIN = 1.10


def models_of(records: list[dict]) -> dict[str, int]:
    """Quantos subagentes correram em cada modelo (decision.scope == "agent")."""
    out: dict[str, int] = {}
    for r in records:
        if (r["decision"].get("scope") or "main") == "agent":
            name = next((m for m in ("haiku", "sonnet", "opus", "fable") if m in (r["decision"].get("model") or "").lower()), "outro")
            out[name] = out.get(name, 0) + 1
    return out


def verdict(out: dict) -> dict:
    base, target = out["subagentes"][BASE], out["subagentes"][TARGET]
    valid = sum(base.values()) >= MIN_SUBAGENTES and base.get("haiku", 0) >= 1
    if not valid:
        return {"válida": False, "critérios": {}, "confirmado": None}
    cost = out["mesmas_condições"]
    criteria = {"M2 novo sem haiku": target.get("haiku", 0) == 0,
                "Q1 tarefas": not out["tarefas_perdidas"],
                "Q2 custo + tempo": cost[TARGET] <= cost[BASE] * COST_MARGIN}
    return {"válida": True, "critérios": criteria, "confirmado": all(criteria.values())}


def evaluate(pilot_id: str) -> dict:
    import avaliar_v4 as v4

    p = next(p for p in pilot.read_all() if p["id"] == pilot_id)
    rows = {(r["arm"], r["task"]): r for r in p["tasks"]}
    lost = [t["id"] for t in p["meta"]["tasks"]
            if rows.get((BASE, t["id"])) and rows.get((TARGET, t["id"]))
            and rows[(BASE, t["id"])]["acceptance"]["ok"] and not rows[(TARGET, t["id"])]["acceptance"]["ok"]]
    arms = {arm: v4.sim.load_arm(pilot_id, arm) for arm in (BASE, TARGET)}
    n = min(len(t) for t in arms.values())
    arms = {arm: turns[:n] for arm, turns in arms.items()}
    prof, contexts = v4.sim.mean_profiles(arms, n), [t["context"] for t in arms[BASE]]
    same = {arm: v4.sim.objective(v4.sim.replay([t["model"] for t in turns], prof, contexts)) for arm, turns in arms.items()}
    subagents = {arm: models_of(ledger.read_all(home=pilot.pilots_dir() / pilot_id / f"{arm}-home")) for arm in (BASE, TARGET)}
    judge = {BASE: 0, TARGET: 0}
    for res in ((p.get("task_judge") or {}).get("results") or []):
        if sorted(res["pair"]) == sorted([TARGET, BASE]):
            for c in res["criteria"]:
                if c["result"] in judge:
                    judge[c["result"]] += 1
    real = {arm: {"custo": sum(r["cost_usd"] for r in p["tasks"] if r["arm"] == arm),
                  "segundos": sum(r["wall_ms"] for r in p["tasks"] if r["arm"] == arm) / 1000} for arm in (BASE, TARGET)}
    out = {"subagentes": subagents, "tarefas_perdidas": lost, "mesmas_condições": same, "juiz (não decide)": judge, "real": real}
    out["veredito"] = verdict(out)
    return out


if __name__ == "__main__":
    out = evaluate(sys.argv[1])
    (Path(__file__).parent / "avaliacao_haiku.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for k, v in out.items():
        print(f"{k}: {v}")
