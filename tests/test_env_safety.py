"""Os modelos Anthropic correm sempre pela subscrição, nunca por uma API key apanhada pelo caminho."""
import os
import subprocess
import sys

from jev import dispatch
from jev.router import Decision

from tests.test_dispatch import SUCCESS, fake_run


def test_importing_jev_does_not_load_the_dotenv_of_the_current_folder(tmp_path):
    # O mod corre o JEV na pasta do projeto do utilizador; o .env desse projeto não é nosso.
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-do-projeto\n")
    env = {k: v for k, v in os.environ.items() if k not in ("LITELLM_MODE", "ANTHROPIC_API_KEY")}

    out = subprocess.run(
        [sys.executable, "-c", "import jev.router, os; print(os.environ.get('ANTHROPIC_API_KEY'))"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    )

    assert out.stdout.strip() == "None"


def test_child_claude_never_receives_an_anthropic_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-x")
    run = fake_run(SUCCESS)

    dispatch.run_claude("x", Decision(runner="anthropic", model="haiku", effort="low", rationale="r"),
                        edits=False, max_usd=0.5, run=run)

    child_env = run.calls[0]["env"]
    assert "ANTHROPIC_API_KEY" not in child_env and "ANTHROPIC_AUTH_TOKEN" not in child_env
