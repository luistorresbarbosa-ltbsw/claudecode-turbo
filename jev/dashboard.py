"""Dashboard local do JEV: standard vs JEV, lido do ledger.

Serve só em 127.0.0.1 e só com a stdlib:

    GET /            dashboard/index.html
    GET /api/ledger  {"records": [...], "summary": {...}}, relido a cada pedido
    GET /api/pilots  {"pilots": [...]}, os pilotos do mais recente para o mais antigo, relidos a cada pedido

O ledger e os pilotos são contratos partilhados (ver jev/ledger.py e jev/pilot.py). Aqui só se lê.
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from jev import ledger, pilot

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
INDEX_HTML = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"

# O ledger tem o texto das tarefas. Com DNS rebinding, uma página alheia pode apontar o
# seu domínio para 127.0.0.1 e ler o ledger no browser do utilizador; o que a denuncia é
# o cabeçalho Host, por isso só aceitamos os nomes que o próprio utilizador digita.
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost"}


def _ledger_payload() -> dict:
    records = ledger.read_all()
    return {"records": records, "summary": ledger.summarize(records)}


class Handler(BaseHTTPRequestHandler):
    server_version = "jev-dashboard"

    def do_GET(self) -> None:
        if not self._host_is_local():
            return self._reply(HTTPStatus.FORBIDDEN, "Host não permitido.")
        route = self.path.partition("?")[0]
        if route == "/":
            self._send_page()
        elif route == "/api/ledger":
            self._send_json(_ledger_payload)
        elif route == "/api/pilots":
            self._send_json(lambda: {"pilots": pilot.read_all()})
        else:
            self._reply(HTTPStatus.NOT_FOUND, "Não encontrado.")

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
