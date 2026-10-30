from __future__ import annotations

import json
from argparse import Namespace

from ges.cli.common import resolve_repo
from ges.governance.execution_gate import evaluate_execution, explain_execution
from ges.governance.gates import evaluate_intake, evaluate_merge, exit_code_for, explain_gate


def run_intake(args: Namespace) -> int:
    result = evaluate_intake(resolve_repo(args.repo), args.work_id)
    print(json.dumps(result, indent=2))
    return exit_code_for(result)


def run_merge(args: Namespace) -> int:
    result = evaluate_merge(resolve_repo(args.repo), args.work_id, args.pr)
    print(json.dumps(result, indent=2))
    return exit_code_for(result)


def run_execution(args: Namespace) -> int:
    result = evaluate_execution(resolve_repo(args.repo), args.work_id)
    print(json.dumps(result, indent=2))
    return exit_code_for(result)


def run_explain(args: Namespace) -> int:
    repo = resolve_repo(args.repo)
    if args.gate == "execution":
        result = explain_execution(repo, args.work_id)
    else:
        result = explain_gate(repo, args.work_id, gate=args.gate, pr_number=args.pr)
    print(json.dumps(result, indent=2))
    return exit_code_for(result)
