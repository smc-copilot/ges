from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ges.io import read_json, sha256_file
from ges.paths import to_posix

OWNED_UNMODIFIED = "OWNED_UNMODIFIED"
OWNED_ABSENT = "OWNED_ABSENT"
LEGACY_OWNERSHIP_UNKNOWN = "LEGACY_OWNERSHIP_UNKNOWN"
PRESERVE = "PRESERVE"

LOCK_CANDIDATES = (
    ".smc/ges-install-lock.json",
    ".smc/ges-install-receipt.json",
)


@dataclass
class LegacyEntry:
    path: str
    status: str
    action: str
    installed_sha256: str | None = None
    current_sha256: str | None = None


@dataclass
class LegacyReport:
    detected: bool
    lock_path: str | None
    entries: list[LegacyEntry] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "lock_path": self.lock_path,
            "counts": self.counts,
            "entries": [entry.__dict__ for entry in self.entries],
        }


def inspect_legacy(repo: Path) -> LegacyReport:
    lock_path, payload = _load_lock(repo)
    if payload is None:
        return LegacyReport(detected=False, lock_path=None, counts={"detected": 0})

    entries: list[LegacyEntry] = []
    for item in _owned_files(payload):
        rel = to_posix(item["path"])
        installed = item.get("installed_sha256")
        current = repo / rel
        if not current.is_file():
            entries.append(
                LegacyEntry(
                    path=rel,
                    status=OWNED_ABSENT,
                    action="REPORT",
                    installed_sha256=installed,
                )
            )
            continue
        current_hash = sha256_file(current)
        if installed and current_hash == installed:
            entries.append(
                LegacyEntry(
                    path=rel,
                    status=OWNED_UNMODIFIED,
                    action="REMOVABLE",
                    installed_sha256=installed,
                    current_sha256=current_hash,
                )
            )
        else:
            entries.append(
                LegacyEntry(
                    path=rel,
                    status=LEGACY_OWNERSHIP_UNKNOWN,
                    action=f"{PRESERVE}+REPORT",
                    installed_sha256=installed,
                    current_sha256=current_hash,
                )
            )

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return LegacyReport(
        detected=True,
        lock_path=lock_path,
        entries=entries,
        counts=counts,
    )


def removable_paths(report: LegacyReport) -> list[str]:
    return [entry.path for entry in report.entries if entry.status == OWNED_UNMODIFIED]


def _load_lock(repo: Path) -> tuple[str | None, dict[str, Any] | None]:
    for rel in LOCK_CANDIDATES:
        path = repo / rel
        if path.is_file():
            data = read_json(path)
            if isinstance(data, dict):
                return rel, data
    return None, None


def _owned_files(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("owned_files") or []
    files: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            files.append({"path": item, "installed_sha256": None})
        elif isinstance(item, dict) and item.get("path"):
            files.append(
                {
                    "path": item["path"],
                    "installed_sha256": item.get("installed_sha256"),
                }
            )
    return files
