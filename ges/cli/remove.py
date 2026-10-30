from __future__ import annotations

from argparse import Namespace

from ges.cli.common import resolve_repo
from ges.remove import run_remove


def run(args: Namespace) -> int:
    removed = run_remove(resolve_repo(args.repo))
    print(f"removed {len(removed)} GES-owned paths")
    for item in removed[:50]:
        print(f"  {item}")
    return 0
