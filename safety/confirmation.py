"""Single-use confirmation tokens for two-step actions (owner: C).

propose_action issues a token bound to one action, one container and one
client. confirm_action consumes it. Tokens are stored only as SHA-256 hashes,
expire after `ttl_seconds`, and can be used exactly once.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

MAX_PENDING = 200
KEEP_EXPIRED_SECONDS = 600  # keep expired records so we can say "expired", not "invalid"


class TokenInvalid(Exception):
    """Unknown, already used, or issued to a different client."""


class TokenExpired(Exception):
    """Valid token, but its window has passed."""


@dataclass(frozen=True)
class Pending:
    action: str
    container: str
    client: str
    reason: str | None
    expires_at: float


@dataclass(frozen=True)
class Issued:
    token: str
    expires_at: float  # epoch seconds
    ttl_seconds: int


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ConfirmationStore:
    def __init__(self, ttl_seconds: int = 60, clock: Callable[[], float] = time.time) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, Pending] = {}

    def issue(self, action: str, container: str, client: str, reason: str | None = None) -> Issued:
        token = secrets.token_urlsafe(24)  # 32 chars, ~192 bits
        now = self._clock()
        record = Pending(action, container, client, reason, now + self.ttl_seconds)
        with self._lock:
            self._purge(now)
            while len(self._pending) >= MAX_PENDING:
                self._pending.pop(next(iter(self._pending)))  # evict oldest
            self._pending[_digest(token)] = record
        return Issued(token, record.expires_at, self.ttl_seconds)

    def consume(self, token: str, client: str) -> Pending:
        """Return the pending record and invalidate the token.

        Raises TokenInvalid or TokenExpired. A token presented by a different
        client is rejected without being consumed, so it cannot be burned by
        someone who intercepted it.
        """
        key = _digest(token)
        with self._lock:
            record = self._pending.get(key)
            if record is None or record.client != client:
                raise TokenInvalid()
            del self._pending[key]
            if self._clock() > record.expires_at:
                raise TokenExpired()
            return record

    def _purge(self, now: float) -> None:
        stale = [k for k, r in self._pending.items() if now > r.expires_at + KEEP_EXPIRED_SECONDS]
        for k in stale:
            del self._pending[k]
