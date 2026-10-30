from __future__ import annotations

from argparse import Namespace

from ges.cli.common import flatten_ids, resolve_repo
from ges.cli.render import render_plan
from ges.compose import compose, prepare_apply
from ges.errors import GES_RECONCILE_NOOP, GesError
from ges.reconciler.apply import apply_plan


def run(args: Namespace) -> int:
    repo = resolve_repo(args.repo)
    ctx = compose(
        repo,
        exclude=flatten_ids(args.exclude),
        extra=flatten_ids(getattr(args, "enable", None)),
        persist_profile=False,
    )
    print(render_plan(ctx.plan.to_dict()))
    try:
        prepare_apply(ctx)
        apply_plan(repo, ctx.plan, ctx.desired, project=ctx.project, profile=ctx.profile, lock=ctx.lock)
    except GesError as exc:
        if exc.code == GES_RECONCILE_NOOP:
            print(GES_RECONCILE_NOOP)
            return 0
        raise
    print("GES_APPLY_OK")
    return 0
