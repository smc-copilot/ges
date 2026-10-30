from __future__ import annotations

from pathlib import Path
from typing import Any

from ges.errors import EVIDENCE_SUBJECT_MISMATCH, UNSUPPORTED_OPERATION, GesError
from ges.governance.git_observe import origin_slug
from ges.governance.github_provider import view_pr
from ges.governance.storage import load_work
from ges.reconciler.state import validate_payload
from ges.stagelog import EVIDENCE_RESOLVE, emit

SUCCESS = {"SUCCESS", "COMPLETED"}
PENDING = {"PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED"}
FAIL = {"FAILURE", "TIMED_OUT", "CANCELLED", "CANCELED", "ACTION_REQUIRED", "ERROR", "STARTUP_FAILURE"}
SKIPPED = {"SKIPPED", "NEUTRAL", "STALE"}


def collect_evidence(repo: Path, work_id: str, pr_number: int) -> dict[str, Any]:
    emit(EVIDENCE_RESOLVE, "start", work_id=work_id, pr=pr_number)
    load_work(repo, work_id)
    pr = view_pr(repo, pr_number)
    subject = str(pr.get("headRefOid") or "").lower()
    checks = []
    for item in _iter_checks(pr.get("statusCheckRollup")):
        conclusion = str(item.get("conclusion") or item.get("state") or item.get("status") or "").upper()
        name = str(item.get("name") or item.get("context") or "check")
        check_sha = str(item.get("commit", {}).get("oid") or item.get("sha") or subject).lower()
        if len(check_sha) == 40 and check_sha != subject:
            raise GesError(EVIDENCE_SUBJECT_MISMATCH, f"check {name} subject {check_sha} != PR head {subject}")
        checks.append(
            {
                "type": "CI_CHECK",
                "name": name,
                "conclusion": conclusion or "UNKNOWN",
                "status": map_check_status(conclusion),
                "subject_sha": subject,
            }
        )
    decision = pr.get("reviewDecision")
    review_status = map_review_status(decision)
    snapshot = {
        "schema": "ges.evidence-snapshot.v1",
        "work_id": work_id,
        "repo": origin_slug(repo),
        "pr_number": pr_number,
        "subject_sha": subject,
        "review": {"type": "REVIEW_DECISION", "status": review_status, "decision": decision},
        "checks": checks,
    }
    validate_payload("ges.evidence-snapshot.v1.json", snapshot)
    emit(EVIDENCE_RESOLVE, "complete", checks=len(checks), review=review_status)
    return snapshot


def map_check_status(conclusion: str) -> str:
    value = conclusion.upper()
    if value in SUCCESS:
        return "PASS"
    if value in PENDING:
        return "PENDING"
    if value in FAIL:
        return "FAIL"
    if value in SKIPPED:
        return "SKIPPED"
    return "FAIL"


def map_review_status(decision: Any) -> str:
    if decision == "APPROVED":
        return "PASS"
    if decision == "CHANGES_REQUESTED":
        return "FAIL"
    return "MISSING"


def _iter_checks(rollup: Any) -> list[dict[str, Any]]:
    if rollup is None:
        return []
    if isinstance(rollup, list):
        return [item for item in rollup if isinstance(item, dict)]
    if isinstance(rollup, dict):
        contexts = rollup.get("contexts") or rollup.get("nodes") or []
        return [item for item in contexts if isinstance(item, dict)]
    return []


def reject_manual_add() -> None:
    raise GesError(UNSUPPORTED_OPERATION, "ges evidence add is not supported")
