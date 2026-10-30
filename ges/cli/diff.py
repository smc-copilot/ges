from __future__ import annotations

import json
from argparse import Namespace

from ges.cli.common import flatten_ids, resolve_repo
from ges.cli.render import render_plan
from ges.compose import compose


def run(args: Namespace) -> int:
    ctx = compose(
        resolve_repo(args.repo),
        exclude=flatten_ids(args.exclude),
        extra=flatten_ids(getattr(args, "enable", None)),
        persist_profile=False,
    )
    payload = ctx.plan.to_dict()
    print(render_plan(payload))
    if args.json:
        print(json.dumps(payload, indent=2))
    return 0
