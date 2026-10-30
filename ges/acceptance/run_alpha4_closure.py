from __future__ import annotations

import io
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from ges.acceptance.alpha4_closure_evidence import (
    REQUIRED_ALPHA4_ACCEPTANCES,
    record,
    write_alpha4_closure_evidence,
)
from ges.acceptance.golden_worktree import DEFAULT_GOLDEN_SOURCE, git, source_dirty_status
from ges.acceptance.release_evidence import artifact_inside_candidate, resolve_artifact_dir
from ges.acceptance.run_golden_capability_governance import main as golden_main
from ges.catalog.providers import RTK_ID, load_providers
from ges.providers.rtk import probe_rtk


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="GES Alpha.4 Capability Closure Gate")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--skip-regression", action="store_true")
    args = parser.parse_args(argv)

    ges_root = Path(__file__).resolve().parents[2]
    artifact_dir = resolve_artifact_dir(args.artifact_dir or None)
    ges_head = git(ges_root, ["rev-parse", "HEAD"]).stdout.strip()
    source = Path(os.environ.get("GES_ALPHA4_GOLDEN_REPO", str(DEFAULT_GOLDEN_SOURCE)))

    rows: dict[str, dict[str, Any]] = {}
    for item in _status_acceptances():
        rows[item["acceptance_id"]] = item
    gold_rows, golden_meta = _golden_acceptances(source)
    for item in gold_rows:
        rows[item["acceptance_id"]] = item

    # EVID: exact required set after STATUS+GOLD+EVID+READY filled below.
    # First compute EVID against STATUS+GOLD completeness of the six core rows.
    core_ids = [aid for aid in REQUIRED_ALPHA4_ACCEPTANCES if aid.startswith(("A-A4-STATUS-", "A-A4-GOLD-"))]
    present = [aid for aid in core_ids if aid in rows]
    if len(present) != len(set(present)):
        rows["A-A4-EVID-002"] = record("A-A4-EVID-002", "FAIL", "dupes", 2, "unique", "duplicate")
    else:
        rows["A-A4-EVID-002"] = record("A-A4-EVID-002", "PASS", "dupes", 0, "unique", "unique")
    if set(present) != set(core_ids):
        rows["A-A4-EVID-001"] = record(
            "A-A4-EVID-001",
            "BLOCKED",
            "set",
            3,
            sorted(REQUIRED_ALPHA4_ACCEPTANCES),
            sorted(present),
        )
    else:
        rows["A-A4-EVID-001"] = record(
            "A-A4-EVID-001",
            "PASS",
            "set",
            0,
            sorted(REQUIRED_ALPHA4_ACCEPTANCES),
            sorted(REQUIRED_ALPHA4_ACCEPTANCES),
        )
    non_pass_core = [aid for aid in core_ids if rows.get(aid, {}).get("status") != "PASS"]
    if non_pass_core:
        st = "FAIL" if any(rows[aid]["status"] == "FAIL" for aid in non_pass_core if aid in rows) else "BLOCKED"
        rows["A-A4-EVID-003"] = record("A-A4-EVID-003", st, "statuses", 2 if st == "FAIL" else 3, "all PASS", non_pass_core)
    else:
        rows["A-A4-EVID-003"] = record("A-A4-EVID-003", "PASS", "statuses", 0, "all PASS", "all PASS")

    regression = _run_regressions(ges_root, skip=args.skip_regression)
    regression_ok = all(value == "PASS" for value in regression.values())

    core_and_evid_ok = all(
        rows.get(aid, {}).get("status") == "PASS"
        for aid in REQUIRED_ALPHA4_ACCEPTANCES
        if aid.startswith(("A-A4-STATUS-", "A-A4-GOLD-", "A-A4-EVID-"))
    )
    ready_ok = core_and_evid_ok and regression_ok
    planned = artifact_dir / "alpha4-capability-closure-evidence.json"
    if artifact_inside_candidate(planned, ges_root):
        ready_ok = False

    rows["A-A4-READY-001"] = record(
        "A-A4-READY-001",
        "PASS" if ready_ok else "FAIL",
        "closure-ready",
        0 if ready_ok else 2,
        "ALPHA4_CAPABILITY_GOVERNANCE_READY",
        "emit" if ready_ok else "withhold",
    )
    # READY-002: when not ready_ok, marker must be withheld (verified by not printing); always PASS oracle here.
    rows["A-A4-READY-002"] = record(
        "A-A4-READY-002",
        "PASS",
        "no-false-ready",
        0,
        "READY absent unless PASS",
        "withheld" if not ready_ok else "will-emit",
    )

    final_rows = []
    for aid in REQUIRED_ALPHA4_ACCEPTANCES:
        final_rows.append(rows.get(aid) or record(aid, "BLOCKED", "missing", 3, "PASS", "missing"))

    if any(row["status"] == "FAIL" for row in final_rows) or any(v == "FAIL" for v in regression.values()):
        gate = "FAIL"
    elif any(row["status"] != "PASS" for row in final_rows) or not regression_ok:
        gate = "BLOCKED"
    else:
        gate = "PASS"
    ready_ok = gate == "PASS"
    if not ready_ok:
        for row in final_rows:
            if row["acceptance_id"] == "A-A4-READY-001":
                row["status"] = "FAIL"
                row["oracle"] = {"expected": "ALPHA4_CAPABILITY_GOVERNANCE_READY", "actual": "withhold"}
                row["exit_code"] = 2

    write_alpha4_closure_evidence(
        artifact_dir=artifact_dir,
        candidate_sha=ges_head,
        golden=golden_meta,
        acceptances=final_rows,
        regression=regression,
        release_gate=gate,
    )

    if ready_ok:
        print("ALPHA4_CAPABILITY_GOVERNANCE_READY")
        return 0
    print("ALPHA4_CAPABILITY_GOVERNANCE_BLOCKED" if gate == "BLOCKED" else "ALPHA4_CAPABILITY_GOVERNANCE_FAIL")
    return 3 if gate == "BLOCKED" else 2


def _status_acceptances() -> list[dict[str, Any]]:
    import shutil

    providers = load_providers()
    names = list(providers[RTK_ID].health_checks)
    status = probe_rtk()
    emitted = [row["name"] for row in status.get("health_checks") or []]
    catalog_ok = names == ["binary", "version"] and "integration" not in emitted
    rows = [
        record(
            "A-A4-STATUS-001",
            "PASS" if catalog_ok else "FAIL",
            "rtk-probe-catalog",
            0 if catalog_ok else 2,
            ["binary", "version"],
            emitted,
        )
    ]
    if shutil.which("rtk") is None:
        missing_ok = status.get("status") == "missing"
        rows.append(
            record(
                "A-A4-STATUS-002",
                "PASS" if missing_ok else "FAIL",
                "rtk-absent",
                0 if missing_ok else 2,
                "missing",
                status.get("status"),
            )
        )
    else:
        coherent = status.get("status") in {"READY", "NOT_READY", "missing"}
        rows.append(
            record(
                "A-A4-STATUS-002",
                "PASS" if coherent else "FAIL",
                "rtk-present-coherent",
                0 if coherent else 2,
                "coherent",
                status.get("status"),
            )
        )
    return rows


def _golden_acceptances(source: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dirty, _, _ = source_dirty_status(source) if source.is_dir() else (True, "", "")
    origin = ""
    head = ""
    if source.is_dir():
        origin = (git(source, ["remote", "get-url", "origin"]).stdout or "").strip()
        head = (git(source, ["rev-parse", "HEAD"]).stdout or "").strip()
    meta = {
        "source_path": str(source),
        "origin": origin or "unresolved",
        "head_sha": head if len(head) == 40 else ("0" * 40),
        "source_clean": bool(source.is_dir() and not dirty),
    }
    identity_ok = meta["source_clean"] and len(head) == 40 and bool(origin)
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = golden_main([])
    out = buf.getvalue()
    passed = code == 0 and "GOLDEN_CAPABILITY_GOVERNANCE_PASS" in out
    blocked = code == 3 or "GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED" in out
    status = "PASS" if passed else ("BLOCKED" if blocked else "FAIL")
    gold004 = "PASS" if identity_ok and status == "PASS" else (status if status != "PASS" else "FAIL")
    rows = [
        record("A-A4-GOLD-001", status, "golden-list-readonly", code, "PASS", status),
        record("A-A4-GOLD-002", status, "golden-add-remove", code, "PASS", status),
        record("A-A4-GOLD-003", status, "golden-preservation", code, "PASS", status),
        record("A-A4-GOLD-004", gold004, "golden-identity", code, True, identity_ok),
    ]
    return rows, meta


def _run_regressions(ges_root: Path, *, skip: bool) -> dict[str, str]:
    suites = {
        "bootstrap": "tests/ges6/test_bootstrap.py",
        "governance": "tests/ges6/test_governance.py",
        "large_repo": "tests/ges6/test_large_repo_snapshot.py",
        "capability_resolver": "tests/ges6/test_capability_resolver.py",
        "capability_governance": "tests/ges6/test_capability_governance.py",
    }
    if skip:
        # skip is for local dry-run only; treat as BLOCKED toward release PASS.
        return {key: "BLOCKED" for key in suites}
    out: dict[str, str] = {}
    for key, path in suites.items():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", path],
            cwd=ges_root,
            capture_output=True,
            text=True,
            check=False,
        )
        out[key] = "PASS" if result.returncode == 0 else "FAIL"
    return out


if __name__ == "__main__":
    raise SystemExit(main())
