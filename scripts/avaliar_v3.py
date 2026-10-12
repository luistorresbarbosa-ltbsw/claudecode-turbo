"""Avaliação da corrida final da v3 (critérios fixados antes de correr, a 2026-10-12).

A v3 passa a defeito se cumprir os quatro critérios, em cada projeto:
1. Tarefas: não chumba nenhuma tarefa que a v1 e a v2 passem (em cada piloto).
2. Custo + tempo (o "equilibrado" do utilizador: $0.01/s): somando as repetições, o da v3 é menor do que o
   da v1 e o da v2. O intervalo de 80% (bootstrap emparelhado por tarefa) diz se a vantagem sai do ruído.
3. Mecanismo: zero trocas de modelo em seguimentos na v3; tokens reescritos pela v3 ≤ os da v2; e todos
   os seguimentos de todos os braços correram o pytest.
4. Juiz por tarefa (painel Opus e Sonnet, 3 de 4 votos): contra cada versão, a v3 não perde mais critérios
   do que ganha.

Uso: avaliar_v3.py <piloto> [<piloto> ...]   (imprime o relatório e grava avaliacao_v3.json ao lado)
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from jev import pilot, pilot_run  # noqa: E402

TIME_USD_PER_S = 0.01
TARGET, OTHERS = "jev-v3", ("jev-v1", "jev-v2")
REWRITE_MIN, NEW_WRITE_PER_PROMPT = 5_000, 1_000
_PYTEST_RESULT = re.compile(r"\d+ (passed|failed)|no tests ran")
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _transcript(pilot_id: str, arm: str) -> Path | None:
    ws = pilot.pilots_dir() / pilot_id / arm
    folder = PROJECTS_DIR / ("-" + str(ws).lstrip("/").replace("/", "-").replace(".", "-"))
    files = list(folder.glob("*.jsonl"))
    return max(files, key=lambda p: p.stat().st_size) if files else None


def session_facts(path: Path) -> dict:
    """Do transcript: tokens reescritos em trocas e, por seguimento, se o pytest deu um resultado."""
    turns, cur, seen, bash = [], None, set(), {}
    for raw in path.read_bytes().splitlines():
        try:
            r = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if r.get("type") == "user" and r.get("promptSource") == "sdk":
            content = r["message"]["content"]
            text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            cur = {"prompt": text.strip(), "first_write": None, "pytest": False}
            turns.append(cur)
            continue
        if cur is None:
            continue
        msg = r.get("message") or {}
        if r.get("type") == "assistant":
            if msg.get("id") not in seen and msg.get("usage") and "<synthetic>" not in (msg.get("model") or ""):
                seen.add(msg.get("id"))
                if cur["first_write"] is None:
                    cur["first_write"] = msg["usage"].get("cache_creation_input_tokens", 0)
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and "pytest" in str((b.get("input") or {}).get("command", "")):
                    bash[b.get("id")] = cur
        elif r.get("type") == "user":
            for b in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in bash:
                    text = b.get("content") if isinstance(b.get("content"), str) else json.dumps(b.get("content"))
                    if _PYTEST_RESULT.search(text or ""):
                        bash[b["tool_use_id"]]["pytest"] = True
    rewritten = sum(max(0, (t["first_write"] or 0) - NEW_WRITE_PER_PROMPT) for t in turns[1:]
                    if (t["first_write"] or 0) > REWRITE_MIN)
    follow_ups = [t for t in turns if t["prompt"] == pilot_run.FOLLOW_UP]
    return {"rewritten": rewritten, "follow_ups": len(follow_ups), "follow_ups_with_pytest": sum(t["pytest"] for t in follow_ups)}


def task_objective(row: dict) -> float:
    return row["cost_usd"] + TIME_USD_PER_S * row["wall_ms"] / 1000


def bootstrap_ci(diffs: list[float], *, n: int = 4000, seed: int = 7) -> tuple[float, float]:
    """Intervalo de 80% da soma das diferenças por tarefa (reamostrando tarefas)."""
    rng = random.Random(seed)
    sums = sorted(sum(rng.choice(diffs) for _ in diffs) for _ in range(n))
    return sums[int(0.1 * n)], sums[int(0.9 * n)]


def evaluate(pilot_ids: list[str]) -> dict:
    pilots = {p["id"]: p for p in pilot.read_all()}
    by_project: dict[str, dict] = {}
    for pid in pilot_ids:
        p = pilots[pid]
        project = pid.split("-")[0]
        proj = by_project.setdefault(project, {"pilotos": [], "braços": {}, "diferenças": {o: [] for o in OTHERS},
                                               "tarefas_perdidas": [], "juiz": {o: {"ganha": 0, "perde": 0} for o in OTHERS}})
        proj["pilotos"].append(pid)
        rows = {(r["arm"], r["task"]): r for r in p["tasks"]}
        arms = [a for a in p["meta"].get("arms") or [] if a in (TARGET, *OTHERS)]
        for arm in arms:
            arm_rows = [r for r in p["tasks"] if r["arm"] == arm]
            facts = session_facts(path) if (path := _transcript(pid, arm)) else {}
            s = proj["braços"].setdefault(arm, {"custo": 0.0, "segundos": 0.0, "concluídas": 0, "tarefas": 0,
                                                "trocas_em_seguimentos": 0, "reescritos": 0, "seguimentos": 0,
                                                "seguimentos_com_pytest": 0})
            s["custo"] += sum(r["cost_usd"] for r in arm_rows)
            s["segundos"] += sum(r["wall_ms"] for r in arm_rows) / 1000
            s["concluídas"] += sum(r["acceptance"]["ok"] for r in arm_rows)
            s["tarefas"] += len(arm_rows)
            s["trocas_em_seguimentos"] += sum(1 for r in arm_rows if len(r.get("call_models") or []) > 1
                                              and r["call_models"][1] != r["call_models"][0])
            s["reescritos"] += facts.get("rewritten", 0)
            s["seguimentos"] += facts.get("follow_ups", 0)
            s["seguimentos_com_pytest"] += facts.get("follow_ups_with_pytest", 0)
        for t in p["meta"]["tasks"]:
            v3 = rows.get((TARGET, t["id"]))
            if not v3:
                continue
            for other in OTHERS:
                if (o := rows.get((other, t["id"]))):
                    proj["diferenças"][other].append(task_objective(v3) - task_objective(o))
            others_ok = [rows[(o, t["id"])]["acceptance"]["ok"] for o in OTHERS if (o, t["id"]) in rows]
            if others_ok and all(others_ok) and not v3["acceptance"]["ok"]:
                proj["tarefas_perdidas"].append(f"{pid}:{t['id']}")
        for res in ((p.get("task_judge") or {}).get("results") or []):
            other = res["pair"][1]
            if other not in OTHERS:
                continue
            for c in res["criteria"]:
                proj["juiz"][other]["ganha"] += c["result"] == TARGET
                proj["juiz"][other]["perde"] += c["result"] == other
    verdict = {}
    for project, proj in by_project.items():
        objective = {a: s["custo"] + TIME_USD_PER_S * s["segundos"] for a, s in proj["braços"].items()}
        v3 = proj["braços"].get(TARGET, {})
        others_present = [o for o in OTHERS if o in objective]
        c2 = bool(others_present) and all(objective[TARGET] < objective[o] for o in others_present)
        ci = {o: bootstrap_ci(proj["diferenças"][o]) for o in others_present if proj["diferenças"][o]}
        c3 = (v3.get("trocas_em_seguimentos", 1) == 0
              and ("jev-v2" not in proj["braços"] or v3.get("reescritos", 0) <= proj["braços"]["jev-v2"]["reescritos"])
              and all(s["seguimentos_com_pytest"] == s["seguimentos"] for s in proj["braços"].values()))
        c4 = all(j["perde"] <= j["ganha"] for o, j in proj["juiz"].items() if o in others_present)
        verdict[project] = {
            "objetivo": objective, "intervalo_80": ci, "braços": proj["braços"], "juiz": proj["juiz"],
            "critérios": {"1 tarefas": not proj["tarefas_perdidas"], "2 custo + tempo": c2, "3 mecanismo": c3,
                          "4 juiz": c4},
            "tarefas_perdidas": proj["tarefas_perdidas"], "pilotos": proj["pilotos"],
        }
    verdict["v3 passa a defeito"] = all(all(v["critérios"].values()) for k, v in verdict.items() if isinstance(v, dict))
    return verdict


if __name__ == "__main__":
    out = evaluate(sys.argv[1:])
    (Path(__file__).parent / "avaliacao_v3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    for project, v in out.items():
        if not isinstance(v, dict):
            continue
        print(f"== {project} ({', '.join(v['pilotos'])})")
        for arm, s in sorted(v["braços"].items()):
            print(f"  {arm}: {s['concluídas']}/{s['tarefas']} tarefas · ${s['custo']:.3f} · {s['segundos']:.0f}s · custo+tempo "
                  f"{v['objetivo'][arm]:.2f} · trocas em seguimentos {s['trocas_em_seguimentos']} · reescritos "
                  f"{s['reescritos']:,} · pytest em {s['seguimentos_com_pytest']}/{s['seguimentos']} seguimentos")
        for other, (lo, hi) in v["intervalo_80"].items():
            print(f"  v3 − {other}: custo+tempo, intervalo de 80% [{lo:+.2f}, {hi:+.2f}]")
        print(f"  juiz: {v['juiz']}")
        print(f"  critérios: {v['critérios']}" + (f" · perdidas: {v['tarefas_perdidas']}" if v["tarefas_perdidas"] else ""))
    print("v3 passa a defeito:", out["v3 passa a defeito"])
