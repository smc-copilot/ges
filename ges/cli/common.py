from __future__ import annotations

from pathlib import Path

from ges.errors import REPO_NOT_SUPPORTED, GesError


def flatten_ids(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for item in values or []:
        out.extend(part.strip() for part in item.split(",") if part.strip())
    return out


def resolve_repo(value: str | None) -> Path:
    raw = value or "."
    path = Path(raw).expanduser()
    if path.exists():
        return path.resolve()
    sibling = Path.cwd().parent / raw
    if sibling.exists():
        return sibling.resolve()
    raise GesError(REPO_NOT_SUPPORTED, f"repository not found: {raw}")
