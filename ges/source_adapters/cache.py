from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

from ges.catalog.loader import SourcePin
from ges.errors import SOURCE_CACHE_INTEGRITY_FAILED, UPSTREAM_SHA_NOT_PINNED, UPSTREAM_SOURCE_UNRESOLVED, GesError
from ges.io import read_json, write_json
from ges.stagelog import FETCH, emit

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MANIFEST_NAME = ".ges-source-manifest.json"
SKIP_NAMES = {MANIFEST_NAME, ".ges-source-ok"}


def cache_root() -> Path:
    override = os.environ.get("GES_SOURCE_CACHE")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "ges" / "sources"


def offline_mode() -> bool:
    return os.environ.get("GES_SOURCE_OFFLINE") == "1"


def ensure_source(pin: SourcePin) -> Path:
    if not SHA_RE.match(pin.commit_sha):
        raise GesError(UPSTREAM_SHA_NOT_PINNED, f"{pin.id} is not pinned to a 40-char SHA")
    dest = cache_root() / pin.cache_key / pin.commit_sha
    if _has_content(dest):
        try:
            verify_manifest(dest, pin)
            emit(FETCH, "cache-hit", source=pin.id, sha=pin.commit_sha)
            return dest
        except GesError as exc:
            if exc.code != SOURCE_CACHE_INTEGRITY_FAILED:
                raise
            if offline_mode():
                raise
            emit(FETCH, "cache-invalid", source=pin.id, sha=pin.commit_sha)
            shutil.rmtree(dest)
    if offline_mode():
        raise GesError(
            UPSTREAM_SOURCE_UNRESOLVED,
            f"source {pin.id}@{pin.commit_sha} is not in the local cache",
            details={"path": str(dest)},
        )
    emit(FETCH, "fetch", source=pin.id, sha=pin.commit_sha, repo=pin.repo)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        _git_fetch(dest, pin.repo, pin.commit_sha)
    except Exception as exc:
        raise GesError(
            UPSTREAM_SOURCE_UNRESOLVED,
            f"failed to fetch {pin.id}@{pin.commit_sha}: {exc}",
        ) from exc
    if not _has_content(dest):
        raise GesError(UPSTREAM_SOURCE_UNRESOLVED, f"fetched tree for {pin.id} is empty")
    head = _git_head(dest)
    if head != pin.commit_sha:
        raise GesError(
            SOURCE_CACHE_INTEGRITY_FAILED,
            f"fetched HEAD {head} does not match pinned {pin.commit_sha}",
        )
    write_manifest(dest, pin)
    return dest


def resolve_path(pin: SourcePin, source_path: str) -> Path:
    root = ensure_source(pin)
    rel = Path(source_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise GesError(UPSTREAM_SOURCE_UNRESOLVED, f"illegal source path {source_path}")
    target = (root / rel).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise GesError(UPSTREAM_SOURCE_UNRESOLVED, f"path escapes source root: {source_path}")
    if target.is_symlink() or (root / rel).is_symlink():
        raise GesError(SOURCE_CACHE_INTEGRITY_FAILED, f"symlink rejected: {source_path}")
    if not target.exists():
        raise GesError(
            UPSTREAM_SOURCE_UNRESOLVED,
            f"{pin.id} path {source_path} is missing at {pin.commit_sha}",
        )
    return target


def list_selected_paths(root: Path) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.name in SKIP_NAMES:
            continue
        if path.is_symlink():
            raise GesError(
                SOURCE_CACHE_INTEGRITY_FAILED,
                f"symlink rejected: {path.relative_to(root).as_posix()}",
            )
        if path.is_file():
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def content_digest(root: Path, selected_paths: list[str] | None = None) -> str:
    paths = selected_paths if selected_paths is not None else list_selected_paths(root)
    digest = hashlib.sha256()
    for rel in paths:
        path = root / rel
        if path.is_symlink():
            raise GesError(SOURCE_CACHE_INTEGRITY_FAILED, f"symlink rejected: {rel}")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def write_manifest(root: Path, pin: SourcePin) -> dict:
    selected = list_selected_paths(root)
    payload = {
        "schema": "ges.source-cache-manifest.v1",
        "source_id": pin.id,
        "repo": pin.repo,
        "commit": pin.commit_sha,
        "selected_paths": selected,
        "content_digest": content_digest(root, selected),
    }
    write_json(root / MANIFEST_NAME, payload)
    return payload


def verify_manifest(root: Path, pin: SourcePin) -> dict:
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise GesError(SOURCE_CACHE_INTEGRITY_FAILED, f"source cache manifest missing for {pin.id}")
    manifest = read_json(path)
    if manifest.get("repo") != pin.repo or manifest.get("commit") != pin.commit_sha:
        raise GesError(
            SOURCE_CACHE_INTEGRITY_FAILED,
            f"source cache provenance mismatch for {pin.id}",
            details={"expected": {"repo": pin.repo, "commit": pin.commit_sha}},
        )
    selected = list_selected_paths(root)
    if sorted(manifest.get("selected_paths") or []) != selected:
        raise GesError(SOURCE_CACHE_INTEGRITY_FAILED, f"source cache selected_paths mismatch for {pin.id}")
    digest = content_digest(root, selected)
    if digest != manifest.get("content_digest"):
        raise GesError(SOURCE_CACHE_INTEGRITY_FAILED, f"source cache content digest mismatch for {pin.id}")
    return manifest


def seed_fixture_manifests(root: Path, pins: list[SourcePin]) -> None:
    for pin in pins:
        dest = root / pin.cache_key / pin.commit_sha
        if dest.is_dir():
            write_manifest(dest, pin)


def _has_content(dest: Path) -> bool:
    if not dest.is_dir():
        return False
    for path in dest.iterdir():
        if path.name not in {".git", *SKIP_NAMES}:
            return True
    return False


def _git_fetch(dest: Path, repo: str, sha: str) -> None:
    if not (dest / ".git").exists():
        _run(["git", "init"], dest)
        _run(["git", "remote", "add", "origin", repo], dest)
    _run(["git", "fetch", "--depth", "1", "origin", sha], dest)
    _run(["git", "checkout", "--force", "FETCH_HEAD"], dest)


def _git_head(dest: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=dest,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git rev-parse HEAD failed")
    return result.stdout.strip()


def _run(args: list[str], cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git failed")


def copy_tree(src: Path, files: dict[str, bytes], dest_prefix: str) -> None:
    if src.is_symlink():
        raise GesError(SOURCE_CACHE_INTEGRITY_FAILED, f"symlink rejected: {src}")
    if src.is_file():
        files[f"{dest_prefix}/{src.name}" if dest_prefix else src.name] = src.read_bytes()
        return
    for path in src.rglob("*"):
        if path.is_symlink():
            raise GesError(SOURCE_CACHE_INTEGRITY_FAILED, f"symlink rejected: {path}")
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        rel = path.relative_to(src).as_posix()
        key = f"{dest_prefix}/{rel}" if dest_prefix else rel
        files[key] = path.read_bytes()
