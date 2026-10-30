from __future__ import annotations

import json
import re
from pathlib import Path

from ges.source_adapters.speckit_render import leftover_tokens

SMOKE_FEATURE = (
    "GES bootstrap acceptance smoke: define a non-production diagnostic preference "
    "with one actor, one setting and one success criterion."
)
ALLOW_PREFIXES = ("specs/_ges-smoke/", ".specify/feature.json", ".specify/")
DENY_PREFIXES = ("apps/", "src/", "services/", "packages/", "contracts/")
FORBIDDEN_REPAIR_PROMPT = "Write only .specify/feature.json"


def smoke_dir(run_id: str) -> str:
    return f"specs/_ges-smoke/{run_id}"


def smoke_prompt(run_id: str) -> str:
    target = smoke_dir(run_id)
    return (
        "Use the speckit-specify skill. "
        "Create only a specification for the smoke feature. "
        "Do not implement code. "
        "Do not modify business source. "
        f"Write artifacts only under {target}/ and .specify/feature.json. "
        f'Write .specify/feature.json as {{"feature_directory":"{target}"}}. '
        f"{SMOKE_FEATURE}"
    )


def smoke_invocation_record(*, primary: int = 1, repair: int = 0) -> dict[str, int]:
    return {"primary_invocation_count": primary, "repair_invocation_count": repair}


# @lat: [[release-hardening#Strict Spec Kit Smoke]]
def feature_state_error(repo: Path, run_id: str) -> str:
    path = repo / ".specify" / "feature.json"
    if not path.is_file():
        return "SPEC_KIT_SMOKE_FEATURE_STATE_MISSING"
    actual = feature_directory(repo)
    if actual != smoke_dir(run_id):
        return "SPEC_KIT_SMOKE_FEATURE_STATE_INVALID"
    return ""


def matt_setup_prompt() -> str:
    return (
        "Use the setup-matt-pocock-skills skill. "
        "Issue tracker is GitHub. No triage skill is installed; skip triage labels. "
        "Write single-context domain docs. "
        "Create docs/agents/issue-tracker.md from the GitHub template and docs/agents/domain.md. "
        "If CLAUDE.md exists, append the Agent skills block there. "
        "Do not modify business source under apps, src, services, packages, or contracts."
    )


def evaluate_spec(path: Path) -> list[str]:
    if not path.is_file():
        return ["spec.md missing"]
    text = path.read_text(encoding="utf-8").strip()
    errors = []
    if not text:
        errors.append("spec.md empty")
    if leftover_tokens(text) or re.search(r"\[FEATURE NAME\]|\$ARGUMENTS", text):
        errors.append("unresolved template placeholder")
    if not re.search(r"functional requirement|FR-|requirement", text, re.I):
        errors.append("missing functional requirement")
    if not re.search(r"success criterion|SC-|acceptance", text, re.I):
        errors.append("missing success criterion")
    return errors


def feature_directory(repo: Path) -> str:
    path = repo / ".specify" / "feature.json"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    return str(payload.get("feature_directory") or "")


def unexpected_writes(before: dict[str, str], after: dict[str, str], run_id: str) -> list[str]:
    allowed = (f"specs/_ges-smoke/{run_id}/", ".specify/")
    unexpected = []
    for rel, identity in after.items():
        if before.get(rel) == identity:
            continue
        if any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in allowed):
            continue
        unexpected.append(rel)
    for rel in before:
        if rel not in after and not any(rel.startswith(prefix) for prefix in allowed):
            unexpected.append(rel)
    return sorted(set(unexpected))
