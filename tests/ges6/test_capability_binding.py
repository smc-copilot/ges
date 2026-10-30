from __future__ import annotations

import json
from pathlib import Path

import pytest

from ges.catalog.providers import RTK_ID
from ges.errors import CAPABILITY_BINDING_CHANGED_DURING_EVALUATION
from ges.providers.rtk_binding import binding_identity, probe_binding
from ges.reconciler.apply import consumer_tree
from ges.governance.storage import init_governance
import subprocess


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_governance(repo)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    return repo


# @lat: [[work-execution-tests#Binding#Cursor bound]]
def test_cursor_bound(tmp_path, monkeypatch):
    cursor = tmp_path / ".cursor"
    cursor.mkdir()
    (cursor / "hooks.json").write_text(
        '{"hooks":{"preToolUse":[{"command":"rtk.exe rewrite"}]}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("ges.providers.rtk_binding.Path.home", lambda: tmp_path)
    monkeypatch.setattr("ges.providers.rtk_binding.probe_rtk", lambda: {"status": "READY"})
    payload = probe_binding(RTK_ID, "cursor")
    assert payload["status"] == "BOUND"
    assert payload["schema"] == "ges.capability-binding-status.v1"


# @lat: [[work-execution-tests#Binding#Codex bound]]
def test_codex_bound(tmp_path, monkeypatch):
    repo = tmp_path / "proj"
    repo.mkdir()
    monkeypatch.chdir(repo)
    codex = repo / ".codex"
    codex.mkdir()
    (codex / "hooks.json").write_text('{"preToolUse":[{"command":"C:\\\\bin\\\\rtk rewrite"}]}', encoding="utf-8")
    monkeypatch.setattr("ges.providers.rtk_binding.probe_rtk", lambda: {"status": "READY"})
    payload = probe_binding(RTK_ID, "codex")
    assert payload["status"] == "BOUND"


# @lat: [[work-execution-tests#Binding#Hermes bound]]
def test_hermes_bound(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    plugins = home / "plugins" / "rtk-plugin"
    plugins.mkdir(parents=True)
    (plugins / "index.js").write_text("// rtk", encoding="utf-8")
    (home / "config.json").write_text('{"plugins":{"rtk":{"enabled":true}}}', encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr("ges.providers.rtk_binding.probe_rtk", lambda: {"status": "READY"})
    payload = probe_binding(RTK_ID, "hermes")
    assert payload["status"] == "BOUND"


# @lat: [[work-execution-tests#Binding#Invalid registration unbound]]
def test_invalid_registration_unbound(tmp_path, monkeypatch):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "hooks.json").write_text('{"hooks":[]}', encoding="utf-8")
    monkeypatch.setattr("ges.providers.rtk_binding.Path.home", lambda: tmp_path)
    monkeypatch.setattr("ges.providers.rtk_binding.probe_rtk", lambda: {"status": "READY"})
    payload = probe_binding(RTK_ID, "cursor")
    assert payload["status"] in {"UNBOUND", "UNPROVEN"}


# @lat: [[work-execution-tests#Binding#Probe writes nothing]]
def test_probe_writes_nothing(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    before = consumer_tree(repo)
    monkeypatch.setattr("ges.providers.rtk_binding.probe_rtk", lambda: {"status": "missing"})
    probe_binding(RTK_ID, "cursor")
    assert consumer_tree(repo) == before


# @lat: [[work-execution-tests#Binding#Identity changes detected]]
def test_identity_changes_detected():
    a = {
        "host": "cursor",
        "observations": [{"source": "a", "digest": "sha256:1"}],
    }
    b = {
        "host": "cursor",
        "observations": [{"source": "a", "digest": "sha256:2"}],
    }
    assert binding_identity(a) != binding_identity(b)
    assert CAPABILITY_BINDING_CHANGED_DURING_EVALUATION
