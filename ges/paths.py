from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SCHEMA_DIR = PACKAGE_ROOT / "schemas"
CATALOG_DIR = PACKAGE_ROOT / "catalog"
LEGACY_DIR = PACKAGE_ROOT / "legacy"

GES_DIRNAME = ".ges"
CAPABILITIES_DIRNAME = "capabilities"
INSTALLED_FILE = "installed.yaml"
CAPABILITY_POLICY_FILE = "policy.yaml"
PROJECT_FILE = "project.yaml"
REPO_PROFILE_FILE = "repo-profile.json"
LOCK_FILE = "lock.json"
RECEIPT_FILE = "install-receipt.json"

AGENTS_BEGIN = "<!-- ges:v6:engineering-stack:begin -->"
AGENTS_END = "<!-- ges:v6:engineering-stack:end -->"

BUSINESS_SOURCE_ROOTS = ("apps", "services", "src", "packages", "contracts")
BUSINESS_SOURCE_SKIP_PREFIXES = (
    "apps/knowledge",
    ".ges",
    ".agents/skills",
    ".specify",
    ".cursor",
    ".codex",
    "docs/agents",
    "AGENTS.md",
    "CLAUDE.md",
    ".gitignore",
)

WRITE_ALLOW_PREFIXES = (
    ".ges/",
    ".agents/skills/",
    ".specify/",
    ".cursor/",
    ".codex/",
)

WRITE_ALLOW_FILES = ("AGENTS.md", ".gitignore")

PRESERVE_ALWAYS = (".agents/governance",)


def repo_ges_dir(repo: Path) -> Path:
    return repo / GES_DIRNAME


def repo_capabilities_dir(repo: Path) -> Path:
    return repo_ges_dir(repo) / CAPABILITIES_DIRNAME


def installed_path(repo: Path) -> Path:
    return repo_capabilities_dir(repo) / INSTALLED_FILE


def capability_policy_path(repo: Path) -> Path:
    return repo_capabilities_dir(repo) / CAPABILITY_POLICY_FILE


def to_posix(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("/")
