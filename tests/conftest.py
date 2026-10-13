import ipaddress
import socket

import pytest

_real_connect = socket.socket.connect


def _is_public(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_global
    except ValueError:  # um nome em vez de um IP
        return host != "localhost"


@pytest.fixture(autouse=True)
def no_internet(monkeypatch):
    """Os testes nunca vão à internet (o litellm carrega o .env sozinho, por isso a chave está lá).
    Loopback e rede local continuam acessíveis: os testes do dashboard precisam deles."""
    def guarded(self, address):
        if isinstance(address, tuple) and _is_public(address[0]):
            raise RuntimeError(f"um teste tentou ir à internet: {address!r}")
        return _real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def jev_defaults(monkeypatch):
    """Os testes valem com os defeitos (v3, pool Anthropic), seja qual for o JEV_POLICY/JEV_POOL de quem os corre.
    Os que querem outra política fixam-na com monkeypatch.setenv."""
    monkeypatch.delenv("JEV_POLICY", raising=False)
    monkeypatch.delenv("JEV_POOL", raising=False)
