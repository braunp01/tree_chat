"""Test-wide guards. Req 17.5: the default suite must never reach a real LLM provider."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def _fake_provider_and_temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TREECHAT_PROVIDER", "fake")
    monkeypatch.setenv("TREECHAT_DB", str(tmp_path / "test.sqlite3"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Refuse every non-loopback connection so a misconfigured test fails instead of spending credits."""
    if request.node.get_closest_marker("live"):
        yield
        return
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise RuntimeError(f"Network access blocked in tests (Req 17.5): {address!r}")
        real_connect(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield
