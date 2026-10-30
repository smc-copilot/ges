from __future__ import annotations

from pathlib import Path
from typing import Any

from ges.providers.rtk_binding import binding_identity, probe_binding


def probe_capability_binding(capability_id: str, host: str) -> dict[str, Any]:
    return probe_binding(capability_id, host)


def capture_binding_identity(payload: dict[str, Any]) -> str:
    return binding_identity(payload)


def recheck_binding(capability_id: str, host: str, expected: str) -> bool:
    return binding_identity(probe_binding(capability_id, host)) == expected
