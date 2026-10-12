"""Simulador das políticas de modelo (v1, v2, v3) sobre sessões reais do piloto.

Lê os transcripts e os ledgers dos braços de uma comparação em sessão contínua (`--session`), reconstrói
cada turno pedido a pedido e volta a pô-lo a correr com outra sequência de modelos:
- o perfil de um turno num modelo (tokens, pedidos, tempo) vem do braço que o correu nesse modelo, sem a
  reescrita de cache que teve por trocar; se nenhum braço o correu nesse modelo, copia o do outro modelo e
  ajusta o tempo à velocidade medida;
- a cache: voltar a um modelo é uma releitura se ele foi usado há 3 pedidos ou menos; senão, reescreve o
  contexto todo menos o system e as ferramentas (medido nos transcripts de 2026-10-11);
- as políticas são as de produção (`jev.policy.apply`), alimentadas com decisões frescas do Jev.

Calibração: com os modelos que cada braço correu de facto, tem de reproduzir o custo real a ±2%.
Não mede qualidade, nem o efeito do esforço na saída (é ruído ao nível de uma corrida).

Uso: simular_politicas.py <decisões.json> <piloto> [<piloto> ...]
     (decisões: {projeto: {índice do turno: [decisão do Jev, ...]}}, como o `Decision.to_ledger()`)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from jev import ledger, pilot, policy  # noqa: E402
from jev.router import Decision  # noqa: E402

PRICE = {  # por token, como a faturação do Claude Code (cache de 1 h)
    "sonnet": {"input": 2e-6, "output": 10e-6, "read": 0.2e-6, "write": 4e-6},
    "opus": {"input": 4e-6, "output": 20e-6, "read": 0.2e-6, "write": 8e-6},
}
SECONDS_PER_TOKEN = {"sonnet": 5.6e-3, "opus": 8.2e-3}
PROJECTS_DIR = Path.home() / ".claude" / "projects"
REREAD_MAX_REQUESTS = 3  # voltar a um modelo usado há ≤ 3 pedidos é releitura (lookback de 20 blocos)
NEW_WRITE_PER_PROMPT = 1_000  # o que um prompt escreve na cache sem trocar de modelo (0,6 a 1,4k medidos)
REWRITE_MIN = 5_000  # acima disto, a escrita do 1.º pedido foi uma reescrita


def _family(model_id: str) -> str | None:
    return "opus" if "opus" in model_id else "sonnet" if "sonnet" in model_id else None


def read_turns(transcript: Path) -> list[dict]:
    """Os turnos de uma sessão: cada prompt `sdk` e os pedidos que se seguiram (um por message.id)."""
    turns, cur, by_id = [], None, {}
    for raw in transcript.read_bytes().splitlines():
        try:
            r = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if r.get("type") == "user" and r.get("promptSource") == "sdk":
            content = r["message"]["content"]
            text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            cur = {"prompt": text.strip(), "requests": []}
            turns.append(cur)
        elif r.get("type") == "assistant" and cur is not None:
            m = r.get("message") or {}
            fam = _family(m.get("model") or "")
            if not fam or not m.get("usage"):
                continue
            u = m["usage"]
            req = {"model": fam, "input": u.get("input_tokens", 0), "read": u.get("cache_read_input_tokens", 0),
                   "write": u.get("cache_creation_input_tokens", 0), "output": u.get("output_tokens", 0)}
            if m.get("id") in by_id:
                by_id[m["id"]].update(req)  # o Claude Code escreve uma linha por bloco: fica a última
            else:
                by_id[m.get("id")] = req
                cur["requests"].append(req)
    return turns


def _cost(model: str, input_, read, write, output) -> float:
    p = PRICE[model]
    return input_ * p["input"] + read * p["read"] + write * p["write"] + output * p["output"]


def load_arm(pilot_id: str, arm: str) -> list[dict]:
    """Os turnos de um braço, com o tempo de cada um (ledger do mod) e o perfil "a quente" (sem reescrita)."""
    ws = pilot.pilots_dir() / pilot_id / arm
    slug = "-" + str(ws).lstrip("/").replace("/", "-").replace(".", "-")
    transcript = max((PROJECTS_DIR / slug).glob("*.jsonl"), key=lambda p: p.stat().st_size)
    turns = read_turns(transcript)
    records = ledger.read_all(home=pilot.pilots_dir() / pilot_id / f"{arm}-home")
    for i, t in enumerate(turns):
        reqs = t["requests"]
        first = reqs[0]
        t["model"] = first["model"]
        t["context"] = first["input"] + first["read"] + first["write"]
        t["seconds"] = (records[i]["jev"].get("duration_ms") or 0) / 1000 if i < len(records) else 0.0
        t["actual_cost"] = sum(_cost(r["model"], r["input"], r["read"], r["write"], r["output"]) for r in reqs)
        rewrite = max(0, first["write"] - NEW_WRITE_PER_PROMPT) if (i and first["write"] > REWRITE_MIN) else 0
        t["warm"] = {"requests": len(reqs), "input": sum(r["input"] for r in reqs),
                     "read": sum(r["read"] for r in reqs) + rewrite, "write": sum(r["write"] for r in reqs) - rewrite,
                     "output": sum(r["output"] for r in reqs)}
    return turns


def profiles(arms: dict[str, list[dict]]) -> dict:
    """Perfil (turno, modelo): de um braço que correu esse turno nesse modelo; senão, sintetizado."""
    n = min(len(t) for t in arms.values())
    prof = {}
    for i in range(n):
        for turns in arms.values():
            prof.setdefault((i, turns[i]["model"]), {**turns[i]["warm"], "seconds": turns[i]["seconds"]})
        for fam in PRICE:
            if (i, fam) not in prof:
                donor_fam = next(f for f in PRICE if (i, f) in prof)
                d = prof[(i, donor_fam)]
                prof[(i, fam)] = {**d, "seconds": max(1.0, d["seconds"] + d["output"] * (
                    SECONDS_PER_TOKEN[fam] - SECONDS_PER_TOKEN[donor_fam])), "synthetic": True}
    return prof


def replay(models: list[str], prof: dict, contexts: list[int]) -> dict:
    """Custo, tempo, trocas e tokens reescritos de uma sequência de modelos."""
    last_use, last_ctx, counter = {}, {}, 0
    cost = seconds = rewritten = 0.0
    switches = 0
    for i, m in enumerate(models):
        p, ctx = prof[(i, m)], contexts[i]
        extra = 0
        if i and m != models[i - 1]:
            switches += 1
            if m in last_use and counter - last_use[m] <= REREAD_MAX_REQUESTS:
                extra = max(0, ctx - last_ctx[m])  # releitura: só o que a conversa cresceu desde então
            else:
                extra = max(0, ctx - policy.CACHE_FIXED_TOKENS)
        rewritten += extra
        cost += _cost(m, p["input"], p["read"] - extra, p["write"] + extra, p["output"])
        seconds += p["seconds"]
        counter += p["requests"]
        last_use[m], last_ctx[m] = counter, contexts[i + 1] if i + 1 < len(contexts) else ctx
    return {"cost": cost, "seconds": seconds, "switches": switches, "rewritten": int(rewritten)}


def run_policy(name: str, decisions: list[dict], prompts: list[str], prof: dict, contexts: list[int],
               regret_rule: bool = False) -> list[str]:
    """Os modelos que uma política escolhe, turno a turno, com as decisões do Jev e o estado da sessão."""
    state, now, models = None, 1_000_000_000.0, []
    for i, raw in enumerate(decisions):
        d = Decision(**{k: raw[k] for k in Decision.__dataclass_fields__ if k in raw})
        if name == "v1":
            chosen = d
        else:
            new_task = policy.is_new_task(d.signals, prompts[i]) if state else True
            chosen = policy.apply(d, state, name, now=now, prompt=prompts[i], context=contexts[i],
                                  regret_rule=regret_rule)
            state = {**policy.next_state(chosen, state, now=now, new_task=new_task), "context": contexts[i]}
            p = prof[(i, chosen.model)]
            if state.get("held_from"):
                state = policy.add_regret(state, output_tokens=p["output"], write_tokens=p["write"])
        models.append(chosen.model)
        now += prof[(i, chosen.model)]["seconds"]
    return models


def main(argv: list[str]) -> dict:
    raw = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    report = {}
    for pilot_id in argv[1:]:
        project = pilot_id.split("-")[0]
        arms = {arm: load_arm(pilot_id, arm) for arm in ("jev-v1", "jev-v2")}
        prof = profiles(arms)
        base = arms["jev-v1"]
        contexts, prompts = [t["context"] for t in base], [t["prompt"] for t in base]
        res = {}
        for arm, turns in arms.items():  # calibração
            sim = replay([t["model"] for t in turns], profiles({arm: turns}), [t["context"] for t in turns])
            actual = sum(t["actual_cost"] for t in turns)
            res[f"calibração {arm}"] = {**sim, "real": actual, "erro": sim["cost"] / actual - 1}
        for sample in range(len(next(iter(raw[project].values())))):
            decisions = [raw[project][str(i)][sample] for i in range(len(base))]
            for name, kw in (("v1", {}), ("v2", {}), ("v3", {}), ("v3+R6", {"regret_rule": True})):
                models = run_policy(name.split("+")[0], decisions, prompts, prof, contexts, **kw)
                res[f"amostra {sample} {name}"] = {**replay(models, prof, contexts), "modelos": "".join(m[0] for m in models)}
        report[project] = res
    return report


if __name__ == "__main__" and "--varrer" not in sys.argv:
    out = main(sys.argv[1:])
    for project, res in out.items():
        print(f"== {project}")
        for name, r in res.items():
            extra = f" real ${r['real']:.3f} (erro {r['erro']:+.1%})" if "real" in r else f" {r.get('modelos', '')}"
            print(f"  {name:<22} ${r['cost']:.3f} {r['seconds']:6.1f}s trocas {r['switches']:>2} reescritos {r['rewritten']:>7,}{extra}")


def sweep(argv: list[str]) -> list[dict]:
    """Varre as constantes da v3 e diz que combinações passam a porta G3: custo ≤ v2 e tempo ≤ v1 em todos os
    projetos e amostras (com as mesmas decisões do Jev para as três versões)."""
    import itertools
    raw = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    cases = []
    for pilot_id in argv[1:]:
        project = pilot_id.split("-")[0]
        arms = {arm: load_arm(pilot_id, arm) for arm in ("jev-v1", "jev-v2")}
        prof, base = profiles(arms), arms["jev-v1"]
        contexts, prompts = [t["context"] for t in base], [t["prompt"] for t in base]
        for sample in range(len(next(iter(raw[project].values())))):
            decisions = [raw[project][str(i)][sample] for i in range(len(base))]
            refs = {name: replay(run_policy(name, decisions, prompts, prof, contexts), prof, contexts)
                    for name in ("v1", "v2")}
            cases.append((project, sample, decisions, prompts, prof, contexts, refs))
    saved = (policy.FREE_SWITCH_CONTEXT, policy.QUALITY_USD, policy.REGRET_K)
    rows = []
    try:
        for free, value, r6, k in itertools.product((25_000, 40_000, 50_000, 60_000, 80_000), (0.75, 1.5, 3.0),
                                                    (False, True), (0.5, 1.0, 1.5)):
            if not r6 and k != 1.5:
                continue
            policy.FREE_SWITCH_CONTEXT, policy.QUALITY_USD, policy.REGRET_K = free, value, k
            row = {"livre": free, "qualidade": value, "R6": r6, "k": k, "casos": []}
            for project, sample, decisions, prompts, prof, contexts, refs in cases:
                models = run_policy("v3", decisions, prompts, prof, contexts, regret_rule=r6)
                sim = replay(models, prof, contexts)
                row["casos"].append({"projeto": project, "amostra": sample, **sim, "modelos": "".join(m[0] for m in models),
                                     "v1": refs["v1"], "v2": refs["v2"]})
            row["passa"] = all(c["cost"] <= c["v2"]["cost"] + 1e-9 and c["seconds"] <= c["v1"]["seconds"] + 1e-9
                               for c in row["casos"])
            row["objetivo"] = sum(c["cost"] + policy.TIME_USD_PER_S * c["seconds"] for c in row["casos"])
            rows.append(row)
    finally:
        policy.FREE_SWITCH_CONTEXT, policy.QUALITY_USD, policy.REGRET_K = saved
    return rows


if __name__ == "__main__" and "--varrer" in sys.argv:
    args = [a for a in sys.argv[1:] if a != "--varrer"]
    rows = sweep(args)
    ref = rows[0]["casos"]
    print("referências (custo/tempo):", "; ".join(f"{c['projeto']}#{c['amostra']} v1 ${c['v1']['cost']:.2f}/{c['v1']['seconds']:.0f}s "
                                                 f"v2 ${c['v2']['cost']:.2f}/{c['v2']['seconds']:.0f}s" for c in ref))
    for row in sorted(rows, key=lambda r: r["objetivo"])[:12]:
        casos = " | ".join(f"{c['projeto'][0]}{c['amostra']} ${c['cost']:.2f}/{c['seconds']:.0f}s {c['modelos']}" for c in row["casos"])
        print(f"{'PASSA' if row['passa'] else '     '} livre {row['livre'] // 1000}k qualidade {row['qualidade']} "
              f"R6 {'sim k=' + str(row['k']) if row['R6'] else 'não':<9} objetivo {row['objetivo']:.2f} | {casos}")
