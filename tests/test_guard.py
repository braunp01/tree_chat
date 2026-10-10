"""Req 17.5: prove the network guard works, so no test can spend AI credits by accident."""

import socket

import pytest


def test_non_loopback_connection_is_refused() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Req 17.5"):
            s.connect(("203.0.113.1", 443))
    finally:
        s.close()


def test_tests_run_on_fake_provider() -> None:
    from treechat.config import ProviderKind, load_config

    assert load_config().provider is ProviderKind.FAKE
