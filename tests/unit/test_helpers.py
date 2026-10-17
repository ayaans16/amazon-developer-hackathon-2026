import time

import pytest

from safety.confirmation import ConfirmationStore, TokenExpired, TokenInvalid
from server.auth import RateLimiter
from server.config import Settings
from server.docker_client import info_from_inspect, parse_docker_time
from server.redact import clean_text, redact


@pytest.mark.parametrize(
    "line,secret",
    [
        ("DATABASE_URL=postgres://app:hunter2@db:5432/prod", "hunter2"),
        ("password=correcthorse", "correcthorse"),
        ('{"api_key": "abc123def456"}', "abc123def456"),
        ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG", "wJalrXUtnFEMI"),
        ("Authorization: Bearer abcdef1234567890", "abcdef1234567890"),
        ("key AKIAIOSFODNN7EXAMPLE leaked", "AKIAIOSFODNN7EXAMPLE"),
        ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghijklmnopqrstuvwxyz"),
        ("jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4fw", "eyJhbGci"),
    ],
)
def test_redacts_secrets(line, secret):
    text, count = redact(line)
    assert secret not in text and count >= 1 and "[REDACTED]" in text


def test_redaction_leaves_ordinary_lines_alone():
    line = "INFO GET /v1/items 200 14ms"
    assert redact(line) == (line, 0)


def test_clean_text_strips_ansi_and_control_characters():
    assert clean_text("\x1b[31mERROR\x1b[0m boom\x07") == "ERROR boom"


def test_confirmation_tokens_are_single_use_and_hashed():
    store = ConfirmationStore(ttl_seconds=60)
    issued = store.issue("restart_container", "web-api", "c1")
    assert issued.token not in repr(store._pending)
    assert store.consume(issued.token, "c1").container == "web-api"
    with pytest.raises(TokenInvalid):
        store.consume(issued.token, "c1")


def test_confirmation_expiry_and_cap():
    now = [0.0]
    store = ConfirmationStore(ttl_seconds=10, clock=lambda: now[0])
    token = store.issue("restart_container", "a", "c").token
    now[0] = 11
    with pytest.raises(TokenExpired):
        store.consume(token, "c")
    for _ in range(300):
        store.issue("restart_container", "a", "c")
    assert len(store._pending) <= 200


def test_rate_limiter_window():
    limiter = RateLimiter(limit=2, window=60)
    assert limiter.check("a") is None and limiter.check("a") is None
    assert limiter.check("a") >= 1
    assert limiter.check("b") is None  # independent per client


def test_parse_docker_time():
    assert parse_docker_time("0001-01-01T00:00:00Z") is None
    assert parse_docker_time("") is None
    parsed = parse_docker_time("2026-10-17T15:04:05.123456789Z")
    assert parsed.year == 2026 and parsed.microsecond == 123456 and parsed.tzinfo is not None
    assert parse_docker_time("2026-10-17T15:04:05Z") is not None


def _inspect(**state):
    base = {"Status": "running", "StartedAt": "2026-10-17T10:00:00.5Z", "FinishedAt": "0001-01-01T00:00:00Z", "ExitCode": 0}
    return {
        "Name": "/web-api",
        "RestartCount": 3,
        "Config": {"Image": "nginx:1.27"},
        "State": {**base, **state},
    }


def test_inspect_normalization():
    info = info_from_inspect(_inspect())
    assert (info.name, info.image, info.state, info.health) == ("web-api", "nginx:1.27", "running", "none")
    assert info.exit_code is None and info.restart_count == 3 and info.last_health_check is None


def test_inspect_exit_code_and_health():
    info = info_from_inspect(
        _inspect(
            Status="exited",
            ExitCode=137,
            FinishedAt="2026-10-17T11:00:00Z",
            OOMKilled=True,
            Health={"Status": "unhealthy", "Log": [{"End": "2026-10-17T10:59:00Z", "Output": "curl: (7) refused"}]},
        )
    )
    assert info.exit_code == 137 and info.oom_killed and info.health == "unhealthy"
    assert info.last_health_check.output == "curl: (7) refused"
    assert info_from_inspect(_inspect(Status="removing")).state == "dead"


def test_uptime_is_zero_unless_running():
    assert info_from_inspect(_inspect(Status="exited")).uptime_seconds() == 0
    assert info_from_inspect(_inspect()).uptime_seconds() > 0


def test_settings_refuse_unsafe_configs():
    with pytest.raises(ValueError, match="No auth configured"):
        Settings().validate()
    with pytest.raises(ValueError, match="16 characters"):
        Settings(tokens=("short",)).validate()
    with pytest.raises(ValueError, match="localhost"):
        Settings(allow_no_auth=True, host="0.0.0.0").validate()
    Settings(tokens=("a" * 24,)).validate()
    Settings(allow_no_auth=True).validate()
    assert Settings.from_env({"VOICEOPS_RESTART_ALLOWLIST": " a, b ,", "VOICEOPS_CONFIRM_TTL_SECONDS": "9999"}).confirm_ttl_seconds == 300
