from __future__ import annotations

from typing import Any, Iterable

from ges.catalog.providers import RTK_ID
from ges.reconciler.state import validate_payload

SPECKIT_DISPLAY = "speckit"


def build_capability_plan(
    profile: dict[str, Any],
    closed: Iterable[str] | None = None,
) -> dict[str, Any]:
    lifecycle = str(profile.get("repository_lifecycle") or "")
    layout = str(profile.get("layout") or "")
    kind = str(profile.get("kind") or profile.get("repository_kind") or "")
    closed_ids = list(closed or [])
    required = [SPECKIT_DISPLAY] if any(item.startswith("speckit.") for item in closed_ids) else []
    recommended: list[str] = []
    optional: list[str] = []
    reasons: dict[str, str] = {}
    if lifecycle == "brownfield" or layout == "monorepo":
        recommended.append(RTK_ID)
        reasons[RTK_ID] = kind
    else:
        optional.append(RTK_ID)
    payload = {
        "schema": "ges.capability-plan.v1",
        "required": required,
        "recommended": recommended,
        "optional": optional,
        "incompatible": [],
        "reasons": reasons,
        "llm_token_usage": 0,
    }
    validate_payload("ges.capability-plan.v1.json", payload)
    return payload
