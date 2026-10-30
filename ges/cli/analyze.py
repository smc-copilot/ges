from __future__ import annotations

import json
from argparse import Namespace

from ges.analyzer.repo_profile import analyze_repo
from ges.cli.common import resolve_repo


def run(args: Namespace) -> int:
    repo = resolve_repo(args.repo)
    profile = analyze_repo(repo)
    print(json.dumps(profile, indent=2))
    return 0
