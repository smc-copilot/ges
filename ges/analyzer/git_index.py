from __future__ import annotations

import hashlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ges.analyzer.source_roots import is_skipped_business_path
from ges.errors import BUSINESS_GIT_INDEX_UNAVAILABLE, GesError
from ges.paths import BUSINESS_SOURCE_SKIP_PREFIXES
from ges.stagelog import FILE_INDEX, emit

ANALYZER_PRUNE_NAMES = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "out",
    "coverage",
    ".next",
    ".turbo",
    ".cache",
    "__pycache__",
    ".venv",
    "venv",
    "target",
}


@dataclass
class TrackedEntry:
    path: str
    mode: str
    blob_oid: str
    stage: str


@dataclass
class StatusEntry:
    kind: str
    path: str
    xy: str = ".."
    orig_path: str = ""


@dataclass
class GitFileIndex:
    repo: Path
    head: str
    tracked: list[TrackedEntry]
    status: list[StatusEntry]
    raw_index: bytes
    raw_status: bytes
    elapsed_ms: int
    path_count: int
    ignored_tree_visits: int = 0

    def visible_paths(self) -> list[str]:
        paths = {item.path for item in self.tracked}
        for item in self.status:
            if item.kind in {"untracked", "changed", "renamed", "unmerged"}:
                paths.add(item.path)
        return sorted(path for path in paths if not is_skipped_business_path(path))

    def business_tracked(self, roots: list[str]) -> list[TrackedEntry]:
        return [
            item
            for item in self.tracked
            if _under_roots(item.path, roots) and not is_skipped_business_path(item.path)
        ]

    def business_status(self, roots: list[str]) -> list[StatusEntry]:
        return [
            item
            for item in self.status
            if _under_roots(item.path, roots) and not is_skipped_business_path(item.path)
        ]


def is_git_repo(repo: Path) -> bool:
    return (repo / ".git").exists()


def build_git_file_index(repo: Path, *, roots: list[str] | None = None) -> GitFileIndex:
    emit(FILE_INDEX, "start", repo=str(repo))
    started = time.perf_counter()
    try:
        head = _git_bytes(repo, ["rev-parse", "HEAD"]).stdout.strip().decode("ascii")
        if len(head) != 40:
            raise GesError(BUSINESS_GIT_INDEX_UNAVAILABLE, "git HEAD is not a 40-character SHA")
        pathspec = _pathspec(repo, roots)
        staged = _git_bytes(repo, ["ls-files", "--stage", "-z", "--", *pathspec])
        status = _git_bytes(
            repo,
            [
                "status",
                "--porcelain=v2",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
                "--",
                *pathspec,
            ],
        )
        if staged.returncode != 0 or status.returncode != 0:
            raise GesError(
                BUSINESS_GIT_INDEX_UNAVAILABLE,
                staged.stderr.decode("utf-8", "replace") or status.stderr.decode("utf-8", "replace") or "git inventory failed",
            )
        tracked = parse_ls_files_stage_z(staged.stdout)
        entries = parse_porcelain_v2_z(status.stdout)
        if any(item.kind == "unmerged" for item in entries):
            raise GesError(BUSINESS_GIT_INDEX_UNAVAILABLE, "unsupported unmerged Git state")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        index = GitFileIndex(
            repo=repo,
            head=head,
            tracked=tracked,
            status=entries,
            raw_index=staged.stdout,
            raw_status=status.stdout,
            elapsed_ms=elapsed_ms,
            path_count=len({item.path for item in tracked} | {item.path for item in entries}),
        )
        emit(FILE_INDEX, "complete", paths=index.path_count, elapsed_ms=elapsed_ms)
        return index
    except GesError:
        raise
    except OSError as exc:
        raise GesError(BUSINESS_GIT_INDEX_UNAVAILABLE, str(exc)) from exc


def parse_ls_files_stage_z(payload: bytes) -> list[TrackedEntry]:
    tracked: list[TrackedEntry] = []
    for record in _split_z(payload):
        tab = record.find(b"\t")
        if tab < 0:
            raise GesError(BUSINESS_GIT_INDEX_UNAVAILABLE, "ls-files record missing tab")
        meta = record[:tab].decode("ascii")
        path = record[tab + 1 :].decode("utf-8")
        mode, blob_oid, stage = meta.split(" ", 2)
        tracked.append(TrackedEntry(path=path.replace("\\", "/"), mode=mode, blob_oid=blob_oid, stage=stage))
    return tracked


def parse_porcelain_v2_z(payload: bytes) -> list[StatusEntry]:
    records = _split_z(payload)
    entries: list[StatusEntry] = []
    index = 0
    while index < len(records):
        raw = records[index]
        index += 1
        if not raw:
            continue
        kind = raw[:1]
        if kind == b"1":
            fields = raw.split(b" ", 8)
            if len(fields) < 9:
                raise GesError(BUSINESS_GIT_INDEX_UNAVAILABLE, "porcelain v2 changed record is truncated")
            entries.append(
                StatusEntry(
                    kind="changed",
                    path=fields[8].decode("utf-8").replace("\\", "/"),
                    xy=fields[1].decode("ascii"),
                )
            )
            continue
        if kind == b"2":
            fields = raw.split(b" ", 9)
            if len(fields) < 10 or index >= len(records):
                raise GesError(BUSINESS_GIT_INDEX_UNAVAILABLE, "porcelain v2 rename record is truncated")
            orig = records[index].decode("utf-8").replace("\\", "/")
            index += 1
            entries.append(
                StatusEntry(
                    kind="renamed",
                    path=fields[9].decode("utf-8").replace("\\", "/"),
                    xy=fields[1].decode("ascii"),
                    orig_path=orig,
                )
            )
            continue
        if kind == b"u":
            path = raw.split(b" ", 10)[-1].decode("utf-8").replace("\\", "/")
            entries.append(StatusEntry(kind="unmerged", path=path))
            continue
        if kind == b"?":
            entries.append(StatusEntry(kind="untracked", path=raw[2:].decode("utf-8").replace("\\", "/"), xy="??"))
            continue
        if kind == b"!":
            continue
        raise GesError(BUSINESS_GIT_INDEX_UNAVAILABLE, "unknown porcelain v2 record")
    return entries


def prune_walk(repo: Path) -> tuple[list[str], int]:
    ignored_visits = 0
    found: list[str] = []
    for current, dirs, files in __import__("os").walk(repo, topdown=True):
        rel_dir = Path(current).relative_to(repo).as_posix()
        names = set(dirs)
        if names & ANALYZER_PRUNE_NAMES:
            ignored_visits += len(names & ANALYZER_PRUNE_NAMES)
        dirs[:] = [
            name
            for name in dirs
            if name not in ANALYZER_PRUNE_NAMES
            and not is_skipped_business_path(name if rel_dir == "." else f"{rel_dir}/{name}")
        ]
        for name in files:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            found.append(rel.replace("\\", "/"))
    return sorted(found), ignored_visits


def digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _git_bytes(repo: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)


def _pathspec(repo: Path, roots: list[str] | None) -> list[str]:
    if not roots:
        specs = ["."]
    else:
        specs = [name for name in roots if (repo / name).exists()] or ["."]
    specs.extend(f":(exclude){prefix}" for prefix in BUSINESS_SOURCE_SKIP_PREFIXES)
    return specs


def _under_roots(path: str, roots: list[str]) -> bool:
    if not roots:
        return True
    return any(path == root or path.startswith(root + "/") for root in roots)


def _split_z(payload: bytes) -> list[bytes]:
    if not payload:
        return []
    parts = payload.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    return parts
