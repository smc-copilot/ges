from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges import __distribution_version__, __product_version__
from ges.io import write_json
from ges.reconciler.state import validate_payload
from ges.stagelog import EVIDENCE_WRITE, RELEASE_GATE, emit

REQUIRED_ALPHA4_ACCEPTANCES = (
    "A-A4-STATUS-001",
    "A-A4-STATUS-002",
    "A-A4-GOLD-001",
    "A-A4-GOLD-002",
    "A-A4-GOLD-003",
    "A-A4-GOLD-004",
    "A-A4-EVID-001",
    "A-A4-EVID-002",
    "A-A4-EVID-003",
    "A-A4-READY-001",
    "A-A4-READY-002",
)


def record(acceptance_id: str, status: str, command: str, exit_code: int, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "acceptance_id": acceptance_id,
        "status": status,
        "command": command,
        "exit_code": exit_code,
        "oracle": {"expected": expected, "actual": actual},
    }


def validate_acceptance_set(acceptances: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Return (gate_hint, extra EVID rows). Exact required set, no dupes/unknowns, all PASS for PASS."""
    from ges.errors import (
        ALPHA4_ACCEPTANCE_DUPLICATE,
        ALPHA4_ACCEPTANCE_UNKNOWN,
        ALPHA4_REQUIRED_ACCEPTANCE_MISSING,
    )

    ids = [item["acceptance_id"] for item in acceptances]
    extras: list[dict[str, Any]] = []
    required = list(REQUIRED_ALPHA4_ACCEPTANCES)
    actual_sorted = sorted(set(ids))
    expected_sorted = sorted(required)

    if len(ids) != len(set(ids)):
        extras.append(record("A-A4-EVID-002", "FAIL", "acceptance-set", 2, "unique", ALPHA4_ACCEPTANCE_DUPLICATE))
        return "FAIL", extras
    extras.append(record("A-A4-EVID-002", "PASS", "acceptance-set", 0, "unique", "unique"))

    unknown = sorted(set(ids) - set(required))
    missing = sorted(set(required) - set(ids))
    if unknown:
        extras.append(record("A-A4-EVID-001", "FAIL", "acceptance-set", 2, expected_sorted, ids))
        return "FAIL", extras + [
            record("A-A4-EVID-001", "FAIL", "unknown", 2, [], unknown + [ALPHA4_ACCEPTANCE_UNKNOWN])
        ]
    if missing:
        extras.append(
            record(
                "A-A4-EVID-001",
                "BLOCKED",
                "acceptance-set",
                3,
                expected_sorted,
                missing + [ALPHA4_REQUIRED_ACCEPTANCE_MISSING],
            )
        )
        return "BLOCKED", extras

    extras.append(record("A-A4-EVID-001", "PASS", "acceptance-set", 0, expected_sorted, actual_sorted))

    non_pass = [item for item in acceptances if item["status"] != "PASS"]
    if non_pass:
        extras.append(
            record(
                "A-A4-EVID-003",
                "FAIL" if any(item["status"] == "FAIL" for item in non_pass) else "BLOCKED",
                "acceptance-status",
                2,
                "all PASS",
                [item["acceptance_id"] for item in non_pass],
            )
        )
        return ("FAIL" if any(item["status"] == "FAIL" for item in non_pass) else "BLOCKED"), extras

    extras.append(record("A-A4-EVID-003", "PASS", "acceptance-status", 0, "all PASS", "all PASS"))
    return "PASS", extras


def write_alpha4_closure_evidence(
    *,
    artifact_dir: Path,
    candidate_sha: str,
    golden: dict[str, Any],
    acceptances: list[dict[str, Any]],
    regression: dict[str, str],
    release_gate: str,
) -> Path:
    emit(EVIDENCE_WRITE, "start", candidate_sha=candidate_sha)
    payload = {
        "schema": "ges.alpha4-capability-closure-evidence.v1",
        "candidate_sha": candidate_sha,
        "product_version": __product_version__,
        "distribution_version": __distribution_version__,
        "golden": golden,
        "required_acceptance_ids": list(REQUIRED_ALPHA4_ACCEPTANCES),
        "acceptances": acceptances,
        "regression": regression,
        "release_gate": {"status": release_gate},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": __product_version__,
    }
    validate_payload("ges.alpha4-capability-closure-evidence.v1.json", payload)
    out = Path(artifact_dir) / "alpha4-capability-closure-evidence.json"
    write_json(out, payload)
    emit(EVIDENCE_WRITE, "complete", path=str(out))
    emit(RELEASE_GATE, "complete", status=release_gate)
    return out
