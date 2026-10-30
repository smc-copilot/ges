from __future__ import annotations

import json
import sys
from pathlib import Path

from ges.acceptance.golden_worktree import git
from ges.reconciler.business_guard import HASH_STATS, capture_business_snapshot, reset_hash_stats

DEFAULT_LARGE_REPO = Path(r"E:\git\smc-copilot")


def main(argv: list[str] | None = None) -> int:
    source = Path((argv or sys.argv[1:])[0] if (argv or sys.argv[1:]) else DEFAULT_LARGE_REPO)
    if not source.is_dir():
        print("GOLDEN_LARGE_REPO_BLOCKED")
        print(f"missing consumer: {source}")
        return 3
    reset_hash_stats()
    t0 = capture_business_snapshot(source)
    t1 = capture_business_snapshot(source)
    payload = {
        "consumer": str(source),
        "head": git(source, ["rev-parse", "HEAD"]).stdout.strip(),
        "strategy": t0.get("strategy"),
        "t0_ms": t0.get("elapsed_ms"),
        "t1_ms": t1.get("elapsed_ms"),
        "bytes_hashed": t0.get("bytes_hashed"),
        "hash_calls": HASH_STATS["calls"],
        "ignored_hash_calls": sum(1 for path in HASH_STATS["paths"] if "node_modules" in path or "dist" in path),
        "unchanged": t0.get("snapshot_digest") == t1.get("snapshot_digest"),
    }
    print(json.dumps(payload, indent=2))
    if (
        payload["strategy"] == "git-index-overlay"
        and payload["ignored_hash_calls"] == 0
        and payload["unchanged"]
        and (payload["t0_ms"] or 0) + (payload["t1_ms"] or 0) <= 30_000
    ):
        print("LARGE_REPO_GUARD_V2_READY")
        return 0
    print("GOLDEN_LARGE_REPO_BLOCKED")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
