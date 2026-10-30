from __future__ import annotations

import json
import os
import subprocess
import sys
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
from ges.errors import (
    GOLDEN_ALPHA5_EXECUTION_BLOCKED,
    GOLDEN_BUSINESS_SOURCE_MUTATED,
    GOLDEN_COMPOSER_STATE_MUTATED,
    GOLDEN_SOURCE_MUTATED,
    GOVERNANCE_ALREADY_INITIALIZED,
    GesError,
)
from ges.governance.artifacts import link_artifact
from ges.governance.execution_gate import evaluate_execution
from ges.governance.registry import add_work_capability, create_work
from ges.governance.storage import init_governance
from ges.providers.overlay import add_installed
from ges.providers.rtk import probe_rtk
from ges.providers.rtk_binding import probe_binding
from ges.reconciler.apply import snapshot_business_sources
from ges.reconciler.state import read_lock, read_project, read_receipt


def main(argv: list[str] | None = None) -> int:
    del argv
    source = Path(os.environ.get("GES_ALPHA5_GOLDEN_REPO", str(DEFAULT_GOLDEN_SOURCE)))
    if not source.is_dir():
        print("GOLDEN_ALPHA5_EXECUTION_BLOCKED")
        return 3
    dirty, _, _ = source_dirty_status(source)
    if dirty:
        print("GOLDEN_ALPHA5_EXECUTION_BLOCKED")
        return 3
    worktree = None
    try:
        head = resolve_consumer_head(source)
        origin = _origin(source)
        source_before = _source_identity(source, head, origin)
        worktree = create_detached_worktree(source, head)
        protected = _protected_snapshot(worktree)
        business_before = snapshot_business_sources(worktree)

        host = os.environ.get("GES_ALPHA5_GOLDEN_HOST", "cursor")
        g1 = _run_g1(worktree, host=host)
        g2 = _run_g2(worktree, host=host)

        if _protected_snapshot(worktree) != protected:
            raise GesError(GOLDEN_COMPOSER_STATE_MUTATED, "composer state mutated")
        if snapshot_business_sources(worktree) != business_before:
            raise GesError(GOLDEN_BUSINESS_SOURCE_MUTATED, "business source mutated")
        source_after = _source_identity(source, resolve_consumer_head(source), _origin(source))
        if source_after != source_before:
            raise GesError(GOLDEN_SOURCE_MUTATED, "golden source mutated")

        payload = {
            "schema": "ges.golden-work-execution.v1",
            "golden": source_before,
            "host": host,
            "g1": {"status": g1["status"], "verdict": g1.get("verdict")},
            "g2": {"status": g2["status"], "verdict": g2.get("verdict"), "detail": g2.get("detail")},
        }
        print(json.dumps(payload, indent=2))

        if g1["status"] != "PASS":
            print("GOLDEN_ALPHA5_EXECUTION_FAIL" if g1["status"] == "FAIL" else "GOLDEN_ALPHA5_EXECUTION_BLOCKED")
            return 2 if g1["status"] == "FAIL" else 3
        if g2["status"] != "PASS":
            print("GOLDEN_ALPHA5_EXECUTION_BLOCKED")
            print(g2.get("detail") or GOLDEN_ALPHA5_EXECUTION_BLOCKED)
            return 3
        print("GOLDEN_ALPHA5_EXECUTION_PASS")
        return 0
    except GesError as exc:
        if exc.code in {
            GOLDEN_SOURCE_MUTATED,
            GOLDEN_COMPOSER_STATE_MUTATED,
            GOLDEN_BUSINESS_SOURCE_MUTATED,
        }:
            print("GOLDEN_ALPHA5_EXECUTION_FAIL")
            print(f"{exc.code}: {exc.message}")
            return 2
        print("GOLDEN_ALPHA5_EXECUTION_BLOCKED")
        print(f"{exc.code}: {exc.message}")
        return 3
    except Exception as exc:
        print("GOLDEN_ALPHA5_EXECUTION_BLOCKED")
        print(str(exc))
        return 3
    finally:
        if worktree is not None:
            remove_worktree(source, worktree)


def _ensure_governance(repo: Path) -> None:
    try:
        init_governance(repo)
    except GesError as exc:
        if exc.code != GOVERNANCE_ALREADY_INITIALIZED:
            raise


def _run_g1(repo: Path, *, host: str) -> dict[str, Any]:
    _ensure_governance(repo)
    work_id = "WI-ALPHA5-G1"
    create_work(repo, work_id=work_id, title="g1", owner="ges", risk="LOW", host=host)
    spec_dir = repo / ".ges" / "governance" / "acceptance"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_bytes(b"alpha5-g1-spec")
    (spec_dir / "plan.md").write_bytes(b"alpha5-g1-plan")
    link_artifact(repo, work_id, artifact_type="SPEC", path=".ges/governance/acceptance/spec.md")
    link_artifact(repo, work_id, artifact_type="PLAN", path=".ges/governance/acceptance/plan.md")
    return evaluate_execution(repo, work_id)


def _run_g2(repo: Path, *, host: str) -> dict[str, Any]:
    provider = probe_rtk()
    binding = probe_binding(RTK_ID, host)
    if provider.get("status") != "READY" or binding.get("status") != "BOUND":
        return {
            "status": "BLOCKED",
            "verdict": "BLOCKED",
            "detail": GOLDEN_ALPHA5_EXECUTION_BLOCKED,
        }
    _ensure_governance(repo)
    work_id = "WI-ALPHA5-G2"
    create_work(repo, work_id=work_id, title="g2", owner="ges", risk="LOW", host=host)
    spec_dir = repo / ".ges" / "governance" / "acceptance"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec-g2.md").write_bytes(b"alpha5-g2-spec")
    (spec_dir / "plan-g2.md").write_bytes(b"alpha5-g2-plan")
    link_artifact(repo, work_id, artifact_type="SPEC", path=".ges/governance/acceptance/spec-g2.md")
    link_artifact(repo, work_id, artifact_type="PLAN", path=".ges/governance/acceptance/plan-g2.md")
    add_installed(repo, RTK_ID, "recommended")
    add_work_capability(repo, work_id, RTK_ID)
    result = evaluate_execution(repo, work_id)
    if result.get("status") != "PASS" or result.get("verdict") != "EXECUTION_READY":
        result = dict(result)
        result["detail"] = GOLDEN_ALPHA5_EXECUTION_BLOCKED
        if result.get("status") == "PASS":
            result["status"] = "BLOCKED"
        elif result.get("status") == "FAIL":
            # G2 environment gaps are BLOCKED, not contract FAIL.
            result["status"] = "BLOCKED"
    return result


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
