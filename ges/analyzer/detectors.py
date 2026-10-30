from __future__ import annotations

import json
from pathlib import Path

from ges.analyzer.git_index import GitFileIndex, prune_walk

_INDEX: GitFileIndex | None = None
_WALK_PATHS: list[str] | None = None
IGNORED_TREE_VISITS = 0


def use_file_inventory(
    *,
    index: GitFileIndex | None = None,
    paths: list[str] | None = None,
    ignored_visits: int = 0,
) -> None:
    global _INDEX, _WALK_PATHS, IGNORED_TREE_VISITS
    _INDEX = index
    _WALK_PATHS = paths
    IGNORED_TREE_VISITS = ignored_visits


def clear_file_inventory() -> None:
    use_file_inventory()


def _candidate_paths(repo: Path) -> list[str]:
    if _INDEX is not None:
        return _INDEX.visible_paths()
    if _WALK_PATHS is not None:
        return list(_WALK_PATHS)
    paths, visits = prune_walk(repo)
    global IGNORED_TREE_VISITS
    IGNORED_TREE_VISITS = visits
    return paths


def exists(repo: Path, rel: str) -> bool:
    return (repo / rel).exists()


def detect_agents(repo: Path) -> list[str]:
    agents: list[str] = []
    if exists(repo, ".cursor") or exists(repo, ".cursor/"):
        agents.append("cursor")
    if exists(repo, ".codex") or exists(repo, ".codex/"):
        agents.append("codex")
    if exists(repo, ".hermes") or exists(repo, ".hermes/"):
        agents.append("hermes")
    return agents


def tsconfig_evidence(repo: Path) -> list[str]:
    found: list[str] = []
    for rel in _candidate_paths(repo):
        name = Path(rel).name
        if not name.startswith("tsconfig") or not name.endswith(".json"):
            continue
        parts = Path(rel).parts[:-1]
        if any(part.startswith(".") and part not in {".", ".."} for part in parts):
            continue
        if "node_modules" in Path(rel).parts or ".git" in Path(rel).parts:
            continue
        found.append(rel)
    return sorted(found)


def typescript_source_evidence(repo: Path) -> list[str]:
    hits = [
        rel
        for rel in _candidate_paths(repo)
        if rel.endswith(".ts") or rel.endswith(".tsx")
        if "node_modules" not in Path(rel).parts and ".git" not in Path(rel).parts
    ]
    return sorted(hits)[:5]


def detect_languages(repo: Path) -> list[str]:
    found: list[str] = []
    mapping = [
        ("python", ("pyproject.toml", "setup.py", "requirements.txt")),
        ("go", ("go.mod",)),
        ("rust", ("Cargo.toml",)),
        ("java", ("pom.xml", "build.gradle", "build.gradle.kts")),
    ]
    for name, files in mapping:
        if any(exists(repo, item) for item in files):
            found.append(name)
    if tsconfig_evidence(repo) or typescript_source_evidence(repo) or package_json_typescript(repo):
        found.insert(0, "typescript")
    elif exists(repo, "package.json") or iter_package_json(repo):
        found.append("javascript")
    return found


def iter_package_json(repo: Path) -> list[Path]:
    found: list[Path] = []
    for rel in _candidate_paths(repo):
        if Path(rel).name != "package.json":
            continue
        if "node_modules" in Path(rel).parts or ".git" in Path(rel).parts:
            continue
        found.append(repo / rel)
    return sorted(found, key=lambda item: item.relative_to(repo).as_posix())


def _package_data(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def package_json_typescript(repo: Path) -> bool:
    for path in iter_package_json(repo):
        data = _package_data(path)
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            block = data.get(key) or {}
            if isinstance(block, dict):
                deps.update(block)
        if "typescript" in deps:
            return True
    return False


def detect_scripts(repo: Path) -> dict[str, list[str]]:
    found = {"test": [], "build": [], "lint": []}
    for path in iter_package_json(repo):
        scripts = _package_data(path).get("scripts") or {}
        if not isinstance(scripts, dict):
            continue
        rel = path.relative_to(repo).as_posix()
        for name in ("test", "build", "lint"):
            if name in scripts:
                found[name].append(rel)
    return found


def detect_package_managers(repo: Path) -> list[str]:
    found: list[str] = []
    mapping = [
        ("pnpm", "pnpm-lock.yaml"),
        ("yarn", "yarn.lock"),
        ("npm", "package-lock.json"),
        ("poetry", "poetry.lock"),
        ("pip", "requirements.txt"),
        ("cargo", "Cargo.lock"),
    ]
    for name, marker in mapping:
        if exists(repo, marker):
            found.append(name)
    return found


def detect_frameworks(repo: Path) -> list[str]:
    found: list[str] = []
    if exists(repo, "nx.json"):
        found.append("nx")
    if exists(repo, "turbo.json"):
        found.append("turbo")
    if exists(repo, "angular.json"):
        found.append("angular")
    pkg = repo / "package.json"
    if pkg.is_file():
        text = pkg.read_text(encoding="utf-8", errors="replace")
        for name in ("next", "react", "vue", "nestjs", "express"):
            if f'"{name}"' in text:
                found.append(name)
    return found


def detect_monorepo(repo: Path) -> bool:
    markers = (
        "pnpm-workspace.yaml",
        "lerna.json",
        "nx.json",
        "turbo.json",
    )
    if any(exists(repo, marker) for marker in markers):
        return True
    app_roots = sum(1 for name in ("apps", "services", "packages") if (repo / name).is_dir())
    return app_roots >= 2


def detect_brownfield(repo: Path) -> bool:
    source_roots = ("apps", "services", "src", "packages", "contracts")
    if any((repo / name).is_dir() and any((repo / name).iterdir()) for name in source_roots if (repo / name).exists()):
        return True
    for marker in ("package.json", "pyproject.toml", "go.mod", "Cargo.toml"):
        if exists(repo, marker):
            return True
    return False


def detect_spec_kit(repo: Path) -> bool:
    return exists(repo, ".specify")


def detect_legacy_ges(repo: Path) -> bool:
    markers = (
        ".smc/ges-install-lock.json",
        ".smc/ges-install-receipt.json",
        ".agents/ges",
        ".smc/ges-bootstrap-receipt.json",
    )
    return any(exists(repo, marker) for marker in markers)


def detect_ci(repo: Path) -> list[str]:
    found: list[str] = []
    if (repo / ".github" / "workflows").is_dir():
        found.append("github-actions")
    if exists(repo, ".gitlab-ci.yml"):
        found.append("gitlab-ci")
    if exists(repo, "azure-pipelines.yml"):
        found.append("azure-pipelines")
    return found


def detect_existing(repo: Path) -> dict[str, bool]:
    return {
        "AGENTS.md": exists(repo, "AGENTS.md"),
        "CLAUDE.md": exists(repo, "CLAUDE.md"),
        ".agents": exists(repo, ".agents"),
        ".cursor": exists(repo, ".cursor"),
        ".codex": exists(repo, ".codex"),
        ".specify": exists(repo, ".specify"),
        ".smc": exists(repo, ".smc"),
        "CONTEXT.md": exists(repo, "CONTEXT.md"),
        "CONTEXT-MAP.md": exists(repo, "CONTEXT-MAP.md"),
        "docs/adr": exists(repo, "docs/adr"),
    }
