from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from ges.acceptance.backplane_evidence import write_backplane_evidence
from ges.acceptance.harness import apply_recommended
from ges.cli.evidence import run_add
from ges.cli.main import main
from ges.errors import (
    APPROVAL_REQUIRED_UNSUPPORTED,
    PR_HEAD_CHANGED_DURING_EVALUATION,
    ARTIFACT_PATH_INVALID,
    ARTIFACT_STALE,
    CI_CHECK_PENDING,
    GOVERNANCE_ALREADY_INITIALIZED,
    POLICY_SCHEMA_INVALID,
    REVIEW_REQUIRED,
    UNSUPPORTED_OPERATION,
    WORK_ALREADY_EXISTS,
    WORK_CLOSED_IMMUTABLE,
    WORK_STATE_TRANSITION_INVALID,
    WORKTREE_DIRTY,
    GesError,
)
from ges.governance.artifacts import digest_file, link_artifact, normalize_pointer
from ges.governance.evidence import collect_evidence, map_check_status
from ges.governance.gates import evaluate_intake, evaluate_merge, explain_gate
from ges.governance.git_observe import local_head
from ges.governance.paths import work_path
from ges.governance.registry import close_work, create_work, update_work
from ges.governance.storage import init_governance, load_policy, load_work, write_policy
from ges.governance.trace import REQUIRED_EDGES, build_trace
from ges.reconciler.apply import snapshot_managed_scope
from ges.reconciler.plan import InstallPlan
from ges.remove import run_remove
from ges.reconciler.apply import consumer_tree


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "github"


def _git_init(repo: Path) -> str:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "ges@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "GES"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    return local_head(repo)


def _gov_repo(tmp_path: Path, *, risk: str = "LOW", with_plan: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "specs").mkdir()
    (repo / "specs" / "spec.md").write_bytes(b"spec-bytes")
    if with_plan:
        (repo / "specs" / "plan.md").write_bytes(b"plan-bytes")
    init_governance(repo)
    create_work(repo, work_id="WI-WORK-0001", title="demo", owner="team", risk=risk, host="cursor")
    link_artifact(repo, "WI-WORK-0001", artifact_type="SPEC", path="specs/spec.md")
    if with_plan:
        link_artifact(repo, "WI-WORK-0001", artifact_type="PLAN", path="specs/plan.md")
    _git_init(repo)
    return repo


def _pr(name: str, head: str) -> dict:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    payload["headRefOid"] = head
    return payload


def _patch_pr(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr("ges.governance.gates.view_pr", lambda _repo, _n: payload)
    monkeypatch.setattr("ges.governance.evidence.view_pr", lambda _repo, _n: payload)


# @lat: [[governance-tests#Governance init#Init creates policy and works]]
def test_init_creates_policy_and_works(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_governance(repo)
    policy = load_policy(repo)
    assert policy["id"] == "default-v1"
    assert (repo / ".ges" / "governance" / "works").is_dir()


# @lat: [[governance-tests#Governance init#Init is idempotent]]
def test_init_is_idempotent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_governance(repo)
    before = consumer_tree(repo)
    with pytest.raises(GesError) as captured:
        init_governance(repo)
    assert captured.value.code == GOVERNANCE_ALREADY_INITIALIZED
    assert consumer_tree(repo) == before


# @lat: [[governance-tests#Work registry#Create valid work]]
def test_create_valid_work(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_governance(repo)
    payload = create_work(repo, work_id="WI-WORK-0001", title="demo", owner="team", risk="LOW", host="cursor")
    assert payload["kind"] == "FEATURE"
    assert payload["status"] == "OPEN"


# @lat: [[governance-tests#Work registry#Duplicate work is rejected]]
def test_duplicate_work_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_governance(repo)
    create_work(repo, work_id="WI-WORK-0001", title="demo", owner="team", risk="LOW", host="cursor")
    original = work_path(repo, "WI-WORK-0001").read_bytes()
    with pytest.raises(GesError) as captured:
        create_work(repo, work_id="WI-WORK-0001", title="other", owner="team", risk="LOW", host="cursor")
    assert captured.value.code == WORK_ALREADY_EXISTS
    assert work_path(repo, "WI-WORK-0001").read_bytes() == original


# @lat: [[governance-tests#Work registry#Closed work cannot update]]
def test_closed_work_cannot_update(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_governance(repo)
    create_work(repo, work_id="WI-WORK-0001", title="demo", owner="team", risk="LOW", host="cursor")
    close_work(repo, "WI-WORK-0001")
    with pytest.raises(GesError) as captured:
        update_work(repo, "WI-WORK-0001", title="nope")
    assert captured.value.code == WORK_CLOSED_IMMUTABLE


# @lat: [[governance-tests#Work registry#Closed cannot reopen]]
def test_closed_cannot_reopen(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_governance(repo)
    create_work(repo, work_id="WI-WORK-0001", title="demo", owner="team", risk="LOW", host="cursor")
    close_work(repo, "WI-WORK-0001")
    with pytest.raises(GesError) as captured:
        close_work(repo, "WI-WORK-0001")
    assert captured.value.code == WORK_STATE_TRANSITION_INVALID


# @lat: [[governance-tests#Artifacts#Link stores exact digest]]
def test_link_stores_exact_digest(tmp_path):
    repo = _gov_repo(tmp_path)
    path = repo / "specs" / "spec.md"
    work = load_work(repo, "WI-WORK-0001")
    spec = next(item for item in work["artifacts"] if item["type"] == "SPEC")
    assert spec["digest"] == digest_file(path)


# @lat: [[governance-tests#Artifacts#Drift fails intake]]
def test_drift_fails_intake(tmp_path):
    repo = _gov_repo(tmp_path)
    (repo / "specs" / "spec.md").write_bytes(b"spec-bytes-changed")
    result = evaluate_intake(repo, "WI-WORK-0001")
    assert result["status"] == "FAIL"
    assert any(item["code"] == ARTIFACT_STALE for item in result["reasons"])


# @lat: [[governance-tests#Artifacts#Path escape rejected]]
def test_path_escape_rejected(tmp_path):
    repo = _gov_repo(tmp_path)
    before = work_path(repo, "WI-WORK-0001").read_bytes()
    with pytest.raises(GesError) as captured:
        normalize_pointer("../secret")
    assert captured.value.code == ARTIFACT_PATH_INVALID
    assert work_path(repo, "WI-WORK-0001").read_bytes() == before


# @lat: [[governance-tests#Policy#Unknown field rejected]]
def test_unknown_field_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_governance(repo)
    policy = load_policy(repo)
    policy["plugin"] = "eval"
    with pytest.raises(GesError) as captured:
        write_policy(repo, policy)
    assert captured.value.code == POLICY_SCHEMA_INVALID


# @lat: [[governance-tests#Policy#HIGH blocks merge]]
def test_high_blocks_merge(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path, risk="HIGH")
    _patch_pr(monkeypatch, _pr("pr_approved_success.json", local_head(repo)))
    result = evaluate_merge(repo, "WI-WORK-0001", 12)
    assert result["status"] == "BLOCKED"
    assert any(item["code"] == APPROVAL_REQUIRED_UNSUPPORTED for item in result["reasons"])


# @lat: [[governance-tests#Policy#LOW may reach merge ready]]
def test_low_may_reach_merge_ready(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path, risk="LOW")
    _patch_pr(monkeypatch, _pr("pr_approved_success.json", local_head(repo)))
    result = evaluate_merge(repo, "WI-WORK-0001", 12)
    assert result["verdict"] == "MERGE_READY"
    assert result["status"] == "PASS"


# @lat: [[governance-tests#Evidence#Success maps pass]]
def test_success_maps_pass(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path)
    _patch_pr(monkeypatch, _pr("pr_approved_success.json", local_head(repo)))
    snapshot = collect_evidence(repo, "WI-WORK-0001", 12)
    assert snapshot["checks"][0]["status"] == "PASS"
    assert map_check_status("SUCCESS") == "PASS"


# @lat: [[governance-tests#Evidence#Manual add unsupported]]
def test_manual_add_unsupported():
    with pytest.raises(GesError) as captured:
        run_add(Namespace())
    assert captured.value.code == UNSUPPORTED_OPERATION


# @lat: [[governance-tests#Trace#Complete graph]]
def test_complete_graph(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path)
    _patch_pr(monkeypatch, _pr("pr_approved_success.json", local_head(repo)))
    graph = build_trace(repo, "WI-WORK-0001", 12)
    kinds = {node["kind"] for node in graph["nodes"]}
    assert kinds >= {"WORK", "SPEC", "PLAN", "PR", "COMMIT", "CI_CHECK", "REVIEW_DECISION"}
    assert {edge["type"] for edge in graph["edges"]} >= set(REQUIRED_EDGES)


# @lat: [[governance-tests#Trace#Missing review visible]]
def test_missing_review_visible(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path)
    _patch_pr(monkeypatch, _pr("pr_review_missing.json", local_head(repo)))
    graph = build_trace(repo, "WI-WORK-0001", 12)
    review = next(node for node in graph["nodes"] if node["kind"] == "REVIEW_DECISION")
    assert review["status"] == "MISSING"


# @lat: [[governance-tests#Gates#Intake work ready]]
def test_intake_work_ready(tmp_path):
    repo = _gov_repo(tmp_path)
    result = evaluate_intake(repo, "WI-WORK-0001")
    assert result["verdict"] == "WORK_READY"
    assert result["status"] == "PASS"


# @lat: [[governance-tests#Gates#Intake missing plan]]
def test_intake_missing_plan(tmp_path):
    repo = _gov_repo(tmp_path, with_plan=False)
    result = evaluate_intake(repo, "WI-WORK-0001")
    assert result["status"] == "FAIL"
    assert any(item["code"] == "REQUIRED_ARTIFACT_MISSING" for item in result["reasons"])


# @lat: [[governance-tests#Gates#Review missing]]
def test_review_missing(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path)
    _patch_pr(monkeypatch, _pr("pr_review_missing.json", local_head(repo)))
    result = evaluate_merge(repo, "WI-WORK-0001", 12)
    assert result["status"] == "FAIL"
    assert any(item["code"] == REVIEW_REQUIRED for item in result["reasons"])


# @lat: [[governance-tests#Gates#Dirty tree]]
def test_dirty_tree(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path)
    (repo / "tracked.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True)
    _patch_pr(monkeypatch, _pr("pr_approved_success.json", local_head(repo)))
    result = evaluate_merge(repo, "WI-WORK-0001", 12)
    assert any(item["code"] == WORKTREE_DIRTY for item in result["reasons"])


# @lat: [[governance-tests#Gates#Pending check]]
def test_pending_check(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path)
    _patch_pr(monkeypatch, _pr("pr_pending.json", local_head(repo)))
    result = evaluate_merge(repo, "WI-WORK-0001", 12)
    assert result["status"] == "FAIL"
    assert any(item["code"] == CI_CHECK_PENDING for item in result["reasons"])


# @lat: [[governance-tests#Gates#Explain deterministic]]
def test_pr_head_race_blocks_merge(tmp_path, monkeypatch):
    repo = _gov_repo(tmp_path)
    first = _pr("pr_approved_success.json", local_head(repo))
    second = dict(first)
    second["headRefOid"] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    calls = {"n": 0}

    def flip(_repo, _n):
        calls["n"] += 1
        return first if calls["n"] == 1 else second

    monkeypatch.setattr("ges.governance.gates.view_pr", flip)
    monkeypatch.setattr("ges.governance.evidence.view_pr", lambda _repo, _n: first)
    result = evaluate_merge(repo, "WI-WORK-0001", 12)
    assert result["status"] == "BLOCKED"
    assert any(item["code"] == PR_HEAD_CHANGED_DURING_EVALUATION for item in result["reasons"])


def test_explain_deterministic(tmp_path):
    repo = _gov_repo(tmp_path, with_plan=False)
    first = explain_gate(repo, "WI-WORK-0001", gate="intake")
    second = explain_gate(repo, "WI-WORK-0001", gate="intake")
    assert [item["code"] for item in first["reasons"]] == [item["code"] for item in second["reasons"]]


# @lat: [[governance-tests#Read-only#Intake does not write]]
def test_intake_does_not_write(tmp_path):
    repo = _gov_repo(tmp_path)
    before = consumer_tree(repo)
    evaluate_intake(repo, "WI-WORK-0001")
    assert consumer_tree(repo) == before


# @lat: [[governance-tests#Composer isolation#Remove preserves governance]]
def test_remove_preserves_governance(brownfield, offline_cache):
    apply_recommended(brownfield)
    init_governance(brownfield)
    create_work(brownfield, work_id="WI-WORK-0001", title="demo", owner="team", risk="LOW", host="cursor")
    run_remove(brownfield)
    assert work_path(brownfield, "WI-WORK-0001").is_file()


# @lat: [[governance-tests#Composer isolation#Snapshot excludes governance]]
def test_snapshot_excludes_governance(brownfield, offline_cache):
    apply_recommended(brownfield)
    init_governance(brownfield)
    create_work(brownfield, work_id="WI-WORK-0001", title="demo", owner="team", risk="LOW", host="cursor")
    snap = snapshot_managed_scope(brownfield, {}, InstallPlan())
    assert not any(rel.startswith(".ges/governance/") for rel in snap)


# @lat: [[governance-tests#External evidence#Manifest binds candidate]]
def test_manifest_binds_candidate(tmp_path):
    out = write_backplane_evidence(
        artifact_dir=tmp_path,
        candidate_sha="a" * 40,
        consumer_repo="loudon84/copilot-work",
        pr_number=12,
        pr_head="b" * 40,
        work_id="WI-WORK-0001",
        policy_digest="c" * 64,
        acceptances=[{"acceptance_id": "A-A2-GOV-001", "status": "PASS", "command": "init", "exit_code": 0, "oracle": {}}],
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ges"]["commit_sha"] == "a" * 40
    assert payload["schema"] == "ges.backplane-evidence.v1"


def test_cli_governance_init(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["governance", "init", str(repo)]) == 0
    assert main(["governance", "init", str(repo)]) == 0


def test_golden_runner_blocks_without_env(tmp_path, monkeypatch):
    from ges.acceptance.run_golden_backplane import main as golden_main

    monkeypatch.delenv("GES_ALPHA2_GOLDEN_PR", raising=False)
    monkeypatch.delenv("GES_ALPHA2_GOLDEN_WORK_ID", raising=False)
    monkeypatch.setenv("GES_RELEASE_EVIDENCE_DIR", str(tmp_path))
    assert golden_main([]) == 3
    assert (tmp_path / "backplane-evidence.json").is_file()


def test_cli_work_and_intake(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "specs").mkdir()
    (repo / "specs" / "spec.md").write_text("s", encoding="utf-8")
    (repo / "specs" / "plan.md").write_text("p", encoding="utf-8")
    assert main(["governance", "init", str(repo)]) == 0
    assert main(["work", "create", str(repo), "--id", "WI-WORK-0001", "--title", "t", "--owner", "o", "--risk", "LOW", "--host", "cursor"]) == 0
    assert main(["artifact", "link", str(repo), "WI-WORK-0001", "--type", "SPEC", "--path", "specs/spec.md"]) == 0
    assert main(["artifact", "link", str(repo), "WI-WORK-0001", "--type", "PLAN", "--path", "specs/plan.md"]) == 0
    assert main(["gate", "intake", str(repo), "WI-WORK-0001"]) == 0
