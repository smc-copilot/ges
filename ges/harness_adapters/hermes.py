from __future__ import annotations

from pathlib import Path

from ges.errors import HARNESS_NOT_SUPPORTED, GesError
from ges.source_adapters.base import Projection


class HermesAdapter:
    harness_id = "hermes"

    def project(self, repo: Path, agents: list[str], shared: Projection) -> Projection:
        if "hermes" in agents:
            raise GesError(HARNESS_NOT_SUPPORTED, "Hermes projection is deferred past alpha.1")
        return Projection()
