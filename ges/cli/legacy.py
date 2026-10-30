from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from ges.cli.common import resolve_repo
from ges.errors import LEGACY_OWNERSHIP_UNKNOWN, GesError
from ges.legacy.v5 import inspect_legacy, removable_paths
from ges.reconciler.guard import contain


def run_inspect(args: Namespace) -> int:
    report = inspect_legacy(resolve_repo(args.repo))
    print(json.dumps(report.to_dict(), indent=2))
    return 0


def run_remove(args: Namespace) -> int:
    repo = resolve_repo(args.repo)
    report = inspect_legacy(repo)
    removable = removable_paths(report)
    unknown = [entry.path for entry in report.entries if entry.status == "LEGACY_OWNERSHIP_UNKNOWN"]
    payload = {
        "dry_run": not args.apply,
        "removable": removable,
        "preserve": unknown,
        "absent": [entry.path for entry in report.entries if entry.status == "OWNED_ABSENT"],
    }
    print(json.dumps(payload, indent=2))
    if not args.apply:
        return 0
    if unknown and not args.force:
        raise GesError(LEGACY_OWNERSHIP_UNKNOWN, "refusing to delete files with unknown ownership")
    for rel in removable:
        target = contain(repo, rel)
        if target.is_file():
            target.unlink()
    return 0
