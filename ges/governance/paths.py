from __future__ import annotations

from pathlib import Path

GOVERNANCE_DIRNAME = "governance"
POLICY_FILE = "policy.yaml"
WORKS_DIRNAME = "works"
GOVERNANCE_REL = f".ges/{GOVERNANCE_DIRNAME}"
POLICY_REL = f"{GOVERNANCE_REL}/{POLICY_FILE}"
WORKS_REL = f"{GOVERNANCE_REL}/{WORKS_DIRNAME}"


def governance_dir(repo: Path) -> Path:
    return repo / ".ges" / GOVERNANCE_DIRNAME


def policy_path(repo: Path) -> Path:
    return governance_dir(repo) / POLICY_FILE


def works_dir(repo: Path) -> Path:
    return governance_dir(repo) / WORKS_DIRNAME


def work_path(repo: Path, work_id: str) -> Path:
    return works_dir(repo) / f"{work_id}.yaml"


def is_governance_rel(rel: str) -> bool:
    posix = rel.replace("\\", "/")
    return posix == GOVERNANCE_REL or posix.startswith(GOVERNANCE_REL + "/")
