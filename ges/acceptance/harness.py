from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ges.compose import compose, prepare_apply
from ges.errors import GES_RECONCILE_NOOP, GesError
from ges.io import write_bytes, write_text
from ges.reconciler.apply import apply_plan, snapshot_business_sources

FIXTURE_CACHE = Path(__file__).resolve().parents[2] / "tests" / "ges6" / "fixtures" / "source-cache"
USER_AGENTS = "# Product Agents\n\nUser-owned routing rules.\nDo not overwrite this paragraph.\n"
SPEC_CONSTITUTION = "# Existing constitution\nUser owned.\n"
THIRD_PARTY = "# third-party skill\n"
GOVERNANCE = "# governance kit\n"
OWNED_BODY = b"v5-owned-unmodified\n"


def configure_offline_cache(cache: Path | None = None) -> Path:
    root = cache or FIXTURE_CACHE
    os.environ["GES_SOURCE_CACHE"] = str(root)
    os.environ["GES_SOURCE_OFFLINE"] = "1"
    return root


def build_brownfield(root: Path) -> Path:
    repo = root / "consumer"
    _write(repo / "apps" / "work" / "src" / "main.ts", "export const app = 1;\n")
    _write(repo / "services" / "runtime" / "src" / "index.ts", "export const svc = 1;\n")
    _write(repo / "packages" / "ui" / "src" / "lib.ts", "export const ui = 1;\n")
    _write(repo / "contracts" / "api.md", "# api\n")
    _write(repo / "src" / "app.ts", "export const src = 1;\n")
    _write(repo / "AGENTS.md", USER_AGENTS)
    _write(repo / ".agents" / "skills" / "third-party" / "SKILL.md", THIRD_PARTY)
    _write(repo / ".agents" / "governance" / "kit.md", GOVERNANCE)
    _write(repo / ".cursor" / "settings.json", "{}\n")
    _write(repo / ".codex" / "config.toml", "model = \"default\"\n")
    _write(repo / ".specify" / "constitution.md", SPEC_CONSTITUTION)
    _write(repo / ".specify" / "templates" / "spec-template.md", "# user spec template\n")
    _write(repo / "package.json", json.dumps({"name": "consumer", "private": True}) + "\n")
    _write(repo / "tsconfig.json", "{}\n")
    _write(repo / "nx.json", "{}\n")
    _write(repo / "pnpm-workspace.yaml", "packages:\n  - apps/*\n")
    _write(repo / ".github" / "workflows" / "ci.yml", "name: ci\n")
    owned = repo / ".agents" / "skills" / "using-superpowers" / "SKILL.md"
    write_bytes(owned, OWNED_BODY)
    drifted = repo / ".cursor" / "skills" / "smc-work-router" / "SKILL.md"
    write_text(drifted, "user-modified leftover\n")
    lock = {
        "schema": "smc.ges.install-lock.v2",
        "bundle": "5.0.0",
        "owned_files": [
            {
                "path": ".agents/skills/using-superpowers/SKILL.md",
                "installed_sha256": hashlib.sha256(OWNED_BODY).hexdigest(),
            },
            {
                "path": ".agents/ges/domain-packs/backend/pack.json",
                "installed_sha256": "a" * 64,
            },
            {
                "path": ".cursor/skills/smc-work-router/SKILL.md",
                "installed_sha256": "b" * 64,
            },
        ],
    }
    _write(repo / ".smc" / "ges-install-lock.json", json.dumps(lock, indent=2) + "\n")
    return repo


def apply_recommended(repo: Path, *, exclude: list[str] | None = None, extra: list[str] | None = None):
    ctx = compose(repo, exclude=exclude, extra=extra, persist_profile=False)
    prepare_apply(ctx)
    try:
        receipt = apply_plan(repo, ctx.plan, ctx.desired, project=ctx.project, profile=ctx.profile, lock=ctx.lock)
        return ctx, receipt, False
    except GesError as exc:
        if exc.code == GES_RECONCILE_NOOP:
            return ctx, None, True
        raise


def business_fingerprint(repo: Path) -> dict[str, dict[str, Any]]:
    return snapshot_business_sources(repo)


def _write(path: Path, text: str) -> None:
    write_text(path, text)
