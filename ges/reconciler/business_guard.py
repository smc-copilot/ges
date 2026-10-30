from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

from ges.analyzer.git_index import (
    GitFileIndex,
    StatusEntry,
    TrackedEntry,
    build_git_file_index,
    digest_bytes,
    is_git_repo,
)
from ges.analyzer.source_roots import business_source_roots, is_skipped_business_path, iter_business_files
from ges.errors import (
    BUSINESS_GIT_HEAD_CHANGED_DURING_APPLY,
    BUSINESS_GIT_INDEX_CHANGED_DURING_APPLY,
    BUSINESS_GIT_INDEX_UNAVAILABLE,
    BUSINESS_SNAPSHOT_FAILED,
    BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
    SUBMODULE_SOURCE_STATE_UNRESOLVED,
    GesError,
)
from ges.io import sha256_bytes
from ges.stagelog import BUSINESS_COMPARE, BUSINESS_SNAPSHOT_T0, BUSINESS_SNAPSHOT_T1, emit

HASH_STATS: dict[str, Any] = {
    "calls": 0,
    "bytes": 0,
    "paths": [],
    "ignored_calls": 0,
    "clean_tracked_calls": 0,
}

SYMLINK_MODE = 0o120000
GITLINK_MODE = 0o160000
COMPARABLE_KEYS = (
    "schema",
    "strategy",
    "repo_head",
    "roots",
    "index_digest",
    "status_digest",
    "overlay_digest",
    "snapshot_digest",
    "counts",
    "bytes_hashed",
    "fallback_reason",
)


def reset_hash_stats() -> None:
    HASH_STATS["calls"] = 0
    HASH_STATS["bytes"] = 0
    HASH_STATS["paths"] = []
    HASH_STATS["ignored_calls"] = 0
    HASH_STATS["clean_tracked_calls"] = 0


def capture_business_snapshot(
    repo: Path,
    *,
    stage: str = BUSINESS_SNAPSHOT_T0,
    index: GitFileIndex | None = None,
) -> dict[str, Any]:
    emit(stage, "start", repo=str(repo))
    started = time.perf_counter()
    roots = business_source_roots(repo)
    try:
        if is_git_repo(repo):
            snapshot = _git_overlay_snapshot(repo, roots, index)
        else:
            snapshot = _full_fallback_snapshot(repo, roots, "non-git")
    except GesError as exc:
        if exc.code == BUSINESS_GIT_INDEX_UNAVAILABLE:
            snapshot = _full_fallback_snapshot(repo, roots, exc.message)
        else:
            raise
    snapshot["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    emit(
        stage,
        "complete",
        strategy=snapshot["strategy"],
        elapsed_ms=snapshot["elapsed_ms"],
        tracked=snapshot["counts"]["tracked"],
        dirty=snapshot["counts"]["dirty_tracked"],
        untracked=snapshot["counts"]["untracked_nonignored"],
        content_hashed=snapshot["counts"]["overlay_content_hashed"],
        bytes_hashed=snapshot["bytes_hashed"],
        fallback_reason=snapshot.get("fallback_reason") or "",
    )
    return snapshot


def snapshot_business_sources(repo: Path) -> dict[str, Any]:
    snap = capture_business_snapshot(repo)
    return comparable_snapshot(snap)


def is_overlay_fingerprint(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("strategy"), str) and "snapshot_digest" in payload


def comparable_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = {key: snapshot[key] for key in COMPARABLE_KEYS if key in snapshot}
    payload["elapsed_ms"] = 0
    return payload


def assert_business_unchanged(repo: Path, before: dict[str, Any]) -> dict[str, Any]:
    after = capture_business_snapshot(repo, stage=BUSINESS_SNAPSHOT_T1)
    compare_business_snapshots(before, after)
    return after


def compare_business_snapshots(before: dict[str, Any], after: dict[str, Any]) -> None:
    emit(BUSINESS_COMPARE, "start")
    left = comparable_snapshot(before)
    right = comparable_snapshot(after)
    if left.get("repo_head") != right.get("repo_head"):
        emit(BUSINESS_COMPARE, "complete", status="FAIL", reason="head")
        raise GesError(
            BUSINESS_GIT_HEAD_CHANGED_DURING_APPLY,
            "Git HEAD changed during Composer apply",
            details={"expected": left.get("repo_head"), "actual": right.get("repo_head")},
        )
    if left.get("index_digest") != right.get("index_digest"):
        emit(BUSINESS_COMPARE, "complete", status="FAIL", reason="index")
        raise GesError(
            BUSINESS_GIT_INDEX_CHANGED_DURING_APPLY,
            "Git index changed during Composer apply",
            details={"expected": left.get("index_digest"), "actual": right.get("index_digest")},
        )
    if left.get("snapshot_digest") != right.get("snapshot_digest"):
        emit(BUSINESS_COMPARE, "complete", status="FAIL", reason="bytes")
        raise GesError(
            BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
            "business source bytes changed during Composer apply",
        )
    emit(BUSINESS_COMPARE, "complete", status="PASS")


def format_guard_summary(t0: dict[str, Any], t1: dict[str, Any] | None = None) -> str:
    hashed = t0.get("counts", {}).get("overlay_content_hashed", 0)
    mb = (t0.get("bytes_hashed") or 0) / 1_000_000
    t1_ms = (t1 or {}).get("elapsed_ms", 0)
    return (
        f"Business Guard: {t0.get('strategy')}\n"
        f"Tracked: {t0.get('counts', {}).get('tracked', 0):,}\n"
        f"Content-hashed overlay: {hashed} files / {mb:.1f} MB\n"
        f"Snapshot: T0 {t0.get('elapsed_ms', 0) / 1000:.1f}s / T1 {t1_ms / 1000:.1f}s"
    )


def _git_overlay_snapshot(repo: Path, roots: list[str], index: GitFileIndex | None) -> dict[str, Any]:
    inventory = index or build_git_file_index(repo)
    tracked = inventory.business_tracked(roots)
    status = inventory.business_status(roots)
    dirty_paths = _dirty_paths(status)
    untracked = [item.path for item in status if item.kind == "untracked"]
    records: list[str] = []
    overlay_hashed = 0
    bytes_hashed = 0
    symlinks = 0
    submodules = 0
    dirty_tracked = 0
    clean_tracked = 0
    by_path = {item.path: item for item in tracked}
    for item in tracked:
        if _mode_int(item.mode) == GITLINK_MODE:
            submodules += 1
            records.append(_gitlink_record(repo, item, item.path in dirty_paths))
            continue
        if item.path in dirty_paths:
            dirty_tracked += 1
            record, hashed, nbytes, is_link = _worktree_record(repo, item.path, item)
            records.append(record)
            overlay_hashed += hashed
            bytes_hashed += nbytes
            symlinks += int(is_link)
            continue
        clean_tracked += 1
        records.append(f"T\0{item.mode}\0{item.blob_oid}\0{item.path}\n")
    for path in untracked:
        record, hashed, nbytes, is_link = _worktree_record(repo, path, by_path.get(path))
        records.append(record)
        overlay_hashed += hashed
        bytes_hashed += nbytes
        symlinks += int(is_link)
    overlay = "".join(sorted(records))
    overlay_digest = "sha256:" + hashlib.sha256(overlay.encode("utf-8")).hexdigest()
    index_digest = digest_bytes(inventory.raw_index)
    status_digest = digest_bytes(inventory.raw_status)
    snapshot_digest = _snapshot_digest(inventory.head, index_digest, status_digest, overlay_digest)
    return _payload(
        strategy="git-index-overlay",
        repo_head=inventory.head,
        roots=roots,
        index_digest=index_digest,
        status_digest=status_digest,
        overlay_digest=overlay_digest,
        snapshot_digest=snapshot_digest,
        counts={
            "tracked": len(tracked),
            "clean_tracked": clean_tracked,
            "dirty_tracked": dirty_tracked,
            "untracked_nonignored": len(untracked),
            "overlay_content_hashed": overlay_hashed,
            "symlinks": symlinks,
            "submodules": submodules,
        },
        bytes_hashed=bytes_hashed,
    )


def _full_fallback_snapshot(repo: Path, roots: list[str], reason: str) -> dict[str, Any]:
    records: list[str] = []
    bytes_hashed = 0
    hashed = 0
    try:
        for path in iter_business_files(repo):
            rel = path.relative_to(repo).as_posix()
            record, count, nbytes, _ = _worktree_record(repo, rel, None)
            records.append(record)
            hashed += count
            bytes_hashed += nbytes
    except OSError as exc:
        raise GesError(BUSINESS_SNAPSHOT_FAILED, str(exc)) from exc
    overlay = "".join(sorted(records))
    overlay_digest = "sha256:" + hashlib.sha256(overlay.encode("utf-8")).hexdigest()
    empty = "sha256:" + hashlib.sha256(b"").hexdigest()
    return _payload(
        strategy="full-sha256-fallback",
        repo_head="",
        roots=roots,
        index_digest=empty,
        status_digest=empty,
        overlay_digest=overlay_digest,
        snapshot_digest=_snapshot_digest("", empty, empty, overlay_digest),
        counts={
            "tracked": 0,
            "clean_tracked": 0,
            "dirty_tracked": 0,
            "untracked_nonignored": hashed,
            "overlay_content_hashed": hashed,
            "symlinks": 0,
            "submodules": 0,
        },
        bytes_hashed=bytes_hashed,
        fallback_reason=reason,
    )


def _worktree_record(repo: Path, rel: str, tracked: TrackedEntry | None) -> tuple[str, int, int, bool]:
    if is_skipped_business_path(rel):
        return f"S\0{rel.rstrip('/')}\n", 0, 0, False
    path = repo / rel
    if path.is_dir() and not path.is_symlink():
        return f"S\0{rel.rstrip('/')}\n", 0, 0, False
    if not path.exists() and not path.is_symlink():
        return f"D\0{rel}\n", 0, 0, False
    if path.is_symlink() or (tracked and _mode_int(tracked.mode) == SYMLINK_MODE):
        try:
            target = os.readlink(path)
        except OSError as exc:
            raise GesError(BUSINESS_SNAPSHOT_FAILED, f"symlink unreadable: {rel}") from exc
        digest = sha256_bytes(target.encode("utf-8"))
        HASH_STATS["calls"] += 1
        HASH_STATS["paths"].append(rel)
        return f"L\0{rel}\0{digest}\n", 1, len(target.encode("utf-8")), True
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GesError(BUSINESS_SNAPSHOT_FAILED, f"content hash permission denied: {rel}") from exc
    HASH_STATS["calls"] += 1
    HASH_STATS["bytes"] += len(data)
    HASH_STATS["paths"].append(rel)
    digest = sha256_bytes(data)
    return f"F\0{rel}\0{len(data)}\0{digest}\n", 1, len(data), False


def _gitlink_record(repo: Path, item: TrackedEntry, dirty: bool) -> str:
    import subprocess

    sub = repo / item.path
    observed = ""
    dirty_state = "dirty" if dirty or (sub.exists() and not (sub / ".git").exists()) else "clean"
    if dirty_state == "dirty":
        if not (sub / ".git").exists():
            raise GesError(
                SUBMODULE_SOURCE_STATE_UNRESOLVED,
                f"dirty submodule cannot be resolved: {item.path}",
                exit_code=3,
            )
        try:
            result = subprocess.run(
                ["git", "-C", str(sub), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            observed = (result.stdout or "").strip().lower()
            status = subprocess.run(
                ["git", "-C", str(sub), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 or status.returncode != 0 or len(observed) != 40:
                raise GesError(
                    SUBMODULE_SOURCE_STATE_UNRESOLVED,
                    f"dirty submodule cannot be resolved: {item.path}",
                    exit_code=3,
                )
        except GesError:
            raise
        except OSError as exc:
            raise GesError(
                SUBMODULE_SOURCE_STATE_UNRESOLVED,
                f"dirty submodule cannot be resolved: {item.path}",
                exit_code=3,
            ) from exc
    return f"G\0{item.path}\0{item.blob_oid}\0{observed}\0{dirty_state}\n"


def _mode_int(mode: str) -> int:
    return int(mode, 8)


def _dirty_paths(status: list[StatusEntry]) -> set[str]:
    dirty: set[str] = set()
    for item in status:
        if item.kind in {"changed", "renamed"} and len(item.xy) >= 2 and item.xy[1] not in {".", " "}:
            dirty.add(item.path)
            if item.orig_path:
                dirty.add(item.orig_path)
    return dirty


def _snapshot_digest(head: str, index_digest: str, status_digest: str, overlay_digest: str) -> str:
    payload = f"{head}\0{index_digest}\0{status_digest}\0{overlay_digest}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _payload(
    *,
    strategy: str,
    repo_head: str,
    roots: list[str],
    index_digest: str,
    status_digest: str,
    overlay_digest: str,
    snapshot_digest: str,
    counts: dict[str, int],
    bytes_hashed: int,
    fallback_reason: str = "",
) -> dict[str, Any]:
    payload = {
        "schema": "ges.business-source-snapshot.v2",
        "strategy": strategy,
        "repo_head": repo_head,
        "roots": roots,
        "index_digest": index_digest,
        "status_digest": status_digest,
        "overlay_digest": overlay_digest,
        "snapshot_digest": snapshot_digest,
        "counts": counts,
        "bytes_hashed": bytes_hashed,
        "elapsed_ms": 0,
    }
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
    return payload
