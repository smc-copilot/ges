from __future__ import annotations

import json
from argparse import Namespace

from ges.cli.common import resolve_repo
from ges.governance.artifacts import link_artifact


def run_link(args: Namespace) -> int:
    payload = link_artifact(resolve_repo(args.repo), args.work_id, artifact_type=args.type, path=args.path, replace=args.replace)
    print(json.dumps(payload, indent=2))
    return 0
