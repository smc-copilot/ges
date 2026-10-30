from __future__ import annotations

import json
from argparse import Namespace

from ges.cli.common import resolve_repo
from ges.doctor import BLOCKED, run_doctor, run_preflight


def run(args: Namespace) -> int:
    repo = resolve_repo(args.repo)
    if args.preflight:
        payload = run_preflight(repo)
    else:
        payload = run_doctor(repo)
    print(json.dumps(payload, indent=2))
    if payload.get("overall") == BLOCKED:
        return 2
    return 0
