from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges import __distribution_version__, __product_version__
from ges.errors import STALE_EVIDENCE, GesError
from ges.reconciler.state import validate_payload
from ges.source_adapters.speckit_render import INTEGRATION, REQUIRED_CLI_VERSION, SPEC_KIT_REPO, SPEC_KIT_SHA
from ges.stagelog import EVIDENCE_WRITE, RELEASE_GATE, emit

REQUIRED_ACCEPTANCES = (
    ("A-SK-001", ["REQ-SPECKIT-FUNC-001"], ["TEST-A-SK-001"]),
    ("A-SK-002", ["REQ-SPECKIT-FUNC-001"], ["TEST-A-SK-002"]),
    ("A-SK-003", ["REQ-SPECKIT-FUNC-001"], ["TEST-A-SK-003"]),
    ("A-SKM-001", ["REQ-SPECKIT-FUNC-002"], ["TEST-A-SKM-001"]),
    ("A-SKM-002", ["REQ-SPECKIT-FUNC-002"], ["TEST-A-SKM-002"]),
    ("A-CURSOR-STRUCT-001", ["REQ-CURSOR-001"], ["TEST-A-CURSOR-STRUCT-001"]),
    ("A-CURSOR-RUNTIME-001", ["REQ-CURSOR-002"], ["TEST-A-CURSOR-RUNTIME-001"]),
    ("A-CURSOR-RUNTIME-002", ["REQ-CURSOR-002"], ["TEST-A-CURSOR-RUNTIME-002"]),
    ("A-SKF-001", ["REQ-SPECKIT-FUNC-003"], ["TEST-A-SKF-001"]),
    ("A-SKF-002", ["REQ-SPECKIT-FUNC-003"], ["TEST-A-SKF-002"]),
    ("A-SKF-003", ["REQ-SPECKIT-FUNC-003"], ["TEST-A-SKF-003"]),
    ("A-GOLDEN-001", ["REQ-GOLDEN-001"], ["TEST-A-GOLDEN-001"]),
    ("A-GOLDEN-002", ["REQ-GOLDEN-001"], ["TEST-A-GOLDEN-002"]),
    ("A-GOLDEN-003", ["REQ-GOLDEN-002"], ["TEST-A-GOLDEN-003"]),
    ("A-GOLDEN-004", ["REQ-GOLDEN-002"], ["TEST-A-GOLDEN-004"]),
    ("A-GOLDEN-005", ["REQ-GOLDEN-001"], ["TEST-A-GOLDEN-005"]),
    ("A-IDEMP-CLI-001", ["REQ-GOLDEN-002"], ["TEST-A-IDEMP-CLI-001"]),
    ("A-EVID-001", ["REQ-EVID-001"], ["TEST-A-EVID-001"]),
    ("A-EVID-002", ["REQ-EVID-001"], ["TEST-A-EVID-002"]),
    ("A-RH-EVID-001", ["REQ-RH-EVID-001"], ["TEST-A-RH-EVID-001"]),
    ("A-RH-EVID-002", ["REQ-RH-EVID-001"], ["TEST-A-RH-EVID-002"]),
    ("A-RH-EVID-003", ["REQ-RH-EVID-001"], ["TEST-A-RH-EVID-003"]),
    ("A-RH-SMOKE-001", ["REQ-RH-SMOKE-001"], ["TEST-A-RH-SMOKE-001"]),
    ("A-RH-SMOKE-002", ["REQ-RH-SMOKE-001"], ["TEST-A-RH-SMOKE-002"]),
    ("A-RH-SMOKE-003", ["REQ-RH-SMOKE-001"], ["TEST-A-RH-SMOKE-003"]),
    ("A-RH-SMOKE-004", ["REQ-RH-SMOKE-001"], ["TEST-A-RH-SMOKE-004"]),
    ("A-RH-SMOKE-005", ["REQ-RH-SMOKE-002"], ["TEST-A-RH-SMOKE-005"]),
    ("A-RH-CURSOR-001", ["REQ-RH-CURSOR-001"], ["TEST-A-RH-CURSOR-001"]),
    ("A-RH-CURSOR-002", ["REQ-RH-CURSOR-001"], ["TEST-A-RH-CURSOR-002"]),
    ("A-RH-CURSOR-003", ["REQ-RH-CURSOR-001"], ["TEST-A-RH-CURSOR-003"]),
    ("A-RH-CURSOR-004", ["REQ-RH-CURSOR-001"], ["TEST-A-RH-CURSOR-004"]),
    ("A-RH-DOC-001", ["REQ-RH-DOC-001"], ["TEST-A-RH-DOC-001"]),
)


def record(
    acceptance_id: str,
    status: str,
    command: str,
    exit_code: int,
    expected: Any,
    actual: Any,
    *,
    oracle_type: str = "equals",
    evidence_files: list[str] | None = None,
) -> dict[str, Any]:
    meta = {item[0]: item for item in REQUIRED_ACCEPTANCES}
    requirement_ids, test_ids = (["REQ-EVID-001"], [f"TEST-{acceptance_id}"])
    if acceptance_id in meta:
        requirement_ids, test_ids = meta[acceptance_id][1], meta[acceptance_id][2]
    return {
        "acceptance_id": acceptance_id,
        "requirement_ids": requirement_ids,
        "test_ids": test_ids,
        "status": status,
        "command": command,
        "exit_code": exit_code,
        "oracle": {"type": oracle_type, "expected": expected, "actual": actual},
        "evidence_files": evidence_files or [],
    }


def bind_commits(payload: dict[str, Any], *, ges_head: str, consumer_head: str) -> None:
    if payload["ges"]["commit_sha"] != ges_head or payload["golden_consumer"]["commit_sha"] != consumer_head:
        raise GesError(
            STALE_EVIDENCE,
            "evidence commit binding does not match tested HEADs",
            details={
                "evidence.ges.commit_sha": payload["ges"]["commit_sha"],
                "current GES_HEAD": ges_head,
                "evidence.consumer.commit_sha": payload["golden_consumer"]["commit_sha"],
                "tested CONSUMER_HEAD": consumer_head,
            },
        )


def write_closure_evidence(
    *,
    run_id: str,
    started_at: datetime,
    ges_head: str,
    ges_branch: str,
    consumer: dict[str, Any],
    spec_kit: dict[str, Any] | None,
    cursor: dict[str, Any],
    acceptances: list[dict[str, Any]],
    root: Path,
    artifact_dir: Path | None = None,
) -> Path:
    emit(EVIDENCE_WRITE, "start", run_id=run_id)
    known = {item["acceptance_id"] for item in acceptances}
    for acceptance_id, _, _ in REQUIRED_ACCEPTANCES:
        if acceptance_id not in known:
            acceptances.append(
                record(acceptance_id, "BLOCKED", "not-executed", 2, "PASS", "missing")
            )
    statuses = {item["status"] for item in acceptances}
    if "FAIL" in statuses:
        gate = "FAIL"
    elif "BLOCKED" in statuses or "SKIPPED" in statuses:
        gate = "BLOCKED"
    else:
        gate = "PASS"
    payload = {
        "schema": "ges.bootstrap-closure-evidence.v1",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "ges": {
            "repository": "loudon84/smc-delivery-governance",
            "branch": ges_branch,
            "commit_sha": ges_head,
            "product_version": __product_version__,
            "distribution_version": __distribution_version__,
        },
        "golden_consumer": consumer,
        "spec_kit": spec_kit
        or {
            "repo": SPEC_KIT_REPO,
            "commit_sha": SPEC_KIT_SHA,
            "specify_cli_version": REQUIRED_CLI_VERSION,
            "integration": INTEGRATION,
            "official_render_manifest_digest": "",
            "projected_manifest_digest": "",
        },
        "cursor": cursor,
        "acceptances": acceptances,
        "release_gate": {"status": gate},
    }
    bind_commits(payload, ges_head=ges_head, consumer_head=consumer["commit_sha"])
    validate_payload("ges.bootstrap-closure-evidence.v1.json", payload)
    out_dir = Path(artifact_dir) / "golden" if artifact_dir is not None else root / "audit" / "ges6" / "bootstrap-closure" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "evidence.json"
    out.write_text(__import__("json").dumps(payload, indent=2) + "\n", encoding="utf-8")
    emit(EVIDENCE_WRITE, "complete", path=str(out))
    emit(RELEASE_GATE, "complete", status=gate)
    return out
