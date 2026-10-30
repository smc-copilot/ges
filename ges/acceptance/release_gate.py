from __future__ import annotations

from pathlib import Path

from ges.acceptance.golden_worktree import git
from ges.errors import RELEASE_DOCUMENTATION_STALE, RELEASE_TAG_COMMIT_MISMATCH, GesError
from ges.stagelog import DOC_STATUS_CHECK, TAG_VERIFY, emit

STALE_CURRENT_STATUS_PHRASES = (
    "A27 remains BLOCKED while the Golden Consumer is dirty",
    "Golden Consumer: BLOCKED",
    "Bootstrap Closure NOT READY",
)
REQUIRED_PRE_TAG_PHRASES = (
    "Alpha.1 Functionally Complete",
    "PENDING RELEASE HARDENING",
)
CURRENT_STATUS_ROOTS = ("lat.md/ges6",)
TAG_NAME = "ges-v6.0.0-alpha.1"


def scan_current_status_docs(root: Path) -> list[str]:
    emit(DOC_STATUS_CHECK, "start")
    hits: list[str] = []
    for rel in CURRENT_STATUS_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        paths = [base] if base.is_file() else list(base.rglob("*.md"))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for phrase in STALE_CURRENT_STATUS_PHRASES:
                if phrase in text:
                    hits.append(f"{path.relative_to(root).as_posix()}: {phrase}")
    status = "PASS" if not hits else "FAIL"
    emit(DOC_STATUS_CHECK, "complete", status=status, hits=len(hits))
    return hits


# @lat: [[release-hardening#Documentation Truth]]
def assert_current_status_current(root: Path) -> None:
    hits = scan_current_status_docs(root)
    missing = missing_pre_tag_status(root)
    if hits or missing:
        raise GesError(
            RELEASE_DOCUMENTATION_STALE,
            (hits or missing)[0],
            details={"hits": hits, "missing": missing},
        )


def missing_pre_tag_status(root: Path) -> list[str]:
    text = (root / "lat.md" / "ges6" / "ges6.md").read_text(encoding="utf-8") if (root / "lat.md" / "ges6" / "ges6.md").is_file() else ""
    return [phrase for phrase in REQUIRED_PRE_TAG_PHRASES if phrase not in text]


# @lat: [[release-hardening#Tag Gate]]
def verify_tag_target(repo: Path, candidate_sha: str, tag: str = TAG_NAME) -> str:
    emit(TAG_VERIFY, "start", tag=tag, candidate_sha=candidate_sha)
    result = git(repo, ["rev-list", "-n", "1", tag])
    target = result.stdout.strip()
    if result.returncode != 0 or target != candidate_sha:
        emit(TAG_VERIFY, "complete", status="FAIL")
        raise GesError(
            RELEASE_TAG_COMMIT_MISMATCH,
            f"{tag} points at {target or 'unresolved'} not {candidate_sha}",
        )
    emit(TAG_VERIFY, "complete", status="PASS", target=target)
    return target
