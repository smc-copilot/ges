from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ges.io import read_yaml
from ges.paths import CATALOG_DIR


@dataclass(frozen=True)
class Capability:
    id: str
    source: str
    source_path: str
    owner_domain: str
    requires: tuple[str, ...]
    conflicts: tuple[str, ...]
    supported_harnesses: tuple[str, ...]
    projection_type: str
    default_profiles: tuple[str, ...]
    skill_name: str | None
    runtime_paths: tuple[str, ...] = ()
    optional: bool = False


@dataclass(frozen=True)
class SourcePin:
    id: str
    cache_key: str
    repo: str
    commit_sha: str


@dataclass
class Profile:
    id: str
    engineering_stack: dict[str, Any]
    required: list[str]
    recommended: list[str]
    optional: list[str]
    forbidden: list[str]


@dataclass
class Catalog:
    capabilities: dict[str, Capability]
    sources: dict[str, SourcePin]
    conflict_pairs: list[tuple[str, str]]
    profiles: dict[str, Profile]

    def get(self, cap_id: str) -> Capability:
        return self.capabilities[cap_id]


def load_catalog(root: Path | None = None) -> Catalog:
    base = root or CATALOG_DIR
    caps_raw = read_yaml(base / "capabilities.yaml")
    sources_raw = read_yaml(base / "sources.yaml")
    conflicts_raw = read_yaml(base / "conflicts.yaml")
    capabilities = {}
    for item in caps_raw.get("capabilities") or []:
        cap = Capability(
            id=item["id"],
            source=item["source"],
            source_path=item["source_path"],
            owner_domain=item["owner_domain"],
            requires=tuple(item.get("requires") or []),
            conflicts=tuple(item.get("conflicts") or []),
            supported_harnesses=tuple(item.get("supported_harnesses") or []),
            projection_type=item["projection_type"],
            default_profiles=tuple(item.get("default_profiles") or []),
            skill_name=item.get("skill_name"),
            runtime_paths=tuple(item.get("runtime_paths") or []),
            optional=bool(item.get("optional")),
        )
        capabilities[cap.id] = cap
    sources = {
        key: SourcePin(
            id=value["id"],
            cache_key=value["cache_key"],
            repo=value["repo"],
            commit_sha=value["commit_sha"],
        )
        for key, value in (sources_raw.get("sources") or {}).items()
    }
    pairs = [tuple(pair) for pair in (conflicts_raw.get("pairs") or [])]
    profiles: dict[str, Profile] = {}
    for path in sorted((base / "profiles").glob("*.yaml")):
        raw = read_yaml(path)
        forbidden = list(raw.get("forbidden") or raw.get("excluded") or [])
        recommended = list(raw.get("recommended") or [])
        required = list(raw.get("required") or [])
        if not recommended and raw.get("required") and raw.get("excluded") is not None and not raw.get("recommended"):
            # v1 profiles treated every former required-except-setup as recommended
            recommended = [item for item in required[1:]] if required else []
            required = required[:1] if required else []
        profiles[raw["id"]] = Profile(
            id=raw["id"],
            engineering_stack=raw.get("engineering_stack") or {},
            required=required,
            recommended=recommended,
            optional=list(raw.get("optional") or []),
            forbidden=forbidden,
        )
    return Catalog(
        capabilities=capabilities,
        sources=sources,
        conflict_pairs=pairs,
        profiles=profiles,
    )
