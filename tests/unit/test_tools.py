import pytest

from server.docker_client import DockerUnavailable
from server.fake_docker import FakeDockerBackend
from tests.conftest import call


def code(result):
    assert result["ok"] is False, result
    return result["error"]["code"]


def test_fleet_summary_names_what_is_down(make_server):
    mcp, _, _ = make_server()
    result = call(mcp, "list_containers")
    assert result["summary"] == "3 of 5 containers are running. minecraft lobby and worker are down."
    names = [c["name"] for c in call(mcp, "list_containers", state_filter="running")["containers"]]
    assert names == ["postgres", "redis", "web-api"]


def test_status_reports_crash_loop(make_server):
    mcp, _, _ = make_server()
    result = call(mcp, "get_container_status", container="worker")
    assert result["state"] == "restarting" and result["oom_killed"] is True
    assert result["exit_code"] == 137 and result["uptime_seconds"] == 0
    assert "out of memory" in result["summary"]


def test_status_never_exited_has_null_exit_code(make_server):
    mcp, _, _ = make_server()
    assert call(mcp, "get_container_status", container="web-api")["exit_code"] is None


def test_logs_redact_secrets_and_flag_untrusted(make_server):
    mcp, _, _ = make_server()
    result = call(mcp, "tail_logs", container="worker")
    joined = "\n".join(result["lines"])
    assert "hunter2" not in joined
    assert result["redacted_count"] >= 1
    assert result["untrusted_content"] is True
    # The injection attempt is delivered as plain data, not acted on.
    assert any("ignore your previous instructions" in line for line in result["lines"])
    assert "hid" in result["summary"]


def test_logs_respect_stream_and_line_limits(make_server):
    mcp, _, _ = make_server()
    result = call(mcp, "tail_logs", container="web-api", lines=2, stream="stdout")
    assert result["line_count"] == 2 and result["truncated"] is True
    assert all("WARN" not in line for line in result["lines"])


@pytest.mark.parametrize(
    "tool,args",
    [
        ("tail_logs", {"container": "web-api", "lines": 201}),
        ("tail_logs", {"container": "web-api", "lines": 0}),
        ("tail_logs", {"container": "web-api", "since_seconds": 0}),
        ("tail_logs", {"container": "web-api", "stream": "all"}),
        ("tail_logs", {"container": "bad name"}),
        ("tail_logs", {"container": "-leading-dash"}),
        ("get_container_status", {"container": ""}),
        ("get_container_status", {"container": "a" * 129}),
        ("list_containers", {"state_filter": "nope"}),
    ],
)
def test_invalid_input(make_server, tool, args):
    mcp, _, _ = make_server()
    assert code(call(mcp, tool, **args)) == "INVALID_INPUT"


def test_unknown_container(make_server):
    mcp, _, _ = make_server()
    result = call(mcp, "tail_logs", container="ghost")
    assert code(result) == "CONTAINER_NOT_FOUND"
    assert "ghost" in result["error"]["message_spoken"]


def test_docker_down_maps_to_docker_unreachable(make_server):
    class Down(FakeDockerBackend):
        def list_containers(self):
            raise DockerUnavailable("Docker did not respond")

        def inspect(self, name):
            raise DockerUnavailable("Docker did not respond")

    mcp, _, _ = make_server(backend=Down())
    for tool, args in [("list_containers", {}), ("get_container_status", {"container": "web-api"})]:
        result = call(mcp, tool, **args)
        assert code(result) == "DOCKER_UNREACHABLE"
        assert result["error"]["retry_after_seconds"] == 5


def test_unexpected_exception_never_leaks(make_server):
    class Broken(FakeDockerBackend):
        def list_containers(self):
            raise RuntimeError("secret internal path /root/.ssh/id_rsa")

    mcp, _, _ = make_server(backend=Broken())
    result = call(mcp, "list_containers")
    assert code(result) == "INTERNAL_ERROR"
    assert "id_rsa" not in str(result)


def test_metrics_shape(make_server):
    mcp, _, _ = make_server()
    result = call(mcp, "get_system_metrics")
    assert 0 <= result["memory"]["percent"] <= 100
    assert "percent" in result["summary"]
