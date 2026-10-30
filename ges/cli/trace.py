from __future__ import annotations

import json
from argparse import Namespace

from ges.cli.common import resolve_repo
from ges.governance.trace import build_trace


def run_show(args: Namespace) -> int:
    print(json.dumps(build_trace(resolve_repo(args.repo), args.work_id, args.pr), indent=2))
    return 0
