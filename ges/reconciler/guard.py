from __future__ import annotations

from pathlib import Path

from ges.errors import BUSINESS_SOURCE_MODIFICATION_FORBIDDEN, GesError
from ges.paths import BUSINESS_SOURCE_ROOTS, WRITE_ALLOW_FILES, WRITE_ALLOW_PREFIXES, to_posix


def assert_allowed(relpath: str) -> None:
    rel = to_posix(relpath)
    if rel in WRITE_ALLOW_FILES:
        return
    if any(rel.startswith(prefix) for prefix in WRITE_ALLOW_PREFIXES):
        _reject_traversal(rel)
        return
    raise GesError(
        BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
        f"write outside Composer allowlist: {rel}",
    )


def assert_not_business_source(relpath: str) -> None:
    rel = to_posix(relpath)
    top = rel.split("/", 1)[0]
    if top in BUSINESS_SOURCE_ROOTS:
        raise GesError(
            BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
            f"business source modification forbidden: {rel}",
        )


def contain(repo: Path, relpath: str) -> Path:
    rel = to_posix(relpath)
    _reject_traversal(rel)
    target = (repo / rel).resolve()
    root = repo.resolve()
    if target != root and root not in target.parents:
        raise GesError(
            BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
            f"path escapes repository: {rel}",
        )
    return target


def _reject_traversal(rel: str) -> None:
    if rel.startswith("/") or rel.startswith("\\") or ".." in Path(rel).parts:
        raise GesError(
            BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
            f"path traversal rejected: {rel}",
        )
