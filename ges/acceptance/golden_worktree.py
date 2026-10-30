from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from ges.errors import GOLDEN_CONSUMER_HEAD_UNRESOLVED, GesError
from ges.io import sha256_file
from ges.stagelog import GOLDEN_RESOLVE, GOLDEN_WORKTREE_CLEANUP, GOLDEN_WORKTREE_CREATE, emit

DEFAULT_GOLDEN_SOURCE = Path(r"E:\git\smc-copilot-desktop")


def git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def resolve_consumer_head(source: Path) -> str:
    emit(GOLDEN_RESOLVE, "start", source=str(source))
    if not source.is_dir():
        raise GesError(GOLDEN_CONSUMER_HEAD_UNRESOLVED, f"Golden Consumer path missing: {source}")
    result = git(source, ["rev-parse", "HEAD"])
    head = result.stdout.strip()
    if result.returncode != 0 or len(head) != 40:
        raise GesError(GOLDEN_CONSUMER_HEAD_UNRESOLVED, f"could not resolve HEAD in {source}")
    emit(GOLDEN_RESOLVE, "complete", commit_sha=head)
    return head


def source_dirty_status(source: Path) -> tuple[bool, str, str]:
    porcelain = git(source, ["status", "--porcelain"]).stdout
    digest = hashlib.sha256(porcelain.encode("utf-8")).hexdigest()
    return bool(porcelain.strip()), porcelain, digest


def source_branch(source: Path) -> str:
    result = git(source, ["symbolic-ref", "--short", "-q", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "DETACHED"


def workspace_identity(repo: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    listed = git(repo, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    names = [name for name in listed.stdout.split("\0") if name]
    for rel in names:
        path = repo / rel
        if not path.is_file():
            continue
        if rel.startswith(".git/"):
            continue
        out[rel.replace("\\", "/")] = f"{path.stat().st_size}:{sha256_file(path)}"
    return out


def create_detached_worktree(source: Path, head: str) -> Path:
    emit(GOLDEN_WORKTREE_CREATE, "start", head=head)
    temp = Path(tempfile.mkdtemp(prefix="ges-golden-wt-"))
    temp.rmdir()
    result = git(source, ["worktree", "add", "--detach", str(temp), head])
    if result.returncode != 0:
        raise GesError(
            GOLDEN_CONSUMER_HEAD_UNRESOLVED,
            f"git worktree add failed: {result.stderr.strip() or result.stdout.strip()}",
        )
    emit(GOLDEN_WORKTREE_CREATE, "complete", path=str(temp))
    return temp


def worktree_clean(repo: Path) -> bool:
    return not git(repo, ["status", "--porcelain"]).stdout.strip()


def remove_worktree(source: Path, worktree: Path) -> None:
    emit(GOLDEN_WORKTREE_CLEANUP, "start", path=str(worktree))
    git(source, ["worktree", "remove", "--force", str(worktree)])
    emit(GOLDEN_WORKTREE_CLEANUP, "complete")
