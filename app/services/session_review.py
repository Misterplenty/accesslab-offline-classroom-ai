from __future__ import annotations


KNOWN_SESSION_LABELS = (
    "good",
    "bad",
    "overlong",
    "over-disclosing",
    "unclear",
    "screen-reader-friendly",
    "needs-review",
)


def session_label_display(label: str) -> str:
    normalized = (label or "").strip().lower()
    if not normalized:
        return "Unlabeled"
    return normalized.replace("-", " ")
