from __future__ import annotations

from pathlib import Path

from ges.harness_adapters.base import managed_pointer
from ges.source_adapters.base import Projection


class CursorAdapter:
    harness_id = "cursor"

    def project(self, repo: Path, agents: list[str], shared: Projection) -> Projection:
        projection = Projection()
        if "cursor" not in agents:
            return projection
        if (repo / ".cursor").exists() or True:
            projection.add(managed_pointer(".cursor/ges/engineering-stack.md", "cursor"))
        return projection
