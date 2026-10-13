"""Avaliação dos subagentes do JEV (critérios fixados antes de correr, a 2026-10-13).

O que se mede: as Fases A e B de 2026-10-13 (commits 898733c e 385a255), isto é, nos subagentes (1) um modelo
declarado mais barato do que o do Jev passa a valer o do Jev, (2) sem decisão do Jev corre em opus, em vez de herdar
o modelo da faixa, (3) no máximo quatro decisões em paralelo e 30 s de espera, e (4) o prompt vai ao Jev cortado a
12 000 caracteres. Os pilotos anteriores nunca lançaram subagentes, por isso nada disto estava medido.

Piloto `calc-subagentes`: as tarefas T2 (como está, só para manter o estado que as seguintes assumem), T3, T4, T5 e T6
do calc, cada uma das quatro últimas com a instrução de lançar, antes de
implementar, dois subagentes em paralelo (um explora o analisador, outro o avaliador). Mesmos testes escondidos, mesmo
CLAUDE.md, mesmo juiz por tarefa, uma sessão contínua por braço, pool do Jev só com Anthropic, 2 repetições.
Braços: `standard` (sem o mod), `jev-v4-antes` (v4 com o mod do commit 96c7c95) e `jev-v4` (v4 com o mod novo).
Só o mod difere entre os dois braços JEV: o núcleo Python é o mesmo.

Condição de validade: cada braço JEV tem de lançar pelo menos 8 subagentes no total (2 repetições × 4 tarefas, um
mínimo de 1 por tarefa). Com menos, a corrida não mede subagentes: não há veredito e repete-se com instruções mais
explícitas, sem contar como falha.

O mod novo passa a recomendado se cumprir os cinco critérios:
1. Tarefas: o `jev-v4` não chumba nenhuma tarefa que o `jev-v4-antes` ou o `standard` passem.
2. Juiz por tarefa (painel Opus e Sonnet × 2 ordens, 3 de 4 votos), somado nas repetições, contra o `jev-v4-antes`:
   o antes não ganha mais critérios do que o novo.
3. Subagentes no braço novo: nenhum subagente "sem decisão do Jev" corre abaixo de opus. Mede-se no ledger
   (`decision.scope == "agent"`). Que um declarado mais barato sobe para o do Jev está nos testes do mod: o ledger
   não guarda o que o Jev tinha decidido quando o declarado já chegava, por isso não se mede aqui.
4. Custo + tempo ($0.01/s) nas mesmas condições (a média dos braços em cada turno e modelo, como em
   `simular_politicas.py --medias`), somado nas repetições:
   a. o `jev-v4` custa no máximo 10% mais do que o `jev-v4-antes` (a mudança sobe de propósito alguns subagentes de
      haiku para sonnet, por isso aceita-se um custo um pouco maior; mais do que 10% não);
   b. o `jev-v4` custa menos do que o `standard` (o objetivo do JEV).
5. Concorrência: nenhum `jev route` de subagente (`route_ms`) passa de 30 s, e nenhum registo de subagente tem a
   decisão a falhar por timeout.

Se falhar o critério 1 ou 2, a mudança é uma regressão de qualidade: reverte-se (ou refaz-se) antes de a instalar.
Se falhar só o 4a, decide o utilizador, com os números à frente. Se falhar o 4b, o JEV com subagentes não compensa
face ao standard nestas tarefas, e isso vai no relatório mesmo que o resto passe.

Uso: avaliar_subagentes.py <piloto> [<piloto> ...]   (imprime o relatório e grava avaliacao_subagentes.json ao lado)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from jev import ledger, pilot  # noqa: E402

BASE, TARGET, STANDARD = "jev-v4-antes", "jev-v4", "standard"
MIN_SUBAGENTES = 8
COST_MARGIN = 1.10  # 4a: o novo custe no máximo 10% mais do que o antes
ROUTE_MAX_MS = 30_000
RANK = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}


def _rank(model: str | None) -> int:
    name = (model or "").lower()
    return next((rank for key, rank in RANK.items() if key in name), -1)


def agent_audit(records: list[dict]) -> dict:
    """Dos registos de um braço, o que importa nos subagentes (critérios 3 e 5 e a condição de validade)."""
    agents = [r for r in records if (r["decision"].get("scope") or "main") == "agent"]
    below_opus = []  # "sem decisão do Jev" a correr abaixo de opus
    for r in agents:
        signals = r["decision"].get("signals") or {}
        no_decision = signals.get("rule") in ("Jev sem resposta", "núcleo em falta")
        if no_decision and _rank(r["decision"].get("model")) < RANK["opus"]:
            below_opus.append(r["id"])
    slow = [r["id"] for r in agents if (r["jev"].get("route_ms") or 0) > ROUTE_MAX_MS]
    return {"subagentes": len(agents), "sem_decisao_abaixo_de_opus": below_opus, "route_lento": slow}


def verdict(out: dict) -> dict:
    """A regra de decisão, só sobre os números (separada da leitura dos dados para se poder testar)."""
    valid = out["subagentes"][TARGET] >= MIN_SUBAGENTES and out["subagentes"][BASE] >= MIN_SUBAGENTES
    if not valid:
        return {"válida": False, "critérios": {}, "recomendado": None}
    cost = out["mesmas_condições"]
    criteria = {
        "1 tarefas": not out["tarefas_perdidas"],
        "2 juiz": out["juiz"][BASE] <= out["juiz"][TARGET],
        "3 subagentes": not out["auditoria"][TARGET]["sem_decisao_abaixo_de_opus"],
        "4a custo contra o antes": cost[TARGET] <= cost[BASE] * COST_MARGIN,
        "4b custo contra o standard": cost[TARGET] < cost[STANDARD],
        "5 concorrência": not out["auditoria"][TARGET]["route_lento"],
    }
    return {"válida": True, "critérios": criteria, "recomendado": all(criteria.values())}


def evaluate(pilot_ids: list[str]) -> dict:
    import avaliar_v4 as v4  # as mesmas condições e o mecanismo, com outros braços

    pilots = {p["id"]: p for p in pilot.read_all()}
    out = {"pilotos": {}, "subagentes": {TARGET: 0, BASE: 0}, "auditoria": {}, "tarefas_perdidas": [],
           "juiz": {TARGET: 0, BASE: 0},
           "mesmas_condições": {STANDARD: 0.0, BASE: 0.0, TARGET: 0.0}}
    audits = {TARGET: {"sem_decisao_abaixo_de_opus": [], "route_lento": []}, BASE: {"sem_decisao_abaixo_de_opus": [], "route_lento": []}}
    for pid in pilot_ids:
        p = pilots[pid]
        rows = {(r["arm"], r["task"]): r for r in p["tasks"]}
        for t in p["meta"]["tasks"]:
            target = rows.get((TARGET, t["id"]))
            for other in (BASE, STANDARD):
                row = rows.get((other, t["id"]))
                if row and target and row["acceptance"]["ok"] and not target["acceptance"]["ok"]:
                    out["tarefas_perdidas"].append(f"{pid}:{t['id']} (perdeu para {other})")
        for res in ((p.get("task_judge") or {}).get("results") or []):
            for c in res["criteria"]:
                if c["result"] in out["juiz"]:
                    out["juiz"][c["result"]] += 1
        for arm in (BASE, TARGET):
            records = ledger.read_all(home=pilot.pilots_dir() / pid / f"{arm}-home")
            audit = agent_audit(records)
            out["subagentes"][arm] += audit["subagentes"]
            for key in ("sem_decisao_abaixo_de_opus", "route_lento"):
                audits[arm][key] += audit[key]
        arms = {arm: v4.sim.load_arm(pid, arm) for arm in (STANDARD, BASE, TARGET)}
        n = min(len(t) for t in arms.values())
        arms = {arm: turns[:n] for arm, turns in arms.items()}
        prof, contexts = v4.sim.mean_profiles(arms, n), [t["context"] for t in arms[BASE]]
        for arm, turns in arms.items():
            r = v4.sim.replay([t["model"] for t in turns], prof, contexts)
            out["mesmas_condições"][arm] += v4.sim.objective(r)
        out["pilotos"][pid] = {arm: {"modelos": "".join(t["model"][0] for t in turns)} for arm, turns in arms.items()}
    out["auditoria"] = audits
    out["veredito"] = verdict(out)
    return out


if __name__ == "__main__":
    out = evaluate(sys.argv[1:])
    (Path(__file__).parent / "avaliacao_subagentes.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("subagentes lançados:", out["subagentes"], "· mínimo por braço:", MIN_SUBAGENTES)
    print("tarefas perdidas:", out["tarefas_perdidas"], "· juiz:", out["juiz"])
    print("mesmas condições:", {k: round(v, 2) for k, v in out["mesmas_condições"].items()})
    print("auditoria:", out["auditoria"])
    v = out["veredito"]
    print("válida:", v["válida"], "· critérios:", v["critérios"], "· recomendado:", v["recomendado"])
