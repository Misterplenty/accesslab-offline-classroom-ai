from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


ROLE_COOKIE_NAME = "accesslab_role"
DEFAULT_LOCAL_ROLE = "learner"
KNOWN_LOCAL_ROLES = frozenset({"learner", "teacher", "admin"})


@dataclass(frozen=True, slots=True)
class LocalRole:
    id: str
    label: str
    short_label: str
    summary: str
    upload_allowed: bool
    manage_materials: bool
    sees_all_sessions: bool
    show_runtime_details: bool


ROLE_CATALOG: dict[str, LocalRole] = {
    "learner": LocalRole(
        id="learner",
        label="Learner",
        short_label="Learner",
        summary="Ask grounded questions, use the beginner Python helper, and reopen your saved work.",
        upload_allowed=False,
        manage_materials=False,
        sees_all_sessions=False,
        show_runtime_details=False,
    ),
    "teacher": LocalRole(
        id="teacher",
        label="Teacher / Coach",
        short_label="Teacher",
        summary="Upload class materials, manage class-shared sources, and inspect saved learner sessions.",
        upload_allowed=True,
        manage_materials=True,
        sees_all_sessions=True,
        show_runtime_details=False,
    ),
    "admin": LocalRole(
        id="admin",
        label="Admin",
        short_label="Admin",
        summary="Review runtime, model, OCR, retrieval, and local deployment settings on this device.",
        upload_allowed=True,
        manage_materials=True,
        sees_all_sessions=True,
        show_runtime_details=True,
    ),
}


def resolve_local_role(role_id: str | None) -> LocalRole:
    normalized = (role_id or "").strip().lower()
    if normalized in ROLE_CATALOG:
        return ROLE_CATALOG[normalized]
    return ROLE_CATALOG[DEFAULT_LOCAL_ROLE]


def current_local_role(request: Request) -> LocalRole:
    return resolve_local_role(request.cookies.get(ROLE_COOKIE_NAME))

