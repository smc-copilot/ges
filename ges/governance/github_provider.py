from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ges.errors import GITHUB_AUTH_UNAVAILABLE, GITHUB_PROVIDER_INVALID, GITHUB_PROVIDER_UNAVAILABLE, GesError
from ges.stagelog import GITHUB_OBSERVE, emit

PR_FIELDS = "number,state,isDraft,url,author,headRefOid,baseRefName,body,reviewDecision,statusCheckRollup"


def _run_gh(args: list[str], *, cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("gh") or "gh"
    return subprocess.run(
        [executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
        env=os.environ.copy(),
    )


def gh_version() -> str:
    try:
        result = _run_gh(["--version"])
    except OSError as exc:
        raise GesError(GITHUB_PROVIDER_UNAVAILABLE, "gh CLI is not available", exit_code=3) from exc
    if result.returncode != 0:
        raise GesError(GITHUB_PROVIDER_UNAVAILABLE, (result.stderr or result.stdout).strip(), exit_code=3)
    return (result.stdout or result.stderr).splitlines()[0].strip()


def gh_auth_status() -> dict[str, str]:
    try:
        result = _run_gh(["auth", "status"])
    except OSError as exc:
        raise GesError(GITHUB_AUTH_UNAVAILABLE, "gh CLI is not available", exit_code=3) from exc
    text = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0 or "not logged in" in text.lower():
        raise GesError(GITHUB_AUTH_UNAVAILABLE, "gh auth status failed", exit_code=3)
    host = "github.com"
    for line in text.splitlines():
        if "Logged in to" in line:
            parts = line.split()
            if parts:
                host = parts[-1].strip()
    return {"host": host, "raw": "redacted"}


def view_pr(repo: Path, number: int) -> dict[str, Any]:
    emit(GITHUB_OBSERVE, "start", pr=number)
    try:
        result = _run_gh(["pr", "view", str(number), "--json", PR_FIELDS], cwd=repo)
    except subprocess.TimeoutExpired as exc:
        raise GesError(GITHUB_PROVIDER_UNAVAILABLE, "gh pr view timed out", exit_code=3) from exc
    except OSError as exc:
        raise GesError(GITHUB_PROVIDER_UNAVAILABLE, str(exc), exit_code=3) from exc
    if result.returncode != 0:
        raise GesError(GITHUB_PROVIDER_UNAVAILABLE, (result.stderr or result.stdout).strip() or "gh pr view failed", exit_code=3)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GesError(GITHUB_PROVIDER_INVALID, "gh pr view returned malformed JSON", exit_code=3) from exc
    if not isinstance(payload, dict) or "headRefOid" not in payload:
        raise GesError(GITHUB_PROVIDER_INVALID, "gh pr view JSON missing required fields", exit_code=3)
    emit(GITHUB_OBSERVE, "complete", pr=number, head=payload.get("headRefOid"))
    return payload
