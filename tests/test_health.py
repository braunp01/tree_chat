from fastapi.testclient import TestClient

from treechat.api.app import create_app


def test_health_reports_provider_without_secrets() -> None:
    body = TestClient(create_app()).get("/api/health").json()
    assert body == {"ok": True, "provider": "fake", "credentials": True}
