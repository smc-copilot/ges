#!/usr/bin/env python3
"""Composer first-install orchestrator for /ges-setup.

Confirms a business-repo target, acquires the locked `ges` CLI, then runs
`ges init --yes`, `ges check`, and `ges doctor`. Projection always goes
through Composer/reconcile — this script never copies files into `.cursor`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from acquire_ges_cli import AcquireError, acquire  # noqa: E402

PRODUCT_REPO = "GES_PRODUCT_REPO"
WHOLE_REPO_IN_CURSOR = "GES_WHOLE_REPO_IN_CURSOR"
TARGET_MISSING = "GES_TARGET_MISSING"
COMPOSER_FAILED = "GES_COMPOSER_FAILED"
CHECK_FAILED = "GES_CHECK_FAILED"
DOCTOR_BLOCKED = "GES_DOCTOR_BLOCKED"
BOOTSTRAP_PENDING = "BOOTSTRAP_PENDING"
READY = "READY"
BLOCKED = "BLOCKED"


class SetupError(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def looks_like_ges_product_repo(root: Path) -> bool:
    root = root.expanduser().resolve()
    engine = root / "ges" / "cli" / "main.py"
    skill = root / "skills" / "ges-setup" / "SKILL.md"
    if engine.is_file() and skill.is_file():
        return True
    pyproject = root / "pyproject.toml"
    if engine.is_file() and pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        if 'name = "ges"' in text and "GES 6" in text:
            return True
    return False


def whole_repo_in_cursor_hits(root: Path) -> list[str]:
    root = root.expanduser().resolve()
    hits: list[Path] = []
    cursor = root / ".cursor"
    dumped = cursor / "ges" / "cli" / "main.py"
    if dumped.is_file():
        hits.append(cursor / "ges")
    if (cursor / "pyproject.toml").is_file() and (cursor / "ges" / "__init__.py").is_file():
        hits.append(cursor)
    if ".cursor" in root.parts and looks_like_ges_product_repo(root):
        hits.append(root)
    return [path.as_posix() for path in hits]


def resolve_target(raw: str | None) -> Path:
    path = Path(raw or ".").expanduser()
    if not path.exists():
        raise SetupError(TARGET_MISSING, f"target repository not found: {raw or '.'}")
    return path.resolve()


def assert_business_target(target: Path, *, allow_product_repo: bool = False) -> None:
    hits = whole_repo_in_cursor_hits(target)
    if hits:
        raise SetupError(
            WHOLE_REPO_IN_CURSOR,
            "this workspace has the GES product repo (including the Python engine) "
            "inside .cursor. Remove it. Install only the skill with "
            "`npx skills@latest add smc-copilot/ges -a cursor --path skills`.",
            paths=hits,
        )
    if looks_like_ges_product_repo(target) and not allow_product_repo:
        raise SetupError(
            PRODUCT_REPO,
            "this workspace is the GES product repo, not a business repo. "
            "Name a business-repo target. Do not treat this checkout as the "
            "Composer Golden target unless the user explicitly asked to.",
            path=str(target),
        )


def run_ges(ges_cli: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([ges_cli, *args], check=False, capture_output=True, text=True)


def parse_doctor(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        payload = None
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return payload
    raise SetupError(DOCTOR_BLOCKED, "ges doctor did not return JSON", stdout=text[-1000:])


def first_install(ges_cli: str, target: Path) -> dict[str, Any]:
    init = run_ges(ges_cli, ["init", str(target), "--yes"])
    init_text = (init.stdout or "") + (init.stderr or "")
    if init.returncode != 0:
        raise SetupError(
            COMPOSER_FAILED,
            "Composer first install failed",
            exit_code=init.returncode,
            output=init_text[-2000:],
        )
    composer = "GES_RECONCILE_NOOP" if "GES_RECONCILE_NOOP" in init_text else "GES_APPLY_OK"
    check = run_ges(ges_cli, ["check", str(target)])
    if check.returncode != 0:
        raise SetupError(
            CHECK_FAILED,
            "ges check failed after Composer apply",
            exit_code=check.returncode,
            output=((check.stdout or "") + (check.stderr or ""))[-2000:],
        )
    doctor = run_ges(ges_cli, ["doctor", str(target)])
    payload = parse_doctor(doctor.stdout or "")
    overall = str(payload.get("overall") or BLOCKED)
    if doctor.returncode != 0 and overall != BOOTSTRAP_PENDING:
        raise SetupError(
            DOCTOR_BLOCKED,
            "ges doctor reported BLOCKED",
            doctor=payload,
            exit_code=doctor.returncode,
        )
    return {
        "composer": composer,
        "check": (check.stdout or "").strip(),
        "doctor": payload,
        "init_output": init.stdout[-2000:] if init.stdout else "",
        "overall": overall,
    }


def render_report(target: Path, acquired: dict[str, Any], result: dict[str, Any]) -> str:
    doctor = result["doctor"]
    overall = result["overall"]
    checks = doctor.get("checks") or {}
    lines = [
        "GES setup",
        "---------",
        f"Target: {target}",
        f"Engine: {acquired['product_version']} (locked)",
        f"Composer: PASS ({result['composer']})",
        f"ges check: {(result['check'] or 'PASS')}",
        f"ges doctor: {overall}",
        "",
        "checks:",
    ]
    for name, status in checks.items():
        lines.append(f"  {name}: {status}")
    lines += ["", f"Overall readiness: {overall}"]
    if overall == BOOTSTRAP_PENDING:
        lines += [
            "",
            "Matt project-level setup is incomplete. This is a recoverable",
            "first-install state, not READY. Do not claim the repo is READY.",
            "",
            "Next:",
            "  1. Run setup-matt-pocock-skills in this business repo",
            "     (Composer already projected it; do not hand-copy skills).",
            "  2. Re-run /ges-setup or ges doctor to re-check.",
        ]
    elif overall == READY:
        lines += ["", "Composer first-install readiness: READY."]
    warnings = doctor.get("warnings") or []
    if warnings:
        lines += ["", "warnings:"]
        lines.extend(f"  - {item}" for item in warnings)
    lines += [
        "",
        "Scope: Composer first-install only. This flow does not run",
        "`ges governance init`, central registry onboarding, or cross-repo features.",
    ]
    return "\n".join(lines) + "\n"


def run_setup(
    *,
    repo: str | None,
    allow_product_repo: bool = False,
    skill_root: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    target = resolve_target(repo)
    assert_business_target(target, allow_product_repo=allow_product_repo)
    acquired = acquire(skill_root=skill_root, home=home)
    installed = first_install(acquired["ges_cli"], target)
    report = render_report(target, acquired, installed)
    return {
        "ok": True,
        "target": str(target),
        "acquired": acquired,
        "result": installed,
        "report": report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GES Composer first-install for /ges-setup.")
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--allow-product-repo",
        action="store_true",
        help="Only when the user explicitly names this GES product repo as the target.",
    )
    parser.add_argument("--skill-root", default=None)
    parser.add_argument("--home", default=None)
    args = parser.parse_args(argv)
    try:
        payload = run_setup(
            repo=args.repo,
            allow_product_repo=args.allow_product_repo,
            skill_root=Path(args.skill_root) if args.skill_root else None,
            home=Path(args.home) if args.home else None,
        )
    except (SetupError, AcquireError) as exc:
        body = {
            "ok": False,
            "code": exc.code,
            "message": exc.message,
            **getattr(exc, "details", {}),
        }
        print(exc.message, file=sys.stderr)
        print("--- ges-setup-result ---")
        print(json.dumps(body, indent=2))
        return 3 if exc.code in {PRODUCT_REPO, WHOLE_REPO_IN_CURSOR, TARGET_MISSING} else 2
    print(payload["report"])
    print("--- ges-setup-result ---")
    print(
        json.dumps(
            {
                "ok": True,
                "target": payload["target"],
                "overall": payload["result"]["overall"],
                "composer": payload["result"]["composer"],
                "acquired": {
                    "ges_cli": payload["acquired"]["ges_cli"],
                    "product_version": payload["acquired"]["product_version"],
                    "ref": payload["acquired"]["ref"],
                    "cache": payload["acquired"]["cache"],
                },
                "doctor": payload["result"]["doctor"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
