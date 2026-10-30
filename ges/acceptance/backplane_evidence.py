from __future__ import annotations

from pathlib import Path
from typing import Any

from ges import __product_version__
from ges.io import write_json
from ges.reconciler.state import validate_payload
from ges.stagelog import EVIDENCE_BIND, emit


def write_backplane_evidence(
    *,
    artifact_dir: Path,
    candidate_sha: str,
    consumer_repo: str,
    pr_number: int | None,
    pr_head: str,
    work_id: str,
    policy_digest: str,
    acceptances: list[dict[str, Any]],
) -> Path:
    emit(EVIDENCE_BIND, "start", candidate_sha=candidate_sha)
    statuses = {item["status"] for item in acceptances}
    if "FAIL" in statuses:
        gate = "FAIL"
    elif "BLOCKED" in statuses or "SKIPPED" in statuses:
        gate = "BLOCKED"
    else:
        gate = "PASS"
    payload = {
        "schema": "ges.backplane-evidence.v1",
        "ges": {
            "repository": "loudon84/smc-delivery-governance",
            "commit_sha": candidate_sha,
            "product_version": __product_version__,
        },
        "golden_consumer": {
            "repository": consumer_repo,
            "pr_number": pr_number,
            "pr_head": pr_head or "0" * 40,
        },
        "work_id": work_id,
        "policy_digest": policy_digest,
        "acceptances": acceptances,
        "release_gate": {"status": gate},
    }
    validate_payload("ges.backplane-evidence.v1.json", payload)
    out = artifact_dir / "backplane-evidence.json"
    write_json(out, payload)
    emit(EVIDENCE_BIND, "complete", path=str(out))
    return out
