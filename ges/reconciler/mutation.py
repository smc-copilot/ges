from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ges.errors import BUSINESS_SOURCE_MODIFICATION_FORBIDDEN, GesError
from ges.io import write_bytes
from ges.paths import BUSINESS_SOURCE_ROOTS, to_posix
from ges.reconciler.guard import assert_allowed, assert_not_business_source, contain

LAST_LEDGER: "MutationLedger | None" = None


@dataclass
class MutationLedger:
    entries: list[dict[str, str]] = field(default_factory=list)
    business_root_write_count: int = 0

    def write_file(self, repo: Path, relpath: str, data: bytes) -> Path:
        rel = self._guard(relpath)
        target = contain(repo, rel)
        self.entries.append({"op": "write", "path": rel})
        write_bytes(target, data)
        return target

    def remove_file(self, repo: Path, relpath: str) -> Path:
        rel = self._guard(relpath)
        target = contain(repo, rel)
        self.entries.append({"op": "remove", "path": rel})
        if target.is_file():
            target.unlink()
        return target

    def _guard(self, relpath: str) -> str:
        rel = to_posix(relpath)
        assert_allowed(rel)
        assert_not_business_source(rel)
        top = rel.split("/", 1)[0]
        if top in BUSINESS_SOURCE_ROOTS:
            self.business_root_write_count += 1
            raise GesError(
                BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
                f"business source modification forbidden: {rel}",
            )
        return rel


def new_ledger() -> MutationLedger:
    global LAST_LEDGER
    LAST_LEDGER = MutationLedger()
    return LAST_LEDGER
