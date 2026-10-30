from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

from ges.catalog.loader import load_catalog
from ges.catalog.providers import RTK_ID, load_providers
from ges.cli.common import resolve_repo
from ges.doctor import _repo_facts
from ges.errors import (
    CAPABILITY_NOT_FOUND,
    CAPABILITY_NOT_INSTALLED,
    CAPABILITY_PROHIBITED,
    COMPOSER_CAPABILITY_FROZEN,
    GesError,
)
from ges.providers.compat import package_incompatible
from ges.providers.overlay import (
    add_installed,
    effective_level,
    is_installed,
    read_policy,
    remove_installed,
    resolver_level,
)
from ges.providers.resolve import build_capability_plan
from ges.providers.rtk import probe_rtk

COMPOSER_PREFIXES = ("matt.", "speckit.", "superpowers.")


def run_list(args: Namespace) -> int:
    repo = resolve_repo(args.repo)
    row = _row(repo, RTK_ID)
    if args.json:
        print(json.dumps({"schema": "ges.capability-list.v1", "items": [row]}, indent=2))
    else:
        print("id\tresolver\tpolicy\tinstalled\tstatus\treason")
        print(
            f"{row['id']}\t{row['resolver_level']}\t{row['policy_level']}\t"
            f"{row['installed']}\t{row['status']}\t{row['reason']}"
        )
    return 0


def run_add(args: Namespace) -> int:
    repo = resolve_repo(args.repo)
    cap_id = args.id
    _reject_composer(cap_id)
    _require_parallel(cap_id)
    plan, policy = _plan_and_policy(repo)
    if effective_level(cap_id, plan, policy) == "prohibited":
        raise GesError(CAPABILITY_PROHIBITED, f"capability is prohibited: {cap_id}")
    add_installed(repo, cap_id, resolver_level(cap_id, plan))
    print(json.dumps(_probe(cap_id), indent=2))
    return 0


def run_remove(args: Namespace) -> int:
    repo = resolve_repo(args.repo)
    cap_id = args.id
    _reject_composer(cap_id)
    _require_parallel(cap_id)
    if not is_installed(repo, cap_id):
        raise GesError(CAPABILITY_NOT_INSTALLED, f"capability is not installed: {cap_id}")
    remove_installed(repo, cap_id)
    return 0


def run_doctor(args: Namespace) -> int:
    cap_id = args.id
    _reject_composer(cap_id)
    _require_parallel(cap_id)
    print(json.dumps(_probe(cap_id), indent=2))
    return 0


def _row(repo: Path, cap_id: str) -> dict[str, Any]:
    plan, policy = _plan_and_policy(repo)
    status = _probe(cap_id)
    return {
        "id": cap_id,
        "resolver_level": resolver_level(cap_id, plan),
        "policy_level": effective_level(cap_id, plan, policy),
        "installed": is_installed(repo, cap_id),
        "status": status["status"],
        "reason": (plan.get("reasons") or {}).get(cap_id, ""),
        "incompatible": list(package_incompatible(cap_id)),
    }


def _plan_and_policy(repo: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    facts = _repo_facts(repo)
    closed = _closed(repo)
    return build_capability_plan(facts, closed), read_policy(repo)


def _closed(repo: Path) -> list[str]:
    from ges.reconciler.state import read_lock

    lock = read_lock(repo) or {}
    closed = list(lock.get("resolved_capabilities") or lock.get("capabilities") or [])
    if closed:
        return closed
    catalog = load_catalog()
    profile = catalog.profiles["brownfield-product-app"]
    return list(profile.required + profile.recommended)


def _probe(cap_id: str) -> dict[str, Any]:
    if cap_id != RTK_ID:
        raise GesError(CAPABILITY_NOT_FOUND, f"capability not found: {cap_id}")
    return probe_rtk()


def _reject_composer(cap_id: str) -> None:
    if cap_id.startswith(COMPOSER_PREFIXES):
        raise GesError(COMPOSER_CAPABILITY_FROZEN, f"composer capability is frozen: {cap_id}")


def _require_parallel(cap_id: str) -> None:
    if cap_id not in load_providers():
        raise GesError(CAPABILITY_NOT_FOUND, f"capability not found: {cap_id}")
