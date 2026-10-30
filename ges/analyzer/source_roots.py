from __future__ import annotations

import os
from pathlib import Path

from ges.paths import BUSINESS_SOURCE_ROOTS, BUSINESS_SOURCE_SKIP_PREFIXES


def business_source_roots(repo: Path) -> list[str]:
    roots: list[str] = []
    for name in BUSINESS_SOURCE_ROOTS:
        if (repo / name).is_dir():
            roots.append(name)
    return roots


# @lat: [[large-repo-snapshot]]
def is_skipped_business_path(rel: str) -> bool:
    path = rel.replace("\\", "/").strip("/")
    return any(path == prefix or path.startswith(prefix + "/") for prefix in BUSINESS_SOURCE_SKIP_PREFIXES)


def iter_business_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for root in business_source_roots(repo):
        base = repo / root
        for current, dirs, names in os.walk(base, topdown=True):
            rel_dir = Path(current).relative_to(repo).as_posix()
            dirs[:] = [
                name
                for name in dirs
                if name != ".git" and not is_skipped_business_path(f"{rel_dir}/{name}")
            ]
            for name in names:
                rel = f"{rel_dir}/{name}"
                if is_skipped_business_path(rel):
                    continue
                path = Path(current) / name
                if path.is_file() and ".git" not in path.parts:
                    files.append(path)
    return files
