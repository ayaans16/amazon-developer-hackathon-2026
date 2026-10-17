import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from server.config import Settings
from server.fake_docker import FakeDockerBackend
from server.main import build_server

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "tools.schema.json"


@pytest.fixture
def contract() -> dict[str, Any]:
    return json.loads(CONTRACT.read_text())


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def make_server(audit_path: Path):
    """Build (mcp, deps, backend) on the fake Docker backend."""

    def _make(backend=None, **overrides):
        settings = Settings(
            backend="fake",
            allow_no_auth=True,
            audit_log=str(audit_path),
            restart_allowlist=overrides.pop("restart_allowlist", ("web-api", "worker", "redis")),
            restart_wait_seconds=overrides.pop("restart_wait_seconds", 0),
            **overrides,
        )
        backend = backend or FakeDockerBackend()
        mcp, deps = build_server(settings, backend)
        return mcp, deps, backend

    return _make


def call(mcp, name: str, **arguments: Any) -> dict[str, Any]:
    """Call a tool through the real MCP layer and return its structured result."""
    result = asyncio.run(mcp.call_tool(name, arguments))
    assert result.structured_content is not None, result
    return result.structured_content


def acall(mcp, name: str, **arguments: Any):
    """Async variant for tests that need several calls in one event loop / context."""

    async def _run():
        result = await mcp.call_tool(name, arguments)
        assert result.structured_content is not None, result
        return result.structured_content

    return _run()
