from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ges.errors import EVIDENCE_ARTIFACT_MISSING, GesError
from ges.io import sha256_file, write_json
from ges.reconciler.state import validate_payload
from ges.stagelog import EVIDENCE_BIND, RELEASE_ASSET, emit

RELEASE_NAME = "ges-v6.0.0-alpha.1"
HISTORICAL_EVIDENCE_NOTE = "HISTORICAL_ONLY: committed audit/ges6/bootstrap-closure is not final Alpha.1 Release Truth."


def resolve_artifact_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        path = Path(explicit)
    elif os.environ.get("GES_RELEASE_EVIDENCE_DIR"):
        path = Path(os.environ["GES_RELEASE_EVIDENCE_DIR"])
    elif os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_TEMP"):
        path = Path(os.environ["RUNNER_TEMP"]) / "ges-alpha1-release-evidence"
    else:
        path = Path(tempfile.mkdtemp(prefix="ges-release-evidence-"))
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def artifact_inside_candidate(artifact: Path, repo: Path) -> bool:
    try:
        artifact.resolve().relative_to(repo.resolve())
    except ValueError:
        return False
    return True


def require_artifact(path: Path) -> str:
    if not path.is_file():
        raise GesError(EVIDENCE_ARTIFACT_MISSING, f"missing release artifact: {path}")
    return sha256_file(path)


def verify_artifact_digest(path: Path, expected: str) -> str:
    actual = require_artifact(path)
    if actual != expected:
        raise GesError(EVIDENCE_ARTIFACT_MISSING, f"artifact digest mismatch for {path}")
    return actual


def release_gate_from_parts(
    *,
    synthetic: str,
    golden: str,
    documentation: str,
    candidate_moved: bool = False,
    artifact_missing: bool = False,
) -> str:
    if candidate_moved:
        return "STALE"
    if artifact_missing:
        return "BLOCKED"
    statuses = {synthetic, golden, documentation}
    if "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED" in statuses or "STALE" in statuses:
        return "BLOCKED"
    if statuses == {"PASS"}:
        return "PASS"
    return "BLOCKED"


# @lat: [[release-hardening#External Evidence]]
def write_release_manifest(
    *,
    artifact_dir: Path,
    candidate_sha: str,
    branch: str,
    consumer_sha: str,
    synthetic: dict,
    golden: dict,
    documentation_status: str,
    release_gate: str,
) -> Path:
    emit(EVIDENCE_BIND, "start", candidate_sha=candidate_sha)
    payload = {
        "schema": "ges.release-evidence-manifest.v1",
        "release": RELEASE_NAME,
        "candidate": {
            "repository": "loudon84/smc-delivery-governance",
            "commit_sha": candidate_sha,
            "branch": branch,
        },
        "golden_consumer": {
            "repository": "loudon84/smc-copilot-desktop",
            "commit_sha": consumer_sha,
        },
        "synthetic": synthetic,
        "golden": golden,
        "documentation": {"status": documentation_status},
        "release_gate": release_gate,
    }
    validate_payload("ges.release-evidence-manifest.v1.json", payload)
    out = artifact_dir / "release-evidence-manifest.json"
    write_json(out, payload)
    emit(RELEASE_ASSET, "complete", path=str(out), sha256=sha256_file(out))
    emit(EVIDENCE_BIND, "complete", candidate_sha=candidate_sha)
    return out
