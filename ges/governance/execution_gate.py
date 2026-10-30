from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges import __product_version__
from ges.catalog.providers import RTK_ID
from ges.errors import (
    CAPABILITY_BINDING_CHANGED_DURING_EVALUATION,
    WORK_CAPABILITY_BINDING_UNBOUND,
    WORK_CAPABILITY_BINDING_UNPROVEN,
    WORK_CAPABILITY_CONFLICT,
    WORK_CAPABILITY_PROHIBITED,
    WORK_CAPABILITY_PROVIDER_NOT_READY,
    WORK_CAPABILITY_REQUIRED_MISSING,
    WORK_EXECUTION_CONTRACT_MISSING,
    WORK_NOT_READY,
    WORK_SCHEMA_INVALID,
)
from ges.governance.gates import evaluate_intake, exit_code_for
from ges.governance.reasons import reason, sort_reasons
from ges.governance.storage import load_work
from ges.paths import capability_policy_path
from ges.providers.binding import capture_binding_identity, probe_capability_binding
from ges.providers.compat import package_incompatible
from ges.providers.overlay import is_installed, read_policy
from ges.providers.rtk import probe_rtk
from ges.reconciler.state import validate_payload
from ges.stagelog import GATE_EXECUTION_INTAKE, GATE_EXPLAIN, emit

GATE_EXECUTION = GATE_EXECUTION_INTAKE


def evaluate_execution(repo: Path, work_id: str) -> dict[str, Any]:
    emit(GATE_EXECUTION, "start", work_id=work_id)
    work = load_work(repo, work_id)
    if work.get("schema") != "ges.work.v2":
        payload = _blocked(
            work_id,
            host="",
            profile="",
            effective=[],
            capabilities=[],
            reasons=[
                reason(
                    WORK_EXECUTION_CONTRACT_MISSING,
                    "work.schema",
                    "ges.work.v2",
                    work.get("schema"),
                    "work",
                    "Run ges work migrate --host <host>.",
                )
            ],
            status="BLOCKED",
        )
        emit(GATE_EXECUTION, "complete", status="BLOCKED")
        return payload

    execution = work.get("execution") or {}
    host = str(execution.get("host") or "")
    profile = str(execution.get("profile") or "")
    if profile != "ges-native" or host not in {"cursor", "codex", "hermes"}:
        payload = _blocked(
            work_id,
            host=host,
            profile=profile,
            effective=[],
            capabilities=[],
            reasons=[
                reason(
                    WORK_SCHEMA_INVALID,
                    "work.execution",
                    "ges-native + host",
                    f"{profile}/{host}",
                    "work",
                    "Fix execution.profile/host.",
                )
            ],
            status="FAIL",
        )
        emit(GATE_EXECUTION, "complete", status="FAIL")
        return payload

    intake = evaluate_intake(repo, work_id)
    if intake.get("status") != "PASS":
        payload = _blocked(
            work_id,
            host=host,
            profile=profile,
            effective=[],
            capabilities=[],
            reasons=[
                reason(
                    WORK_NOT_READY,
                    "gate.intake",
                    "PASS",
                    intake.get("status"),
                    "gate",
                    "Make Gate A PASS before execution gate.",
                )
            ]
            + list(intake.get("reasons") or []),
            status="BLOCKED",
        )
        emit(GATE_EXECUTION, "complete", status="BLOCKED")
        return payload

    try:
        effective, fail_reasons = resolve_effective_required(repo, work)
    except Exception as exc:  # policy invalid
        payload = _blocked(
            work_id,
            host=host,
            profile=profile,
            effective=[],
            capabilities=[],
            reasons=[reason(str(getattr(exc, "code", WORK_SCHEMA_INVALID)), "policy", "valid", str(exc), "policy", "Fix policy.yaml")],
            status="FAIL",
        )
        emit(GATE_EXECUTION, "complete", status="FAIL")
        return payload

    if fail_reasons:
        payload = _blocked(
            work_id,
            host=host,
            profile=profile,
            effective=effective,
            capabilities=[],
            reasons=fail_reasons,
            status="FAIL",
        )
        emit(GATE_EXECUTION, "complete", status="FAIL")
        return payload

    capability_rows: list[dict[str, Any]] = []
    block_reasons: list[dict[str, Any]] = []
    identities: dict[str, str] = {}
    for cap_id in effective:
        if not is_installed(repo, cap_id):
            block_reasons.append(
                reason(
                    WORK_CAPABILITY_REQUIRED_MISSING,
                    f"installed.{cap_id}",
                    "installed",
                    "missing",
                    "overlay",
                    "Run ges capability add.",
                )
            )
            continue
        provider = probe_rtk() if cap_id == RTK_ID else {"status": "missing", "capability_id": cap_id}
        if provider.get("status") != "READY":
            block_reasons.append(
                reason(
                    WORK_CAPABILITY_PROVIDER_NOT_READY,
                    f"provider.{cap_id}",
                    "READY",
                    provider.get("status"),
                    "provider",
                    "Install/fix provider binary.",
                )
            )
            continue
        binding = probe_capability_binding(cap_id, host)
        identities[cap_id] = capture_binding_identity(binding)
        capability_rows.append({"capability_id": cap_id, "provider": provider, "binding": binding})
        if binding["status"] == "UNBOUND":
            block_reasons.append(
                reason(
                    WORK_CAPABILITY_BINDING_UNBOUND,
                    f"binding.{cap_id}",
                    "BOUND",
                    "UNBOUND",
                    "host",
                    "Register RTK hooks for the declared host.",
                )
            )
        elif binding["status"] != "BOUND":
            block_reasons.append(
                reason(
                    WORK_CAPABILITY_BINDING_UNPROVEN,
                    f"binding.{cap_id}",
                    "BOUND",
                    binding["status"],
                    "host",
                    "Resolve ambiguous host binding evidence.",
                )
            )

    for cap_id, expected in identities.items():
        later = capture_binding_identity(probe_capability_binding(cap_id, host))
        if later != expected:
            block_reasons.append(
                reason(
                    CAPABILITY_BINDING_CHANGED_DURING_EVALUATION,
                    f"binding.{cap_id}",
                    expected,
                    later,
                    "host",
                    "Re-run after host config stabilizes.",
                )
            )

    if block_reasons:
        payload = _blocked(
            work_id,
            host=host,
            profile=profile,
            effective=effective,
            capabilities=capability_rows,
            reasons=sort_reasons(block_reasons),
            status="BLOCKED",
        )
        emit(GATE_EXECUTION, "complete", status="BLOCKED")
        return payload

    payload = {
        "schema": "ges.execution-readiness.v1",
        "work_id": work_id,
        "status": "PASS",
        "verdict": "EXECUTION_READY",
        "execution_profile": profile,
        "host": host,
        "effective_required": effective,
        "capabilities": capability_rows,
        "reasons": [],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": __product_version__,
    }
    validate_payload("ges.execution-readiness.v1.json", payload)
    emit(GATE_EXECUTION, "complete", status="PASS")
    return payload


def explain_execution(repo: Path, work_id: str) -> dict[str, Any]:
    emit(GATE_EXPLAIN, "start", work_id=work_id, gate="execution")
    payload = evaluate_execution(repo, work_id)
    emit(GATE_EXPLAIN, "complete", reasons=len(payload.get("reasons") or []))
    return payload


def resolve_effective_required(repo: Path, work: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    policy = read_policy(repo)
    if policy is None and not capability_policy_path(repo).is_file():
        policy = {"required": [], "recommended": [], "optional": [], "prohibited": []}
    elif policy is None:
        policy = {"required": [], "recommended": [], "optional": [], "prohibited": []}

    buckets = ("prohibited", "required", "recommended", "optional")
    seen: dict[str, str] = {}
    for key in buckets:
        for cap_id in policy.get(key) or []:
            if cap_id in seen and seen[cap_id] != key:
                from ges.errors import POLICY_SCHEMA_INVALID, GesError

                raise GesError(POLICY_SCHEMA_INVALID, f"capability listed in multiple policy buckets: {cap_id}")
            seen[cap_id] = key

    work_required = list((work.get("capabilities") or {}).get("required") or [])
    project_required = list(policy.get("required") or [])
    prohibited = set(policy.get("prohibited") or [])
    effective = sorted(set(project_required) | set(work_required))
    fail: list[dict[str, Any]] = []
    for cap_id in effective:
        if cap_id in prohibited:
            fail.append(
                reason(
                    WORK_CAPABILITY_PROHIBITED,
                    f"policy.prohibited",
                    "allowed",
                    cap_id,
                    "policy",
                    "Remove prohibited or work required.",
                )
            )
    for cap_id in effective:
        for other in package_incompatible(cap_id):
            if other in effective:
                fail.append(
                    reason(
                        WORK_CAPABILITY_CONFLICT,
                        "providers.incompatible",
                        "compatible",
                        f"{cap_id}|{other}",
                        "catalog",
                        "Remove conflicting required capabilities.",
                    )
                )
    return effective, sort_reasons(fail)


def _blocked(
    work_id: str,
    *,
    host: str,
    profile: str,
    effective: list[str],
    capabilities: list[dict[str, Any]],
    reasons: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    payload = {
        "schema": "ges.execution-readiness.v1",
        "work_id": work_id,
        "status": status,
        "verdict": "BLOCKED",
        "execution_profile": profile,
        "host": host,
        "effective_required": effective,
        "capabilities": capabilities,
        "reasons": reasons,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": __product_version__,
    }
    validate_payload("ges.execution-readiness.v1.json", payload)
    return payload


__all__ = ["evaluate_execution", "explain_execution", "exit_code_for", "resolve_effective_required"]
