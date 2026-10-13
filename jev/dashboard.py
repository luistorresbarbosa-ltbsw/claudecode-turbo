"""Dashboard local do JEV: standard vs JEV, lido do ledger.

Serve só em 127.0.0.1 e só com a stdlib:

    GET /            dashboard/index.html
    GET /api/ledger  {"records": [...], "summary": {...}}, relido a cada pedido: o uso real; com
                     ?source=<id> (de /api/sources) ou ?source=tudo, essa origem ou todas, cada registo
                     com o seu "source"
    GET /api/sources {"sources": [...]}: o uso real e o ledger de cada braço de cada piloto
    GET /api/live    {"live": [...]}: os turnos em curso (o Jev já decidiu, o turno ainda não acabou)
    GET /api/events  um stream (text/event-stream) que diz "change" quando um ledger, um turno em curso ou um
                     piloto muda, para a página reler logo em vez de esperar pela próxima leitura
    GET /api/pilots  {"pilots": [...]}, os pilotos do mais recente para o mais antigo, relidos a cada pedido

O ledger e os pilotos são contratos partilhados (ver jev/ledger.py e jev/pilot.py). Aqui só se lê.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jev import ledger, pilot

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
# Instalado (uv tool install), a página vem dentro do pacote; no repositório, de dashboard/
_PACKAGED_HTML = Path(__file__).resolve().parent / "dashboard_index.html"
INDEX_HTML = (_PACKAGED_HTML if _PACKAGED_HTML.is_file()
              else Path(__file__).resolve().parent.parent / "dashboard" / "index.html")

# O ledger tem o texto das tarefas. Com DNS rebinding, uma página alheia pode apontar o
# seu domínio para 127.0.0.1 e ler o ledger no browser do utilizador; o que a denuncia é
# o cabeçalho Host, por isso só aceitamos os nomes que o próprio utilizador digita.
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost"}
EVENTS_CHECK_S, EVENTS_PING_S = 0.5, 15.0


def _ledger_payload() -> dict:
    records = ledger.read_all()
    return {"records": records, "summary": ledger.summarize(records)}


def _sources() -> list[dict]:
    """O uso real (o ledger do JEV_HOME) e o ledger de cada braço dos pilotos, onde o mod regista cada turno;
    os pilotos do mais recente para o mais antigo (o id acaba em AAAAMMDD-HHMM)."""
    out = [{"id": "uso", "label": "Uso real", "kind": "uso", "home": ledger.ledger_path().parent}]
    root = pilot.pilots_dir()
    arms = sorted(root.glob("*/*-home/ledger.jsonl"), key=lambda p: (p.parent.parent.name[-13:], p.parent.name),
                  reverse=True) if root.is_dir() else []
    for path in arms:
        pilot_id, arm = path.parent.parent.name, path.parent.name.removesuffix("-home")
        out.append({"id": f"{pilot_id}/{arm}", "label": f"{pilot_id} · {arm}", "kind": "piloto", "home": path.parent,
                    "policy": _arm_policy(arm)})
    return out


def _arm_policy(arm: str) -> str | None:
    """A versão que um braço de piloto correu: jev-vN; "jev" (as corridas contra o standard) era a v1."""
    if arm.startswith("jev-v"):
        return arm.removeprefix("jev-")
    return "v1" if arm == "jev" else None


def _sources_payload() -> dict:
    rows = []
    for src in _sources():
        records = ledger.read_all(home=src["home"])
        rows.append({"id": src["id"], "label": src["label"], "kind": src["kind"], "records": len(records),
                     "jev_usd": round(sum(r["jev"]["cost_usd"] for r in records), 9)})
    return {"sources": rows}


def _live_payload() -> dict:
    live = []
    for src in _sources():
        tag = {"id": src["id"], "kind": src["kind"], "label": src["label"]}
        live += [{**entry, "source": tag} for entry in ledger.read_live(home=src["home"])]
    return {"live": sorted(live, key=lambda e: e["ts"])}


def _signature() -> tuple:
    """O que, ao mudar, a página deve reler: cada ledger, cada turno em curso e as linhas dos pilotos."""
    paths = []
    for src in _sources():
        paths.append(src["home"] / "ledger.jsonl")
        folder = src["home"] / "live"
        if folder.is_dir():
            paths += sorted(folder.glob("*.json"))
    root = pilot.pilots_dir()
    if root.is_dir():
        paths += sorted(root.glob("*.jsonl"))
    sig = []
    for path in paths:
        try:
            st = path.stat()
            sig.append((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((str(path), None, None))
    return tuple(sig)


def _source_payload(wanted: str) -> dict:
    """Os registos de uma origem (ou de todas, "tudo"), cada um com o "source" de onde veio, por ordem de tempo.
    O id escolhe-se entre as origens conhecidas, nunca é um caminho."""
    chosen = [s for s in _sources() if wanted in ("tudo", s["id"])]
    records = []
    for src in chosen:
        tag = {"id": src["id"], "kind": src["kind"], "label": src["label"]}
        if src.get("policy"):
            tag["policy"] = src["policy"]
        records += [{**r, "source": tag} for r in ledger.read_all(home=src["home"])]
    records.sort(key=lambda r: str(r.get("ts") or ""))
    return {"records": records, "summary": ledger.summarize(records)}


class Handler(BaseHTTPRequestHandler):
    server_version = "jev-dashboard"

    def do_GET(self) -> None:
        if not self._host_is_local():
            return self._reply(HTTPStatus.FORBIDDEN, "Host não permitido.")
        route, _, query = self.path.partition("?")
        source = (parse_qs(query).get("source") or [""])[0]
        if route == "/":
            self._send_page()
        elif route == "/api/ledger" and source in ("", "uso"):
            self._send_json(_ledger_payload)
        elif route == "/api/ledger":
            if source != "tudo" and source not in {s["id"] for s in _sources()}:
                return self._reply(HTTPStatus.NOT_FOUND, json.dumps({"error": f"origem desconhecida: {source}"}),
                                   "application/json; charset=utf-8")
            self._send_json(lambda: _source_payload(source))
        elif route == "/api/sources":
            self._send_json(_sources_payload)
        elif route == "/api/pilots":
            self._send_json(lambda: {"pilots": pilot.read_all()})
        elif route == "/api/live":
            self._send_json(_live_payload)
        elif route == "/api/events":
            self._stream_events()
        else:
            self._reply(HTTPStatus.NOT_FOUND, "Não encontrado.")

    def _stream_events(self) -> None:
        """Diz "change" assim que alguma coisa que a página mostra muda (verifica de meio em meio segundo) e manda
        um sinal de vida de 15 em 15 s; acaba quando a página fecha a ligação."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(b"event: ready\ndata: {}\n\n")
            self.wfile.flush()
            last, quiet = _signature(), 0.0
            while True:
                time.sleep(EVENTS_CHECK_S)
                now = _signature()
                if now != last:
                    last, quiet = now, 0.0
                    self.wfile.write(b"event: change\ndata: {}\n\n")
                    self.wfile.flush()
                else:
                    quiet += EVENTS_CHECK_S
                    if quiet >= EVENTS_PING_S:
                        quiet = 0.0
                        self.wfile.write(b": vivo\n\n")
                        self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return  # a página fechou: acabou

    def _host_is_local(self) -> bool:
        host = self.headers.get("Host")
        if host is None:
            return True
        try:
            return urlsplit(f"//{host}").hostname in LOCAL_HOSTNAMES
        except ValueError:
            return False

    def _send_page(self) -> None:
        try:
            html = INDEX_HTML.read_bytes()
        except OSError:
            return self._reply(HTTPStatus.INTERNAL_SERVER_ERROR,
                               f"Não encontrei a página do dashboard em {INDEX_HTML}")
        self._reply(HTTPStatus.OK, html, "text/html; charset=utf-8")

    def _send_json(self, build) -> None:
        try:
            payload, status = build(), HTTPStatus.OK
        except (OSError, ValueError) as exc:  # sem permissão, um diretório onde devia haver um ficheiro...
            payload, status = {"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR
        self._reply(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def _reply(self, status: HTTPStatus, body: str | bytes,
               content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def log_request(self, code="-", size="-") -> None:
        # A página pergunta de 5 em 5 s: registar só os erros, senão o terminal é ruído.
        if isinstance(code, int) and code < 400:
            return
        super().log_request(code, size)


def make_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Servidor ligado só a 127.0.0.1. Com port=0 o sistema escolhe um porto livre."""
    return ThreadingHTTPServer((HOST, port), Handler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jev-dashboard",
        description="Dashboard local do JEV: o que custa o Claude Code standard vs com JEV.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"porto onde servir (por omissão {DEFAULT_PORT})")
    parser.add_argument("--open", action="store_true", help="abre o dashboard no browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        server = make_server(args.port)
    except OSError as exc:
        print(f"Não consegui usar o porto {args.port} ({exc.strerror or exc}). "
              "Escolhe outro com --port.", file=sys.stderr)
        return 1

    url = f"http://{HOST}:{server.server_port}/"
    print(f"Dashboard do JEV em {url}", flush=True)
    print(f"A ler {ledger.ledger_path()}. Ctrl-C para parar.", flush=True)
    try:
        if args.open:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard parado.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
