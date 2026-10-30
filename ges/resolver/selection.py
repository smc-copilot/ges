from __future__ import annotations

from ges.catalog.loader import Catalog, Profile
from ges.errors import CAPABILITY_NOT_FOUND, DESIRED_STATE_INVALID, GesError
from ges.resolver.capability_graph import Resolution, resolve_graph


def initial_requested(profile: Profile) -> list[str]:
    return list(dict.fromkeys(profile.required + profile.recommended))


def recommend(catalog: Catalog, profile: Profile) -> list[str]:
    return initial_requested(profile)


def resolve_selection(
    catalog: Catalog,
    profile: Profile,
    *,
    requested: list[str] | None = None,
    exclude: list[str] | None = None,
    extra: list[str] | None = None,
) -> Resolution:
    exclude = list(exclude or [])
    extra = list(extra or [])
    unknown = [item for item in [*exclude, *extra, *(requested or [])] if item not in catalog.capabilities]
    if unknown:
        raise GesError(CAPABILITY_NOT_FOUND, f"unknown capability {unknown[0]}", details={"ids": unknown})

    if requested is not None:
        selected = list(dict.fromkeys([item for item in requested if item not in exclude] + extra))
    else:
        selected = list(dict.fromkeys([item for item in initial_requested(profile) if item not in exclude] + extra))

    required_hit = [item for item in profile.required if item in exclude]
    if required_hit:
        raise GesError(
            DESIRED_STATE_INVALID,
            f"required capability cannot be excluded: {required_hit[0]}",
            details={"required": required_hit},
        )

    resolution = resolve_graph(
        catalog,
        profile=profile.id,
        selected=selected,
        excluded=exclude,
    )
    forbidden_hit = [item for item in resolution.closed if item in profile.forbidden]
    if forbidden_hit and not resolution.ownership_blocked:
        raise GesError(
            DESIRED_STATE_INVALID,
            f"forbidden capability cannot be selected: {forbidden_hit[0]}",
            details={"forbidden": forbidden_hit},
        )
    resolution.selected = selected
    resolution.excluded = list(dict.fromkeys(exclude))
    return resolution


def project_desired_state(profile: Profile, resolution: Resolution, agents: list[str]) -> dict:
    return {
        "schema": "ges.project.v2",
        "profile": profile.id,
        "agents": agents,
        "capabilities": {
            "requested": list(resolution.selected),
            "explicitly_disabled": list(resolution.excluded),
        },
        "resolution": {"mode": "explicit"},
        "engineering_stack": profile.engineering_stack,
    }
