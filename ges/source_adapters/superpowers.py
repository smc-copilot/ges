from __future__ import annotations

from pathlib import Path

from ges.catalog.loader import Capability, Catalog, SourcePin
from ges.resolver.capability_graph import Resolution
from ges.source_adapters.base import ProjectedFile, Projection
from ges.source_adapters.cache import copy_tree, resolve_path

EXCLUDED_BOOTSTRAP = {"superpowers.using-superpowers", "superpowers.brainstorming"}


class SuperpowersAdapter:
    source_id = "superpowers"

    def project(
        self,
        catalog: Catalog,
        pin: SourcePin,
        capabilities: list[Capability],
        repo: Path,
        resolution: Resolution,
    ) -> Projection:
        projection = Projection()
        for cap in capabilities:
            if cap.id in EXCLUDED_BOOTSTRAP:
                continue
            if cap.projection_type != "skill" or not cap.skill_name:
                continue
            src = resolve_path(pin, cap.source_path)
            files: dict[str, bytes] = {}
            copy_tree(src, files, f".agents/skills/{cap.skill_name}")
            for rel, content in files.items():
                projection.add(
                    ProjectedFile(
                        relpath=rel,
                        content=content,
                        capability=cap.id,
                        source=pin.id,
                        source_sha=pin.commit_sha,
                        kind="skill",
                    )
                )
        return projection
