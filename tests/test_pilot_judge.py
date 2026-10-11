"""Juiz do piloto: Opus pela subscrição, às cegas, duas passagens com a ordem trocada."""
import json

from jev import pilot, pilot_run


def flag(argv, name):
    return argv[argv.index(name) + 1]


def test_the_judge_is_opus_on_the_subscription_without_the_mod_or_tools():
    argv = pilot_run.judge_argv()

    assert flag(argv, "--model") == "opus"
    assert flag(argv, "--tools") == ""
    assert "--plugin-dir" not in argv  # senão seria o Jev a escolher o modelo do juiz
    assert json.loads(flag(argv, "--json-schema"))["required"] == ["criteria"]


def _workspaces(tmp_path):
    out = {}
    for arm, marker in (("standard", "CODIGO_DO_PRIMEIRO"), ("jev", "CODIGO_DO_SEGUNDO")):
        ws = tmp_path / arm
        (ws / "fatura").mkdir(parents=True)
        (ws / "fatura" / "x.py").write_text(f"# {marker}\n")
        (ws / ".venv").mkdir()
        (ws / ".venv" / "lixo.py").write_text("NAO_DEVE_APARECER")
        out[arm] = ws
    return out


def test_the_material_is_blind_and_the_order_decides_who_is_a(tmp_path):
    ws = _workspaces(tmp_path)

    ab = pilot_run.judge_material(ws, order=("standard", "jev"))
    ba = pilot_run.judge_material(ws, order=("jev", "standard"))

    assert ab.index("CODIGO_DO_PRIMEIRO") < ab.index("CODIGO_DO_SEGUNDO")
    assert ba.index("CODIGO_DO_SEGUNDO") < ba.index("CODIGO_DO_PRIMEIRO")
    assert "Projeto A" in ab and "Projeto B" in ab
    assert "NAO_DEVE_APARECER" not in ab
    assert "standard" not in ab.lower() and "/jev" not in ab  # nem o nome da pasta denuncia o braço


def _verdicts(*pairs):
    return {"criteria": [{"id": cid, "winner": w, "reason": "porque sim"} for cid, w in pairs]}


def test_verdicts_map_back_to_arms_and_a_flip_with_the_order_is_inconclusive():
    by_order = {
        ("standard", "jev"): _verdicts(("legibilidade", "A"), ("robustez", "B"), ("textos", "tie")),
        ("jev", "standard"): _verdicts(("legibilidade", "B"), ("robustez", "B"), ("textos", "tie")),
    }

    result = {c["id"]: c for c in pilot_run.aggregate_verdicts(by_order)}

    assert result["legibilidade"]["result"] == "standard"  # A na 1.ª passagem e B na 2.ª: o mesmo projeto
    assert result["robustez"]["result"] == "inconclusive"  # mudou com a ordem
    assert result["textos"]["result"] == "tie"
    assert [v["winner"] for v in result["legibilidade"]["verdicts"]] == ["standard", "standard"]


def test_judging_a_pilot_records_a_judge_row(tmp_path):
    ws = _workspaces(tmp_path)
    pilot.append({"v": 1, "type": "meta", "pilot": "p1", "started": "x", "tasks": []}, home=tmp_path)
    calls = []

    def run_judge(prompt):
        calls.append(prompt)
        return {"status": "done", "cost_usd": 0.25, "structured": _verdicts(("legibilidade", "A")), "result": ""}

    pilot_run.judge_pilot("p1", ws, home=tmp_path, run_judge=run_judge)

    [p] = pilot.read_all(home=tmp_path)
    assert len(calls) == 2 and p["judge"]["cost_usd"] == 0.5 and p["judge"]["model"] == "opus"
    assert {c["id"] for c in p["judge"]["criteria"]} >= {"legibilidade"}


def test_the_judge_row_says_how_each_pass_went(tmp_path):
    ws = _workspaces(tmp_path)
    pilot.append({"v": 1, "type": "meta", "pilot": "p1", "started": "x", "tasks": []}, home=tmp_path)
    replies = iter([{"status": "done", "cost_usd": 0.3, "structured": _verdicts(("legibilidade", "A")), "result": ""},
                    {"status": "error", "cost_usd": 0.1, "structured": None, "result": "", "error": "timeout"}])

    row = pilot_run.judge_pilot("p1", ws, home=tmp_path, run_judge=lambda prompt: next(replies))

    assert [(p["a"], p["ok"]) for p in row["passes"]] == [("standard", True), ("jev", False)]
    assert row["passes"][1]["error"] == "timeout"
