from __future__ import annotations

from argparse import Namespace

from ges.check import run_check
from ges.cli.common import resolve_repo


def run(args: Namespace) -> int:
    print(run_check(resolve_repo(args.repo)))
    return 0
