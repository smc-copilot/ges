from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ges.errors import DESIRED_STATE_INVALID, GES_CHECK_FAILED, REPO_PROFILE_INVALID, GesError
from ges.io import read_json, read_yaml, write_json_atomic, write_yaml
from ges.paths import (
    LOCK_FILE,
    PROJECT_FILE,
    RECEIPT_FILE,
    REPO_PROFILE_FILE,
    SCHEMA_DIR,
    repo_ges_dir,
)

SCHEMA_MAP = {
    PROJECT_FILE: "ges.project.v2.json",
    REPO_PROFILE_FILE: "ges.repo-profile.v2.json",
    LOCK_FILE: "ges.lock.v1.json",
    RECEIPT_FILE: "ges.install-receipt.v2.json",
}


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validate_payload(schema_name: str, payload: dict[str, Any], *, code: str = REPO_PROFILE_INVALID) -> None:
    validator = Draft202012Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        raise GesError(code, errors[0].message, details={"schema": schema_name})


def write_project(repo: Path, payload: dict[str, Any]) -> Path:
    validate_payload("ges.project.v2.json", payload, code=DESIRED_STATE_INVALID)
    path = repo_ges_dir(repo) / PROJECT_FILE
    write_yaml(path, payload)
    return path


def write_profile(repo: Path, payload: dict[str, Any]) -> Path:
    validate_payload("ges.repo-profile.v2.json", payload)
    path = repo_ges_dir(repo) / REPO_PROFILE_FILE
    write_json(path, payload)
    return path


def write_lock(repo: Path, payload: dict[str, Any]) -> Path:
    validate_payload("ges.lock.v1.json", payload, code=GES_CHECK_FAILED)
    path = repo_ges_dir(repo) / LOCK_FILE
    write_json_atomic(path, payload)
    return path


def write_receipt(repo: Path, payload: dict[str, Any]) -> Path:
    validate_payload("ges.install-receipt.v2.json", payload, code=GES_CHECK_FAILED)
    path = repo_ges_dir(repo) / RECEIPT_FILE
    write_json_atomic(path, payload)
    return path


def read_project(repo: Path) -> dict[str, Any] | None:
    path = repo_ges_dir(repo) / PROJECT_FILE
    return read_yaml(path) if path.is_file() else None


def read_profile(repo: Path) -> dict[str, Any] | None:
    path = repo_ges_dir(repo) / REPO_PROFILE_FILE
    return read_json(path) if path.is_file() else None


def read_lock(repo: Path) -> dict[str, Any] | None:
    path = repo_ges_dir(repo) / LOCK_FILE
    return read_json(path) if path.is_file() else None


def read_receipt(repo: Path) -> dict[str, Any] | None:
    path = repo_ges_dir(repo) / RECEIPT_FILE
    return read_json(path) if path.is_file() else None
