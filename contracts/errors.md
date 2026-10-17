# VoiceOps MCP: Error Codes

Companion to `tools.schema.json`. The `error_code` enum in that file must match the codes below exactly. If you add or rename a code, update both files in the same PR (A approves; C reviews the wording).

## Error envelope

Every tool returns this shape on failure:

```json
{
  "ok": false,
  "error": {
    "code": "CONTAINER_NOT_FOUND",
    "message_spoken": "I couldn't find a container called web-api.",
    "detail": "docker inspect returned 404 for 'web-api'",
    "retry_after_seconds": null
  }
}
```

| Field | Audience | Rules |
|---|---|---|
| `code` | Code, tests, agent logic | One of the codes in the table below. Never invent ad-hoc codes. |
| `message_spoken` | The user, read aloud | One short sentence (under 240 chars). Plain words. No code, no IDs, no stack traces, no markdown. Say what happened and, where useful, what to do next. |
| `detail` | Developers and audit log only | Max 500 chars. Never include tokens, secrets, file paths from the host, or raw stack traces. Not read aloud. |
| `retry_after_seconds` | Agent | Only set for `RATE_LIMITED` and `DOCKER_UNREACHABLE`. Omit otherwise. |

## Codes

Placeholders in `message_spoken` use `{braces}` and are filled in by the server. Wording is owned by C (`safety/voice_messages.py`); A owns the codes and when they are raised.

| Code | Meaning | Raised by | Spoken message | Retry? |
|---|---|---|---|---|
| `UNAUTHORIZED` | Missing, malformed or wrong bearer token. | `auth.py` | "I'm not authorized to do that. Check the connection settings." | No. Fix credentials. |
| `RATE_LIMITED` | Client exceeded the per-client request limit. | `auth.py` | "I'm getting too many requests. Try again in {seconds} seconds." | Yes, after `retry_after_seconds`. |
| `INVALID_INPUT` | Arguments failed schema validation (bad container name, out-of-range `lines`, unknown action, missing field). | Any tool | "I didn't understand that request. Could you rephrase it?" | No. Fix the input. |
| `CONTAINER_NOT_FOUND` | No container with that name exists. | `containers.py`, `logs.py`, `actions.py` | "I couldn't find a container called {container}." | No. Agent can call `list_containers` and offer close matches. |
| `DOCKER_UNREACHABLE` | The Docker daemon or socket proxy didn't respond or refused the call. | `docker_client.py` | "I can't reach Docker on that server right now." | Yes, once or twice with backoff. |
| `ACTION_NOT_ALLOWED` | Safety policy refused the action: container not on the allowlist, or a wildcard such as "all" or "everything". (An unknown action name is `INVALID_INPUT`.) | `propose_action` (via `safety/policy.py`) | "I'm not allowed to {action} {container}. It isn't on the approved list." | No. |
| `TOKEN_INVALID` | Confirmation token is unknown, already used, malformed, or doesn't match the proposed action. | `confirm_action` (via `safety/confirmation.py`) | "That confirmation isn't valid. Ask me to propose the action again." | No. Start over with `propose_action`. |
| `TOKEN_EXPIRED` | Confirmation token was valid but its time window passed. | `confirm_action` | "That confirmation timed out. Ask me again and confirm within a minute." | No. Start over with `propose_action`. |
| `INTERNAL_ERROR` | Unexpected server failure. Catch-all so nothing leaks a stack trace. | `main.py` error handler | "Something went wrong on my end. Try again in a moment." | Maybe once. |

## Rules for raising errors

1. **Fail closed.** Any doubt about a token or the policy means `TOKEN_INVALID` or `ACTION_NOT_ALLOWED`, never a silent success.
2. **Don't leak.** `detail` is sanitized and capped, and `message_spoken` never contains secrets, host paths or raw exception text. Full exceptions go to the server log only, keyed by request ID.
3. **Every error is audited.** `audit.py` logs the code, tool, client and request ID for every failure, including `UNAUTHORIZED` and `RATE_LIMITED`.
4. **Distinguish "not found" from "not allowed".** `CONTAINER_NOT_FOUND` is for containers that don't exist. `ACTION_NOT_ALLOWED` is for existing containers the policy forbids. Don't reveal more than the user needs: for read tools, a non-allowlisted container may still be readable; for actions, it is not.
5. **One code per failure.** Pick the most specific code. Use `INTERNAL_ERROR` only when nothing else fits.
6. **Order of checks** (so behavior is predictable and testable): `UNAUTHORIZED` → `RATE_LIMITED` → `INVALID_INPUT` → `ACTION_NOT_ALLOWED` / `TOKEN_*` → `CONTAINER_NOT_FOUND` → `DOCKER_UNREACHABLE` → `INTERNAL_ERROR`.

## Guidance for the agent layer (B)

- Read `message_spoken` aloud as written. Don't paraphrase error text into something that sounds more confident than it is.
- On `CONTAINER_NOT_FOUND`: call `list_containers` and offer the closest names.
- On `DOCKER_UNREACHABLE`: retry once, then tell the user plainly that the server can't be reached.
- On `TOKEN_EXPIRED` / `TOKEN_INVALID`: never retry `confirm_action` with the same token. Re-propose and ask the user to confirm again.
- On `ACTION_NOT_ALLOWED`: do not try to work around it with a different phrasing or container.

## Test checklist (for C)

- [ ] Each code has at least one unit test that triggers it and checks `code` and `message_spoken`.
- [ ] A replayed token returns `TOKEN_INVALID`; a token past its window returns `TOKEN_EXPIRED`.
- [ ] "Restart everything" / "restart all" returns `ACTION_NOT_ALLOWED`.
- [ ] No test output contains a token, secret, or stack trace in `message_spoken` or `detail`.
- [ ] Every `message_spoken` is under 240 characters.
