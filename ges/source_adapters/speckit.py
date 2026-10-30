from __future__ import annotations

from pathlib import Path

from ges.catalog.loader import Capability, Catalog, SourcePin
from ges.errors import SPEC_KIT_MANAGED_CONFLICT, GesError
from ges.reconciler.hashes import artifact_index
from ges.reconciler.state import read_receipt
from ges.resolver.capability_graph import Resolution
from ges.source_adapters.base import Projection
from ges.source_adapters.speckit_render import render_selected


class SpecKitAdapter:
    source_id = "spec-kit"

    def project(
        self,
        catalog: Catalog,
        pin: SourcePin,
        capabilities: list[Capability],
        repo: Path,
        resolution: Resolution,
    ) -> Projection:
        projection = Projection()
        owned = artifact_index(read_receipt(repo) or {})
        for item in render_selected(pin, capabilities):
            if (repo / item.relpath).is_file() and item.relpath not in owned:
                current = (repo / item.relpath).read_bytes()
                if current != item.content:
                    if item.relpath.startswith(".cursor/skills/"):
                        raise GesError(
                            SPEC_KIT_MANAGED_CONFLICT,
                            f"managed Spec Kit path {item.relpath} exists without GES receipt ownership",
                        )
                    continue
            projection.add(item)
        return projection
