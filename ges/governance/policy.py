from __future__ import annotations

from typing import Any

from ges.errors import APPROVAL_REQUIRED_UNSUPPORTED, POLICY_SCHEMA_INVALID, GesError
from ges.governance.reasons import reason
from ges.governance.storage import load_policy
from ges.reconciler.state import validate_payload


def load_and_validate_policy(repo) -> dict[str, Any]:
    payload = load_policy(repo)
    try:
        validate_payload("ges.policy.v1.json", payload, code=POLICY_SCHEMA_INVALID)
    except GesError as exc:
        raise GesError(POLICY_SCHEMA_INVALID, exc.message, details=exc.details, exit_code=4) from exc
    return payload


def evaluate_intake(policy: dict[str, Any], work: dict[str, Any], artifact_states: dict[str, str]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    intake = policy["intake"]
    if intake.get("require_owner") and not (work.get("owner") or "").strip():
        reasons.append(reason("REQUIRED_OWNER_MISSING", "work.owner", "non-empty", work.get("owner"), "policy.intake", "Set a non-empty owner on the Work."))
    if work.get("status") != "OPEN":
        reasons.append(reason("WORK_NOT_OPEN", "work.status", "OPEN", work.get("status"), "work", "Only OPEN work can be WORK_READY."))
    for required in intake.get("required_artifacts") or []:
        state = artifact_states.get(required, "MISSING")
        if state == "MISSING":
            reasons.append(reason("REQUIRED_ARTIFACT_MISSING", required, "CURRENT", state, "work.artifacts", f"Link a current {required} with ges artifact link."))
        elif state != "CURRENT":
            reasons.append(reason("ARTIFACT_STALE", required, "CURRENT", state, "work.artifacts", f"Re-link {required} after updating the file bytes."))
    return reasons


def evaluate_merge_risk(policy: dict[str, Any], work: dict[str, Any]) -> list[dict[str, Any]]:
    risk = work.get("risk")
    if risk == "HIGH":
        return [
            reason(
                APPROVAL_REQUIRED_UNSUPPORTED,
                "work.risk",
                policy["merge"]["supported_risks"],
                risk,
                "policy.merge",
                "HIGH risk cannot MERGE_READY until Approval Runtime exists.",
            )
        ]
    if risk not in policy["merge"]["supported_risks"]:
        return [reason("RISK_NOT_SUPPORTED", "work.risk", policy["merge"]["supported_risks"], risk, "policy.merge", "Use LOW or MEDIUM risk.")]
    return []
