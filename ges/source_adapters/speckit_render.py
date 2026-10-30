from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ges.catalog.loader import Capability, SourcePin
from ges.errors import (
    SPEC_KIT_CLI_IDENTITY_MISMATCH,
    SPEC_KIT_OFFICIAL_RENDER_FAILED,
    SPEC_KIT_RENDER_FAILED,
    SPEC_KIT_RUNTIME_INCOMPLETE,
    SPEC_KIT_UNRESOLVED_TOKEN,
    GesError,
)
from ges.io import sha256_bytes
from ges.paths import PACKAGE_ROOT
from ges.source_adapters.base import ProjectedFile
from ges.stagelog import SPECKIT_CLI_VERIFY, SPECKIT_MANIFEST_COMPARE, SPECKIT_OFFICIAL_RENDER, emit

SELECTED_COMMANDS = ("constitution", "specify", "clarify", "plan")
SPEC_KIT_REPO = "https://github.com/github/spec-kit.git"
SPEC_KIT_SHA = "1d5106f59e1b148ee23ab136638932dd790ff1b6"
SPEC_KIT_FROM = f"git+{SPEC_KIT_REPO}@{SPEC_KIT_SHA}"
REQUIRED_CLI_VERSION = "1.0.8.dev0"
INTEGRATION = "cursor-agent"
TOKEN_RE = re.compile(r"\{SCRIPT\}|__SPECKIT_COMMAND_[A-Z_]+__")
USER_OWNED_PREFIXES = ("specs/",)
USER_OWNED_FILES = {".specify/constitution.md"}
SKIP_PREFIXES = (".git/",)
_LAST_RENDER: dict = {}


@dataclass
class RenderReport:
    specify_cli_version: str
    official_files: dict[str, bytes] = field(default_factory=dict)
    projected_files: dict[str, bytes] = field(default_factory=dict)
    official_digest: str = ""
    projected_digest: str = ""
    mismatch_count: int = 0


def skill_rel(command: str) -> str:
    return f".cursor/skills/speckit-{command}/SKILL.md"


def command_rel(command: str) -> str:
    return skill_rel(command)


def script_rel(command: str) -> str:
    return f".specify/scripts/python/{command}.py"


def leftover_tokens(text: str) -> list[str]:
    return sorted(set(TOKEN_RE.findall(text)))


def obsolete_ges_stub_paths(commands: tuple[str, ...] = SELECTED_COMMANDS) -> list[str]:
    paths: list[str] = []
    for command in commands:
        paths.append(f".specify/.ges/runtime/scripts/{command}.py")
        paths.append(f".specify/.ges/commands/{command}.md")
        paths.append(f".specify/.ges/runtime/templates/{command}-template.md")
        paths.append(f".agents/skills/speckit-{command}/SKILL.md")
    return paths


def last_render_report() -> RenderReport:
    return _LAST_RENDER.get("report") or RenderReport(specify_cli_version="")


def manifest_digest(files: dict[str, bytes]) -> str:
    joined = "".join(f"{rel}:{sha256_bytes(content)}\n" for rel, content in sorted(files.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def offline_staging_root() -> Path | None:
    explicit = os.environ.get("GES_SPECKIT_STAGING_FIXTURE")
    if explicit:
        return Path(explicit)
    if os.environ.get("GES_SOURCE_OFFLINE") == "1":
        default = PACKAGE_ROOT.parent / "tests" / "ges6" / "fixtures" / "speckit-official-staging"
        if default.is_dir():
            return default
    return None


def verify_specify_cli() -> str:
    emit(SPECKIT_CLI_VERIFY, "start")
    fixture = offline_staging_root()
    if fixture is not None:
        version = (fixture / "specify-cli-version.txt").read_text(encoding="utf-8").strip()
        if version != REQUIRED_CLI_VERSION:
            raise GesError(
                SPEC_KIT_CLI_IDENTITY_MISMATCH,
                f"specify-cli version {version} != {REQUIRED_CLI_VERSION}",
            )
        emit(SPECKIT_CLI_VERIFY, "complete", version=version, source="fixture")
        return version
    result = subprocess.run(
        ["uvx", "--from", SPEC_KIT_FROM, "specify", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise GesError(
            SPEC_KIT_OFFICIAL_RENDER_FAILED,
            f"pinned specify-cli could not execute: {result.stderr.strip() or result.stdout.strip()}",
        )
    version = _parse_version(result.stdout + result.stderr)
    if version != REQUIRED_CLI_VERSION:
        raise GesError(
            SPEC_KIT_CLI_IDENTITY_MISMATCH,
            f"specify-cli version {version} != {REQUIRED_CLI_VERSION}",
        )
    emit(SPECKIT_CLI_VERIFY, "complete", version=version, source="uvx")
    return version


def official_stage() -> tuple[dict[str, bytes], str]:
    version = verify_specify_cli()
    emit(SPECKIT_OFFICIAL_RENDER, "start", integration=INTEGRATION)
    fixture = offline_staging_root()
    if fixture is not None:
        files = collect_staging_files(fixture)
    else:
        files = _run_official_init()
    validate_selected_skills(files)
    emit(SPECKIT_OFFICIAL_RENDER, "complete", files=len(files), version=version)
    return files, version


def collect_staging_files(stage: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    selected = {f"speckit-{command}" for command in SELECTED_COMMANDS}
    skills = stage / ".cursor" / "skills"
    if skills.is_dir():
        for skill_dir in skills.iterdir():
            if not skill_dir.is_dir() or skill_dir.name not in selected:
                continue
            for path in skill_dir.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(stage).as_posix()
                    _reject_traversal(rel)
                    files[rel] = path.read_bytes()
    specify = stage / ".specify"
    if specify.is_dir():
        for path in specify.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(stage).as_posix()
            if rel in USER_OWNED_FILES or rel.startswith(USER_OWNED_PREFIXES) or rel.startswith(SKIP_PREFIXES):
                continue
            _reject_traversal(rel)
            files[rel] = path.read_bytes()
    return files


def validate_selected_skills(files: dict[str, bytes]) -> None:
    missing = [skill_rel(command) for command in SELECTED_COMMANDS if skill_rel(command) not in files]
    if missing:
        raise GesError(
            SPEC_KIT_RUNTIME_INCOMPLETE,
            f"official staging missing selected skill: {missing[0]}",
            details={"missing": missing},
        )
    leftovers: dict[str, list[str]] = {}
    for rel, content in files.items():
        if not rel.startswith(".cursor/skills/") or not rel.endswith("SKILL.md"):
            continue
        found = leftover_tokens(content.decode("utf-8", errors="replace"))
        if found:
            leftovers[rel] = found
    if leftovers:
        first = next(iter(leftovers))
        raise GesError(
            SPEC_KIT_UNRESOLVED_TOKEN,
            f"unresolved Spec Kit token in {first}: {leftovers[first][0]}",
            details={"tokens": leftovers},
        )


def render_selected(pin: SourcePin, capabilities: list[Capability]) -> list[ProjectedFile]:
    commands = [
        cap.id.split(".", 1)[1]
        for cap in capabilities
        if cap.projection_type == "speckit-capability" and cap.id.split(".", 1)[1] in SELECTED_COMMANDS
    ]
    try:
        official, version = official_stage()
    except GesError:
        raise
    except Exception as exc:
        raise GesError(SPEC_KIT_RENDER_FAILED, f"Spec Kit official render failed: {exc}") from exc
    selected = {
        rel: content
        for rel, content in official.items()
        if _keep_for_commands(rel, commands)
    }
    emit(SPECKIT_MANIFEST_COMPARE, "start")
    mismatches = [
        rel
        for rel, content in selected.items()
        if rel.startswith(".cursor/skills/") and official.get(rel) != content
    ]
    report = RenderReport(
        specify_cli_version=version,
        official_files=official,
        projected_files=selected,
        official_digest=manifest_digest(official),
        projected_digest=manifest_digest(selected),
        mismatch_count=len(mismatches),
    )
    _LAST_RENDER["report"] = report
    emit(SPECKIT_MANIFEST_COMPARE, "complete", mismatch_count=report.mismatch_count)
    return [
        ProjectedFile(
            relpath=rel,
            content=content,
            capability=_capability_for(rel),
            source=pin.id,
            source_sha=pin.commit_sha,
            kind="skill" if rel.startswith(".cursor/skills/") else "specify-runtime",
            ownership_type="FILE",
        )
        for rel, content in selected.items()
    ]


def _keep_for_commands(rel: str, commands: list[str]) -> bool:
    if rel.startswith(".cursor/skills/"):
        return any(rel.startswith(f".cursor/skills/speckit-{command}/") for command in commands)
    return rel.startswith(".specify/scripts/")


def _capability_for(rel: str) -> str | None:
    for command in SELECTED_COMMANDS:
        if rel.startswith(f".cursor/skills/speckit-{command}/"):
            return f"speckit.{command}"
    return None


def _reject_traversal(rel: str) -> None:
    if rel.startswith("/") or rel.startswith("\\") or ".." in Path(rel).parts:
        raise GesError(SPEC_KIT_OFFICIAL_RENDER_FAILED, f"staged path rejected: {rel}")


def _parse_version(text: str) -> str:
    for token in text.replace(",", " ").split():
        if token[0].isdigit() and "dev" in token:
            return token
        if token == REQUIRED_CLI_VERSION:
            return token
    stripped = text.strip().splitlines()[-1].strip() if text.strip() else ""
    return stripped


def _run_official_init() -> dict[str, bytes]:
    stage = Path(tempfile.mkdtemp(prefix="ges-speckit-stage-"))
    try:
        subprocess.run(["git", "init"], cwd=stage, check=True, capture_output=True, text=True)
        result = subprocess.run(
            [
                "uvx",
                "--from",
                SPEC_KIT_FROM,
                "specify",
                "init",
                "--here",
                "--force",
                "--non-interactive",
                "--ignore-agent-tools",
                "--integration",
                INTEGRATION,
                "--script",
                "py",
            ],
            cwd=stage,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise GesError(
                SPEC_KIT_OFFICIAL_RENDER_FAILED,
                f"official specify init failed: {result.stderr.strip() or result.stdout.strip()}",
            )
        return collect_staging_files(stage)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
