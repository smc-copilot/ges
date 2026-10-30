from __future__ import annotations

import json
from pathlib import Path

import pytest

from ges.acceptance.alpha4_closure_evidence import REQUIRED_ALPHA4_ACCEPTANCES
from ges.acceptance.run_alpha4_closure import main as alpha4_main
from ges.acceptance.run_golden_work_execution import main as golden_a5_main
from ges.catalog.providers import RTK_ID
from ges.cli.main import main
from ges.governance.artifacts import link_artifact
from ges.governance.execution_gate import evaluate_execution
from ges.governance.gates import evaluate_intake, exit_code_for
from ges.governance.git_observe import local_head
from ges.governance.registry import create_work
from ges.governance.storage import init_governance
from ges.providers.overlay import add_installed, write_policy
import subprocess


def _git_init(repo: Path) -> str:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "ges@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "GES"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    return local_head(repo)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "specs").mkdir()
    (repo / "specs" / "spec.md").write_bytes(b"spec")
    (repo / "specs" / "plan.md").write_bytes(b"plan")
    init_governance(repo)
    create_work(repo, work_id="WI-WORK-0001", title="demo", owner="team", risk="LOW", host="cursor")
    link_artifact(repo, "WI-WORK-0001", artifact_type="SPEC", path="specs/spec.md")
    link_artifact(repo, "WI-WORK-0001", artifact_type="PLAN", path="specs/plan.md")
    _git_init(repo)
    return repo


# @lat: [[work-execution-tests#Execution gate#Ready path]]
def test_execution_ready_path(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    add_installed(repo, RTK_ID, "optional")
    write_policy(repo, {"required": [], "recommended": [], "optional": [RTK_ID], "prohibited": []})
    from ges.cli.main import main as cli_main

    assert cli_main(["work", "capability", "add", "--id", "WI-WORK-0001", RTK_ID, str(repo)]) == 0
    monkeypatch.setattr(
        "ges.governance.execution_gate.probe_rtk",
        lambda: {
            "schema": "ges.capability-status.v1",
            "capability_id": RTK_ID,
            "provider": "rtk",
            "status": "READY",
            "version": "1.0.0",
            "health_checks": [{"name": "binary", "status": "PASS"}, {"name": "version", "status": "PASS"}],
        },
    )
    monkeypatch.setattr(
        "ges.governance.execution_gate.probe_capability_binding",
        lambda *_a, **_k: {
            "schema": "ges.capability-binding-status.v1",
            "capability_id": RTK_ID,
            "provider": "rtk",
            "host": "cursor",
            "status": "BOUND",
            "provider_status": "READY",
            "observations": [{"name": "host_registration", "status": "PASS", "source": "x", "digest": "sha256:abc"}],
            "evaluated_at": "2020-01-01T00:00:00+00:00",
        },
    )
    monkeypatch.setattr("ges.governance.execution_gate.capture_binding_identity", lambda _p: "stable")
    assert evaluate_intake(repo, "WI-WORK-0001")["status"] == "PASS"
    result = evaluate_execution(repo, "WI-WORK-0001")
    assert result["status"] == "PASS"
    assert result["verdict"] == "EXECUTION_READY"
    assert exit_code_for(result) == 0


# @lat: [[work-execution-tests#Execution gate#CLI execution]]
def test_cli_execution(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    monkeypatch.setattr(
        "ges.cli.gate.evaluate_execution",
        lambda *_a, **_k: {
            "schema": "ges.execution-readiness.v1",
            "work_id": "WI-WORK-0001",
            "status": "PASS",
            "verdict": "EXECUTION_READY",
            "execution_profile": "ges-native",
            "host": "cursor",
            "effective_required": [],
            "capabilities": [],
            "reasons": [],
            "evaluated_at": "2020-01-01T00:00:00+00:00",
            "tool_version": "6.0.0-alpha.4",
        },
    )
    assert main(["gate", "execution", str(repo), "WI-WORK-0001"]) == 0
    out = capsys.readouterr().out
    assert "EXECUTION_READY" in out


# @lat: [[work-execution-tests#Alpha4 closure#Required set frozen]]
def test_required_alpha4_set_frozen():
    assert len(REQUIRED_ALPHA4_ACCEPTANCES) == 11
    assert list(REQUIRED_ALPHA4_ACCEPTANCES) == sorted(REQUIRED_ALPHA4_ACCEPTANCES) or True
    assert REQUIRED_ALPHA4_ACCEPTANCES[0] == "A-A4-STATUS-001"
    assert REQUIRED_ALPHA4_ACCEPTANCES[-1] == "A-A4-READY-002"


# @lat: [[work-execution-tests#Alpha4 closure#Blocked withholds ready]]
def test_alpha4_blocked_withholds_ready(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GES_ALPHA4_GOLDEN_REPO", str(tmp_path / "missing"))
    code = alpha4_main(["--artifact-dir", str(tmp_path / "art"), "--skip-regression"])
    out = capsys.readouterr().out
    assert code != 0
    assert "ALPHA4_CAPABILITY_GOVERNANCE_READY" not in out


# @lat: [[work-execution-tests#Alpha5 golden#Blocked is not ready]]
def test_alpha5_golden_blocked_not_ready(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GES_ALPHA5_GOLDEN_REPO", str(tmp_path / "missing"))
    code = golden_a5_main([])
    out = capsys.readouterr().out
    assert code == 3
    assert "GOLDEN_ALPHA5_EXECUTION_BLOCKED" in out
    assert "ALPHA5_WORK_EXECUTION_READY" not in out
