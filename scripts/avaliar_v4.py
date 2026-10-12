"""Avaliação da corrida final v3 contra v4 (critérios fixados antes de correr, a 2026-10-12).

A v4 é a v3 com duas mudanças: os seguimentos óbvios correm na faixa sem perguntar ao Jev, e a porta do Sonnet
(onde o Jev pede Opus com ganho ≤ 0,50, corre sonnet · high). Corrida: fatura e calc, 2 repetições, uma sessão
contínua por braço, o mesmo CLAUDE.md, o pool do Jev só com modelos Anthropic, juiz por tarefa com a v4 como alvo.

A v4 passa a defeito se cumprir os três critérios:
1. Tarefas: em cada piloto, não chumba nenhuma tarefa que a v3 passe.
2. Juiz por tarefa (painel Opus e Sonnet × 2 ordens, 3 de 4 votos), somado nos dois projetos e nas repetições:
   a v3 não ganha mais critérios do que a v4.
3. Custo + tempo ($0.01/s) nas mesmas condições: a sequência de modelos que cada braço correu, posta a correr
   sobre os mesmos perfis (a média dos dois braços em cada turno e modelo, como em `simular_politicas.py --medias`),
   somada nos 4 pilotos, é menor na v4.
O custo e o tempo reais, e o mecanismo (seguimentos sem decisão do Jev, `route_ms` registado), vão no relatório.

Uso: avaliar_v4.py <piloto> [<piloto> ...]   (imprime o relatório e grava avaliacao_v4.json ao lado)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from jev import ledger, pilot  # noqa: E402
import simular_politicas as sim  # noqa: E402

BASE, TARGET = "jev-v3", "jev-v4"


def same_conditions(pilot_id: str) -> dict:
    """Custo, tempo e custo + tempo da sequência de modelos de cada braço, sobre os perfis médios dos dois."""
    arms = {arm: sim.load_arm(pilot_id, arm) for arm in (BASE, TARGET)}
    n = min(len(t) for t in arms.values())
    arms = {arm: turns[:n] for arm, turns in arms.items()}
    prof, contexts = sim.mean_profiles(arms, n), [t["context"] for t in arms[BASE]]
    out = {}
    for arm, turns in arms.items():
        r = sim.replay([t["model"] for t in turns], prof, contexts)
        out[arm] = {**r, "objective": sim.objective(r), "models": "".join(t["model"][0] for t in turns)}
    return out


def mechanism(pilot_id: str, arm: str) -> dict:
    """Do ledger do braço: quantos prompts saltaram o Jev, e se todos têm o tempo do route."""
    records = ledger.read_all(home=pilot.pilots_dir() / pilot_id / f"{arm}-home")
    main = [r for r in records if (r["decision"].get("scope") or "main") == "main"]
    skipped = [r for r in main if (r["decision"].get("signals") or {}).get("jev") == "saltado"]
    gated = [r for r in main if (r["decision"].get("signals") or {}).get("gate") == "sonnet"]
    return {"prompts": len(main), "sem_jev": len(skipped), "porta_sonnet": len(gated),
            "decide_ms_sem_jev": sum(r["jev"].get("decide_ms") or 0 for r in skipped),
            "com_route_ms": sum(r["jev"].get("route_ms") is not None for r in main),
            "route_ms_total": sum(r["jev"].get("route_ms") or 0 for r in main)}


def evaluate(pilot_ids: list[str]) -> dict:
    pilots = {p["id"]: p for p in pilot.read_all()}
    out = {"pilotos": {}, "juiz": {"v4": 0, "v3": 0}, "tarefas_perdidas": [], "mesmas_condições": {BASE: 0.0, TARGET: 0.0},
           "real": {BASE: {"custo": 0.0, "segundos": 0.0, "concluídas": 0, "tarefas": 0},
                    TARGET: {"custo": 0.0, "segundos": 0.0, "concluídas": 0, "tarefas": 0}}}
    for pid in pilot_ids:
        p = pilots[pid]
        rows = {(r["arm"], r["task"]): r for r in p["tasks"]}
        for t in p["meta"]["tasks"]:
            base, target = rows.get((BASE, t["id"])), rows.get((TARGET, t["id"]))
            if base and target and base["acceptance"]["ok"] and not target["acceptance"]["ok"]:
                out["tarefas_perdidas"].append(f"{pid}:{t['id']}")
        for arm in (BASE, TARGET):
            arm_rows = [r for r in p["tasks"] if r["arm"] == arm]
            real = out["real"][arm]
            real["custo"] += sum(r["cost_usd"] for r in arm_rows)
            real["segundos"] += sum(r["wall_ms"] for r in arm_rows) / 1000
            real["concluídas"] += sum(r["acceptance"]["ok"] for r in arm_rows)
            real["tarefas"] += len(arm_rows)
        for res in ((p.get("task_judge") or {}).get("results") or []):
            for c in res["criteria"]:
                out["juiz"]["v4"] += c["result"] == TARGET
                out["juiz"]["v3"] += c["result"] == BASE
        same = same_conditions(pid)
        for arm in (BASE, TARGET):
            out["mesmas_condições"][arm] += same[arm]["objective"]
        out["pilotos"][pid] = {"mesmas_condições": same, "mecanismo": {arm: mechanism(pid, arm) for arm in (BASE, TARGET)}}
    for real in out["real"].values():
        real["custo + tempo"] = real["custo"] + sim.policy.TIME_USD_PER_S * real["segundos"]
    out["critérios"] = {"1 tarefas": not out["tarefas_perdidas"],
                        "2 juiz": out["juiz"]["v3"] <= out["juiz"]["v4"],
                        "3 custo + tempo": out["mesmas_condições"][TARGET] < out["mesmas_condições"][BASE]}
    out["v4 passa a defeito"] = all(out["critérios"].values())
    return out


if __name__ == "__main__":
    out = evaluate(sys.argv[1:])
    (Path(__file__).parent / "avaliacao_v4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for pid, v in out["pilotos"].items():
        print(f"== {pid}")
        for arm in (BASE, TARGET):
            s, m = v["mesmas_condições"][arm], v["mecanismo"][arm]
            print(f"  {arm}: mesmas condições ${s['cost']:.3f} {s['seconds']:.0f}s custo+tempo {s['objective']:.2f} "
                  f"{s['models']} · prompts {m['prompts']}, sem Jev {m['sem_jev']}, porta {m['porta_sonnet']}, "
                  f"route_ms em {m['com_route_ms']}/{m['prompts']} ({m['route_ms_total'] / 1000:.1f}s)")
    for arm, r in out["real"].items():
        print(f"real {arm}: {r['concluídas']}/{r['tarefas']} · ${r['custo']:.2f} · {r['segundos']:.0f}s · "
              f"custo+tempo {r['custo + tempo']:.2f}")
    print("mesmas condições:", {k: round(v, 2) for k, v in out["mesmas_condições"].items()})
    print("juiz:", out["juiz"], "· perdidas:", out["tarefas_perdidas"])
    print("critérios:", out["critérios"], "· v4 passa a defeito:", out["v4 passa a defeito"])
