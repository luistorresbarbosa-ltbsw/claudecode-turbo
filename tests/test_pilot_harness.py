"""Harness do piloto: os dois braços correm o mesmo `claude -p`; só o braço JEV leva o mod."""
import json
import subprocess
import sys
from datetime import datetime, timezone
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

    def __call__(self, arm, task, workspace, *, max_usd, timeout_s, jev_home, **kw):
        self.order.append((task["id"], arm))
        if arm == "jev":  # o mod regista a decisão do Jev no ledger da casa do braço JEV
            ledger.append(ledger.make_record(
                task=task["prompt"],
                decision={"model": "haiku", "effort": "low", "rationale": "Jev: x", "router_cost_usd": 0.0002},
                jev={"cost_usd": 0.01}, standard={"kind": "estimated", "cost_usd": 0.05}), home=jev_home)
        return {"status": "done", "cost_usd": self.cost, "wall_ms": 1000, "models": {"claude-x": self.cost}, "result": "ok"}


def run(tmp_path, fake, **kw):
    seed = tmp_path / "seed"
    (seed / "fatura").mkdir(parents=True)
    (seed / "fatura" / "__init__.py").write_text("")
    return pilot_run.run_pilot(
        TASKS, pilot_id="p1", seed=seed, inject_root=tmp_path / "inject", acceptance_root=tmp_path / "acc",
        home=tmp_path / "home", run_arm=fake, accept=lambda *a, **k: {"ok": True, "passed": 1, "failed": 0},
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

def _transcript(folder, cwd, lines, name="s1"):
    folder.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "user", "cwd": str(cwd), "message": {"role": "user", "content": "x"}}, *lines]
    (folder / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


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


def test_the_claude_md_lands_in_both_arms_in_the_starting_commit(tmp_path):
    rules = tmp_path / "CLAUDE.md"
    rules.write_text("# Regras\n- nomes claros\n", encoding="utf-8")
    seed = tmp_path / "seed"
    (seed / "fatura").mkdir(parents=True)
    (seed / "fatura" / "__init__.py").write_text("")

    pilot_run.run_pilot(TASKS[:1], pilot_id="p1", seed=seed, inject_root=tmp_path / "i", acceptance_root=tmp_path / "a",
                        home=tmp_path / "home", run_arm=FakeArms(), git=True, claude_md=rules,
                        accept=lambda *a, **k: {"ok": True, "passed": 1, "failed": 0})

    for arm in pilot_run.ARMS:
        ws = pilot.pilots_dir(tmp_path / "home") / "p1" / arm
        assert (ws / "CLAUDE.md").read_text(encoding="utf-8") == "# Regras\n- nomes claros\n"
        added_in = subprocess.run(["git", "log", "--diff-filter=A", "--format=%s", "--", "CLAUDE.md"],
                                  cwd=ws, capture_output=True, text=True).stdout.strip()
        assert added_in == "ponto de partida"  # vem no ponto de partida: não é trabalho do braço
    [p] = pilot.read_all(home=tmp_path / "home")
    assert p["meta"]["claude_md"] is True


def test_without_a_claude_md_no_arm_gets_one_and_the_meta_says_so(tmp_path):
    run(tmp_path, FakeArms())

    run_dir = pilot.pilots_dir(tmp_path / "home") / "p1"
    assert not (run_dir / "standard" / "CLAUDE.md").exists() and not (run_dir / "jev" / "CLAUDE.md").exists()
    [p] = pilot.read_all(home=tmp_path / "home")
    assert p["meta"]["claude_md"] is False


def test_a_hanging_acceptance_fails_that_task_instead_of_stopping_the_pilot(tmp_path):
    test_file = tmp_path / "test_lento.py"
    test_file.write_text("import time\n\ndef test_pendurado():\n    time.sleep(30)\n")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    r = pilot_run.accept(test_file, workspace, python=sys.executable, timeout_s=1)

    assert r["ok"] is False and r["passed"] == 0 and "1 s" in r["error"]


def test_the_judge_gets_the_projects_spec(tmp_path):
    prompts = []

    def run_judge(prompt):
        prompts.append(prompt)
        return {"status": "done", "cost_usd": 0.0, "structured": {"criteria": []}, "result": ""}

    run(tmp_path, FakeArms(), judge=True, run_judge=run_judge,
        judge_spec={"projeto": "o interpretador calc", "criterios": {}})

    assert len(prompts) == 2 and all("o interpretador calc" in p for p in prompts)



# --- v2 contra v1: braços com nome e uma sessão contínua por braço ----------------------------------

def test_each_jev_version_runs_the_mod_with_its_policy(tmp_path):
    for arm, policy in (("jev-v1", "v1"), ("jev-v2", "v2"), ("jev-v3", "v3"), ("jev-v4", "v4")):
        assert "--plugin-dir" in pilot_run.arm_argv(arm, max_usd=1.0)
        assert pilot_run.arm_env(arm, jev_home=tmp_path)["JEV_POLICY"] == policy
    assert "--plugin-dir" not in pilot_run.arm_argv("standard", max_usd=1.0)
    assert "JEV_POLICY" not in pilot_run.arm_env("standard", jev_home=tmp_path)


def test_a_fixed_arm_runs_claude_with_its_model_and_effort_without_the_mod(tmp_path):
    # para testar o Sonnet onde o Jev pede Opus: o mesmo Claude Code, sem o mod, sempre em sonnet · high
    argv = pilot_run.arm_argv("sonnet-high", max_usd=1.0)

    assert argv[argv.index("--model") + 1] == "sonnet" and argv[argv.index("--effort") + 1] == "high"
    assert "--plugin-dir" not in argv and not pilot_run.uses_mod("sonnet-high")
    assert "JEV_POLICY" not in pilot_run.arm_env("sonnet-high", jev_home=tmp_path)
    assert "--model" not in pilot_run.arm_argv("jev-v3", max_usd=1.0)


def test_the_main_model_of_a_fixed_arm_is_its_own():
    assert pilot_run._main_model({"arm": "sonnet-high", "jev": None}) == "sonnet"
    assert pilot_run._main_model({"arm": "standard", "jev": None}) == "opus"


def test_named_arms_alternate_who_goes_first(tmp_path):
    arms = FakeArms()

    run(tmp_path, arms, arms=("jev-v1", "jev-v2"))

    assert arms.order == [("T1", "jev-v1"), ("T1", "jev-v2"), ("T2", "jev-v2"), ("T2", "jev-v1"),
                          ("T3", "jev-v1"), ("T3", "jev-v2")]
    [p] = pilot.read_all(home=tmp_path / "home")
    assert p["meta"]["arms"] == ["jev-v1", "jev-v2"]


def test_an_unknown_arm_is_refused(tmp_path):
    with pytest.raises(ValueError, match="braço"):
        run(tmp_path, FakeArms(), arms=("standard", "jev-v9"))


def test_the_resume_flag_continues_a_session():
    argv = pilot_run.arm_argv("jev-v2", max_usd=1.0, resume="00b3744d")

    assert argv[argv.index("--resume") + 1] == "00b3744d"


class SessionArms:
    """Fronteira externa falsa de uma sessão contínua: o total_cost_usd do claude -p é cumulativo."""

    def __init__(self):
        self.calls, self.total = [], {}

    def __call__(self, arm, task, workspace, *, max_usd, timeout_s, jev_home, resume=None, prompt=None, **kw):
        self.calls.append((arm, task["id"], resume, prompt))
        self.total[arm] = self.total.get(arm, 0.0) + 0.10
        return {"status": "done", "cost_usd": self.total[arm], "models": {"claude-x": self.total[arm]},
                "result": "ok", "wall_ms": 1000, "session_id": f"sessao-{arm}",
                "tokens": {"input": 1, "output": 2, "cache_read": 30, "cache_write_1h": 40}}


def test_in_session_mode_each_arm_continues_one_session_with_a_follow_up(tmp_path):
    arms = SessionArms()

    run(tmp_path, arms, arms=("jev-v1", "jev-v2"), session=True)

    v1 = [(task, resume, prompt) for arm, task, resume, prompt in arms.calls if arm == "jev-v1"]
    assert [resume for _, resume, _ in v1] == [None] + ["sessao-jev-v1"] * 5  # 3 tarefas, cada uma com seguimento
    assert [prompt for _, _, prompt in v1][1] == pilot_run.FOLLOW_UP
    [p] = pilot.read_all(home=tmp_path / "home")
    row = next(t for t in p["tasks"] if t["arm"] == "jev-v1" and t["task"] == "T3")
    assert row["cost_usd"] == pytest.approx(0.20)  # as duas chamadas da tarefa, não o total cumulativo
    assert row["models"] == {"claude-x": pytest.approx(0.20)}
    assert row["wall_ms"] == 2000
    assert row["tokens"] == {"input": 2, "output": 4, "cache_read": 60, "cache_write_1h": 80}
    assert p["meta"]["session"] is True


def test_a_text_task_gets_no_follow_up_because_its_answer_is_the_document(tmp_path):
    arms = SessionArms()
    seed = tmp_path / "seed"
    seed.mkdir()
    text = [{"id": "T1", "title": "Glossário", "kind": "text", "prompt": "escreve", "output_file": "docs/x.md"}]

    pilot_run.run_pilot(text, pilot_id="p1", seed=seed, inject_root=tmp_path / "i", acceptance_root=tmp_path / "a",
                        home=tmp_path / "home", run_arm=arms, git=False, arms=("jev-v1", "jev-v2"), session=True,
                        accept=lambda *a, **k: {"ok": True, "passed": 1, "failed": 0})

    assert [(arm, prompt) for arm, _, _, prompt in arms.calls] == [("jev-v1", None), ("jev-v2", None)]


def test_the_judge_compares_the_two_named_arms(tmp_path):
    prompts = []

    def run_judge(prompt):
        prompts.append(prompt)
        winner = "A" if len(prompts) == 1 else "B"  # as duas passagens dão o mesmo braço
        return {"status": "done", "cost_usd": 0.0, "result": "",
                "structured": {"criteria": [{"id": "legibilidade", "winner": winner, "reason": "r"}]}}

    run(tmp_path, FakeArms(), arms=("jev-v1", "jev-v2"), judge=True, run_judge=run_judge)

    [p] = pilot.read_all(home=tmp_path / "home")
    legibilidade = next(c for c in p["judge"]["criteria"] if c["id"] == "legibilidade")
    assert legibilidade["result"] == "jev-v1"


# --- sessão contínua: o teto e o custo de uma chamada cortada são só dessa chamada ---------------------

def test_in_session_mode_the_budget_cap_is_per_call(tmp_path):
    # O --max-budget-usd conta só a chamada atual, também com --resume (o total_cost_usd é que é cumulativo)
    arms = SessionArms()
    caps = []
    original = arms.__call__

    def capturing(arm, task, workspace, **kw):
        caps.append(kw["max_usd"])
        return original(arm, task, workspace, **kw)

    run(tmp_path, capturing, arms=("jev-v1", "jev-v2"), session=True, max_usd_task=1.5, max_usd_total=9.0)

    assert max(caps) <= 1.5


def test_partial_cost_of_a_resumed_session_counts_only_this_call(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    usage = {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 10738,
             "cache_creation_input_tokens": 14262,
             "cache_creation": {"ephemeral_1h_input_tokens": 14262, "ephemeral_5m_input_tokens": 0}}

    def msg(i, ts):
        return {"type": "assistant", "cwd": str(workspace), "timestamp": ts,
                "message": {"id": f"msg_{i}", "model": "claude-sonnet-5-5", "usage": usage}}

    _transcript(tmp_path / "projects" / "x", workspace, [
        msg(1, "2026-10-11T20:00:00Z"),  # de uma tarefa anterior
        {"type": "cost-state", "totalCostUSD": 5.0},  # o total cumulativo da sessão: não serve aqui
        msg(2, "2026-10-11T21:00:00Z"), msg(2, "2026-10-11T21:00:00Z"),  # desta chamada, em 2 linhas
    ], name="sessao-1")
    since = datetime(2026, 10, 11, 20, 30, tzinfo=timezone.utc).timestamp()

    cost = pilot_run.partial_cost(workspace, since=since, projects_dir=tmp_path / "projects", session="sessao-1")

    assert cost == pytest.approx(0.0592396)  # só a mensagem desta chamada, uma vez


def test_a_call_cut_in_session_mode_costs_only_its_own_messages(tmp_path):
    class CutArms(SessionArms):
        def __call__(self, arm, task, workspace, *, resume=None, prompt=None, **kw):
            if task["id"] == "T2" and prompt is None:  # o pedido da T2 é cortado pelo envelope
                self.calls.append((arm, task["id"], resume, prompt))
                return {"status": "timeout", "cost_usd": 0.07, "models": {}, "result": "", "wall_ms": 1000,
                        "session_id": resume, "error": "cortada"}
            return super().__call__(arm, task, workspace, resume=resume, prompt=prompt, **kw)

    run(tmp_path, CutArms(), arms=("jev-v1", "jev-v2"), session=True)

    [p] = pilot.read_all(home=tmp_path / "home")
    rows = {t["task"]: t for t in p["tasks"] if t["arm"] == "jev-v1"}
    assert rows["T2"]["cost_usd"] == pytest.approx(0.07) and rows["T2"]["status"] == "timeout"
    # a chamada morta não grava o total: a seguinte continua do total de antes dela
    assert rows["T3"]["cost_usd"] == pytest.approx(0.20)


# --- corrida final da v3: três braços, pytest em todas as formas, o mecanismo por chamada, juiz por tarefa ---

def test_three_arms_rotate_who_goes_first(tmp_path):
    arms = FakeArms()

    run(tmp_path, arms, arms=("jev-v1", "jev-v2", "jev-v3"))

    firsts = [arms.order[i][1] for i in (0, 3, 6)]
    assert firsts == ["jev-v1", "jev-v2", "jev-v3"]  # cada braço é o primeiro numa tarefa


def test_the_v3_arm_runs_the_mod_with_its_policy(tmp_path):
    assert "--plugin-dir" in pilot_run.arm_argv("jev-v3", max_usd=1.0)
    assert pilot_run.arm_env("jev-v3", jev_home=tmp_path)["JEV_POLICY"] == "v3"


def test_the_tests_can_run_in_any_usual_form():
    # no calc o agente correu `python -m pytest` e foi recusado: os seguimentos nunca correram testes
    argv = pilot_run.arm_argv("standard", max_usd=1.0)
    for rule in ("Bash(uv run pytest:*)", "Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)", "Bash(pytest:*)",
                 "Bash(uv run python -m pytest:*)"):
        assert rule in argv


def test_each_call_keeps_its_model_and_tokens(tmp_path):
    run(tmp_path, SessionArms(), arms=("jev-v1", "jev-v2"), session=True)

    [p] = pilot.read_all(home=tmp_path / "home")
    row = next(t for t in p["tasks"] if t["arm"] == "jev-v1" and t["task"] == "T2")
    assert row["call_models"] == ["claude-x", "claude-x"]
    assert len(row["call_tokens"]) == 2 and row["call_tokens"][1]["cache_write_1h"] == 40


@pytest.mark.parametrize(("votes", "result"), [
    (["a", "a", "a", "b"], "a"), (["b", "b", "b", "tie"], "b"), (["a", "a", "b", "b"], "inconclusive"),
    (["a", "a", "tie", "tie"], "inconclusive"), (["tie", "tie", "tie", "a"], "tie"),
])
def test_a_panel_result_needs_three_of_four_votes(votes, result):
    assert pilot_run.panel_result(votes) == result


class ModelArms(FakeArms):
    """Cada braço do mod regista a decisão do Jev com o modelo dado por (braço, tarefa) e escreve um ficheiro."""

    def __init__(self, models):
        super().__init__()
        self.models = models

    def __call__(self, arm, task, workspace, *, max_usd, timeout_s, jev_home, **kw):
        self.order.append((task["id"], arm))
        (workspace / "fatura" / f"{task['id'].lower()}.py").write_text(f"# {task['id']} por {arm}\n")
        ledger.append(ledger.make_record(
            task=task["prompt"], decision={"model": self.models[(arm, task["id"])], "effort": "medium",
                                           "rationale": "Jev: x", "router_cost_usd": 0.0},
            jev={"cost_usd": 0.01}, standard={"kind": "estimated", "cost_usd": 0.05}), home=jev_home)
        return {"status": "done", "cost_usd": 0.1, "wall_ms": 1000, "models": {"claude-x": 0.1}, "result": "ok"}


def test_the_task_judge_only_judges_tasks_where_the_main_model_differs(tmp_path):
    models = {("jev-v1", "T1"): "sonnet", ("jev-v3", "T1"): "sonnet",
              ("jev-v1", "T2"): "sonnet", ("jev-v3", "T2"): "opus",
              ("jev-v1", "T3"): "opus", ("jev-v3", "T3"): "opus"}
    calls = []

    def run_judge(prompt, model="opus"):
        calls.append((model, prompt))
        a_is_v3 = prompt.index("por jev-v3") < prompt.index("por jev-v1")
        winner = "A" if a_is_v3 else "B"  # os quatro votos dão a v3 na legibilidade
        return {"status": "done", "cost_usd": 0.01, "result": "",
                "structured": {"criteria": [{"id": "legibilidade", "winner": winner, "reason": "r"}]}}

    seed = tmp_path / "seed"
    (seed / "fatura").mkdir(parents=True)
    (seed / "fatura" / "__init__.py").write_text("")
    pilot_run.run_pilot(TASKS, pilot_id="p1", seed=seed, inject_root=tmp_path / "i", acceptance_root=tmp_path / "a",
                        home=tmp_path / "home", run_arm=ModelArms(models), git=True, arms=("jev-v1", "jev-v3"),
                        judge=True, judge_target="jev-v3", run_judge=run_judge,
                        accept=lambda *a, **k: {"ok": True, "passed": 1, "failed": 0})

    assert sorted(m for m, _ in calls) == ["opus", "opus", "sonnet", "sonnet"]  # só a T2, com o painel inteiro
    assert all("t2.py" in p and "t1.py" not in p and "t3.py" not in p for _, p in calls)  # só o diff da T2
    [p] = pilot.read_all(home=tmp_path / "home")
    [res] = p["task_judge"]["results"]
    assert res["pair"] == ["jev-v3", "jev-v1"] and res["task"] == "T2" and res["models"] == ["opus", "sonnet"]
    assert next(c for c in res["criteria"] if c["id"] == "legibilidade")["result"] == "jev-v3"
