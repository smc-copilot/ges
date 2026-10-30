from __future__ import annotations

import argparse
import io
import json
import re
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from ges import __distribution_version__, __product_version__
from ges.acceptance.golden_worktree import DEFAULT_GOLDEN_SOURCE, git, source_dirty_status
from ges.acceptance.release_evidence import artifact_inside_candidate, resolve_artifact_dir
from ges.acceptance.run_alpha4_closure import main as alpha4_main
from ges.acceptance.run_golden_work_execution import main as golden_a5_main
from ges.io import write_json
from ges.reconciler.state import validate_payload
from ges.stagelog import EVIDENCE_WRITE, RELEASE_GATE, emit

PRODUCT_INIT = Path(__file__).resolve().parents[1] / "__init__.py"
TARGET_VERSION = "6.0.0-alpha.5"
READY_MARKER = "ALPHA5_WORK_EXECUTION_READY"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GES Alpha.5 Work Execution Release Gate")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--skip-alpha4", action="store_true", help="reuse prior closure only when evidence PASS present")
    parser.add_argument("--alpha4-evidence", default="")
    args = parser.parse_args(argv)

    ges_root = Path(__file__).resolve().parents[2]
    artifact_dir = resolve_artifact_dir(args.artifact_dir or None)
    ges_head = git(ges_root, ["rev-parse", "HEAD"]).stdout.strip()

    if __product_version__ != "6.0.0-alpha.4" and __product_version__ != TARGET_VERSION:
        print("ALPHA5_RELEASE_BLOCKED")
        print(f"unexpected product version: {__product_version__}")
        return 3

    alpha4_gate = _resolve_alpha4(args, artifact_dir)
    buf = io.StringIO()
    with redirect_stdout(buf):
        g_code = golden_a5_main([])
    g_out = buf.getvalue()
    g1_status, g2_status, golden_meta = _parse_golden(g_out, g_code)

    release = "PASS"
    if alpha4_gate != "PASS":
        release = "BLOCKED" if alpha4_gate == "BLOCKED" else "FAIL"
    if g1_status != "PASS" or g2_status != "PASS":
        if g1_status == "FAIL" or "GOLDEN_ALPHA5_EXECUTION_FAIL" in g_out:
            release = "FAIL"
        elif release != "FAIL":
            release = "BLOCKED"

    planned = artifact_dir / "alpha5-work-execution-evidence.json"
    if artifact_inside_candidate(planned, ges_root):
        release = "FAIL"

    payload = {
        "schema": "ges.alpha5-work-execution-evidence.v1",
        "candidate_sha": ges_head,
        "product_version": __product_version__,
        "distribution_version": __distribution_version__,
        "alpha4_closure_gate": alpha4_gate,
        "golden": golden_meta,
        "g1": {"status": g1_status, "verdict": "EXECUTION_READY" if g1_status == "PASS" else "BLOCKED"},
        "g2": {"status": g2_status, "verdict": "EXECUTION_READY" if g2_status == "PASS" else "BLOCKED"},
        "release_gate": {"status": release},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": __product_version__,
    }
    emit(EVIDENCE_WRITE, "start", candidate_sha=ges_head)
    validate_payload("ges.alpha5-work-execution-evidence.v1.json", payload)
    write_json(planned, payload)
    emit(EVIDENCE_WRITE, "complete", path=str(planned))
    emit(RELEASE_GATE, "complete", status=release)

    if release != "PASS":
        print("ALPHA5_RELEASE_BLOCKED" if release == "BLOCKED" else "ALPHA5_RELEASE_FAIL")
        return 3 if release == "BLOCKED" else 2

    if __product_version__ != TARGET_VERSION:
        _bump_product_version(PRODUCT_INIT, TARGET_VERSION)
    print(READY_MARKER)
    return 0


def _resolve_alpha4(args: argparse.Namespace, artifact_dir: Path) -> str:
    if args.alpha4_evidence:
        path = Path(args.alpha4_evidence)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return str((data.get("release_gate") or {}).get("status") or "BLOCKED")
        return "BLOCKED"
    if args.skip_alpha4:
        prior = artifact_dir / "alpha4-capability-closure-evidence.json"
        if prior.is_file():
            data = json.loads(prior.read_text(encoding="utf-8"))
            return str((data.get("release_gate") or {}).get("status") or "BLOCKED")
        return "BLOCKED"
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = alpha4_main(["--artifact-dir", str(artifact_dir)])
    out = buf.getvalue()
    if code == 0 and "ALPHA4_CAPABILITY_GOVERNANCE_READY" in out:
        return "PASS"
    if code == 2 or "FAIL" in out:
        return "FAIL"
    return "BLOCKED"


def _parse_golden(output: str, code: int) -> tuple[str, str, dict]:
    source = Path(__import__("os").environ.get("GES_ALPHA5_GOLDEN_REPO", str(DEFAULT_GOLDEN_SOURCE)))
    dirty, _, _ = source_dirty_status(source) if source.is_dir() else (True, "", "")
    origin = ""
    head = "0" * 40
    if source.is_dir():
        origin = (git(source, ["remote", "get-url", "origin"]).stdout or "").strip() or "unresolved"
        head = (git(source, ["rev-parse", "HEAD"]).stdout or "").strip() or head
    meta = {
        "source_path": str(source),
        "origin": origin or "unresolved",
        "head_sha": head if len(head) == 40 else ("0" * 40),
        "source_clean": bool(source.is_dir() and not dirty),
    }
    g1 = "BLOCKED"
    g2 = "BLOCKED"
    try:
        start = output.find("{")
        end = output.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(output[start : end + 1])
            g1 = str((payload.get("g1") or {}).get("status") or "BLOCKED")
            g2 = str((payload.get("g2") or {}).get("status") or "BLOCKED")
            if payload.get("golden"):
                meta = {
                    "source_path": str(payload["golden"].get("source_path") or meta["source_path"]),
                    "origin": str(payload["golden"].get("origin") or meta["origin"]),
                    "head_sha": str(payload["golden"].get("head_sha") or meta["head_sha"]),
                    "source_clean": bool(payload["golden"].get("source_clean", meta["source_clean"])),
                }
    except json.JSONDecodeError:
        pass
    if code == 0 and "GOLDEN_ALPHA5_EXECUTION_PASS" in output:
        g1, g2 = "PASS", "PASS"
    return g1, g2, meta


def _bump_product_version(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated = re.sub(r'__product_version__ = "[^"]+"', f'__product_version__ = "{version}"', text)
    updated = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', updated)
    updated = re.sub(r'__release__ = "[^"]+"', f'__release__ = "{version}"', updated)
    path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
