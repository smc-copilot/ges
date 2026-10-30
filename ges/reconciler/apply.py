from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges import __distribution_version__, __product_version__, __version__
from ges.errors import (
    GES_RECONCILE_NOOP,
    TRANSACTION_ROLLBACK_FAILED,
    GesError,
)
from ges.io import sha256_file, write_bytes, write_json, write_yaml
from ges.governance.paths import is_governance_rel
from ges.paths import LOCK_FILE, PROJECT_FILE, RECEIPT_FILE, REPO_PROFILE_FILE
from ges.reconciler.business_guard import (
    assert_business_unchanged,
    capture_business_snapshot,
    format_guard_summary,
    snapshot_business_sources,
)
from ges.reconciler.mutation import MutationLedger, new_ledger
from ges.reconciler.state import read_receipt
from ges.reconciler.guard import contain
from ges.reconciler.hashes import desired_identity
from ges.reconciler.plan import ADD, REMOVE, UPDATE, InstallPlan
from ges.reconciler.state import validate_payload
from ges.source_adapters.base import ProjectedFile
from ges.stagelog import COMPOSER_APPLY, RECONCILE, emit

GES_STATE_FILES = (PROJECT_FILE, REPO_PROFILE_FILE, LOCK_FILE, RECEIPT_FILE)


def apply_plan(
    repo: Path,
    plan: InstallPlan,
    desired: dict[str, ProjectedFile],
    *,
    project: dict[str, Any],
    profile: dict[str, Any],
    lock: dict[str, Any],
    force_noop_code: bool = True,
    fail_at: str | None = None,
    fail_after_writes: int = 3,
) -> dict[str, Any]:
    emit(RECONCILE, "start", repo=str(repo), noop=plan.noop)
    if plan.noop:
        if force_noop_code:
            raise GesError(GES_RECONCILE_NOOP, "desired state already matches current state")
        return read_or_empty_receipt(repo)

    transaction_id = str(uuid.uuid4())
    receipt = build_receipt(repo, desired, profile, lock, transaction_id=transaction_id)
    before = capture_business_snapshot(repo)
    ledger = new_ledger()
    stage = Path(tempfile.mkdtemp(prefix="ges-stage-"))
    backup = Path(tempfile.mkdtemp(prefix="ges-t0-"))
    ges_existed = (repo / ".ges").is_dir()
    keep_backup = False
    try:
        _stage_projection(stage, desired, project, profile, lock, receipt)
        if fail_at == "before_commit":
            raise RuntimeError("injected failure before_commit")
        t0 = snapshot_managed_scope(repo, desired, plan)
        _persist_snapshot(backup, t0)
        try:
            emit(COMPOSER_APPLY, "start", transaction_id=transaction_id)
            _commit_stage(
                repo,
                stage,
                desired,
                changing={entry.path for entry in plan.changing()},
                fail_at=fail_at,
                fail_after_writes=fail_after_writes,
                ledger=ledger,
            )
            _apply_removes(repo, plan, ledger=ledger)
            emit(COMPOSER_APPLY, "complete", writes=len(ledger.entries))
            if fail_at in {"post_verify", "post_check", "rollback_write_failure"}:
                raise RuntimeError(f"injected failure {fail_at}")
            from ges.check import run_check

            run_check(repo)
            after = assert_business_unchanged(repo, before)
            print(format_guard_summary(before, after))
        except Exception:
            try:
                if fail_at == "rollback_write_failure":
                    raise RuntimeError("injected rollback_write_failure")
                _rollback(
                    repo,
                    t0,
                    extra_rels=set(desired) | {entry.path for entry in plan.entries},
                    ges_existed=ges_existed,
                    transaction_id=transaction_id,
                    backup=backup,
                )
            except GesError as rollback_error:
                if rollback_error.code == TRANSACTION_ROLLBACK_FAILED:
                    keep_backup = True
                raise
            except Exception as rollback_error:
                keep_backup = True
                raise GesError(
                    TRANSACTION_ROLLBACK_FAILED,
                    "failed to restore T0 snapshot after apply failure",
                    details={
                        "transaction_id": transaction_id,
                        "backup_location": str(backup),
                        "manual_recovery": f"Restore managed files from {backup}.",
                        "error": str(rollback_error),
                    },
                ) from rollback_error
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if not keep_backup:
            shutil.rmtree(backup, ignore_errors=True)
    emit(RECONCILE, "applied", changed=len(plan.changing()), transaction_id=transaction_id)
    return receipt


def build_receipt(
    repo: Path,
    desired: dict[str, ProjectedFile],
    profile: dict[str, Any],
    lock: dict[str, Any],
    *,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    artifacts = []
    for rel, item in sorted(desired.items()):
        identity = desired_identity(item)
        artifacts.append(
            {
                "path": rel,
                "ownership_type": item.ownership_type,
                "selector": item.selector,
                "last_applied_hash": identity,
                "generated_hash": identity,
                "producer": item.source or "ges",
                "capability_ids": [item.capability] if item.capability else [],
            }
        )
    return {
        "schema": "ges.install-receipt.v2",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "ges_version": __product_version__,
        "distribution_version": __distribution_version__,
        "transaction_id": transaction_id or str(uuid.uuid4()),
        "repo_identity": {
            "path": str(repo.resolve()),
            "kind": profile.get("kind") or profile.get("repository_kind"),
            "git_head": (profile.get("git") or {}).get("head"),
        },
        "managed_artifacts": artifacts,
        "source_commits": lock.get("sources") or {},
        "capability_set": lock.get("capabilities") or lock.get("resolved_capabilities") or [],
    }


def read_or_empty_receipt(repo: Path) -> dict[str, Any]:
    from ges.reconciler.state import read_receipt

    return read_receipt(repo) or {}


def snapshot_managed_scope(repo: Path, desired: dict[str, ProjectedFile], plan: InstallPlan) -> dict[str, bytes | None]:
    rels = {item.path for item in plan.entries}
    rels.update(desired)
    rels.add("AGENTS.md")
    for name in GES_STATE_FILES:
        rels.add(f".ges/{name}")
    receipt = read_receipt(repo)
    if receipt:
        for artifact in receipt.get("managed_artifacts") or []:
            path = artifact.get("path")
            if path:
                rels.add(path)
    snap: dict[str, bytes | None] = {}
    for rel in sorted(rels):
        if is_governance_rel(rel):
            continue
        path = repo / rel
        snap[rel] = path.read_bytes() if path.is_file() else None
    return snap


def consumer_tree(repo: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo).as_posix()
        out[rel] = f"{path.stat().st_size}:{sha256_file(path)}"
    return out


def _stage_projection(
    stage: Path,
    desired: dict[str, ProjectedFile],
    project: dict[str, Any],
    profile: dict[str, Any],
    lock: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    for rel, item in desired.items():
        write_bytes(stage / rel, item.content)
    ges = stage / ".ges"
    validate_payload("ges.project.v2.json", project)
    validate_payload("ges.repo-profile.v2.json", profile)
    validate_payload("ges.lock.v1.json", lock)
    validate_payload("ges.install-receipt.v2.json", receipt)
    write_yaml(ges / PROJECT_FILE, project)
    write_json(ges / REPO_PROFILE_FILE, profile)
    write_json(ges / LOCK_FILE, lock)
    write_json(ges / RECEIPT_FILE, receipt)


def _commit_stage(
    repo: Path,
    stage: Path,
    desired: dict[str, ProjectedFile],
    *,
    changing: set[str],
    fail_at: str | None,
    fail_after_writes: int,
    ledger: MutationLedger,
) -> None:
    written = 0
    for rel, item in sorted(desired.items()):
        if rel not in changing:
            continue
        ledger.write_file(repo, rel, item.content)
        written += 1
        if fail_at == "after_first_write" and written == 1:
            raise RuntimeError("injected failure after_first_write")
        if fail_at == "after_nth_write" and written == fail_after_writes:
            raise RuntimeError("injected failure after_nth_write")
    for name in (PROJECT_FILE, REPO_PROFILE_FILE, LOCK_FILE):
        ledger.write_file(repo, f".ges/{name}", (stage / ".ges" / name).read_bytes())
        written += 1
        if fail_at == "after_nth_write" and written == fail_after_writes:
            raise RuntimeError("injected failure after_nth_write")
    if fail_at == "before_receipt":
        raise RuntimeError("injected failure before_receipt")
    ledger.write_file(repo, f".ges/{RECEIPT_FILE}", (stage / ".ges" / RECEIPT_FILE).read_bytes())


def _apply_removes(repo: Path, plan: InstallPlan, *, ledger: MutationLedger) -> None:
    for entry in plan.entries:
        if entry.action != REMOVE:
            continue
        target = ledger.remove_file(repo, entry.path)
        if not target.exists():
            _prune_empty(repo, target.parent)


def _persist_snapshot(backup: Path, snap: dict[str, bytes | None]) -> None:
    for rel, content in snap.items():
        marker = backup / rel
        if content is None:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("ABSENT\n", encoding="utf-8")
            continue
        write_bytes(marker, content)


def _rollback(
    repo: Path,
    t0: dict[str, bytes | None],
    *,
    extra_rels: set[str],
    ges_existed: bool,
    transaction_id: str,
    backup: Path,
) -> None:
    failed: list[str] = []
    try:
        current = set(t0) | set(extra_rels)
        ges = repo / ".ges"
        if ges.is_dir():
            for path in ges.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(repo).as_posix()
                    if is_governance_rel(rel):
                        continue
                    current.add(rel)
        for rel, item in t0.items():
            target = repo / rel
            if item is None:
                if target.is_file():
                    target.unlink()
                continue
            write_bytes(target, item)
        for rel in sorted(current):
            if rel in t0 and t0[rel] is not None:
                continue
            target = repo / rel
            if target.is_file() and (rel not in t0 or t0[rel] is None):
                target.unlink()
                _prune_empty(repo, target.parent)
        if not ges_existed:
            _remove_ges_if_new(repo)
        elif ges_existed and not (repo / ".ges").exists():
            raise RuntimeError("pre-existing .ges disappeared during rollback")
    except Exception as exc:
        raise GesError(
            TRANSACTION_ROLLBACK_FAILED,
            "failed to restore T0 snapshot after apply failure",
            details={
                "transaction_id": transaction_id,
                "failed_paths": failed,
                "backup_location": str(backup),
                "manual_recovery": (
                    f"Restore managed files from {backup}. "
                    "Do not delete a pre-existing .ges directory."
                ),
                "error": str(exc),
            },
        ) from exc


def _remove_ges_if_new(repo: Path) -> None:
    ges = repo / ".ges"
    if not ges.exists():
        return
    for path in sorted(ges.rglob("*"), reverse=True):
        rel = path.relative_to(repo).as_posix()
        if is_governance_rel(rel):
            continue
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    if ges.exists() and not any(ges.rglob("*")):
        ges.rmdir()


def _prune_empty(repo: Path, directory: Path) -> None:
    root = repo.resolve()
    current = directory
    while current != root and current.exists():
        if any(current.iterdir()):
            return
        current.rmdir()
        current = current.parent
