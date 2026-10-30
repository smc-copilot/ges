from __future__ import annotations

from pathlib import Path

from ges.errors import MANAGED_CONTENT_MODIFIED, GesError
from ges.harness_adapters.agents_md import remove_marker, section_hash
from ges.io import sha256_file, write_text
from ges.governance.paths import is_governance_rel
from ges.paths import PRESERVE_ALWAYS
from ges.reconciler.guard import assert_allowed, contain
from ges.reconciler.hashes import artifact_index
from ges.reconciler.state import read_receipt
from ges.stagelog import REMOVE, emit


def run_remove(repo: Path) -> list[str]:
    emit(REMOVE, "start", repo=str(repo))
    repo = repo.expanduser().resolve()
    receipt = read_receipt(repo)
    if receipt:
        _preflight(repo, receipt)
    removed: list[str] = []
    if receipt:
        for rel, meta in artifact_index(receipt).items():
            if any(rel.startswith(prefix.rstrip("/") + "/") or rel == prefix.rstrip("/") for prefix in PRESERVE_ALWAYS):
                continue
            if meta.get("ownership_type") == "SECTION" or rel == "AGENTS.md":
                path = repo / rel
                if path.is_file():
                    write_text(path, remove_marker(path.read_text(encoding="utf-8")))
                    removed.append(rel)
                continue
            assert_allowed(rel)
            target = contain(repo, rel)
            if target.is_file():
                target.unlink()
                removed.append(rel)
                _prune_empty(repo, target.parent)
    ges_dir = repo / ".ges"
    if ges_dir.exists():
        preserved = False
        for path in sorted(ges_dir.rglob("*"), reverse=True):
            rel = path.relative_to(repo).as_posix()
            if is_governance_rel(rel):
                preserved = True
                continue
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        if preserved:
            print("governance data preserved at .ges/governance/")
            emit(REMOVE, "governance-preserved", path=".ges/governance/")
        elif ges_dir.exists():
            remaining = list(ges_dir.rglob("*"))
            if not remaining:
                ges_dir.rmdir()
                removed.append(".ges/")
    emit(REMOVE, "complete", removed=len(removed))
    return removed


def _preflight(repo: Path, receipt: dict) -> None:
    for rel, meta in artifact_index(receipt).items():
        if any(rel.startswith(prefix.rstrip("/") + "/") or rel == prefix.rstrip("/") for prefix in PRESERVE_ALWAYS):
            continue
        path = repo / rel
        last = meta.get("last_applied_hash")
        if last is None or not path.is_file():
            continue
        current = (
            section_hash(path.read_text(encoding="utf-8"))
            if meta.get("ownership_type") == "SECTION" or rel == "AGENTS.md"
            else sha256_file(path)
        )
        if current != last:
            raise GesError(
                MANAGED_CONTENT_MODIFIED,
                f"managed content was modified: {rel}",
                details={"path": rel},
            )


def _prune_empty(repo: Path, directory: Path) -> None:
    root = repo.resolve()
    current = directory
    while current != root and current.exists():
        if any(current.iterdir()):
            return
        current.rmdir()
        current = current.parent
