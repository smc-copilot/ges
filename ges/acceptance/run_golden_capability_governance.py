from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from ges.acceptance.golden_worktree import (
    DEFAULT_GOLDEN_SOURCE,
    create_detached_worktree,
    remove_worktree,
    resolve_consumer_head,
    source_dirty_status,
)
from ges.catalog.providers import RTK_ID
from ges.cli.capability import run_add, run_doctor, run_list, run_remove
from ges.errors import (
    GOLDEN_BUSINESS_SOURCE_MUTATED,
    GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED,
    GOLDEN_COMPOSER_STATE_MUTATED,
    GOLDEN_OVERLAY_CONTRACT_FAILED,
    GOLDEN_SOURCE_MUTATED,
    GesError,
)
from ges.paths import capability_policy_path, installed_path
from ges.providers.overlay import read_installed, read_policy
from ges.reconciler.apply import consumer_tree, snapshot_business_sources
from ges.reconciler.state import read_lock, read_project, read_receipt


PROTECTED_PREFIXES = (".ges/project.yaml", ".ges/lock.json", ".ges/install-receipt.json")


def main(argv: list[str] | None = None) -> int:
    del argv
    source = Path(os.environ.get("GES_ALPHA4_GOLDEN_REPO", str(DEFAULT_GOLDEN_SOURCE)))
    if not source.is_dir():
        print("GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED")
        return 3
    dirty, _, _ = source_dirty_status(source)
    if dirty:
        print("GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED")
        return 3
    worktree = None
    try:
        head = resolve_consumer_head(source)
        origin = _origin(source)
        source_before = _source_identity(source, head, origin)
        worktree = create_detached_worktree(source, head)
        protected = _protected_snapshot(worktree)
        business_before = snapshot_business_sources(worktree)
        tree_before_list = consumer_tree(worktree)

        if run_list(Namespace(repo=str(worktree), json=True)) != 0:
            raise GesError(GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED, "capability list failed")
        if consumer_tree(worktree) != tree_before_list:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "list mutated consumer tree")

        if run_add(Namespace(repo=str(worktree), id=RTK_ID)) != 0:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "capability add failed")
        if read_installed(worktree).get("installed") != [RTK_ID]:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "first add did not install rtk")
        if not capability_policy_path(worktree).is_file():
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "add did not create policy")

        if run_doctor(Namespace(repo=str(worktree), id=RTK_ID)) != 0:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "capability doctor failed")

        if run_add(Namespace(repo=str(worktree), id=RTK_ID)) != 0:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "idempotent add failed")
        if read_installed(worktree).get("installed") != [RTK_ID]:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "repeat add changed installed rows")

        policy_before_remove = read_policy(worktree)
        if run_remove(Namespace(repo=str(worktree), id=RTK_ID)) != 0:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "capability remove failed")
        if read_installed(worktree).get("installed") != []:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "remove did not clear installed")
        if not installed_path(worktree).is_file():
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "remove deleted installed file")
        if read_policy(worktree) != policy_before_remove:
            raise GesError(GOLDEN_OVERLAY_CONTRACT_FAILED, "remove mutated policy")

        if run_list(Namespace(repo=str(worktree), json=True)) != 0:
            raise GesError(GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED, "final list failed")

        if _protected_snapshot(worktree) != protected:
            raise GesError(GOLDEN_COMPOSER_STATE_MUTATED, "composer state mutated")
        if snapshot_business_sources(worktree) != business_before:
            raise GesError(GOLDEN_BUSINESS_SOURCE_MUTATED, "business source mutated")
        source_after = _source_identity(source, resolve_consumer_head(source), _origin(source))
        if source_after != source_before:
            raise GesError(GOLDEN_SOURCE_MUTATED, "golden source mutated")

        print(
            json.dumps(
                {
                    "schema": "ges.golden-capability-governance.v1",
                    "golden": source_before,
                    "lifecycle": "list-add-doctor-add-remove-list",
                },
                indent=2,
            )
        )
        print("GOLDEN_CAPABILITY_GOVERNANCE_PASS")
        return 0
    except GesError as exc:
        marker = (
            "GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED"
            if exc.code
            in {
                GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED,
                "GOLDEN_CONSUMER_HEAD_UNRESOLVED",
            }
            or "BLOCKED" in exc.code
            else "GOLDEN_CAPABILITY_GOVERNANCE_FAIL"
        )
        if exc.code in {
            GOLDEN_SOURCE_MUTATED,
            GOLDEN_COMPOSER_STATE_MUTATED,
            GOLDEN_BUSINESS_SOURCE_MUTATED,
            GOLDEN_OVERLAY_CONTRACT_FAILED,
        }:
            marker = "GOLDEN_CAPABILITY_GOVERNANCE_FAIL"
            print(marker)
            print(f"{exc.code}: {exc.message}")
            return 2
        print("GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED")
        print(f"{exc.code}: {exc.message}")
        return 3
    except Exception as exc:
        print("GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED")
        print(str(exc))
        return 3
    finally:
        if worktree is not None:
            remove_worktree(source, worktree)


def _origin(repo: Path) -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout or "").strip()


def _source_identity(repo: Path, head: str, origin: str) -> dict[str, Any]:
    dirty, _, digest = source_dirty_status(repo)
    return {
        "source_path": str(repo),
        "origin": origin,
        "head_sha": head,
        "source_clean": not dirty,
        "status_digest": digest,
    }


def _protected_snapshot(repo: Path) -> dict[str, Any]:
    return {
        "lock": read_lock(repo),
        "project": read_project(repo),
        "receipt": read_receipt(repo),
        "requested": list((read_lock(repo) or {}).get("requested") or []),
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
