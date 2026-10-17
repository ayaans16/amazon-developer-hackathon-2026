import asyncio
import json

import pytest

from safety.confirmation import ConfirmationStore
from safety.policy import RestartPolicy
from server.audit import client_var
from tests.conftest import acall


def run(coro):
    return asyncio.run(coro)


def code(result):
    assert result["ok"] is False, result
    return result["error"]["code"]


async def propose(mcp, container="web-api"):
    return await acall(mcp, "propose_action", action="restart_container", container=container)


def test_propose_does_not_restart(make_server):
    mcp, _, backend = make_server()
    result = run(propose(mcp))
    assert result["ok"] and len(result["token"]) >= 16 and result["expires_in_seconds"] == 60
    assert backend.restarted == []


def test_propose_then_confirm_restarts_once(make_server):
    mcp, _, backend = make_server()

    async def flow():
        proposal = await propose(mcp)
        first = await acall(mcp, "confirm_action", token=proposal["token"])
        replay = await acall(mcp, "confirm_action", token=proposal["token"])
        return first, replay

    first, replay = run(flow())
    assert first["status"] == "executed" and first["post_state"] == "running"
    assert first["audit_id"].startswith("req_")
    assert code(replay) == "TOKEN_INVALID"
    assert backend.restarted == ["web-api"]


@pytest.mark.parametrize("target", ["all", "ALL", "everything", "*", "web-*", "."])
def test_wildcards_are_refused(make_server, target):
    mcp, _, backend = make_server()
    result = run(propose(mcp, target))
    assert code(result) == "ACTION_NOT_ALLOWED"
    assert "one named container" in result["error"]["message_spoken"]
    assert backend.restarted == []


def test_not_on_allowlist_is_refused(make_server):
    mcp, _, _ = make_server()
    assert code(run(propose(mcp, "postgres"))) == "ACTION_NOT_ALLOWED"


def test_empty_allowlist_denies_everything(make_server):
    mcp, _, _ = make_server(restart_allowlist=())
    assert code(run(propose(mcp, "web-api"))) == "ACTION_NOT_ALLOWED"


def test_unknown_action_is_invalid_input(make_server):
    mcp, _, _ = make_server()
    result = run(acall(mcp, "propose_action", action="delete_container", container="web-api"))
    assert code(result) == "INVALID_INPUT"


def test_allowlisted_but_missing_container(make_server):
    mcp, _, _ = make_server(restart_allowlist=("ghost",))
    assert code(run(propose(mcp, "ghost"))) == "CONTAINER_NOT_FOUND"


def test_crash_looping_container_reports_unhealthy(make_server):
    mcp, _, _ = make_server()

    async def flow():
        proposal = await propose(mcp, "worker")
        return await acall(mcp, "confirm_action", token=proposal["token"])

    result = run(flow())
    assert result["ok"] and result["status"] == "executed_unhealthy"
    assert result["post_state"] == "restarting"


def test_expired_token(make_server):
    mcp, deps, backend = make_server()
    now = [1000.0]
    deps.confirmations = ConfirmationStore(ttl_seconds=60, clock=lambda: now[0])

    async def flow():
        proposal = await propose(mcp)
        now[0] += 61
        late = await acall(mcp, "confirm_action", token=proposal["token"])
        again = await acall(mcp, "confirm_action", token=proposal["token"])
        return late, again

    late, again = run(flow())
    assert code(late) == "TOKEN_EXPIRED"
    assert code(again) == "TOKEN_INVALID"
    assert backend.restarted == []


def test_token_is_bound_to_the_client_that_asked(make_server):
    mcp, _, backend = make_server()

    async def flow():
        client_var.set("tok_aaaaaaaa")
        proposal = await propose(mcp)
        client_var.set("tok_bbbbbbbb")
        stolen = await acall(mcp, "confirm_action", token=proposal["token"])
        client_var.set("tok_aaaaaaaa")
        genuine = await acall(mcp, "confirm_action", token=proposal["token"])
        return stolen, genuine

    stolen, genuine = run(flow())
    assert code(stolen) == "TOKEN_INVALID"
    assert genuine["status"] == "executed"  # the failed attempt did not burn the token
    assert backend.restarted == ["web-api"]


def test_policy_is_rechecked_at_confirmation(make_server):
    mcp, deps, backend = make_server()

    async def flow():
        proposal = await propose(mcp)
        deps.policy = RestartPolicy([])  # allowlist tightened in the meantime
        return await acall(mcp, "confirm_action", token=proposal["token"])

    assert code(run(flow())) == "ACTION_NOT_ALLOWED"
    assert backend.restarted == []


def test_audit_failure_blocks_the_restart(make_server):
    mcp, deps, backend = make_server()
    original = deps.audit.write

    def flaky(**fields):
        if fields.get("event") == "action_attempt":
            raise OSError("disk full")
        return original(**fields)

    deps.audit.write = flaky

    async def flow():
        proposal = await propose(mcp)
        return await acall(mcp, "confirm_action", token=proposal["token"])

    assert code(run(flow())) == "INTERNAL_ERROR"
    assert backend.restarted == []


def test_audit_log_records_actions_and_never_tokens(make_server, audit_path):
    mcp, _, _ = make_server()

    async def flow():
        proposal = await propose(mcp)
        await acall(mcp, "confirm_action", token=proposal["token"])
        return proposal["token"]

    token = run(flow())
    raw = audit_path.read_text()
    assert token not in raw
    entries = [json.loads(line) for line in raw.splitlines()]
    assert [e.get("tool") or e.get("event") for e in entries] == ["propose_action", "action_attempt", "confirm_action"]
    confirm = entries[-1]
    assert confirm["ok"] and confirm["container"] == "web-api" and confirm["status"] == "executed"
    assert confirm["args"] == {"token": "[REDACTED]"}
    assert entries[1]["request_id"] == confirm["request_id"]


def test_failures_are_audited_too(make_server, audit_path):
    mcp, _, _ = make_server()
    run(propose(mcp, "all"))
    entry = json.loads(audit_path.read_text().splitlines()[-1])
    assert entry["ok"] is False and entry["error_code"] == "ACTION_NOT_ALLOWED"
