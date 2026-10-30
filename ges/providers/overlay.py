from __future__ import annotations

from pathlib import Path
from typing import Any

from ges.errors import POLICY_SCHEMA_INVALID
from ges.io import read_yaml, write_yaml
from ges.paths import capability_policy_path, installed_path, repo_capabilities_dir
from ges.reconciler.state import validate_payload

POLICY_ORDER = ("prohibited", "required", "recommended", "optional")


def empty_policy() -> dict[str, Any]:
    return {
        "schema": "ges.capability-policy.v1",
        "required": [],
        "recommended": [],
        "optional": [],
        "prohibited": [],
    }


def empty_installed() -> dict[str, Any]:
    return {"schema": "ges.capability-installed.v1", "installed": []}


def read_installed(repo: Path) -> dict[str, Any]:
    path = installed_path(repo)
    if not path.is_file():
        return empty_installed()
    payload = read_yaml(path) or {}
    validate_payload("ges.capability-installed.v1.json", payload, code=POLICY_SCHEMA_INVALID)
    return payload


def read_policy(repo: Path) -> dict[str, Any] | None:
    path = capability_policy_path(repo)
    if not path.is_file():
        return None
    payload = read_yaml(path) or {}
    validate_payload("ges.capability-policy.v1.json", payload, code=POLICY_SCHEMA_INVALID)
    return payload


def write_installed(repo: Path, installed: list[str]) -> dict[str, Any]:
    payload = {"schema": "ges.capability-installed.v1", "installed": list(installed)}
    validate_payload("ges.capability-installed.v1.json", payload, code=POLICY_SCHEMA_INVALID)
    repo_capabilities_dir(repo).mkdir(parents=True, exist_ok=True)
    write_yaml(installed_path(repo), payload)
    return payload


def write_policy(repo: Path, policy: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema": "ges.capability-policy.v1",
        "required": list(policy.get("required") or []),
        "recommended": list(policy.get("recommended") or []),
        "optional": list(policy.get("optional") or []),
        "prohibited": list(policy.get("prohibited") or []),
    }
    validate_payload("ges.capability-policy.v1.json", payload, code=POLICY_SCHEMA_INVALID)
    repo_capabilities_dir(repo).mkdir(parents=True, exist_ok=True)
    write_yaml(capability_policy_path(repo), payload)
    return payload


def seed_policy_from_resolver(policy: dict[str, Any], cap_id: str, resolver_level: str) -> dict[str, Any]:
    if any(cap_id in (policy.get(key) or []) for key in POLICY_ORDER):
        return policy
    level = resolver_level if resolver_level in POLICY_ORDER else "optional"
    bucket = list(policy.get(level) or [])
    if cap_id not in bucket:
        bucket.append(cap_id)
    policy[level] = bucket
    return policy


def effective_level(cap_id: str, plan: dict[str, Any], policy: dict[str, Any] | None) -> str:
    if policy:
        for key in POLICY_ORDER:
            if cap_id in (policy.get(key) or []):
                return key
    if cap_id in (plan.get("recommended") or []):
        return "recommended"
    if cap_id in (plan.get("optional") or []):
        return "optional"
    if cap_id in (plan.get("required") or []):
        return "required"
    return "optional"


def resolver_level(cap_id: str, plan: dict[str, Any]) -> str:
    if cap_id in (plan.get("recommended") or []):
        return "recommended"
    if cap_id in (plan.get("optional") or []):
        return "optional"
    if cap_id in (plan.get("required") or []):
        return "required"
    return "optional"


def is_installed(repo: Path, cap_id: str) -> bool:
    return cap_id in list(read_installed(repo).get("installed") or [])


def add_installed(repo: Path, cap_id: str, resolver_level_name: str) -> dict[str, Any]:
    installed = list(read_installed(repo).get("installed") or [])
    if cap_id not in installed:
        installed.append(cap_id)
    policy = read_policy(repo)
    if policy is None:
        policy = empty_policy()
        seed_policy_from_resolver(policy, cap_id, resolver_level_name)
        write_policy(repo, policy)
    write_installed(repo, installed)
    return read_installed(repo)


def remove_installed(repo: Path, cap_id: str) -> dict[str, Any]:
    installed = [item for item in (read_installed(repo).get("installed") or []) if item != cap_id]
    write_installed(repo, installed)
    return read_installed(repo)


def overlay_exists(repo: Path) -> bool:
    return installed_path(repo).is_file() or capability_policy_path(repo).is_file()
