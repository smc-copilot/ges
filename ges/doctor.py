from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges import __product_version__
from ges.analyzer.repo_profile import analyze_repo
from ges.catalog.loader import load_catalog
from ges.catalog.providers import RTK_ID
from ges.check import run_check
from ges.errors import BOOTSTRAP_PREREQUISITE_FAILED, GES_CHECK_FAILED, REPO_NOT_SUPPORTED, GesError
from ges.providers.resolve import build_capability_plan
from ges.providers.rtk import probe_rtk
from ges.reconciler.state import read_lock, read_profile, read_project
from ges.source_adapters.speckit_render import SELECTED_COMMANDS, leftover_tokens, skill_rel
from ges.stagelog import DOCTOR, PREFLIGHT, emit


PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"
READY = "READY"
BOOTSTRAP_PENDING = "BOOTSTRAP_PENDING"
BLOCKED = "BLOCKED"


def run_preflight(repo: Path) -> dict[str, Any]:
    emit(PREFLIGHT, "start", repo=str(repo))
    repo = repo.expanduser().resolve()
    checks = {
        "python": PASS if sys.version_info >= (3, 11) else FAIL,
        "git": PASS if shutil.which("git") else FAIL,
        "cursor_harness": PASS if (repo / ".cursor").exists() else FAIL,
    }
    warnings = []
    if (repo / ".specify" / "constitution.md").is_file():
        warnings.append(
            "LEGACY_OR_USER_SPEC_STATE: current Spec Kit expects .specify/memory/constitution.md"
        )
    failed = [name for name, status in checks.items() if status != PASS]
    payload = {
        "schema": "ges.readiness.v1",
        "mode": "preflight",
        "ges_version": __product_version__,
        "repo_head": _git_head(repo),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall": PASS if not failed else BLOCKED,
        "checks": checks,
        "warnings": warnings,
    }
    emit(PREFLIGHT, "complete", overall=payload["overall"])
    if failed:
        raise GesError(
            BOOTSTRAP_PREREQUISITE_FAILED,
            f"preflight failed: {', '.join(failed)}",
            details=payload,
        )
    return payload


def run_doctor(repo: Path) -> dict[str, Any]:
    emit(DOCTOR, "start", repo=str(repo))
    repo = repo.expanduser().resolve()
    checks = {
        "ges_core": FAIL,
        "cursor_harness": PASS if (repo / ".cursor").exists() else FAIL,
        "spec_kit_runtime": FAIL,
        "matt_skills_installed": FAIL,
        "matt_project_bootstrap": PENDING,
        "superpowers_skills": FAIL,
    }
    core_error = ""
    try:
        run_check(repo)
        checks["ges_core"] = PASS
    except GesError as exc:
        if exc.code != GES_CHECK_FAILED:
            raise
        checks["ges_core"] = FAIL
        core_error = f"{exc.code}: {exc.message}"

    catalog = load_catalog()
    project = read_project(repo) or {}
    lock = read_lock(repo) or {}
    closed = list(lock.get("resolved_capabilities") or lock.get("capabilities") or [])
    if not closed:
        profile = catalog.profiles[project.get("profile") or "brownfield-product-app"]
        closed = list(profile.required + profile.recommended)

    checks["matt_skills_installed"] = PASS if _skills_present(repo, closed, "matt.") else FAIL
    checks["superpowers_skills"] = PASS if _skills_present(repo, closed, "superpowers.") else FAIL
    checks["spec_kit_runtime"] = PASS if _speckit_runtime_ok(repo, closed) else FAIL
    if (repo / "docs" / "agents" / "issue-tracker.md").is_file() and (repo / "docs" / "agents" / "domain.md").is_file():
        checks["matt_project_bootstrap"] = PASS
    elif not (repo / ".agents" / "skills" / "setup-matt-pocock-skills").exists():
        checks["matt_project_bootstrap"] = FAIL

    overall = _overall(checks)
    facts = _repo_facts(repo)
    plan = build_capability_plan(facts, closed)
    status = probe_rtk()
    warnings: list[str] = []
    if core_error:
        warnings.append(core_error)
    if RTK_ID in plan.get("recommended", []):
        if status["status"] == "missing":
            warnings.append(f"RECOMMENDED_PROVIDER_MISSING: {RTK_ID}")
        elif status["status"] == "NOT_READY":
            warnings.append(f"RECOMMENDED_PROVIDER_NOT_READY: {RTK_ID}")
    payload = {
        "schema": "ges.readiness.v1",
        "ges_version": __product_version__,
        "repo_head": _git_head(repo),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "checks": checks,
        "warnings": warnings,
        "capabilities": [status],
    }
    emit(DOCTOR, "complete", overall=overall)
    return payload


def _repo_facts(repo: Path) -> dict[str, Any]:
    stored = read_profile(repo) or {}
    try:
        return analyze_repo(repo)
    except GesError as exc:
        if exc.code != REPO_NOT_SUPPORTED:
            raise
        return stored


def _overall(checks: dict[str, str]) -> str:
    required = {key: value for key, value in checks.items() if key != "matt_project_bootstrap"}
    if any(value == FAIL for value in required.values()):
        return BLOCKED
    if checks["matt_project_bootstrap"] == PENDING:
        return BOOTSTRAP_PENDING
    if checks["matt_project_bootstrap"] == FAIL:
        return BLOCKED
    return READY


def _skills_present(repo: Path, closed: list[str], prefix: str) -> bool:
    catalog = load_catalog()
    hits = [cap_id for cap_id in closed if cap_id.startswith(prefix)]
    if not hits:
        return True
    for cap_id in hits:
        cap = catalog.get(cap_id)
        if cap.projection_type == "virtual" or not cap.skill_name:
            continue
        root = (
            repo / ".cursor" / "skills" / cap.skill_name
            if cap.projection_type == "speckit-capability"
            else repo / ".agents" / "skills" / cap.skill_name
        )
        if not root.exists():
            return False
    return True


def _speckit_runtime_ok(repo: Path, closed: list[str]) -> bool:
    for command in SELECTED_COMMANDS:
        if f"speckit.{command}" not in closed:
            continue
        skill = repo / skill_rel(command)
        if not skill.is_file():
            return False
        if leftover_tokens(skill.read_text(encoding="utf-8")):
            return False
    return True


def _git_head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""
