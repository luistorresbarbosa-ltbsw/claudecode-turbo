"""Avaliação da experiência "o Sonnet onde o Jev pede Opus" (critérios fixados antes de correr, a 2026-10-13).

Braços: jev-v3 (o Jev escolhe; nestas tarefas pediu sempre Opus, em todas as corridas finais) contra
sonnet-high (o Claude Code sem o mod, sempre sonnet · high). Tarefas: fatura T2 e T6; calc T3, T5, T6 e T7.
Três repetições de cada projeto, uma tarefa por prompt (sem sessão), com o mesmo CLAUDE.md e o pool do Jev só
com modelos Anthropic.

1. Validade: uma tarefa só conta numa repetição se o braço do Jev correu o pedido principal no Opus.
2. O Sonnet·high aguenta uma tarefa se:
   a) há pelo menos 2 repetições válidas e passa os testes escondidos em todas;
   b) o juiz por tarefa (painel Opus e Sonnet × 2 ordens, 3 de 4 votos), somado nas repetições, não dá ao
      braço do Jev mais critérios do que ao Sonnet.
3. Porta de ganho G: a v4 passa a usar o Sonnet onde o Jev pede Opus com `gain` ≤ G. O ganho de cada tarefa é a
   média do `gain` que o Jev lhe deu nas repetições válidas.
   - G é o maior ganho de uma tarefa aguentada que fique abaixo do menor ganho de uma tarefa falhada (as
     aguentadas acima de uma falhada não alargam a porta).
   - Nunca se extrapola: sem falhas, G é o maior ganho medido.
   - Sem porta, se o Sonnet falhar a tarefa de menor ganho.
O custo e o tempo de cada tarefa, Sonnet contra Opus, vão no relatório, mas não decidem: a decisão é de qualidade.

Uso: avaliar_sonnet.py <piloto> [<piloto> ...]   (imprime o relatório e grava avaliacao_sonnet.json ao lado)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from jev import ledger, pilot  # noqa: E402

JEV, SONNET = "jev-v3", "sonnet-high"
MIN_VALID = 2


def gate(tasks: dict[str, dict]) -> float | None:
    """A porta de ganho, dado {tarefa: {"gain": ganho médio, "holds": o Sonnet aguentou}} (critério 3)."""
    ranked = sorted(tasks.values(), key=lambda t: t["gain"])
    failed = [t["gain"] for t in ranked if not t["holds"]]
    ceiling = min(failed) if failed else float("inf")
    held = [t["gain"] for t in ranked if t["holds"] and t["gain"] < ceiling]
    return max(held) if held else None


def _gains(pilot_id: str, project: str) -> dict[str, float | None]:
    """O `gain` do Jev para cada tarefa, do ledger do braço do Jev (o ledger guarda o início do prompt, com "…")."""
    records = ledger.read_all(home=pilot.pilots_dir() / pilot_id / f"{JEV}-home")
    prompts = {t["id"]: t["prompt"].strip()
               for t in json.loads((REPO / "pilot" / project / "tasks.json").read_text(encoding="utf-8"))}
    out = {}
    for task_id, prompt in prompts.items():
        rec = next((r for r in records if (head := (r.get("task") or "").rstrip("…").strip())
                    and prompt.startswith(head)), None)
        out[task_id] = ((rec or {}).get("decision", {}).get("signals") or {}).get("gain")
    return out


def evaluate(pilot_ids: list[str]) -> dict:
    pilots = {p["id"]: p for p in pilot.read_all()}
    per_task: dict[str, dict] = {}
    for pid in pilot_ids:
        p = pilots[pid]
        project = pid.split("-")[0]
        rows = {(r["arm"], r["task"]): r for r in p["tasks"]}
        gains = _gains(pid, project)
        verdicts = {res["task"]: res for res in ((p.get("task_judge") or {}).get("results") or [])}
        for t in p["meta"]["tasks"]:
            key = f"{project}:{t['id']}"
            s = per_task.setdefault(key, {"título": t["title"], "repetições": [], "gain": [], "sonnet_passa": 0,
                                          "jev_passa": 0, "válidas": 0, "juiz_sonnet": 0, "juiz_jev": 0,
                                          "custo": {JEV: 0.0, SONNET: 0.0}, "segundos": {JEV: 0.0, SONNET: 0.0}})
            jev, son = rows.get((JEV, t["id"])), rows.get((SONNET, t["id"]))
            decisions = [d for d in ((jev or {}).get("jev") or {}).get("decisions") or [] if d.get("scope") == "main"]
            valid = bool(jev and son and decisions and decisions[0]["model"] == "opus")
            s["repetições"].append({"piloto": pid, "válida": valid,
                                    "jev": f"{decisions[0]['model']} · {decisions[0]['effort']}" if decisions else "—",
                                    "jev_passa": bool(jev and jev["acceptance"]["ok"]),
                                    "sonnet_passa": bool(son and son["acceptance"]["ok"])})
            if not valid:
                continue
            s["válidas"] += 1
            if gains.get(t["id"]) is not None:
                s["gain"].append(gains[t["id"]])
            s["sonnet_passa"] += son["acceptance"]["ok"]
            s["jev_passa"] += jev["acceptance"]["ok"]
            for arm, row in ((JEV, jev), (SONNET, son)):
                s["custo"][arm] += row["cost_usd"]
                s["segundos"][arm] += row["wall_ms"] / 1000
            for c in (verdicts.get(t["id"]) or {}).get("criteria") or []:
                s["juiz_sonnet"] += c["result"] == SONNET
                s["juiz_jev"] += c["result"] == JEV
    for s in per_task.values():
        s["ganho"] = sum(s["gain"]) / len(s["gain"]) if s["gain"] else None
        s["aguenta"] = (s["válidas"] >= MIN_VALID and s["sonnet_passa"] == s["válidas"]
                        and s["juiz_jev"] <= s["juiz_sonnet"])
    measured = {k: {"gain": s["ganho"], "holds": s["aguenta"]} for k, s in per_task.items() if s["ganho"] is not None}
    return {"tarefas": per_task, "porta": gate(measured), "pilotos": pilot_ids}


if __name__ == "__main__":
    out = evaluate(sys.argv[1:])
    (Path(__file__).parent / "avaliacao_sonnet.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for key, s in sorted(out["tarefas"].items(), key=lambda kv: kv[1]["ganho"] or 0):
        print(f"{key:<10} {s['título']:<22} ganho {s['ganho'] if s['ganho'] is None else round(s['ganho'], 2)} · "
              f"válidas {s['válidas']} · testes Sonnet {s['sonnet_passa']}/{s['válidas']} Opus {s['jev_passa']}/{s['válidas']}"
              f" · juiz Sonnet {s['juiz_sonnet']} Opus {s['juiz_jev']} · custo Sonnet ${s['custo'][SONNET]:.2f} Opus "
              f"${s['custo'][JEV]:.2f} · tempo {s['segundos'][SONNET]:.0f}s contra {s['segundos'][JEV]:.0f}s · "
              f"{'AGUENTA' if s['aguenta'] else 'não aguenta'}")
    print("porta de ganho:", out["porta"])
