"""HTTP layer: auth, rate limiting, healthz, and a real MCP initialize."""
import json

from starlette.testclient import TestClient

from server.config import Settings
from server.fake_docker import FakeDockerBackend
from server.main import create_app

TOKEN = "test-token-0123456789abcdef"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "0"}},
}


def make_client(tmp_path, **overrides):
    settings = Settings(
        backend="fake", tokens=(TOKEN,), audit_log=str(tmp_path / "audit.jsonl"), **overrides
    )
    return TestClient(create_app(settings, FakeDockerBackend()), base_url="http://127.0.0.1:8000")


def test_healthz_is_public(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/healthz").json() == {"ok": True}


def test_missing_or_wrong_token_is_rejected(tmp_path):
    with make_client(tmp_path) as client:
        for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}):
            response = client.post("/mcp", json=INIT, headers={**HEADERS, **headers})
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"
            assert response.headers["www-authenticate"] == "Bearer"
    log = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert len(log) == 3 and all(e["event"] == "auth" and e["ok"] is False for e in log)
    assert TOKEN not in json.dumps(log)


def test_valid_token_can_initialize(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert "voiceops" in response.text


def test_rate_limit_returns_429_with_envelope(tmp_path):
    with make_client(tmp_path, rate_limit_per_min=3) as client:
        headers = {**HEADERS, "Authorization": f"Bearer {TOKEN}"}
        statuses = [client.post("/mcp", json=INIT, headers=headers).status_code for _ in range(5)]
        assert statuses[:3] == [200, 200, 200] and statuses[3:] == [429, 429]
        limited = client.post("/mcp", json=INIT, headers=headers)
        assert limited.json()["error"]["code"] == "RATE_LIMITED"
        assert int(limited.headers["retry-after"]) >= 1
