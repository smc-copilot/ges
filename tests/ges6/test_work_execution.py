from __future__ import annotations

import json
from pathlib import Path

import pytest

from ges.catalog.providers import RTK_ID
from ges.cli.main import main
from ges.errors import (
    WORK_ALREADY_V2,
    WORK_CAPABILITY_NOT_BOUND,
    WORK_CAPABILITY_NOT_FOUND,
    WORK_CAPABILITY_UNSUPPORTED,
    WORK_EXECUTION_CONTRACT_MISSING,
    GesError,
)
from ges.governance.artifacts import link_artifact
from ges.governance.execution_gate import evaluate_execution, resolve_effective_required
from ges.governance.gates import evaluate_intake
from ges.governance.git_observe import local_head
from ges.governance.registry import (
    add_work_capability,
    create_work,
    migrate_work,
    remove_work_capability,
)
from ges.governance.storage import init_governance, load_work, now_rfc3339, write_work
from ges.providers.overlay import write_installed, write_policy
from ges.reconciler.apply import consumer_tree
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
    _git_init(repo)
    return repo


def _ready_work(repo: Path, work_id: str = "WI-WORK-0001", *, host: str = "cursor") -> None:
    create_work(repo, work_id=work_id, title="demo", owner="team", risk="LOW", host=host)
    link_artifact(repo, work_id, artifact_type="SPEC", path="specs/spec.md")
    link_artifact(repo, work_id, artifact_type="PLAN", path="specs/plan.md")


def _write_v1(repo: Path, work_id: str = "WI-WORK-V1") -> dict:
    stamp = now_rfc3339()
    payload = {
        "schema": "ges.work.v1",
        "id": work_id,
        "kind": "FEATURE",
        "title": "legacy",
        "status": "OPEN",
        "owner": "team",
        "risk": "LOW",
        "policy": "default-v1",
        "artifacts": [],
        "created_at": stamp,
        "updated_at": stamp,
    }
    write_work(repo, payload, create=True)
    return payload


# @lat: [[work-execution-tests#Work v2#Create emits v2 with host]]
def test_create_emits_v2_with_host(tmp_path):
    repo = _repo(tmp_path)
    payload = create_work(repo, work_id="WI-WORK-0001", title="t", owner="o", risk="LOW", host="codex")
    assert payload["schema"] == "ges.work.v2"
    assert payload["execution"] == {"profile": "ges-native", "host": "codex"}
    assert payload["capabilities"]["required"] == []


# @lat: [[work-execution-tests#Work v2#Unknown capability rejected]]
def test_unknown_capability_rejected(tmp_path):
    repo = _repo(tmp_path)
    _ready_work(repo)
    before = consumer_tree(repo)
    with pytest.raises(GesError) as exc:
        add_work_capability(repo, "WI-WORK-0001", "unknown.cap")
    assert exc.value.code == WORK_CAPABILITY_NOT_FOUND
    assert consumer_tree(repo) == before


# @lat: [[work-execution-tests#Work v2#Composer capability rejected]]
def test_composer_capability_rejected(tmp_path):
    repo = _repo(tmp_path)
    _ready_work(repo)
    before = consumer_tree(repo)
    with pytest.raises(GesError) as exc:
        add_work_capability(repo, "WI-WORK-0001", "matt.setup")
    assert exc.value.code == WORK_CAPABILITY_UNSUPPORTED
    assert consumer_tree(repo) == before


# @lat: [[work-execution-tests#Migrate#Explicit migrate preserves fields]]
def test_explicit_migrate_preserves_fields(tmp_path):
    repo = _repo(tmp_path)
    _write_v1(repo)
    migrated = migrate_work(repo, "WI-WORK-V1", host="hermes")
    assert migrated["schema"] == "ges.work.v2"
    assert migrated["title"] == "legacy"
    assert migrated["execution"]["host"] == "hermes"
    assert migrated["capabilities"]["required"] == []
    with pytest.raises(GesError) as exc:
        migrate_work(repo, "WI-WORK-V1", host="hermes")
    assert exc.value.code == WORK_ALREADY_V2


# @lat: [[work-execution-tests#Migrate#Show does not migrate]]
def test_show_does_not_migrate(tmp_path):
    repo = _repo(tmp_path)
    _write_v1(repo)
    path = repo / ".ges" / "governance" / "works" / "WI-WORK-V1.yaml"
    before = path.read_bytes()
    assert main(["work", "show", str(repo), "--id", "WI-WORK-V1"]) == 0
    assert path.read_bytes() == before
    assert load_work(repo, "WI-WORK-V1")["schema"] == "ges.work.v1"


# @lat: [[work-execution-tests#Work capability#Add remove idempotent]]
def test_add_remove_idempotent(tmp_path):
    repo = _repo(tmp_path)
    _ready_work(repo)
    write_policy(repo, {"required": [], "recommended": [], "optional": [], "prohibited": []})
    first = add_work_capability(repo, "WI-WORK-0001", RTK_ID)
    assert first["capabilities"]["required"] == [RTK_ID]
    second = add_work_capability(repo, "WI-WORK-0001", RTK_ID)
    assert second["capabilities"]["required"] == [RTK_ID]
    remove_work_capability(repo, "WI-WORK-0001", RTK_ID)
    assert load_work(repo, "WI-WORK-0001")["capabilities"]["required"] == []
    with pytest.raises(GesError) as exc:
        remove_work_capability(repo, "WI-WORK-0001", RTK_ID)
    assert exc.value.code == WORK_CAPABILITY_NOT_BOUND


# @lat: [[work-execution-tests#Work capability#Policy digest unchanged]]
def test_work_capability_leaves_policy(tmp_path):
    repo = _repo(tmp_path)
    _ready_work(repo)
    write_policy(repo, {"required": [], "recommended": [RTK_ID], "optional": [], "prohibited": []})
    path = repo / ".ges" / "capabilities" / "policy.yaml"
    before = path.read_bytes()
    add_work_capability(repo, "WI-WORK-0001", RTK_ID)
    assert path.read_bytes() == before


# @lat: [[work-execution-tests#Create CLI#Host required]]
def test_create_requires_host(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(SystemExit):
        main(["work", "create", str(repo), "--id", "WI-X", "--title", "t", "--owner", "o", "--risk", "LOW"])


# @lat: [[work-execution-tests#Execution gate#Empty required may pass]]
def test_empty_required_may_pass(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _ready_work(repo)
    monkeypatch.setattr("ges.governance.execution_gate.probe_rtk", lambda: {"status": "missing"})
    monkeypatch.setattr(
        "ges.governance.execution_gate.probe_capability_binding",
        lambda *_a, **_k: {"status": "UNBOUND", "observations": []},
    )
    assert evaluate_intake(repo, "WI-WORK-0001")["status"] == "PASS"
    result = evaluate_execution(repo, "WI-WORK-0001")
    assert result["status"] == "PASS"
    assert result["verdict"] == "EXECUTION_READY"
    assert result["effective_required"] == []


# @lat: [[work-execution-tests#Execution gate#V1 is blocked]]
def test_v1_execution_blocked(tmp_path):
    repo = _repo(tmp_path)
    _write_v1(repo)
    result = evaluate_execution(repo, "WI-WORK-V1")
    assert result["status"] == "BLOCKED"
    assert any(r["code"] == WORK_EXECUTION_CONTRACT_MISSING for r in result["reasons"])


# @lat: [[work-execution-tests#Execution gate#Policy union]]
def test_policy_union_effective_required(tmp_path):
    repo = _repo(tmp_path)
    _ready_work(repo)
    write_policy(repo, {"required": [RTK_ID], "recommended": [], "optional": [], "prohibited": []})
    work = load_work(repo, "WI-WORK-0001")
    effective, fails = resolve_effective_required(repo, work)
    assert effective == [RTK_ID]
    assert fails == []


# @lat: [[work-execution-tests#Execution gate#Prohibited fails]]
def test_prohibited_fails(tmp_path):
    repo = _repo(tmp_path)
    _ready_work(repo)
    add_work_capability(repo, "WI-WORK-0001", RTK_ID)
    write_policy(repo, {"required": [], "recommended": [], "optional": [], "prohibited": [RTK_ID]})
    result = evaluate_execution(repo, "WI-WORK-0001")
    assert result["status"] == "FAIL"


# @lat: [[work-execution-tests#Execution gate#Missing installed blocks]]
def test_missing_installed_blocks(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _ready_work(repo)
    add_work_capability(repo, "WI-WORK-0001", RTK_ID)
    monkeypatch.setattr(
        "ges.governance.execution_gate.probe_rtk",
        lambda: {"status": "READY", "capability_id": RTK_ID, "health_checks": []},
    )
    monkeypatch.setattr(
        "ges.governance.execution_gate.probe_capability_binding",
        lambda *_a, **_k: {"status": "BOUND", "observations": []},
    )
    result = evaluate_execution(repo, "WI-WORK-0001")
    assert result["status"] == "BLOCKED"
    assert any(r["code"] == "WORK_CAPABILITY_REQUIRED_MISSING" for r in result["reasons"])


# @lat: [[work-execution-tests#Execution gate#JSON schema]]
def test_execution_json_schema(tmp_path):
    repo = _repo(tmp_path)
    _ready_work(repo)
    result = evaluate_execution(repo, "WI-WORK-0001")
    assert result["schema"] == "ges.execution-readiness.v1"
    assert "capabilities" in result


# @lat: [[work-execution-tests#Regression#Gate A verdicts preserved]]
def test_gate_a_verdicts_preserved(tmp_path):
    repo = _repo(tmp_path)
    _ready_work(repo)
    assert evaluate_intake(repo, "WI-WORK-0001")["verdict"] == "WORK_READY"


# @lat: [[work-execution-tests#Regression#Unchanged]]
def test_evidence_snapshot_unchanged():
    from ges.paths import SCHEMA_DIR

    schema = json.loads((SCHEMA_DIR / "ges.evidence-snapshot.v1.json").read_text(encoding="utf-8"))
    assert "capabilities" not in schema["properties"]
