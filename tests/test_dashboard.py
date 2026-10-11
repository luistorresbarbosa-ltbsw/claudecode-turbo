"""Dashboard local: serve a página e o ledger em JSON, só em 127.0.0.1.

Os testes sobem um servidor REAL num porto efémero (porto 0), numa thread, com
JEV_HOME a apontar para uma pasta temporária. Nada de mocks do http.server.
Cada docstring diz que alteração ao código de produção faria o teste falhar.
"""
import _thread
import http.client
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pytest

from jev import dashboard, ledger, pilot

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "dashboard" / "index.html"


# ---------------------------------------------------------------- helpers

@dataclass
class Reply:
    status: int
    headers: http.client.HTTPMessage
    body: bytes

    def json(self):
        return json.loads(self.body)


def get(server, path, headers=None) -> Reply:
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        return Reply(resp.status, resp.headers, resp.read())
    finally:
        conn.close()


def _rec(task="t", std=0.30, jev=0.05, *, router_error=None, fallback=None, ok=True):
    return ledger.make_record(
        task=task,
        decision={"runner": "anthropic", "model": "haiku", "effort": "low",
                  "rationale": "trivial", "router_model": "heuristic",
                  "router_cost_usd": 0.0, "router_error": router_error},
        jev={"model_id": "claude-haiku-4-5", "cost_usd": jev, "tokens": None,
             "duration_ms": 100, "ok": ok, "fallback": fallback},
        standard={"kind": "estimated", "model_id": "claude-opus-5-5", "effort": "xhigh",
                  "cost_usd": std, "tokens": None, "duration_ms": None},
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _lan_ip() -> str | None:
    """IP da interface principal que não é o loopback, ou None se a máquina não tem rota."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: o connect de UDP não envia nada
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith("127.") else ip


def _poll_api(port, *, alive=lambda: True, timeout=15) -> dict:
    """Pede /api/ledger até o servidor responder; devolve o JSON."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive():
            raise AssertionError("o processo do dashboard terminou antes de responder")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/ledger")
            return json.loads(conn.getresponse().read())
        except OSError:
            time.sleep(0.05)
        finally:
            conn.close()
    raise AssertionError(f"o dashboard não respondeu no porto {port} a tempo")


@pytest.fixture
def jev_home(tmp_path, monkeypatch):
    """Pasta do ledger. Ainda não existe: cada teste cria o que precisa."""
    home = tmp_path / "jev-home"
    monkeypatch.setenv("JEV_HOME", str(home))
    return home


@pytest.fixture
def server(jev_home):
    srv = dashboard.make_server(port=0)
    # poll_interval curto: o shutdown() espera por ele e, a 0,5 s por teste, a suite arrastava-se.
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


# ------------------------------------------------------------- /api/ledger

def test_api_returns_every_record_untouched_plus_the_summary(server, jev_home):
    """Falha se o handler filtrar ou reescrever campos (abs() na poupança, deitar fora
    fallback/router_error) ou devolver um resumo que não é o do ledger."""
    ganhou = _rec(task="primeira", std=0.30, jev=0.05)
    perdeu = _rec(task="segunda", std=0.10, jev=0.40, router_error="429 rate limit",
                  fallback={"from": "google/gemma:free", "reason": "timeout"}, ok=False)
    ledger.append(ganhou, home=jev_home)
    ledger.append(perdeu, home=jev_home)

    reply = get(server, "/api/ledger")

    assert reply.status == 200
    assert reply.headers["Content-Type"].startswith("application/json")
    body = reply.json()
    assert body["records"] == [ganhou, perdeu]
    # À mão: a segunda falhou, por isso o standard só conta a primeira (0.30); o JEV conta
    # tudo o que gastou (0.05 + 0.40 = 0.45); 0.30 - 0.45 = -0.15, ou -50%.
    assert body["summary"] == {
        "tasks": 2,
        "failed": 1,
        "standard_usd": pytest.approx(0.30),
        "jev_usd": pytest.approx(0.45),
        "saved_usd": pytest.approx(-0.15),
        "saved_pct": pytest.approx(-50.0),
        "speed": {"jev_median_ms": 100, "standard_median_ms": None, "standard_measured": 0},
    }


def test_record_appended_after_startup_shows_up_without_restart(server, jev_home):
    """Falha se o ledger for lido uma só vez (no arranque) ou ficar em cache."""
    assert get(server, "/api/ledger").json()["summary"]["tasks"] == 0

    ledger.append(_rec(task="chegou depois"), home=jev_home)

    body = get(server, "/api/ledger").json()
    assert [r["task"] for r in body["records"]] == ["chegou depois"]
    assert body["summary"]["tasks"] == 1


def test_missing_ledger_gives_no_records_and_a_zero_summary(server, jev_home):
    """Falha se um ledger inexistente (primeira utilização) der 500 ou um resumo nulo."""
    assert not jev_home.exists()

    reply = get(server, "/api/ledger")

    assert reply.status == 200
    assert reply.json() == {
        "records": [],
        "summary": {"tasks": 0, "failed": 0, "standard_usd": 0.0, "jev_usd": 0.0,
                    "saved_usd": 0.0, "saved_pct": 0.0, "speed": {"jev_median_ms": None, "standard_median_ms": None, "standard_measured": 0}},
    }


def test_unreadable_ledger_is_a_json_500_not_a_dropped_connection(server, jev_home):
    """Falha se um ledger ilegível rebentar a thread do pedido: a página ficava sem resposta
    e sem maneira de dizer ao utilizador o que se passa. (Bytes que não são UTF-8 já não
    servem de gatilho: o ledger salta essas linhas. Uma pasta no lugar do ficheiro serve.)"""
    jev_home.mkdir()
    (jev_home / "ledger.jsonl").mkdir()

    reply = get(server, "/api/ledger")

    assert reply.status == 500
    assert reply.headers["Content-Type"].startswith("application/json")
    assert "error" in reply.json()


@pytest.mark.parametrize("path", ["/api/ledger", "/api/pilots"])
def test_api_responses_are_never_cached(server, path):
    """Falha se o browser ou um proxy puderem reutilizar uma resposta: os números
    ficariam desatualizados depois de uma tarefa nova."""
    assert "no-store" in get(server, path).headers["Cache-Control"]


# ---------------------------------------------------------------- routing

@pytest.mark.parametrize("path", [
    "/nope",
    "/api",
    "/api/ledger/",
    "/api/pilots/",
    "/index.html",
    "/../pyproject.toml",
    "/dashboard/demo/ledger.jsonl",
])
def test_every_other_path_is_404(server, path):
    """Falha se existir um catch-all que sirva o index, ou se o servidor passar a servir
    ficheiros do disco (o ledger tem o texto das tarefas do utilizador)."""
    assert get(server, path).status == 404


@pytest.mark.parametrize("path", ["/?x=1", "/api/ledger?_=1760000000", "/api/pilots?_=1760000000"])
def test_query_string_does_not_change_routing(server, path):
    """Falha se um cache-buster (?_=...) transformar rotas válidas em 404."""
    assert get(server, path).status == 200


# ------------------------------------------------------------ the page (/)

def test_root_serves_the_dashboard_page(server):
    """Falha se / devolver outra coisa que não o dashboard/index.html, ou o tipo errado."""
    reply = get(server, "/")

    assert reply.status == 200
    assert reply.headers["Content-Type"].startswith("text/html")
    assert reply.body == INDEX_HTML.read_bytes()


def test_root_finds_the_page_even_when_cwd_is_elsewhere(server, tmp_path, monkeypatch):
    """Falha se o caminho do index for relativo ao cwd em vez de ao pacote. A isca no
    cwd apanha também uma versão que 'funciona' por acaso quando se corre da raiz."""
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "index.html").write_text("ISCA", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    reply = get(server, "/")

    assert reply.status == 200
    assert reply.body == INDEX_HTML.read_bytes()
    assert b"ISCA" not in reply.body


def test_missing_page_is_a_clear_error_not_a_dropped_connection(server, tmp_path, monkeypatch):
    """Falha se um index em falta (ex.: instalação sem a pasta dashboard/) rebentar a
    thread do pedido e o browser ficar sem resposta nenhuma."""
    monkeypatch.setattr(dashboard, "INDEX_HTML", tmp_path / "em-falta.html")

    reply = get(server, "/")

    assert reply.status == 500
    assert "em-falta.html" in reply.body.decode("utf-8")


# ------------------------------------------------------- local-only access

def test_server_binds_to_127_0_0_1(server):
    """Falha se o bind passar a '' ou 0.0.0.0."""
    assert server.server_address[0] == "127.0.0.1"


def test_server_does_not_answer_on_the_lan_address(server):
    """O mesmo, mas pelo comportamento: o ledger não pode ser lido por outra máquina."""
    lan_ip = _lan_ip()
    if lan_ip is None:
        pytest.skip("esta máquina não tem interface de rede além do loopback")

    with pytest.raises((ConnectionRefusedError, TimeoutError)):
        socket.create_connection((lan_ip, server.server_port), timeout=2).close()


@pytest.mark.parametrize("path", ["/", "/api/ledger", "/api/pilots"])
@pytest.mark.parametrize("host, allowed", [
    ("127.0.0.1:{port}", True),
    ("localhost:{port}", True),
    ("evil.example", False),
    ("evil.example:{port}", False),
    ("127.0.0.1.evil.example", False),   # um startswith('127.0.0.1') deixava passar
    ("localhost.evil.example", False),
])
def test_requests_with_a_foreign_host_header_are_refused(server, path, host, allowed):
    """DNS rebinding: uma página maliciosa pode apontar o seu domínio para 127.0.0.1 e
    ler o ledger no browser do utilizador. Falha se o Host deixar de ser validado."""
    reply = get(server, path, headers={"Host": host.format(port=server.server_port)})

    assert reply.status == (200 if allowed else 403)


# ------------------------------------------------------------- /api/pilots

def _pilot_meta(pid="p1", started="2026-10-11T12:00:00Z"):
    return {"v": 1, "type": "meta", "pilot": pid, "started": started,
            "tasks": [{"id": "T1", "title": "Primeira", "kind": "code"}],
            "max_usd_per_task": 1.0, "max_usd_total": 9.0}


def _pilot_task(pid, arm, cost, ok=True):
    return {"v": 1, "type": "task", "pilot": pid, "arm": arm, "task": "T1", "title": "Primeira", "kind": "code",
            "status": "done", "cost_usd": cost, "wall_ms": 1500, "models": {"claude-sonnet-5-5": cost},
            "jev": {"decisions": [{"model": "haiku", "effort": "low", "rationale": "Jev: x", "scope": "agent"}],
                    "decision_cost_usd": 0.001} if arm == "jev" else None,
            "acceptance": {"ok": ok, "passed": 1 if ok else 0, "failed": 0 if ok else 1}}


def test_api_pilots_returns_every_pilot_newest_first_with_all_their_rows(server, jev_home):
    """Falha se o endpoint filtrar ou reescrever linhas (a decisão do Jev, o scope do subagente, os
    modelos cobrados, a aceitação) ou devolver os pilotos pela ordem errada."""
    standard, jev = _pilot_task("novo", "standard", 0.30), _pilot_task("novo", "jev", 0.05, ok=False)
    end = {"v": 1, "type": "end", "pilot": "novo", "finished": "2026-10-11T10:00:00Z", "stopped": "orçamento total"}
    pilot.append(_pilot_meta("velho", "2026-10-10T09:00:00Z"), home=jev_home)
    pilot.append(_pilot_meta("novo", "2026-10-11T09:00:00Z"), home=jev_home)
    for row in (standard, jev, end):
        pilot.append(row, home=jev_home)

    reply = get(server, "/api/pilots")

    assert reply.status == 200
    assert reply.headers["Content-Type"].startswith("application/json")
    novo, velho = reply.json()["pilots"]
    assert (novo["id"], velho["id"]) == ("novo", "velho")
    assert novo["tasks"] == [standard, jev]
    assert novo["end"] == end
    assert velho["tasks"] == [] and velho["end"] is None  # ainda a correr: sem linha end


def test_pilot_rows_written_while_the_server_runs_show_up_without_restart(server, jev_home):
    """Falha se os pilotos forem lidos uma só vez: o dashboard é visto a encher-se em direto."""
    pilot.append(_pilot_meta(), home=jev_home)
    assert get(server, "/api/pilots").json()["pilots"][0]["tasks"] == []

    pilot.append(_pilot_task("p1", "standard", 0.30), home=jev_home)
    pilot.append({"v": 1, "type": "end", "pilot": "p1", "finished": "2026-10-11T10:00:00Z", "stopped": None}, home=jev_home)

    [p] = get(server, "/api/pilots").json()["pilots"]
    assert [t["arm"] for t in p["tasks"]] == ["standard"]
    assert p["end"]["finished"] == "2026-10-11T10:00:00Z"


def test_no_pilots_gives_an_empty_list(server, jev_home):
    """Falha se a primeira utilização (sem pasta pilots/) der 500 ou null."""
    assert not jev_home.exists()

    reply = get(server, "/api/pilots")

    assert reply.status == 200
    assert reply.json() == {"pilots": []}


def test_unreadable_pilot_store_is_a_json_500_not_a_dropped_connection(server, jev_home):
    """Falha se um registo ilegível rebentar a thread do pedido: a vista Piloto ficava sem
    resposta e sem dizer porquê. (Uma pasta com nome de .jsonl já não serve: o read_all salta-a.
    Um ficheiro sem permissão de leitura serve.)"""
    store = jev_home / "pilots" / "partido.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text('{"v": 1, "type": "meta", "pilot": "p", "started": "x", "tasks": []}\n')
    store.chmod(0)
    try:
        reply = get(server, "/api/pilots")
    finally:
        store.chmod(0o600)

    assert reply.status == 500
    assert reply.headers["Content-Type"].startswith("application/json")
    assert "error" in reply.json()


# --------------------------------------------------------------------- CLI

@pytest.mark.parametrize("argv, port, open_browser", [
    ([], 8787, False),
    (["--port", "9001"], 9001, False),
    (["--open"], 8787, True),
    (["--port", "9001", "--open"], 9001, True),
])
def test_cli_flags(argv, port, open_browser):
    """Falha se o porto por omissão deixar de ser 8787 ou as flags mudarem de nome."""
    args = dashboard.parse_args(argv)

    assert (args.port, args.open) == (port, open_browser)


@pytest.mark.parametrize("open_flag", [True, False], ids=["com --open", "sem --open"])
def test_cli_serves_on_the_requested_port_and_opens_the_browser_only_on_request(
        tmp_path, jev_home, open_flag):
    """Processo real (python -m jev.dashboard). Falha se --port for ignorado, se o
    browser abrir sem --open, ou se --open não abrir o URL do dashboard. O BROWSER
    aponta para um script que só regista o URL: nunca se abre um browser a sério."""
    ledger.append(_rec(task="via cli"), home=jev_home)
    port = _free_port()
    opened = tmp_path / "aberto.txt"
    fake_browser = tmp_path / "fake_browser.py"
    fake_browser.write_text("import sys, pathlib\npathlib.Path(sys.argv[2]).write_text(sys.argv[1])\n")
    env = {
        **os.environ,
        "JEV_HOME": str(jev_home),
        "PYTHONPATH": str(REPO_ROOT),
        "BROWSER": " ".join([shlex.quote(sys.executable), shlex.quote(str(fake_browser)),
                             "%s", shlex.quote(str(opened))]),
    }
    argv = [sys.executable, "-m", "jev.dashboard", "--port", str(port)]
    proc = subprocess.Popen(argv + (["--open"] if open_flag else []), env=env, cwd=tmp_path,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        body = _poll_api(port, alive=lambda: proc.poll() is None)
    finally:
        proc.terminate()
        proc.communicate(timeout=10)

    assert [r["task"] for r in body["records"]] == ["via cli"]
    if open_flag:
        assert opened.read_text().startswith(f"http://127.0.0.1:{port}")
    else:
        assert not opened.exists()


def test_main_reports_a_busy_port_instead_of_a_traceback(jev_home, capsys):
    """Falha se um porto ocupado (ex.: o dashboard já está aberto noutro terminal) acabar
    num OSError por tratar em vez de uma linha a dizer qual é o porto."""
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]

        code = dashboard.main(["--port", str(port)])

    assert code == 1
    assert str(port) in capsys.readouterr().err


@pytest.mark.skipif(signal.getsignal(signal.SIGINT) is not signal.default_int_handler,
                    reason="o SIGINT deste processo não gera KeyboardInterrupt")
def test_ctrl_c_stops_main_cleanly(jev_home):
    """Falha se o Ctrl-C deixar escapar um KeyboardInterrupt com traceback."""
    port = _free_port()

    def interrupt_once_serving():
        _poll_api(port)  # só responde quando o serve_forever já está a correr
        _thread.interrupt_main()

    threading.Thread(target=interrupt_once_serving, daemon=True).start()
    try:
        code = dashboard.main(["--port", str(port)])
    except KeyboardInterrupt:
        pytest.fail("main() deixou o Ctrl-C escapar")

    assert code == 0


# ------------------------------------------------- a página não precisa de rede

class _References(HTMLParser):
    """Recolhe tudo o que uma página iria buscar fora de si: atributos src/href/..., e os
    URLs que aparecem no CSS (url(), @import) e no JS (http(s):// e ws(s)://)."""

    ATTRS = {"src", "href", "srcset", "poster", "action", "formaction", "data"}
    NAMESPACES = ("http://www.w3.org/",)  # identificam o SVG, não são pedidos de rede

    def __init__(self):
        super().__init__()
        self.found = []
        self._tag = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in self.ATTRS and value and not value.startswith(("data:", "#")):
                self.found.append(value)
        if tag in ("style", "script"):
            self._tag, self._text = tag, []

    def handle_data(self, data):
        if self._tag:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag != self._tag:
            return
        text = "".join(self._text)
        if tag == "style":
            self.found += re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", text)
            self.found += re.findall(r"@import\s+(?:url\()?['\"]?([^'\");\s]+)", text)
        else:
            self.found += re.findall(r"(?:https?|wss?)://[^\s'\"`)]+", text)
        self._tag = None

    def external(self):
        return [u for u in self.found if not u.startswith(self.NAMESPACES)]


def _external_references(html: str) -> list[str]:
    parser = _References()
    parser.feed(html)
    parser.close()
    return parser.external()


def test_page_is_self_contained_and_works_offline():
    """Falha se alguém acrescentar à página um CDN, uma fonte web, uma imagem ou um fetch
    para fora: o dashboard deixava de funcionar sem rede."""
    assert _external_references(INDEX_HTML.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("html", [
    '<script src="https://cdn.example/x.js"></script>',
    '<link rel="stylesheet" href="//fonts.example/a.css">',
    '<link rel="stylesheet" href="style.css">',
    '<img src="http://x.example/i.png">',
    '<style>@import url("https://x.example/a.css");</style>',
    '<style>.a { background: url(http://x.example/i.png) }</style>',
    '<script>fetch("https://api.example/data")</script>',
    '<script>new WebSocket("wss://x.example/live")</script>',
])
def test_the_offline_check_catches_each_way_a_page_can_go_online(html):
    """Sem isto o teste acima passava sempre: prova que o detetor sabe falhar."""
    assert _external_references(html) != []


@pytest.mark.parametrize("html", [
    '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\'%3E%3C/svg%3E">',
    '<script>document.createElementNS("http://www.w3.org/2000/svg", "svg")</script>',
    '<a href="#topo">topo</a>',
    '<script>fetch("/api/ledger")</script>',
])
def test_the_offline_check_lets_self_contained_pages_through(html):
    """O inverso: um detetor que acusa tudo também passava a ser inútil."""
    assert _external_references(html) == []
