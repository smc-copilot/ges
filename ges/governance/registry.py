from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from ges.catalog.providers import load_providers
from ges.errors import (
    WORK_ALREADY_EXISTS,
    WORK_ALREADY_V2,
    WORK_CAPABILITY_NOT_BOUND,
    WORK_CAPABILITY_NOT_FOUND,
    WORK_CAPABILITY_PROHIBITED,
    WORK_CAPABILITY_UNSUPPORTED,
    WORK_CLOSED_IMMUTABLE,
    WORK_EXECUTION_HOST_UNSUPPORTED,
    WORK_ID_INVALID,
    WORK_MIGRATION_INVALID,
    WORK_STATE_TRANSITION_INVALID,
    GesError,
)
from ges.governance.paths import work_path
from ges.governance.storage import EXECUTION_HOSTS, load_work, now_rfc3339, require_governance, write_work
from ges.providers.overlay import read_policy
from ges.stagelog import WORK_VALIDATE, emit

WORK_ID_RE = re.compile(r"^[A-Z][A-Z0-9._-]{2,63}$")
COMPOSER_PREFIXES = ("matt.", "speckit.", "superpowers.")


def create_work(
    repo: Path,
    *,
    work_id: str,
    title: str,
    owner: str,
    risk: str,
    host: str,
) -> dict[str, Any]:
    require_governance(repo)
    if not WORK_ID_RE.fullmatch(work_id):
        raise GesError(WORK_ID_INVALID, f"invalid work id: {work_id}")
    if host not in EXECUTION_HOSTS:
        raise GesError(WORK_EXECUTION_HOST_UNSUPPORTED, f"unsupported execution host: {host}")
    if work_path(repo, work_id).exists():
        raise GesError(WORK_ALREADY_EXISTS, f"work already exists: {work_id}")
    stamp = now_rfc3339()
    payload = {
        "schema": "ges.work.v2",
        "id": work_id,
        "kind": "FEATURE",
        "title": title,
        "status": "OPEN",
        "owner": owner,
        "risk": risk,
        "policy": "default-v1",
        "artifacts": [],
        "capabilities": {"required": []},
        "execution": {"profile": "ges-native", "host": host},
        "created_at": stamp,
        "updated_at": stamp,
    }
    emit(WORK_VALIDATE, "complete", work_id=work_id)
    write_work(repo, payload, create=True)
    return payload


def show_work(repo: Path, work_id: str) -> dict[str, Any]:
    return load_work(repo, work_id)


def update_work(
    repo: Path,
    work_id: str,
    *,
    title: str | None = None,
    owner: str | None = None,
    risk: str | None = None,
    policy: str | None = None,
) -> dict[str, Any]:
    current = load_work(repo, work_id)
    if current["status"] == "CLOSED":
        raise GesError(WORK_CLOSED_IMMUTABLE, f"closed work cannot be updated: {work_id}")
    if title is not None:
        current["title"] = title
    if owner is not None:
        current["owner"] = owner
    if risk is not None:
        current["risk"] = risk
    if policy is not None:
        current["policy"] = policy
    current["updated_at"] = now_rfc3339()
    write_work(repo, current)
    return current


def close_work(repo: Path, work_id: str) -> dict[str, Any]:
    current = load_work(repo, work_id)
    if current["status"] != "OPEN":
        raise GesError(WORK_STATE_TRANSITION_INVALID, "only OPEN work can be closed")
    current["status"] = "CLOSED"
    current["updated_at"] = now_rfc3339()
    write_work(repo, current)
    return current


def migrate_work(repo: Path, work_id: str, *, host: str) -> dict[str, Any]:
    require_governance(repo)
    if host not in EXECUTION_HOSTS:
        raise GesError(WORK_EXECUTION_HOST_UNSUPPORTED, f"unsupported execution host: {host}")
    current = load_work(repo, work_id)
    if current.get("schema") == "ges.work.v2":
        raise GesError(WORK_ALREADY_V2, f"work is already v2: {work_id}")
    if current.get("schema") != "ges.work.v1":
        raise GesError(WORK_MIGRATION_INVALID, f"cannot migrate schema: {current.get('schema')}")
    before = work_path(repo, work_id).read_bytes()
    try:
        payload = {
            "schema": "ges.work.v2",
            "id": current["id"],
            "kind": current["kind"],
            "title": current["title"],
            "status": current["status"],
            "owner": current["owner"],
            "risk": current["risk"],
            "policy": current["policy"],
            "artifacts": copy.deepcopy(current.get("artifacts") or []),
            "capabilities": {"required": []},
            "execution": {"profile": "ges-native", "host": host},
            "created_at": current["created_at"],
            "updated_at": now_rfc3339(),
        }
        write_work(repo, payload)
        return payload
    except Exception:
        work_path(repo, work_id).write_bytes(before)
        raise


def add_work_capability(repo: Path, work_id: str, cap_id: str) -> dict[str, Any]:
    current = _require_v2(repo, work_id)
    _reject_capability(repo, cap_id)
    required = list((current.get("capabilities") or {}).get("required") or [])
    if cap_id not in required:
        required.append(cap_id)
    current["capabilities"] = {"required": sorted(set(required))}
    current["updated_at"] = now_rfc3339()
    write_work(repo, current)
    return current


def remove_work_capability(repo: Path, work_id: str, cap_id: str) -> dict[str, Any]:
    current = _require_v2(repo, work_id)
    required = list((current.get("capabilities") or {}).get("required") or [])
    if cap_id not in required:
        raise GesError(WORK_CAPABILITY_NOT_BOUND, f"capability is not bound on work: {cap_id}")
    current["capabilities"] = {"required": [item for item in required if item != cap_id]}
    current["updated_at"] = now_rfc3339()
    write_work(repo, current)
    return current


def _require_v2(repo: Path, work_id: str) -> dict[str, Any]:
    current = load_work(repo, work_id)
    if current.get("schema") != "ges.work.v2":
        raise GesError(WORK_MIGRATION_INVALID, f"work must be ges.work.v2: {work_id}")
    if current["status"] == "CLOSED":
        raise GesError(WORK_CLOSED_IMMUTABLE, f"closed work cannot be updated: {work_id}")
    return current


def _reject_capability(repo: Path, cap_id: str) -> None:
    if cap_id.startswith(COMPOSER_PREFIXES):
        raise GesError(WORK_CAPABILITY_UNSUPPORTED, f"composer capability unsupported: {cap_id}")
    if cap_id not in load_providers():
        raise GesError(WORK_CAPABILITY_NOT_FOUND, f"capability not found: {cap_id}")
    policy = read_policy(repo) or {}
    if cap_id in (policy.get("prohibited") or []):
        raise GesError(WORK_CAPABILITY_PROHIBITED, f"capability is prohibited: {cap_id}")
