from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ges.check import run_check
from ges.cli.common import resolve_repo
from ges.compose import compose, prepare_apply
from ges.errors import GES_RECONCILE_NOOP, GesError
from ges.legacy.v5 import inspect_legacy
from ges.reconciler.apply import apply_plan, snapshot_business_sources
from ges.remove import run_remove


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GES 6 golden consumer acceptance")
    parser.add_argument("--repo", default="E:/git/smc-copilot")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--skip-remove", action="store_true")
    args = parser.parse_args(argv)
    repo = resolve_repo(args.repo)
    if not args.allow_dirty and _git(repo, ["status", "--porcelain"]):
        raise SystemExit("golden consumer worktree is dirty; commit/stash or pass --allow-dirty")
    before_head = _git(repo, ["rev-parse", "HEAD"])
    snapshots = {
        "before": _tree(repo),
        "business_before": snapshot_business_sources(repo),
    }
    legacy = inspect_legacy(repo)
    ctx = compose(repo, persist_profile=False)
    prepare_apply(ctx)
    try:
        apply_plan(repo, ctx.plan, ctx.desired, project=ctx.project, profile=ctx.profile, lock=ctx.lock)
        first = "applied"
    except GesError as exc:
        if exc.code != GES_RECONCILE_NOOP:
            raise
        first = GES_RECONCILE_NOOP
    snapshots["after_init"] = _tree(repo)
    check = run_check(repo)
    ctx2 = compose(repo)
    second = GES_RECONCILE_NOOP if ctx2.plan.noop else "changed"
    snapshots["after_second_apply"] = _tree(repo)
    snapshots["business_after_apply"] = snapshot_business_sources(repo)
    if snapshots["business_after_apply"] != snapshots["business_before"]:
        raise SystemExit("BUSINESS_SOURCE_MODIFICATION_FORBIDDEN")
    if not args.skip_remove:
        run_remove(repo)
        snapshots["after_remove"] = _tree(repo)
        snapshots["business_after_remove"] = snapshot_business_sources(repo)
        if snapshots["business_after_remove"] != snapshots["business_before"]:
            raise SystemExit("BUSINESS_SOURCE_MODIFICATION_FORBIDDEN")
    receipt = {
        "repo": str(repo),
        "head": before_head,
        "legacy_detected": legacy.detected,
        "legacy_counts": legacy.counts,
        "first_apply": first,
        "second_apply": second,
        "check": check,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    out_dir = Path(__file__).resolve().parents[2] / "audit" / "ges6" / "golden-consumer"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    print(f"wrote {out}")
    return 0


def _git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _tree(repo: Path) -> dict[str, str]:
    result = subprocess.run(["git", "ls-files", "-s"], cwd=repo, capture_output=True, text=True, check=False)
    return {"git_ls_files": result.stdout, "status": _git(repo, ["status", "--porcelain"])}


if __name__ == "__main__":
    raise SystemExit(main())
