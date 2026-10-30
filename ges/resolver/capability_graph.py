from __future__ import annotations

from dataclasses import dataclass, field

from ges.catalog.loader import Catalog
from ges.errors import (
    CAPABILITY_DEPENDENCY_MISSING,
    CAPABILITY_NOT_FOUND,
    CAPABILITY_OWNERSHIP_CONFLICT,
    GesError,
)


@dataclass
class Resolution:
    profile: str
    selected: list[str]
    excluded: list[str]
    closed: list[str]
    conflicts: list[dict[str, str]] = field(default_factory=list)
    ownership_blocked: bool = False


def close_dependencies(catalog: Catalog, selected: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    def visit(cap_id: str) -> None:
        if cap_id in seen:
            return
        if cap_id not in catalog.capabilities:
            raise GesError(CAPABILITY_NOT_FOUND, f"unknown capability {cap_id}")
        seen.add(cap_id)
        cap = catalog.get(cap_id)
        for dep in cap.requires:
            if dep not in catalog.capabilities:
                raise GesError(
                    CAPABILITY_DEPENDENCY_MISSING,
                    f"{cap_id} requires missing {dep}",
                )
            visit(dep)
        ordered.append(cap_id)

    for item in selected:
        visit(item)
    return ordered


def detect_conflicts(catalog: Catalog, closed: list[str]) -> list[dict[str, str]]:
    selected = set(closed)
    found: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add(left: str, right: str, reason: str) -> None:
        key = tuple(sorted((left, right)))
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        found.append({"left": left, "right": right, "reason": reason})

    for left, right in catalog.conflict_pairs:
        left_hit = _expand(catalog, left, selected)
        right_hit = _expand(catalog, right, selected)
        if left_hit and right_hit:
            add(left_hit[0], right_hit[0], "catalog-pair")

    by_domain: dict[str, list[str]] = {}
    for cap_id in closed:
        cap = catalog.get(cap_id)
        if cap.projection_type == "virtual":
            continue
        by_domain.setdefault(cap.owner_domain, []).append(cap_id)
    for domain, ids in by_domain.items():
        sources = {catalog.get(cap_id).source for cap_id in ids}
        if len(sources) > 1:
            add(ids[0], ids[1], f"owner-domain:{domain}")

    for cap_id in closed:
        cap = catalog.get(cap_id)
        for other in cap.conflicts:
            hits = _expand(catalog, other, selected)
            if hits:
                add(cap_id, hits[0], "capability-conflicts")
    return found


def _expand(catalog: Catalog, cap_id: str, selected: set[str]) -> list[str]:
    if cap_id in selected:
        return [cap_id]
    # virtual nodes match any selected capability that requires them
    if cap_id in catalog.capabilities and catalog.get(cap_id).projection_type == "virtual":
        return [item for item in selected if cap_id in catalog.get(item).requires]
    return []


def resolve_graph(
    catalog: Catalog,
    *,
    profile: str,
    selected: list[str],
    excluded: list[str],
) -> Resolution:
    wanted = [item for item in selected if item not in excluded]
    closed = [item for item in close_dependencies(catalog, wanted) if item not in excluded]
    missing = []
    for cap_id in closed:
        for dep in catalog.get(cap_id).requires:
            if dep in excluded or dep not in closed:
                missing.append((cap_id, dep))
    if missing:
        cap_id, dep = missing[0]
        raise GesError(
            CAPABILITY_DEPENDENCY_MISSING,
            f"{cap_id} is missing required dependency {dep}",
            details={"missing": missing},
        )
    conflicts = detect_conflicts(catalog, closed)
    return Resolution(
        profile=profile,
        selected=sorted(wanted),
        excluded=sorted(excluded),
        closed=sorted(closed),
        conflicts=conflicts,
        ownership_blocked=bool(conflicts),
    )


def assert_no_conflicts(resolution: Resolution) -> None:
    if resolution.ownership_blocked:
        raise GesError(
            CAPABILITY_OWNERSHIP_CONFLICT,
            "capability ownership conflict blocks apply",
            details={"conflicts": resolution.conflicts},
        )
