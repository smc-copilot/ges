from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ges.source_adapters.base import ProjectedFile, Projection

HARNESS_NOTE = """<!-- ges:v6:managed -->
GES 6 composed shared skills live in `.agents/skills/`.
This harness file is GES-managed integration material only.
"""


class HarnessAdapter(Protocol):
    harness_id: str

    def project(self, repo: Path, agents: list[str], shared: Projection) -> Projection:
        ...


def managed_pointer(relpath: str, harness: str) -> ProjectedFile:
    return ProjectedFile(
        relpath=relpath,
        content=HARNESS_NOTE.encode("utf-8"),
        capability=None,
        source="ges",
        source_sha=None,
        kind="harness",
        ownership_type="FILE",
    )
