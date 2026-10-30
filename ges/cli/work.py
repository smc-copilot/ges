from __future__ import annotations

import json
from argparse import Namespace

from ges.cli.common import resolve_repo
from ges.governance.registry import (
    add_work_capability,
    close_work,
    create_work,
    migrate_work,
    remove_work_capability,
    show_work,
    update_work,
)


def run_create(args: Namespace) -> int:
    payload = create_work(
        resolve_repo(args.repo),
        work_id=args.id,
        title=args.title,
        owner=args.owner,
        risk=args.risk,
        host=args.host,
    )
    print(json.dumps(payload, indent=2))
    return 0


def run_show(args: Namespace) -> int:
    print(json.dumps(show_work(resolve_repo(args.repo), args.id), indent=2))
    return 0


def run_update(args: Namespace) -> int:
    payload = update_work(
        resolve_repo(args.repo),
        args.id,
        title=args.title,
        owner=args.owner,
        risk=args.risk,
        policy=args.policy,
    )
    print(json.dumps(payload, indent=2))
    return 0


def run_close(args: Namespace) -> int:
    print(json.dumps(close_work(resolve_repo(args.repo), args.id), indent=2))
    return 0


def run_migrate(args: Namespace) -> int:
    payload = migrate_work(resolve_repo(args.repo), args.id, host=args.host)
    print(json.dumps(payload, indent=2))
    return 0


def run_capability_add(args: Namespace) -> int:
    payload = add_work_capability(resolve_repo(args.repo), args.id, args.capability_id)
    print(json.dumps(payload, indent=2))
    return 0


def run_capability_remove(args: Namespace) -> int:
    payload = remove_work_capability(resolve_repo(args.repo), args.id, args.capability_id)
    print(json.dumps(payload, indent=2))
    return 0
