from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ges import __distribution_version__, __product_version__
from ges.cli.common import resolve_repo
from ges.doctor import run_doctor, run_preflight
from ges.errors import GesError
from ges.reconciler.apply import consumer_tree, snapshot_business_sources


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="GES 6 Golden Bootstrap")
    parser.add_argument("--repo", default="E:/git/smc-copilot")
    args = parser.parse_args(argv)
    repo = resolve_repo(args.repo)
    started = datetime.now(timezone.utc)
    dirty = _git(repo, ["status", "--porcelain"])
    acceptances = []
    if dirty:
        for acceptance_id in (
            "A-BOOT-001",
            "A-CHECK-001",
            "A-CHECK-009",
            "A-DOCTOR-002",
            "A-DOCTOR-003",
            "A-CURSOR-001",
            "A-IDEMP-001",
        ):
            acceptances.append(
                _record(
                    acceptance_id,
                    "BLOCKED",
                    "git status --porcelain",
                    2,
                    "clean worktree on work/prd-v5.1",
                    dirty[:500],
                )
            )
        _write_evidence(repo, started, acceptances, dirty=True)
        print("Golden Bootstrap BLOCKED: dirty consumer worktree. SKIPPED/BLOCKED is not PASS.")
        print("BOOTSTRAP_ALPHA_READY is not claimed.")
        return 2
    try:
        before = consumer_tree(repo)
        business = snapshot_business_sources(repo)
        run_preflight(repo)
        acceptances.append(_record("A-BOOT-001", "PASS", "ges doctor --preflight", 0, "0 mutation", "0 mutation"))
        from ges.compose import compose, prepare_apply
        from ges.reconciler.apply import apply_plan
        from ges.check import run_check
        from ges.errors import GES_RECONCILE_NOOP

        ctx = compose(repo, persist_profile=False)
        if consumer_tree(repo) != before:
            raise SystemExit("preview mutated consumer")
        prepare_apply(ctx)
        apply_plan(repo, ctx.plan, ctx.desired, project=ctx.project, profile=ctx.profile, lock=ctx.lock)
        run_check(repo)
        readiness = run_doctor(repo)
        acceptances.append(_record("A-CHECK-001", "PASS", "ges check", 0, "PASS", "PASS"))
        if readiness.get("overall") == "BOOTSTRAP_PENDING":
            acceptances.append(_record("A-DOCTOR-002", "PASS", "ges doctor", 0, "BOOTSTRAP_PENDING", "BOOTSTRAP_PENDING"))
            acceptances.append(_record("A-DOCTOR-003", "BLOCKED", "ges doctor", 0, "READY", readiness.get("overall")))
        elif readiness.get("overall") == "READY":
            acceptances.append(_record("A-DOCTOR-003", "PASS", "ges doctor", 0, "READY", "READY"))
        skills = {path.name for path in (repo / ".agents" / "skills").iterdir() if path.is_dir()}
        discovered = "grill-with-docs" in skills and "speckit-specify" in skills and "writing-plans" in skills
        acceptances.append(
            _record("A-CURSOR-001", "PASS" if discovered else "FAIL", "skill frontmatter", 0 if discovered else 2, "discoverable", str(discovered))
        )
        ctx2 = compose(repo, persist_profile=False)
        second = "GES_RECONCILE_NOOP" if ctx2.plan.noop else "changed"
        acceptances.append(
            _record("A-IDEMP-001", "PASS" if ctx2.plan.noop else "FAIL", "ges init", 0 if ctx2.plan.noop else 1, GES_RECONCILE_NOOP, second)
        )
        if snapshot_business_sources(repo) != business:
            acceptances.append(_record("A-CHECK-009", "FAIL", "business snapshot", 2, "unchanged", "changed"))
        else:
            acceptances.append(_record("A-CHECK-009", "PASS", "business snapshot", 0, "unchanged", "unchanged"))
    except GesError as exc:
        acceptances.append(_record("A-BOOT-001", "FAIL", "golden bootstrap", 2, "PASS", exc.code))
        _write_evidence(repo, started, acceptances, dirty=False)
        return 2
    _write_evidence(repo, started, acceptances, dirty=False)
    statuses = {item["status"] for item in acceptances}
    if "FAIL" in statuses or "BLOCKED" in statuses:
        print("Golden Bootstrap is not Release Ready. SKIPPED/BLOCKED is not PASS.")
        print("BOOTSTRAP_ALPHA_READY is not claimed.")
        return 2
    print("Golden Bootstrap chain PASS.")
    print("BOOTSTRAP_ALPHA_READY")
    return 0


def _record(acceptance_id: str, status: str, command: str, exit_code: int, expected: str, actual: str) -> dict:
    return {
        "acceptance_id": acceptance_id,
        "requirement_ids": [],
        "test_ids": [f"TEST-{acceptance_id}"],
        "status": status,
        "command": command,
        "exit_code": exit_code,
        "oracle": {"expected": expected, "actual": actual},
        "evidence_files": [],
    }


def _write_evidence(repo: Path, started: datetime, acceptances: list[dict], *, dirty: bool) -> Path:
    finished = datetime.now(timezone.utc)
    payload = {
        "schema": "ges.bootstrap-evidence.v1",
        "ges_version": __product_version__,
        "distribution_version": __distribution_version__,
        "ges_commit": _git(Path(__file__).resolve().parents[2], ["rev-parse", "HEAD"]),
        "consumer_repo": "loudon84/smc-copilot",
        "consumer_commit": _git(repo, ["rev-parse", "HEAD"]),
        "branch": "work/prd-v5.1",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "acceptances": acceptances,
    }
    out_dir = Path(__file__).resolve().parents[2] / "audit" / "ges6" / "bootstrap"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{finished.strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"wrote {out}")
    return out


def _git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
