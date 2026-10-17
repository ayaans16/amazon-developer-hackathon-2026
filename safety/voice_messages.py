"""Spoken wording for errors and confirmations (owner: C).

Keep every message short, plain, and free of code, IDs and markdown, because it
is read aloud. Placeholders in {braces} are filled in by the server. The codes
must match contracts/errors.md.
"""

MAX_SPOKEN_CHARS = 240

MESSAGES = {
    "UNAUTHORIZED": "I'm not authorized to do that. Check the connection settings.",
    "RATE_LIMITED": "I'm getting too many requests. Try again in {seconds} seconds.",
    "INVALID_INPUT": "I didn't understand that request. Could you rephrase it?",
    "CONTAINER_NOT_FOUND": "I couldn't find a container called {container}.",
    "DOCKER_UNREACHABLE": "I can't reach Docker on that server right now.",
    "ACTION_NOT_ALLOWED": "I'm not allowed to {action} {container}. It isn't on the approved list.",
    "TOKEN_INVALID": "That confirmation isn't valid. Ask me to propose the action again.",
    "TOKEN_EXPIRED": "That confirmation timed out. Ask me again and confirm within a minute.",
    "INTERNAL_ERROR": "Something went wrong on my end. Try again in a moment.",
}


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "that"


def speak_name(name: str) -> str:
    """Make a container name read naturally: 'web-api' -> 'web api'."""
    return name.replace("-", " ").replace("_", " ")


def spoken(code: str, **fmt: object) -> str:
    template = MESSAGES.get(code, MESSAGES["INTERNAL_ERROR"])
    return template.format_map(_Safe(fmt))[:MAX_SPOKEN_CHARS]


def describe_restart(container: str) -> str:
    """Plain-language read-back of what a confirmed restart will do."""
    return f"Restart the container {speak_name(container)}. It will be briefly unavailable."
