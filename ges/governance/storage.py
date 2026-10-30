from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges.errors import (
    GOVERNANCE_ALREADY_INITIALIZED,
    GOVERNANCE_NOT_INITIALIZED,
    GOVERNANCE_PATH_CONFLICT,
    POLICY_SCHEMA_INVALID,
    WORK_ALREADY_EXISTS,
    WORK_NOT_FOUND,
    WORK_SCHEMA_INVALID,
    GesError,
)
from ges.governance.paths import governance_dir, policy_path, work_path, works_dir
from ges.io import read_yaml, sha256_file, write_yaml_atomic
from ges.reconciler.state import validate_payload
from ges.stagelog import GOVERNANCE_INIT, POLICY_LOAD, WORK_LOAD, emit

DEFAULT_POLICY: dict[str, Any] = {
    "schema": "ges.policy.v1",
    "id": "default-v1",
    "intake": {"require_owner": True, "required_artifacts": ["SPEC", "PLAN"]},
    "merge": {
        "supported_risks": ["LOW", "MEDIUM"],
        "pr": {
            "require_open": True,
            "require_not_draft": True,
            "require_work_marker": True,
            "work_marker": "GES-Work: {work_id}",
        },
        "local": {"require_head_equals_pr_head": True, "require_clean_tracked_tree": True},
        "review": {"require_decision": "APPROVED"},
        "checks": {
            "min_successful": 1,
            "allow_pending": False,
            "allow_failed": False,
            "allow_cancelled": False,
            "allow_skipped_as_success": False,
        },
    },
}

EXECUTION_HOSTS = ("cursor", "codex", "hermes")


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_governance(repo: Path) -> dict[str, Any]:
    emit(GOVERNANCE_INIT, "start", repo=str(repo))
    root = governance_dir(repo)
    policy = policy_path(repo)
    works = works_dir(repo)
    if policy.is_file() and works.is_dir():
        try:
            load_policy(repo)
        except GesError:
            raise GesError(GOVERNANCE_PATH_CONFLICT, "existing governance directory is not a valid policy+works layout")
        emit(GOVERNANCE_INIT, "complete", status="already")
        raise GesError(GOVERNANCE_ALREADY_INITIALIZED, "governance already initialized", exit_code=0)
    if root.exists() and (any(root.iterdir()) if root.is_dir() else True):
        raise GesError(GOVERNANCE_PATH_CONFLICT, "unknown path already occupies .ges/governance")
    works.mkdir(parents=True, exist_ok=True)
    write_policy(repo, DEFAULT_POLICY)
    emit(GOVERNANCE_INIT, "complete", status="created")
    return DEFAULT_POLICY


def require_governance(repo: Path) -> None:
    if not policy_path(repo).is_file() or not works_dir(repo).is_dir():
        raise GesError(GOVERNANCE_NOT_INITIALIZED, "run ges governance init first")


def load_policy(repo: Path) -> dict[str, Any]:
    emit(POLICY_LOAD, "start")
    require_governance(repo)
    payload = read_yaml(policy_path(repo)) or {}
    try:
        validate_payload("ges.policy.v1.json", payload, code=POLICY_SCHEMA_INVALID)
    except GesError as exc:
        raise GesError(POLICY_SCHEMA_INVALID, exc.message, details=exc.details, exit_code=4) from exc
    emit(POLICY_LOAD, "complete", policy_id=payload.get("id"))
    return payload


def write_policy(repo: Path, payload: dict[str, Any]) -> None:
    validate_payload("ges.policy.v1.json", payload, code=POLICY_SCHEMA_INVALID)
    write_yaml_atomic(policy_path(repo), payload)


def policy_digest(repo: Path) -> str:
    return sha256_file(policy_path(repo))


def work_schema_name(payload: dict[str, Any]) -> str:
    schema = str(payload.get("schema") or "")
    if schema == "ges.work.v2":
        return "ges.work.v2.json"
    if schema == "ges.work.v1":
        return "ges.work.v1.json"
    raise GesError(WORK_SCHEMA_INVALID, f"unsupported work schema: {schema}")


def validate_work_payload(payload: dict[str, Any]) -> None:
    validate_payload(work_schema_name(payload), payload, code=WORK_SCHEMA_INVALID)


def load_work(repo: Path, work_id: str) -> dict[str, Any]:
    emit(WORK_LOAD, "start", work_id=work_id)
    require_governance(repo)
    path = work_path(repo, work_id)
    if not path.is_file():
        raise GesError(WORK_NOT_FOUND, f"work not found: {work_id}")
    payload = read_yaml(path) or {}
    validate_work_payload(payload)
    emit(WORK_LOAD, "complete", work_id=work_id)
    return payload


def write_work(repo: Path, payload: dict[str, Any], *, create: bool = False) -> Path:
    require_governance(repo)
    validate_work_payload(payload)
    path = work_path(repo, payload["id"])
    if create and path.exists():
        raise GesError(WORK_ALREADY_EXISTS, f"work already exists: {payload['id']}")
    write_yaml_atomic(path, payload)
    load_work(repo, payload["id"])
    return path


def work_exists(repo: Path, work_id: str) -> bool:
    return work_path(repo, work_id).is_file()
