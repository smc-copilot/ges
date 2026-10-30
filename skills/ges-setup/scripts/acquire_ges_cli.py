#!/usr/bin/env python3
"""Acquire the locked GES Composer CLI without a user-facing pip ritual.

Installs this repo's pinned `ges` engine into a user-local prefix
(`$XDG_DATA_HOME/ges/engines/<ref>` or `%LOCALAPPDATA%\\ges\\engines\\<ref>`),
preferring a venv and falling back to `pip --target` when ensurepip is missing.
Never writes the Python package into a business repo or into `.cursor`.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
LOCK_NAME = "engine.lock.json"
SHA_LEN = 40
MIN_PYTHON = (3, 11)


class AcquireError(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def skill_root_from(start: Path | None = None) -> Path:
    if start is not None:
        return start.resolve()
    return SKILL_ROOT


def load_pin(root: Path | None = None) -> dict[str, Any]:
    lock_path = skill_root_from(root) / LOCK_NAME
    if not lock_path.is_file():
        raise AcquireError("GES_ENGINE_PIN_MISSING", f"engine pin not found: {lock_path}")
    try:
        pin = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AcquireError("GES_ENGINE_PIN_INVALID", f"engine pin is not JSON: {exc}") from exc
    if pin.get("schema") != "ges.engine-pin.v1":
        raise AcquireError("GES_ENGINE_PIN_INVALID", "engine pin schema must be ges.engine-pin.v1")
    ref = str(pin.get("ref") or "")
    if pin.get("ref_kind") == "commit" and len(ref) != SHA_LEN:
        raise AcquireError("GES_ENGINE_PIN_INVALID", "engine pin commit ref must be a 40-char SHA")
    if not pin.get("requirement"):
        raise AcquireError("GES_ENGINE_PIN_INVALID", "engine pin is missing requirement")
    if not pin.get("product_version"):
        raise AcquireError("GES_ENGINE_PIN_INVALID", "engine pin is missing product_version")
    return pin


def engine_home() -> Path:
    override = os.environ.get("GES_ENGINE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return (base / "ges" / "engines").resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / "ges" / "engines").resolve()


def engine_source_override() -> Path | None:
    raw = os.environ.get("GES_ENGINE_SOURCE")
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise AcquireError("GES_ENGINE_SOURCE_MISSING", f"GES_ENGINE_SOURCE is not a directory: {path}")
    return path


def pin_home(pin: dict[str, Any], home: Path | None = None) -> Path:
    return (home or engine_home()) / str(pin["ref"])


def venv_dir(pin: dict[str, Any], home: Path | None = None) -> Path:
    return pin_home(pin, home) / "venv"


def target_dir(pin: dict[str, Any], home: Path | None = None) -> Path:
    return pin_home(pin, home) / "py"


def launcher_path(pin: dict[str, Any], home: Path | None = None) -> Path:
    name = "ges.cmd" if os.name == "nt" else "ges"
    return pin_home(pin, home) / "bin" / name


def ges_executable(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "ges.exe"
    return venv_path / "bin" / "ges"


def venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def resolve_cli(pin: dict[str, Any], home: Path | None = None) -> Path | None:
    candidates = (ges_executable(venv_dir(pin, home)), launcher_path(pin, home))
    for path in candidates:
        if path.is_file():
            return path
    return None


def require_python_311(executable: str | None = None) -> str:
    exe = executable or sys.executable
    version = sys.version_info if exe == sys.executable else _python_version(exe)
    if version >= MIN_PYTHON:
        return exe
    raise AcquireError(
        "GES_PYTHON_TOO_OLD",
        f"GES setup needs Python 3.11+ (found {version.major}.{version.minor} at {exe})",
    )


def _python_version(executable: str) -> tuple[int, int]:
    result = subprocess.run(
        [executable, "-c", "import sys; print(f'{sys.version_info[0]} {sys.version_info[1]}')"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AcquireError("GES_PYTHON_TOO_OLD", f"could not read Python version from {executable}")
    major, minor = result.stdout.split()
    return int(major), int(minor)


def cli_version(ges_cli: Path) -> str:
    result = subprocess.run([str(ges_cli), "--version"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise AcquireError("GES_ENGINE_VERSION_FAILED", result.stderr.strip() or "ges --version failed")
    return (result.stdout or result.stderr).strip()


def version_matches(ges_cli: Path, pin: dict[str, Any]) -> bool:
    if not ges_cli.is_file():
        return False
    try:
        reported = cli_version(ges_cli)
    except AcquireError:
        return False
    return str(pin["product_version"]) in reported


def acquire(
    *,
    skill_root: Path | None = None,
    home: Path | None = None,
    source: Path | None = None,
    python: str | None = None,
) -> dict[str, Any]:
    pin = load_pin(skill_root)
    source = source if source is not None else engine_source_override()
    existing = resolve_cli(pin, home)
    if existing and version_matches(existing, pin):
        return _payload(pin, existing, existing.parent, cache="hit", source=source)
    python_exe = require_python_311(python)
    requirement = str(source) if source is not None else str(pin["requirement"])
    venv_error = _install_into_venv(pin, home, requirement, source is not None, python_exe)
    exe = resolve_cli(pin, home)
    if exe and version_matches(exe, pin):
        return _payload(pin, exe, exe.parent, cache="miss", source=source, python=python_exe)
    target_error = _install_into_target(pin, home, requirement, source is not None, python_exe)
    exe = resolve_cli(pin, home)
    if exe and version_matches(exe, pin):
        return _payload(pin, exe, exe.parent, cache="miss", source=source, python=python_exe)
    reported = cli_version(exe) if exe and exe.is_file() else ""
    raise AcquireError(
        "GES_ENGINE_INSTALL_FAILED",
        "could not acquire the locked ges CLI",
        stderr="\n".join(item for item in (venv_error, target_error, reported) if item)[-2000:],
        requirement=requirement,
    )


def venv_available(python_exe: str) -> bool:
    probe = subprocess.run(
        [python_exe, "-c", "import ensurepip, venv"],
        check=False,
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def _install_into_venv(
    pin: dict[str, Any],
    home: Path | None,
    requirement: str,
    editable: bool,
    python_exe: str,
) -> str:
    if not venv_available(python_exe):
        return "venv unavailable (ensurepip missing); using target install"
    dest = venv_dir(pin, home)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    created = subprocess.run(
        [python_exe, "-m", "venv", str(dest)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        if dest.exists():
            shutil.rmtree(dest)
        return created.stderr.strip() or created.stdout.strip() or "venv create failed"
    return _pip_install([str(venv_python(dest)), "-m", "pip"], requirement, editable, target=None)


def _install_into_target(
    pin: dict[str, Any],
    home: Path | None,
    requirement: str,
    editable: bool,
    python_exe: str,
) -> str:
    dest = target_dir(pin, home)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    error = _pip_install(
        [python_exe, "-m", "pip"],
        requirement,
        editable,
        target=dest,
    )
    if error:
        return error
    write_launcher(launcher_path(pin, home), python_exe, dest)
    return ""


def _pip_install(pip_prefix: list[str], requirement: str, editable: bool, target: Path | None) -> str:
    argv = [*pip_prefix, "install", "--disable-pip-version-check", "--no-input"]
    if target is not None:
        argv.extend(["--target", str(target)])
    if editable:
        argv.extend(["-e", requirement])
    else:
        argv.append(requirement)
    result = subprocess.run(argv, check=False, capture_output=True, text=True)
    if result.returncode == 0:
        return ""
    return (result.stderr or result.stdout)[-2000:]


def write_launcher(path: Path, python: str, site: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path.write_text(
            f'@echo off\r\nset PYTHONPATH={site};%PYTHONPATH%\r\n"{python}" -m ges %*\r\n',
            encoding="utf-8",
        )
        return path
    path.write_text(
        "#!/bin/sh\n"
        f"export PYTHONPATH={shlex.quote(str(site))}${{PYTHONPATH:+:$PYTHONPATH}}\n"
        f"exec {shlex.quote(python)} -m ges \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _payload(
    pin: dict[str, Any],
    exe: Path,
    dest: Path,
    *,
    cache: str,
    source: Path | None,
    python: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "ges_cli": str(exe),
        "venv": str(dest),
        "product_version": pin["product_version"],
        "ref": pin["ref"],
        "cache": cache,
        "source": str(source) if source else pin["requirement"],
        "python": python or sys.executable,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire the locked ges CLI (user-unaware).")
    parser.add_argument("--skill-root", default=None)
    parser.add_argument("--home", default=None)
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args(argv)
    try:
        payload = acquire(
            skill_root=Path(args.skill_root) if args.skill_root else None,
            home=Path(args.home) if args.home else None,
        )
    except AcquireError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message, **exc.details}, indent=2))
        return 2
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
