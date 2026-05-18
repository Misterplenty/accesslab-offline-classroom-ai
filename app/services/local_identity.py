from __future__ import annotations

import secrets

from fastapi import Request, Response


ACTOR_COOKIE_NAME = "accesslab_actor"
DEFAULT_ACTOR_PREFIX = "user"


def generate_actor_key() -> str:
    return f"{DEFAULT_ACTOR_PREFIX}-{secrets.token_hex(4)}"


def resolve_actor_key(actor_key: str | None) -> str:
    normalized = (actor_key or "").strip().lower()
    if not normalized:
        return ""
    allowed = "".join(ch for ch in normalized if ch.isalnum() or ch in {"-", "_"})
    return allowed[:40]


def current_actor_key(request: Request) -> str:
    cached = getattr(request.state, "accesslab_actor_key", "")
    if cached:
        return str(cached)

    resolved = resolve_actor_key(request.cookies.get(ACTOR_COOKIE_NAME))
    if resolved:
        request.state.accesslab_actor_key = resolved
        request.state.issue_actor_cookie = False
        return resolved

    generated = generate_actor_key()
    request.state.accesslab_actor_key = generated
    request.state.issue_actor_cookie = True
    return generated


def attach_actor_cookie(response: Response, request: Request) -> Response:
    actor_key = current_actor_key(request)
    if not getattr(request.state, "issue_actor_cookie", False):
        return response
    response.set_cookie(
        key=ACTOR_COOKIE_NAME,
        value=actor_key,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
        path="/",
    )
    request.state.issue_actor_cookie = False
    return response


def actor_label(*, actor_key: str, actor_role: str) -> str:
    parts = resolve_actor_key(actor_key).split("-")
    last = parts[-1] if parts else ""
    # Only use the last segment as a unique suffix if it looks like a hex token
    is_hex_token = len(last) >= 4 and all(c in "0123456789abcdef" for c in last)
    suffix = last[-4:] if is_hex_token else ""
    role = (actor_role or "learner").strip().lower()
    if role == "teacher":
        return f"Teacher {suffix}".strip()
    if role == "admin":
        return f"Admin {suffix}".strip()
    return f"Learner {suffix}".strip()
