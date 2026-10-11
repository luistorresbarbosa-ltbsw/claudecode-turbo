"""Harness do piloto: os dois braços correm o mesmo `claude -p`; só o braço JEV leva o mod."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jev import ledger, pilot, pilot_run

FIX = Path(__file__).parent / "fixtures"
SUCCESS = (FIX / "claude_p_success.json").read_text()
BUDGET = (FIX / "claude_p_budget_error.json").read_text()


def flag(argv, name):
    return argv[argv.index(name) + 1]


# --- a linha de comando de cada braço ----------------------------------------

def test_both_arms_run_the_same_claude_and_only_jev_loads_the_mod():
    std = pilot_run.arm_argv("standard", max_usd=1.0)
    jev = pilot_run.arm_argv("jev", max_usd=1.0)

    assert "--plugin-dir" not in std
    assert flag(jev, "--plugin-dir").endswith("mod/jev")
    for argv in (std, jev):
        assert argv[:2] == ["claude", "-p"]
        assert flag(argv, "--output-format") == "json"
        assert flag(argv, "--permission-mode") == "acceptEdits"
        assert flag(argv, "--permission-prompts") == "none"
        assert flag(argv, "--allowed-tools") == "Bash(uv run pytest:*)"
        assert flag(argv, "--max-budget-usd") == "1.0"
        assert "--model" not in argv and "--effort" not in argv  # o standard é o teu Claude Code tal como está


# --- ler o resultado de um claude -p -----------------------------------------

def test_a_successful_run_reports_cost_models_and_answer():
    r = pilot_run.read_claude(SUCCESS, returncode=0)

    assert r["status"] == "done" and r["result"] == "ok"
    assert r["cost_usd"] == pytest.approx(0.0592396)
    assert r["models"] == {"claude-sonnet-5-5": pytest.approx(0.0592396)}


def test_a_budget_stop_is_marked_and_still_costs():
    r = pilot_run.read_claude(BUDGET, returncode=1)

    assert r["status"] == "budget" and r["cost_usd"] == pytest.approx(0.0219195)


def test_output_with_a_warning_before_the_json_is_still_read():
    r = pilot_run.read_claude("Warning: no stdin data received in 3s\n" + SUCCESS, returncode=0)

    assert r["status"] == "done"


def test_output_without_json_is_an_error():
    assert pilot_run.read_claude("Segmentation fault", returncode=139)["status"] == "error"


# --- tarefas de texto e aceitação --------------------------------------------

def test_a_text_answer_is_saved_without_the_hook_prefix(tmp_path):
    pilot_run.save_text_answer(tmp_path, "docs/IVA.md", "Prompt dropped by a hook: | Taxa | 23% |")

    assert (tmp_path / "docs/IVA.md").read_text() == "| Taxa | 23% |"


def test_acceptance_reads_the_real_pytest_result(tmp_path):
    test_file = tmp_path / "test_x.py"
    test_file.write_text("def test_ok():\n    assert True\n\ndef test_ko():\n    assert False\n")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    r = pilot_run.accept(test_file, workspace, python=sys.executable)

    assert r == {"ok": False, "passed": 1, "failed": 1}


# --- orquestração ------------------------------------------------------------

TASKS = [{"id": f"T{i}", "title": f"Tarefa {i}", "kind": "code", "prompt": f"faz {i}"} for i in (1, 2, 3)]


class FakeArms:
    """Fronteira externa falsa: cada claude -p custa `cost` e escreve no ledger do mod (braço JEV)."""

    def __init__(self, cost=0.10):
        self.cost, self.order = cost, []

    def __call__(self, arm, task, workspace, *, max_usd, timeout_s, jev_home):
        self.order.append((task["id"], arm))
        if arm == "jev":  # o mod regista a decisão do Jev no ledger da casa do braço JEV
            ledger.append(ledger.make_record(
                task=task["prompt"],
                decision={"model": "haiku", "effort": "low", "rationale": "Jev: x", "router_cost_usd": 0.0002},
                jev={"cost_usd": 0.01}, standard={"kind": "estimated", "cost_usd": 0.05}), home=jev_home)
        return {"status": "done", "cost_usd": self.cost, "wall_ms": 1000, "models": {"claude-x": self.cost}, "result": "ok"}


def run(tmp_path, arms, **kw):
    seed = tmp_path / "seed"
    (seed / "fatura").mkdir(parents=True)
    (seed / "fatura" / "__init__.py").write_text("")
    return pilot_run.run_pilot(
        TASKS, pilot_id="p1", seed=seed, inject_root=tmp_path / "inject", acceptance_root=tmp_path / "acc",
        home=tmp_path / "home", run_arm=arms, accept=lambda *a, **k: {"ok": True, "passed": 1, "failed": 0},
        git=False, **kw)


def test_arms_alternate_who_goes_first_on_each_task(tmp_path):
    arms = FakeArms()

    run(tmp_path, arms)

    assert arms.order == [("T1", "standard"), ("T1", "jev"), ("T2", "jev"), ("T2", "standard"),
                          ("T3", "standard"), ("T3", "jev")]


def test_every_task_is_recorded_for_both_arms_with_jevs_decision(tmp_path):
    run(tmp_path, FakeArms())

    [p] = pilot.read_all(home=tmp_path / "home")
    assert p["end"] is not None and len(p["tasks"]) == 6
    jev_row = next(t for t in p["tasks"] if t["arm"] == "jev")
    assert jev_row["jev"]["decisions"] == [{"model": "haiku", "effort": "low", "rationale": "Jev: x", "scope": "main"}]
    assert jev_row["cost_usd"] == pytest.approx(0.10 + 0.0002)  # o claude -p + a decisão do Jev
    assert next(t for t in p["tasks"] if t["arm"] == "standard")["jev"] is None


def test_the_pilot_stops_when_the_total_budget_runs_out(tmp_path):
    run(tmp_path, FakeArms(cost=0.30), max_usd_total=1.0)

    [p] = pilot.read_all(home=tmp_path / "home")
    statuses = [(t["task"], t["arm"], t["status"]) for t in p["tasks"]]
    assert ("T3", "standard", "skipped") in statuses and ("T3", "jev", "skipped") in statuses
    assert p["end"]["stopped"] == "orçamento total"


# --- envelope de tempo por braço ---------------------------------------------

class SlowArms(FakeArms):
    """Cada tarefa leva 6 minutos; regista o timeout que o harness lhe deu."""

    def __init__(self):
        super().__init__()
        self.timeouts = []

    def __call__(self, arm, task, workspace, *, max_usd, timeout_s, jev_home):
        self.timeouts.append((task["id"], arm, timeout_s))
        out = super().__call__(arm, task, workspace, max_usd=max_usd, timeout_s=timeout_s, jev_home=jev_home)
        return {**out, "wall_ms": 6 * 60_000}


def test_each_arm_stops_when_its_time_envelope_runs_out(tmp_path):
    arms = SlowArms()

    run(tmp_path, arms, max_min_arm=10)

    # cada braço gastou 6 min na T1: na T2 cada um só tem 4 min (240 s) de timeout
    assert ("T2", "jev", 240) in arms.timeouts and ("T2", "standard", 240) in arms.timeouts
    [p] = pilot.read_all(home=tmp_path / "home")
    t3 = [t["status"] for t in p["tasks"] if t["task"] == "T3"]
    assert t3 == ["skipped", "skipped"]  # 12 min > 10: já não há tempo para a T3


# --- custo de uma tarefa cortada a meio --------------------------------------

def _transcript(folder, cwd, lines):
    folder.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "user", "cwd": str(cwd), "message": {"role": "user", "content": "x"}}, *lines]
    (folder / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_a_killed_run_is_priced_from_its_transcript_counting_each_message_once(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    usage = {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 10738,
             "cache_creation_input_tokens": 14262,
             "cache_creation": {"ephemeral_1h_input_tokens": 14262, "ephemeral_5m_input_tokens": 0}}
    msg = {"type": "assistant", "cwd": str(workspace),
           "message": {"id": "msg_1", "model": "claude-sonnet-5-5", "usage": usage}}
    _transcript(tmp_path / "projects" / "qualquer", workspace, [msg, msg])  # o Claude Code escreve 2 linhas por mensagem

    cost = pilot_run.partial_cost(workspace, since=0, projects_dir=tmp_path / "projects")

    assert cost == pytest.approx(0.0592396)  # o turno real de sonnet, uma só vez


def test_the_cost_state_line_wins_when_the_session_wrote_it(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _transcript(tmp_path / "projects" / "x", workspace, [{"type": "cost-state", "totalCostUSD": 0.0247934}])

    assert pilot_run.partial_cost(workspace, since=0, projects_dir=tmp_path / "projects") == pytest.approx(0.0247934)


def test_no_transcript_means_an_unknown_cost_of_zero(tmp_path):
    assert pilot_run.partial_cost(tmp_path, since=0, projects_dir=tmp_path / "nada") == 0.0


def test_a_crashing_pilot_is_still_closed_so_it_never_looks_like_it_is_running(tmp_path):
    def crashing(arm, task, workspace, **kw):
        raise RuntimeError("o claude rebentou")

    with pytest.raises(RuntimeError):
        run(tmp_path, crashing)

    [p] = pilot.read_all(home=tmp_path / "home")
    assert p["end"] is not None and "o claude rebentou" in p["end"]["stopped"]


def test_the_venv_an_agent_creates_never_lands_in_the_arm_commits(tmp_path):
    class VenvArms(FakeArms):
        def __call__(self, arm, task, workspace, **kw):
            (workspace / ".venv" / "lib").mkdir(parents=True, exist_ok=True)
            (workspace / ".venv" / "lib" / "x.py").write_text("lixo")
            (workspace / "fatura" / "nova.py").write_text("x = 1\n")
            return super().__call__(arm, task, workspace, **kw)

    seed = tmp_path / "seed"
    (seed / "fatura").mkdir(parents=True)
    (seed / "fatura" / "__init__.py").write_text("")
    pilot_run.run_pilot(TASKS[:1], pilot_id="p1", seed=seed, inject_root=tmp_path / "i", acceptance_root=tmp_path / "a",
                        home=tmp_path / "home", run_arm=VenvArms(), git=True,
                        accept=lambda *a, **k: {"ok": True, "passed": 1, "failed": 0})

    ws = pilot.pilots_dir(tmp_path / "home") / "p1" / "standard"
    tracked = subprocess.run(["git", "ls-files"], cwd=ws, capture_output=True, text=True).stdout.split()
    assert "fatura/nova.py" in tracked and not any(f.startswith(".venv") for f in tracked)


def test_a_free_answer_gets_its_newlines_back_and_loses_the_mod_signature(tmp_path):
    # O claude -p devolve o motivo do drop numa linha só: cada \n vira U+FFFD; e o mod assina a resposta.
    shown = ("Prompt dropped by a hook: ## Glossário��| Taxa | % |�|---|---|�| Normal | 23% |"
             "��— JEV: respondido por nvidia/nemotron-3-ultra-550b-a55b:free (free) · Jev: qa_knowledge")

    pilot_run.save_text_answer(tmp_path, "docs/IVA.md", shown)

    # sem a assinatura: o juiz tem de ser cego
    assert (tmp_path / "docs/IVA.md").read_text() == "## Glossário\n\n| Taxa | % |\n|---|---|\n| Normal | 23% |"


def test_the_jev_pool_setting_reaches_only_the_jev_arm(tmp_path):
    jev = pilot_run.arm_env("jev", jev_home=tmp_path, jev_env={"JEV_POOL": "anthropic"})
    std = pilot_run.arm_env("standard", jev_home=tmp_path, jev_env={"JEV_POOL": "anthropic"})

    assert jev["JEV_POOL"] == "anthropic" and "JEV_POOL" not in std
    assert jev["JEV_HOME"] == str(tmp_path)
