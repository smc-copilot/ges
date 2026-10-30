from __future__ import annotations

import json
from argparse import Namespace

from ges.cli.common import resolve_repo
from ges.errors import UNSUPPORTED_OPERATION, GesError
from ges.governance.evidence import collect_evidence


def run_collect(args: Namespace) -> int:
    payload = collect_evidence(resolve_repo(args.repo), args.work_id, args.pr)
    print(json.dumps(payload, indent=2))
    return 0


def run_add(_args: Namespace) -> int:
    raise GesError(UNSUPPORTED_OPERATION, "ges evidence add is not supported")
