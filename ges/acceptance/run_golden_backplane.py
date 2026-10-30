from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ges.acceptance.backplane_evidence import write_backplane_evidence
from ges.acceptance.golden_worktree import DEFAULT_GOLDEN_SOURCE, create_detached_worktree, git, remove_worktree, resolve_consumer_head
from ges.acceptance.release_evidence import resolve_artifact_dir
from ges.errors import GITHUB_AUTH_UNAVAILABLE, GesError
from ges.governance.gates import evaluate_intake, evaluate_merge, exit_code_for
from ges.governance.git_observe import origin_slug
from ges.governance.github_provider import gh_auth_status, view_pr
from ges.governance.storage import policy_digest
from ges.governance.trace import build_trace


def main(argv: list[str] | None = None) -> int:
    work_id = os.environ.get("GES_ALPHA2_GOLDEN_WORK_ID", "")
    pr_raw = os.environ.get("GES_ALPHA2_GOLDEN_PR", "")
    source = Path(os.environ.get("GES_ALPHA2_GOLDEN_REPO", str(DEFAULT_GOLDEN_SOURCE)))
    artifact_dir = resolve_artifact_dir(os.environ.get("GES_RELEASE_EVIDENCE_DIR"))
    ges_root = Path(__file__).resolve().parents[2]
    candidate = git(ges_root, ["rev-parse", "HEAD"]).stdout.strip()
    acceptances: list[dict] = []
    if not work_id or not pr_raw:
        acceptances.append(_ac("A-A2-GOLDEN-PRE", "BLOCKED", "env", 3, "set", "missing GES_ALPHA2_GOLDEN_PR/WORK_ID"))
        write_backplane_evidence(
            artifact_dir=artifact_dir,
            candidate_sha=candidate if len(candidate) == 40 else "0" * 40,
            consumer_repo="",
            pr_number=None,
            pr_head="",
            work_id=work_id or "UNSET",
            policy_digest="",
            acceptances=acceptances,
        )
        print("GOLDEN_BACKPLANE_BLOCKED")
        return 3
    pr_number = int(pr_raw)
    worktree = None
    try:
        gh_auth_status()
        head = resolve_consumer_head(source)
        pr = view_pr(source, pr_number)
        pr_head = str(pr.get("headRefOid") or "").lower()
        worktree = create_detached_worktree(source, pr_head or head)
        intake = evaluate_intake(worktree, work_id)
        acceptances.append(_ac("A-A2-INTAKE-001", intake["status"] if intake["status"] != "FAIL" else "FAIL", "gate intake", exit_code_for(intake), "WORK_READY", intake["verdict"]))
        merge = evaluate_merge(worktree, work_id, pr_number)
        acceptances.append(_ac("A-A2-MERGE-001", merge["status"] if merge["verdict"] == "MERGE_READY" else merge["status"], "gate merge", exit_code_for(merge), "MERGE_READY", merge["verdict"]))
        build_trace(worktree, work_id, pr_number)
        acceptances.append(_ac("A-A2-TRACE-001", "PASS", "trace show", 0, True, True))
        write_backplane_evidence(
            artifact_dir=artifact_dir,
            candidate_sha=candidate,
            consumer_repo=origin_slug(source),
            pr_number=pr_number,
            pr_head=pr_head,
            work_id=work_id,
            policy_digest=policy_digest(worktree) if (worktree / ".ges" / "governance" / "policy.yaml").is_file() else "",
            acceptances=acceptances,
        )
        print(json.dumps({"intake": intake, "merge": merge}, indent=2))
        if merge["verdict"] == "MERGE_READY" and intake["verdict"] == "WORK_READY":
            print("BACKPLANE_ALPHA2_READY")
            return 0
        print("GOLDEN_BACKPLANE_BLOCKED")
        return exit_code_for(merge)
    except GesError as exc:
        status = "BLOCKED" if exc.exit_code == 3 or exc.code == GITHUB_AUTH_UNAVAILABLE else "FAIL"
        acceptances.append(_ac("A-A2-GOLDEN-RUN", status, "golden", exc.exit_code, "PASS", exc.code))
        write_backplane_evidence(
            artifact_dir=artifact_dir,
            candidate_sha=candidate if len(candidate) == 40 else "0" * 40,
            consumer_repo=origin_slug(source) if source.is_dir() else "",
            pr_number=pr_number,
            pr_head="",
            work_id=work_id,
            policy_digest="",
            acceptances=acceptances,
        )
        print("GOLDEN_BACKPLANE_BLOCKED")
        print(f"{exc.code}: {exc.message}")
        return exc.exit_code
    finally:
        if worktree is not None:
            remove_worktree(source, worktree)


def _ac(acceptance_id: str, status: str, command: str, exit_code: int, expected, actual) -> dict:
    return {
        "acceptance_id": acceptance_id,
        "status": status,
        "command": command,
        "exit_code": exit_code,
        "oracle": {"expected": expected, "actual": actual},
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
