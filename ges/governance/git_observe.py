from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ges.errors import WORKTREE_DIRTY, GesError
from ges.stagelog import GIT_OBSERVE, emit


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def git_version() -> str:
    result = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False)
    return (result.stdout or result.stderr).strip()


def local_head(repo: Path) -> str:
    emit(GIT_OBSERVE, "start", repo=str(repo))
    result = _git(repo, ["rev-parse", "HEAD"])
    head = result.stdout.strip().lower()
    emit(GIT_OBSERVE, "complete", head=head)
    return head


def tracked_dirty(repo: Path) -> bool:
    result = _git(repo, ["status", "--porcelain"])
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        code = line[:2]
        if code[0] not in {"?", "!"} or code[1] not in {"?", " "}:
            if not line.startswith("??") and not line.startswith("!!"):
                return True
    return False


def assert_tracked_clean(repo: Path) -> None:
    if tracked_dirty(repo):
        raise GesError(WORKTREE_DIRTY, "tracked tree is dirty")


def origin_slug(repo: Path) -> str:
    result = _git(repo, ["remote", "get-url", "origin"])
    url = (result.stdout or "").strip()
    match = re.search(r"[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$", url)
    if not match:
        return ""
    return f"{match.group('owner')}/{match.group('repo')}"
