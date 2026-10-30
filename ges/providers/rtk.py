from __future__ import annotations

import shutil
import subprocess
from typing import Any

from ges.catalog.providers import RTK_ID, rtk_provider
from ges.reconciler.state import validate_payload

PASS = "PASS"
FAIL = "FAIL"


def probe_rtk() -> dict[str, Any]:
    names = list(rtk_provider().health_checks) or ["binary", "version"]
    checks = [{"name": name, "status": FAIL} for name in names]
    by_name = {row["name"]: row for row in checks}
    binary = shutil.which("rtk")
    if not binary:
        return _status("missing", "", checks)
    if "binary" in by_name:
        by_name["binary"]["status"] = PASS
    result = subprocess.run(
        [binary, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    version = text.splitlines()[0].strip() if text else ""
    if result.returncode != 0 or not version:
        return _status("NOT_READY", version, checks)
    if "version" in by_name:
        by_name["version"]["status"] = PASS
    return _status("READY", version, checks)


def _status(status: str, version: str, checks: list[dict[str, str]]) -> dict[str, Any]:
    payload = {
        "schema": "ges.capability-status.v1",
        "capability_id": RTK_ID,
        "provider": "rtk",
        "status": status,
        "version": version,
        "health_checks": checks,
    }
    validate_payload("ges.capability-status.v1.json", payload)
    return payload
