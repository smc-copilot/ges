from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ges.errors import MANAGED_CONTENT_MODIFIED, UNMANAGED_PATH_CONFLICT, GesError
from ges.harness_adapters.agents_md import extract_section
from ges.legacy.v5 import LegacyReport
from ges.paths import PRESERVE_ALWAYS, to_posix
from ges.reconciler.guard import assert_allowed, assert_not_business_source
from ges.reconciler.hashes import artifact_index, current_identity, desired_identity
from ges.reconciler.state import read_receipt
from ges.source_adapters.base import ProjectedFile
from ges.stagelog import COLLISION_CHECK, PLAN, emit

ADD = "ADD"
UPDATE = "UPDATE"
REMOVE = "REMOVE"
PRESERVE = "PRESERVE"
CONFLICT = "CONFLICT"
ADOPT_IDENTICAL = "ADOPT_IDENTICAL"


@dataclass
class PlanEntry:
    path: str
    action: str
    kind: str
    capability: str | None = None
    ownership_type: str = "FILE"
    selector: Any = None
    reason: str = ""
    producer: str | None = None
    capability_ids: list[str] = field(default_factory=list)
    current_identity: str | None = None
    desired_identity: str | None = None


@dataclass
class InstallPlan:
    entries: list[PlanEntry] = field(default_factory=list)
    source_shas: dict[str, str] = field(default_factory=dict)
    legacy_report: dict[str, Any] = field(default_factory=dict)
    business_source_guard: dict[str, Any] = field(default_factory=dict)
    skills_to_add: list[str] = field(default_factory=list)
    skills_to_remove: list[str] = field(default_factory=list)
    managed_sections_to_add: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def noop(self) -> bool:
        return not any(entry.action in {ADD, UPDATE, REMOVE} for entry in self.entries)

    def changing(self) -> list[PlanEntry]:
        return [entry for entry in self.entries if entry.action in {ADD, UPDATE, REMOVE}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ges.install-plan.v1",
            "files_to_create": [e.path for e in self.entries if e.action == ADD],
            "files_to_update": [e.path for e in self.entries if e.action == UPDATE],
            "managed_sections_to_add": self.managed_sections_to_add,
            "skills_to_add": self.skills_to_add,
            "skills_to_remove": self.skills_to_remove,
            "source_shas": self.source_shas,
            "legacy_report": self.legacy_report,
            "business_source_guard": self.business_source_guard,
            "entries": [entry.__dict__ for entry in self.entries],
            "warnings": self.warnings,
            "noop": self.noop,
        }


def build_plan(
    repo: Path,
    desired: dict[str, ProjectedFile],
    *,
    source_shas: dict[str, str],
    legacy: LegacyReport,
    business_guard: dict[str, Any],
) -> InstallPlan:
    emit(COLLISION_CHECK, "start")
    receipt = read_receipt(repo) or {}
    artifacts = artifact_index(receipt)
    plan = InstallPlan(
        source_shas=source_shas,
        legacy_report=legacy.to_dict(),
        business_source_guard=business_guard,
    )
    if (repo / ".specify" / "constitution.md").is_file():
        plan.warnings.append(
            "LEGACY_OR_USER_SPEC_STATE: .specify/constitution.md is preserved; "
            "current Spec Kit expects .specify/memory/constitution.md; manual review may be required"
        )
    emit(PLAN, "start")
    for rel, item in sorted(desired.items()):
        assert_allowed(rel)
        assert_not_business_source(rel)
        target = repo / rel
        _assert_compatible_path(target, rel, item)
        current = current_identity(repo, rel, item)
        generated = desired_identity(item)
        last = (artifacts.get(rel) or {}).get("last_applied_hash")
        owned = rel in artifacts
        caps = [item.capability] if item.capability else []
        if any(to_posix(rel).startswith(prefix) for prefix in PRESERVE_ALWAYS):
            plan.entries.append(
                _entry(item, rel, PRESERVE, current, generated, reason="preserve-always", capability_ids=caps)
            )
            continue
        if item.ownership_type == "SECTION":
            _plan_section(plan, repo, rel, item, current, generated, last, owned, caps)
            continue
        if current is None:
            plan.entries.append(
                _entry(item, rel, ADD, current, generated, reason="missing", capability_ids=caps)
            )
            _note_skill(plan, rel, item)
            continue
        if current == generated:
            reason = "adopt-identical" if not owned else "already-desired"
            action = ADOPT_IDENTICAL if not owned else PRESERVE
            plan.entries.append(_entry(item, rel, action, current, generated, reason=reason, capability_ids=caps))
            continue
        if owned and last and current != last:
            raise GesError(MANAGED_CONTENT_MODIFIED, f"managed content was modified: {rel}")
        if owned and last == generated:
            plan.entries.append(
                _entry(item, rel, PRESERVE, current, generated, reason="matches-last-applied", capability_ids=caps)
            )
            continue
        if owned:
            plan.entries.append(
                _entry(item, rel, UPDATE, current, generated, reason="desired-differs", capability_ids=caps)
            )
            continue
        raise GesError(
            UNMANAGED_PATH_CONFLICT,
            f"unmanaged path exists with different content: {rel}",
            details={"path": rel},
        )

    for rel, meta in sorted(artifacts.items()):
        if rel in desired:
            continue
        if (repo / rel).exists():
            current = current_identity(repo, rel, ownership_type=meta.get("ownership_type") or "FILE")
            last = meta.get("last_applied_hash")
            if last and current != last:
                raise GesError(MANAGED_CONTENT_MODIFIED, f"managed content was modified: {rel}")
            plan.entries.append(
                PlanEntry(
                    path=rel,
                    action=REMOVE,
                    kind="managed",
                    ownership_type=meta.get("ownership_type") or "FILE",
                    selector=meta.get("selector"),
                    reason="no-longer-desired",
                    producer=meta.get("producer"),
                    capability_ids=list(meta.get("capability_ids") or []),
                    current_identity=current,
                    desired_identity=None,
                )
            )
            if rel.startswith(".agents/skills/"):
                skill = rel.split("/")[2]
                if skill not in plan.skills_to_remove:
                    plan.skills_to_remove.append(skill)
    emit(PLAN, "complete", entries=len(plan.entries), noop=plan.noop)
    return plan


def _plan_section(
    plan: InstallPlan,
    repo: Path,
    rel: str,
    item: ProjectedFile,
    current: str | None,
    generated: str,
    last: str | None,
    owned: bool,
    caps: list[str],
) -> None:
    path = repo / rel
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    has_section = bool(extract_section(text))
    if not path.is_file() or not has_section:
        plan.entries.append(_entry(item, rel, ADD, current, generated, reason="section-missing", capability_ids=caps))
        if rel == "AGENTS.md":
            plan.managed_sections_to_add.append("engineering-stack")
        return
    if current == generated:
        plan.entries.append(_entry(item, rel, PRESERVE, current, generated, reason="section-desired", capability_ids=caps))
        return
    if owned and last and current != last:
        raise GesError(MANAGED_CONTENT_MODIFIED, f"managed content was modified: {rel}")
    if owned:
        plan.entries.append(_entry(item, rel, UPDATE, current, generated, reason="section-differs", capability_ids=caps))
        return
    raise GesError(
        UNMANAGED_PATH_CONFLICT,
        f"unmanaged section exists with different content: {rel}",
        details={"path": rel},
    )


def _assert_compatible_path(target: Path, rel: str, item: ProjectedFile) -> None:
    if not target.exists():
        return
    if target.is_symlink() or target.is_dir():
        raise GesError(
            UNMANAGED_PATH_CONFLICT,
            f"incompatible ownership for {rel}",
            details={"path": rel, "ownership_type": item.ownership_type},
        )


def _note_skill(plan: InstallPlan, rel: str, item: ProjectedFile) -> None:
    if item.kind == "skill" and item.capability:
        skill = rel.split("/")[2] if rel.startswith(".agents/skills/") else item.capability
        if skill not in plan.skills_to_add:
            plan.skills_to_add.append(skill)


def _entry(
    item: ProjectedFile,
    rel: str,
    action: str,
    current: str | None,
    generated: str,
    *,
    reason: str,
    capability_ids: list[str],
) -> PlanEntry:
    return PlanEntry(
        path=rel,
        action=action,
        kind=item.kind,
        capability=item.capability,
        ownership_type=item.ownership_type,
        selector=item.selector,
        reason=reason,
        producer=item.source,
        capability_ids=capability_ids,
        current_identity=current,
        desired_identity=generated,
    )
