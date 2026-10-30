from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges import __product_version__
from ges.errors import (
    APPROVAL_REQUIRED_UNSUPPORTED,
    ARTIFACT_STALE,
    CI_CHECK_PENDING,
    EVIDENCE_SUBJECT_MISMATCH,
    LOCAL_HEAD_CHANGED_DURING_EVALUATION,
    PR_HEAD_CHANGED_DURING_EVALUATION,
    PR_HEAD_MISMATCH,
    PR_WORK_BINDING_CONFLICT,
    PR_WORK_BINDING_MISSING,
    REQUIRED_ARTIFACT_MISSING,
    REVIEW_REQUIRED,
    WORKTREE_DIRTY,
)
from ges.governance.artifacts import artifact_status
from ges.governance.evidence import collect_evidence
from ges.governance.git_observe import local_head, tracked_dirty
from ges.governance.github_provider import view_pr
from ges.governance.policy import evaluate_intake as policy_intake
from ges.governance.policy import evaluate_merge_risk, load_and_validate_policy
from ges.governance.reasons import reason, sort_reasons
from ges.governance.storage import load_work
from ges.reconciler.state import validate_payload
from ges.stagelog import GATE_EXPLAIN, GATE_INTAKE, GATE_MERGE, emit

HINTS = {
    ARTIFACT_STALE: "Re-link the artifact after the file bytes change.",
    REQUIRED_ARTIFACT_MISSING: "Link SPEC and PLAN with ges artifact link.",
    REVIEW_REQUIRED: "Obtain an APPROVED GitHub review decision on the PR.",
    CI_CHECK_PENDING: "Wait for required checks to finish successfully.",
    PR_WORK_BINDING_MISSING: "Add the exact GES-Work marker to the PR body.",
    PR_WORK_BINDING_CONFLICT: "This PR declares a different Work ID.",
    PR_HEAD_MISMATCH: "Check out the PR head commit locally.",
    WORKTREE_DIRTY: "Commit or stash tracked changes before merge gate.",
    APPROVAL_REQUIRED_UNSUPPORTED: "HIGH risk cannot merge in Alpha.2.",
}


# @lat: [[governance-backplane]]
def evaluate_intake(repo: Path, work_id: str) -> dict[str, Any]:
    emit(GATE_INTAKE, "start", work_id=work_id)
    work = load_work(repo, work_id)
    policy = load_and_validate_policy(repo)
    states = {kind: artifact_status(repo, work, kind)[1] for kind in ("SPEC", "PLAN")}
    reasons = sort_reasons(policy_intake(policy, work, states))
    status = "PASS" if not reasons else "FAIL"
    payload = _result(
        gate="INTAKE",
        work_id=work_id,
        status=status,
        verdict="WORK_READY" if status == "PASS" else "BLOCKED",
        subject_sha="",
        reasons=reasons,
    )
    emit(GATE_INTAKE, "complete", status=status)
    return payload


def evaluate_merge(repo: Path, work_id: str, pr_number: int) -> dict[str, Any]:
    emit(GATE_MERGE, "start", work_id=work_id, pr=pr_number)
    captured_at = datetime.now(timezone.utc).isoformat()
    t0_local = local_head(repo)
    work = load_work(repo, work_id)
    policy = load_and_validate_policy(repo)
    intake = evaluate_intake(repo, work_id)
    reasons: list[dict[str, Any]] = []
    if intake["status"] != "PASS":
        reasons.extend(intake["reasons"])
    reasons.extend(evaluate_merge_risk(policy, work))
    high = work.get("risk") == "HIGH"
    dirty = tracked_dirty(repo)
    if dirty and policy["merge"]["local"]["require_clean_tracked_tree"]:
        reasons.append(reason(WORKTREE_DIRTY, "git.status", "clean tracked", "dirty", "git", HINTS[WORKTREE_DIRTY]))
    pr = view_pr(repo, pr_number)
    t0_pr = str(pr.get("headRefOid") or "").lower()
    reasons.extend(_pr_reasons(policy, work_id, pr))
    if policy["merge"]["local"]["require_head_equals_pr_head"] and t0_local != t0_pr:
        reasons.append(reason(PR_HEAD_MISMATCH, "git.HEAD", t0_pr, t0_local, "git+github", HINTS[PR_HEAD_MISMATCH]))
    snapshot = collect_evidence(repo, work_id, pr_number)
    if snapshot["subject_sha"] != t0_pr:
        reasons.append(reason(EVIDENCE_SUBJECT_MISMATCH, "evidence.subject_sha", t0_pr, snapshot["subject_sha"], "github", "Re-collect evidence against current PR head."))
    reasons.extend(_check_reasons(policy, snapshot))
    if snapshot["review"]["status"] != "PASS":
        reasons.append(reason(REVIEW_REQUIRED, "review.decision", "APPROVED", snapshot["review"].get("decision"), "github", HINTS[REVIEW_REQUIRED]))
    rechecked_at = datetime.now(timezone.utc).isoformat()
    later_local = local_head(repo)
    later_pr = str(view_pr(repo, pr_number).get("headRefOid") or "").lower()
    if later_local != t0_local:
        reasons.append(reason(LOCAL_HEAD_CHANGED_DURING_EVALUATION, "git.HEAD", t0_local, later_local, "git", "Re-run the gate after local HEAD stabilizes."))
    if later_pr != t0_pr:
        reasons.append(reason(PR_HEAD_CHANGED_DURING_EVALUATION, "pr.headRefOid", t0_pr, later_pr, "github", "Re-run the gate after the PR head stabilizes."))
    reasons = sort_reasons(reasons)
    blocked_codes = {
        APPROVAL_REQUIRED_UNSUPPORTED,
        LOCAL_HEAD_CHANGED_DURING_EVALUATION,
        PR_HEAD_CHANGED_DURING_EVALUATION,
    }
    if any(item["code"] in blocked_codes for item in reasons) or high:
        status, verdict = "BLOCKED", "BLOCKED"
    elif reasons:
        status, verdict = "FAIL", "BLOCKED"
    else:
        status, verdict = "PASS", "MERGE_READY"
    payload = _result(
        gate="MERGE",
        work_id=work_id,
        status=status,
        verdict=verdict,
        subject_sha=t0_pr,
        reasons=reasons,
        captured_at=captured_at,
        rechecked_at=rechecked_at,
    )
    emit(GATE_MERGE, "complete", status=status, verdict=verdict)
    return payload


def explain_gate(repo: Path, work_id: str, *, gate: str, pr_number: int | None = None) -> dict[str, Any]:
    emit(GATE_EXPLAIN, "start", work_id=work_id, gate=gate)
    if gate == "intake":
        payload = evaluate_intake(repo, work_id)
    else:
        if pr_number is None:
            raise ValueError("merge explain requires --pr")
        payload = evaluate_merge(repo, work_id, pr_number)
    emit(GATE_EXPLAIN, "complete", reasons=len(payload["reasons"]))
    return payload


def exit_code_for(result: dict[str, Any]) -> int:
    if result["status"] == "PASS":
        return 0
    if result["status"] == "BLOCKED":
        return 3
    return 2


def _pr_reasons(policy: dict[str, Any], work_id: str, pr: dict[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    merge = policy["merge"]["pr"]
    if merge["require_open"] and str(pr.get("state") or "").upper() != "OPEN":
        reasons.append(reason("PR_NOT_OPEN", "pr.state", "OPEN", pr.get("state"), "github", "Use an OPEN pull request."))
    if merge["require_not_draft"] and pr.get("isDraft") is True:
        reasons.append(reason("PR_IS_DRAFT", "pr.isDraft", False, True, "github", "Mark the PR as ready for review."))
    marker = merge["work_marker"].replace("{work_id}", work_id)
    body = pr.get("body") or ""
    if merge["require_work_marker"]:
        if marker not in body:
            other = [line.strip() for line in body.splitlines() if line.strip().startswith("GES-Work:")]
            if other:
                reasons.append(reason(PR_WORK_BINDING_CONFLICT, "pr.body", marker, other[0], "github", HINTS[PR_WORK_BINDING_CONFLICT]))
            else:
                reasons.append(reason(PR_WORK_BINDING_MISSING, "pr.body", marker, "", "github", HINTS[PR_WORK_BINDING_MISSING]))
    return reasons


def _check_reasons(policy: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    checks = snapshot["checks"]
    rules = policy["merge"]["checks"]
    reasons: list[dict[str, Any]] = []
    success = [item for item in checks if item["status"] == "PASS"]
    pending = [item for item in checks if item["status"] == "PENDING"]
    failed = [item for item in checks if item["status"] == "FAIL"]
    skipped = [item for item in checks if item["status"] == "SKIPPED"]
    if len(success) < rules["min_successful"]:
        reasons.append(reason("CI_SUCCESS_BELOW_MIN", "checks.success", rules["min_successful"], len(success), "github", "Need at least one SUCCESS check; SKIPPED does not count."))
    if pending and not rules["allow_pending"]:
        reasons.append(reason(CI_CHECK_PENDING, "checks.pending", 0, len(pending), "github", HINTS[CI_CHECK_PENDING]))
    if failed and not rules["allow_failed"]:
        reasons.append(reason("CI_CHECK_FAILED", "checks.failed", 0, len(failed), "github", "Fix failing checks."))
    if skipped and not rules["allow_skipped_as_success"] and not success:
        reasons.append(reason("CI_SKIPPED_ONLY", "checks.skipped", ">=1 SUCCESS", len(skipped), "github", "SKIPPED is not SUCCESS."))
    cancelled = [item for item in checks if item["conclusion"] in {"CANCELLED", "CANCELED"}]
    if cancelled and not rules["allow_cancelled"]:
        reasons.append(reason("CI_CHECK_CANCELLED", "checks.cancelled", 0, len(cancelled), "github", "Re-run cancelled checks."))
    return reasons


def _result(
    *,
    gate: str,
    work_id: str,
    status: str,
    verdict: str,
    subject_sha: str,
    reasons: list[dict[str, Any]],
    captured_at: str = "",
    rechecked_at: str = "",
) -> dict[str, Any]:
    payload = {
        "schema": "ges.gate-result.v1",
        "gate": gate,
        "work_id": work_id,
        "status": status,
        "verdict": verdict,
        "subject_sha": subject_sha,
        "reasons": reasons,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": __product_version__,
    }
    if captured_at:
        payload["captured_at"] = captured_at
    if rechecked_at:
        payload["rechecked_at"] = rechecked_at
    validate_payload("ges.gate-result.v1.json", payload)
    return payload
