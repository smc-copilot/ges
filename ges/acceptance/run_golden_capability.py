from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ges.acceptance.golden_worktree import (
    DEFAULT_GOLDEN_SOURCE,
    create_detached_worktree,
    remove_worktree,
    resolve_consumer_head,
    source_dirty_status,
)
from ges.analyzer.repo_profile import analyze_repo
from ges.cli.render import render_capability_plan
from ges.errors import GesError
from ges.providers.resolve import build_capability_plan
from ges.providers.rtk import probe_rtk


def main(argv: list[str] | None = None) -> int:
    del argv
    source = Path(os.environ.get("GES_ALPHA3_GOLDEN_REPO", str(DEFAULT_GOLDEN_SOURCE)))
    if not source.is_dir():
        print("GOLDEN_CAPABILITY_BLOCKED")
        return 3
    dirty, _, _ = source_dirty_status(source)
    if dirty:
        print("GOLDEN_CAPABILITY_BLOCKED")
        return 3
    worktree = None
    try:
        head = resolve_consumer_head(source)
        worktree = create_detached_worktree(source, head)
        profile = analyze_repo(worktree)
        plan = build_capability_plan(profile)
        status = probe_rtk()
        print(json.dumps({"plan": plan, "status": status}, indent=2))
        print(render_capability_plan(plan, status))
        print("GOLDEN_CAPABILITY_OBSERVED")
        return 0
    except GesError as exc:
        print("GOLDEN_CAPABILITY_BLOCKED")
        print(f"{exc.code}: {exc.message}")
        return 3
    finally:
        if worktree is not None:
            remove_worktree(source, worktree)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
