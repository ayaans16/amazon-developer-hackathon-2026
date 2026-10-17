"""What the server is allowed to change (owner: C).

Fail closed: an empty allowlist denies everything, and anything that looks like
a wildcard ("all", "everything", "*") is always denied.
"""
from __future__ import annotations

from typing import Iterable

SUPPORTED_ACTIONS = frozenset({"restart_container"})
WILDCARD_WORDS = frozenset({"*", "all", "everything", "every", "any", "."})


class PolicyDenied(Exception):
    """The requested action is not permitted. `reason` is for logs, not speech."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RestartPolicy:
    def __init__(self, allowlist: Iterable[str]) -> None:
        self._allow = frozenset(allowlist)

    @staticmethod
    def is_wildcard(name: str) -> bool:
        n = name.strip().lower()
        return n in WILDCARD_WORDS or any(ch in n for ch in "*?[]")

    def check(self, action: str, container: str) -> None:
        """Raise PolicyDenied unless `action` on `container` is allowed."""
        if action not in SUPPORTED_ACTIONS:
            raise PolicyDenied("unsupported action")
        if self.is_wildcard(container):
            raise PolicyDenied("wildcards are not allowed")
        if container not in self._allow:
            raise PolicyDenied("container is not on the allowlist")
