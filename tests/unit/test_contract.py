"""The running server must match contracts/tools.schema.json. Fails on drift."""
import asyncio
from datetime import datetime

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import call


def _validator(contract, tool_name):
    tool = next(t for t in contract["tools"] if t["name"] == tool_name)
    return Draft202012Validator({"$defs": contract["$defs"], **tool["outputSchema"]})


def _walk_timestamps(value):
    if isinstance(value, dict):
        for key, v in value.items():
            if key.endswith("_at") and isinstance(v, str):
                datetime.fromisoformat(v)  # must be valid ISO-8601
            _walk_timestamps(v)
    elif isinstance(value, list):
        for v in value:
            _walk_timestamps(v)


def check(contract, tool_name, result):
    errors = list(_validator(contract, tool_name).iter_errors(result))
    assert not errors, f"{tool_name} output violates contract: {[e.message for e in errors][:3]}\n{result}"
    _walk_timestamps(result)
    text = result.get("summary") or result.get("error", {}).get("message_spoken", "")
    assert 0 < len(text) <= 240


def test_tool_names_inputs_and_annotations_match(make_server, contract):
    mcp, _, _ = make_server()
    live = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert set(live) == {t["name"] for t in contract["tools"]}
    for spec in contract["tools"]:
        tool = live[spec["name"]]
        assert set(tool.input_schema.get("properties", {})) == set(spec["inputSchema"].get("properties", {})), spec["name"]
        assert set(tool.input_schema.get("required", [])) == set(spec["inputSchema"].get("required", [])), spec["name"]
        live_hints = tool.annotations.model_dump(by_alias=True)
        for hint, expected in spec["annotations"].items():
            assert live_hints[hint] is expected, (spec["name"], hint)


@pytest.mark.parametrize("state_filter", ["all", "running", "not_running", "unhealthy"])
def test_list_containers(make_server, contract, state_filter):
    mcp, _, _ = make_server()
    result = call(mcp, "list_containers", state_filter=state_filter)
    check(contract, "list_containers", result)
    assert result["total"] == 5


@pytest.mark.parametrize("name", ["web-api", "postgres", "redis", "worker", "minecraft-lobby"])
def test_status_and_logs_for_every_container(make_server, contract, name):
    mcp, _, _ = make_server()
    check(contract, "get_container_status", call(mcp, "get_container_status", container=name))
    check(contract, "tail_logs", call(mcp, "tail_logs", container=name))


def test_system_metrics(make_server, contract):
    mcp, _, _ = make_server()
    check(contract, "get_system_metrics", call(mcp, "get_system_metrics"))


def test_action_flow_outputs(make_server, contract):
    mcp, _, _ = make_server()

    async def flow():
        from tests.conftest import acall

        proposal = await acall(mcp, "propose_action", action="restart_container", container="web-api")
        check(contract, "propose_action", proposal)
        outcome = await acall(mcp, "confirm_action", token=proposal["token"])
        check(contract, "confirm_action", outcome)
        return outcome

    assert asyncio.run(flow())["status"] == "executed"


@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_container_status", {"container": "ghost"}),
        ("get_container_status", {"container": "../etc/passwd"}),
        ("tail_logs", {"container": "web-api", "lines": 0}),
        ("list_containers", {"state_filter": "everything"}),
        ("propose_action", {"action": "restart_container", "container": "all"}),
        ("confirm_action", {"token": "not-a-real-token-at-all"}),
    ],
)
def test_error_envelopes_match_contract(make_server, contract, tool, args):
    mcp, _, _ = make_server()
    result = call(mcp, tool, **args)
    assert result["ok"] is False
    check(contract, tool, result)
