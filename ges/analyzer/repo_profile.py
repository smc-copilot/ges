from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges import __version__
from ges.analyzer import detectors
from ges.analyzer.git_index import build_git_file_index, is_git_repo, prune_walk
from ges.analyzer.source_roots import business_source_roots
from ges.errors import BUSINESS_GIT_INDEX_UNAVAILABLE, REPO_NOT_SUPPORTED, GesError
from ges.stagelog import ANALYZE, ANALYZER_INDEX, emit


def analyze_repo(repo: Path) -> dict[str, Any]:
    """Build a deterministic repo profile. LLM token usage is always 0."""
    emit(ANALYZE, "start", repo=str(repo))
    root = repo.expanduser().resolve()
    if not root.is_dir():
        raise GesError(REPO_NOT_SUPPORTED, f"repository path does not exist: {repo}")
    _bind_analyzer_index(root)

    brownfield = detectors.detect_brownfield(root)
    monorepo = detectors.detect_monorepo(root)
    lifecycle = "brownfield" if brownfield else "greenfield"
    layout = "monorepo" if monorepo else "single"
    kind = f"{lifecycle}-{layout}" if monorepo else lifecycle

    profile = {
        "schema": "ges.repo-profile.v2",
        "repository_lifecycle": lifecycle,
        "layout": layout,
        "kind": kind,
        "repository_kind": kind,
        "agents": detectors.detect_agents(root),
        "languages": detectors.detect_languages(root),
        "spec_kit": detectors.detect_spec_kit(root),
        "legacy_ges": detectors.detect_legacy_ges(root),
        "ci": detectors.detect_ci(root),
        "package_managers": detectors.detect_package_managers(root),
        "frameworks": detectors.detect_frameworks(root),
        "existing": detectors.detect_existing(root),
        "source_roots": business_source_roots(root),
        "scripts": detectors.detect_scripts(root),
        "tsconfig_evidence": detectors.tsconfig_evidence(root),
        "analyzer_version": __version__,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "git": _git_identity(root),
        "llm_token_usage": 0,
    }
    emit(ANALYZE, "complete", repository_kind=kind, agents=profile["agents"])
    return profile


def _bind_analyzer_index(repo: Path) -> None:
    emit(ANALYZER_INDEX, "start", repo=str(repo))
    if is_git_repo(repo):
        try:
            index = build_git_file_index(repo)
            detectors.use_file_inventory(index=index)
            emit(ANALYZER_INDEX, "complete", paths=index.path_count, elapsed_ms=index.elapsed_ms, mode="git")
            return
        except GesError as exc:
            if exc.code != BUSINESS_GIT_INDEX_UNAVAILABLE:
                raise
    paths, visits = prune_walk(repo)
    detectors.use_file_inventory(paths=paths, ignored_visits=visits)
    emit(ANALYZER_INDEX, "complete", paths=len(paths), elapsed_ms=0, mode="walk")


def _git_identity(repo: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"repository": (repo / ".git").exists()}
    if not info["repository"]:
        return info
    info["head"] = _git(repo, ["rev-parse", "HEAD"])
    info["remote"] = _git(repo, ["config", "--get", "remote.origin.url"])
    return info


def _git(repo: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
