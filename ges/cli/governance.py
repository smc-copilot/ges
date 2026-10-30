from __future__ import annotations

from argparse import Namespace

from ges.cli.common import resolve_repo
from ges.governance.storage import init_governance


def run_init(args: Namespace) -> int:
    init_governance(resolve_repo(args.repo))
    print("initialized .ges/governance/")
    return 0
