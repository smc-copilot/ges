from __future__ import annotations

from pathlib import Path

from ges.harness_adapters.base import managed_pointer
from ges.source_adapters.base import Projection


class CodexAdapter:
    harness_id = "codex"

    def project(self, repo: Path, agents: list[str], shared: Projection) -> Projection:
        projection = Projection()
        if "codex" not in agents:
            return projection
        projection.add(managed_pointer(".codex/ges/engineering-stack.md", "codex"))
        return projection
