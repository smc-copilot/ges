from __future__ import annotations

from pathlib import Path
from typing import Any

from ges.errors import ARTIFACT_ALREADY_BOUND, ARTIFACT_PATH_INVALID, ARTIFACT_PATH_UNSAFE, ARTIFACT_STALE, GesError
from ges.governance.storage import load_work, now_rfc3339, write_work
from ges.io import sha256_bytes
from ges.stagelog import ARTIFACT_RESOLVE, emit


def normalize_pointer(raw: str) -> str:
    text = raw.replace("\\", "/").strip()
    if text.startswith("repo://"):
        text = text[len("repo://") :]
    while text.startswith("./"):
        text = text[2:]
    if text.startswith("/") or text.startswith("..") or "/../" in f"/{text}/" or ".." in text.split("/"):
        raise GesError(ARTIFACT_PATH_INVALID, f"artifact path escapes repo: {raw}")
    if not text:
        raise GesError(ARTIFACT_PATH_INVALID, "artifact path is empty")
    return f"repo://{text}"


def resolve_artifact_file(repo: Path, pointer: str) -> Path:
    rel = pointer.removeprefix("repo://")
    target = (repo / rel).resolve()
    try:
        target.relative_to(repo.resolve())
    except ValueError as exc:
        raise GesError(ARTIFACT_PATH_UNSAFE, f"artifact path is outside repo: {pointer}") from exc
    if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if repo.resolve() in parent.resolve().parents or parent == target):
        resolved = target.resolve()
        try:
            resolved.relative_to(repo.resolve())
        except ValueError as exc:
            raise GesError(ARTIFACT_PATH_UNSAFE, f"symlink escape: {pointer}") from exc
    if not target.is_file() or target.is_dir():
        raise GesError(ARTIFACT_PATH_INVALID, f"artifact is not a regular file: {pointer}")
    if target.is_symlink():
        raise GesError(ARTIFACT_PATH_UNSAFE, f"artifact path is a symlink: {pointer}")
    return target


def digest_file(path: Path) -> str:
    return f"sha256:{sha256_bytes(path.read_bytes())}"


def link_artifact(repo: Path, work_id: str, *, artifact_type: str, path: str, replace: bool = False) -> dict[str, Any]:
    emit(ARTIFACT_RESOLVE, "start", work_id=work_id, type=artifact_type)
    pointer = normalize_pointer(path)
    target = resolve_artifact_file(repo, pointer)
    digest = digest_file(target)
    work = load_work(repo, work_id)
    existing = [item for item in work["artifacts"] if item["type"] == artifact_type]
    same = [item for item in existing if item["pointer"] == pointer and item["digest"] == digest]
    if same:
        emit(ARTIFACT_RESOLVE, "complete", status="noop")
        return work
    if existing and not replace:
        raise GesError(ARTIFACT_ALREADY_BOUND, f"{artifact_type} already bound; pass --replace")
    kept = [item for item in work["artifacts"] if item["type"] != artifact_type]
    kept.append({"id": f"ART-{artifact_type}", "type": artifact_type, "pointer": pointer, "digest": digest})
    work["artifacts"] = kept
    work["updated_at"] = now_rfc3339()
    write_work(repo, work)
    emit(ARTIFACT_RESOLVE, "complete", status="linked", digest=digest)
    return work


def artifact_status(repo: Path, work: dict[str, Any], artifact_type: str) -> tuple[dict[str, Any] | None, str]:
    items = [item for item in work.get("artifacts") or [] if item["type"] == artifact_type]
    if not items:
        return None, "MISSING"
    item = items[0]
    try:
        target = resolve_artifact_file(repo, item["pointer"])
    except GesError:
        return item, "STALE"
    current = digest_file(target)
    if current != item["digest"]:
        return item, ARTIFACT_STALE
    return item, "CURRENT"
