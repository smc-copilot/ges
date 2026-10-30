from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ges.acceptance.harness import build_brownfield, configure_offline_cache
from ges.catalog.loader import load_catalog
from ges.source_adapters.cache import seed_fixture_manifests


@pytest.fixture
def offline_cache(tmp_path, monkeypatch):
    src = ROOT / "tests" / "ges6" / "fixtures" / "source-cache"
    dest = tmp_path / "source-cache"
    if src.exists():
        import shutil

        shutil.copytree(src, dest)
    seed_fixture_manifests(dest, list(load_catalog().sources.values()))
    monkeypatch.setenv("GES_SOURCE_CACHE", str(dest))
    monkeypatch.setenv("GES_SOURCE_OFFLINE", "1")
    return dest


@pytest.fixture
def brownfield(tmp_path, offline_cache):
    return build_brownfield(tmp_path)
