from __future__ import annotations

import json
from pathlib import Path

import pytest

from ges.acceptance.closure_evidence import REQUIRED_ACCEPTANCES, record, write_closure_evidence
from ges.acceptance.golden_worktree import (
    create_detached_worktree,
    remove_worktree,
    resolve_consumer_head,
    source_dirty_status,
    workspace_identity,
    worktree_clean,
)
from ges.acceptance.harness import apply_recommended
from ges.compose import compose
from ges.cursor_probe import PROBE_ID, _parse_probe_json, structural_discovery
from ges.errors import (
    MANAGED_CONTENT_MODIFIED,
    SPEC_KIT_CLI_IDENTITY_MISMATCH,
    SPEC_KIT_OFFICIAL_RENDER_FAILED,
    GesError,
)
from ges.io import sha256_bytes, write_bytes, write_json
from ges.reconciler.apply import consumer_tree
from ges.reconciler.state import read_receipt
from ges.source_adapters.speckit_render import (
    REQUIRED_CLI_VERSION,
    collect_staging_files,
    last_render_report,
    official_stage,
    offline_staging_root,
    skill_rel,
    verify_specify_cli,
)


# @lat: [[closure-tests#TEST-A-SK-001]]
def test_a_sk_001_official_identity(brownfield, offline_cache):
    version = verify_specify_cli()
    assert version == REQUIRED_CLI_VERSION
    apply_recommended(brownfield)
    for command in ("constitution", "specify", "clarify", "plan"):
        assert (brownfield / skill_rel(command)).is_file()
    assert last_render_report().specify_cli_version == REQUIRED_CLI_VERSION


# @lat: [[closure-tests#TEST-A-SK-002]]
def test_a_sk_002_hash_parity(brownfield, offline_cache):
    apply_recommended(brownfield)
    stage = offline_staging_root()
    assert stage is not None
    official = collect_staging_files(stage)
    for command in ("constitution", "specify", "clarify", "plan"):
        rel = skill_rel(command)
        assert sha256_bytes((brownfield / rel).read_bytes()) == sha256_bytes(official[rel])
    assert last_render_report().mismatch_count == 0


# @lat: [[closure-tests#TEST-A-SK-003]]
def test_a_sk_003_staging_does_not_mutate_consumer(brownfield, offline_cache):
    before = consumer_tree(brownfield)
    official_stage()
    assert consumer_tree(brownfield) == before


# @lat: [[closure-tests#TEST-A-SKM-001]]
def test_a_skm_001_unmodified_stub_removed(brownfield, offline_cache):
    apply_recommended(brownfield)
    stub = brownfield / ".specify" / ".ges" / "runtime" / "scripts" / "specify.py"
    write_bytes(stub, b"old-stub\n")
    receipt = read_receipt(brownfield)
    receipt["managed_artifacts"].append(
        {
            "path": stub.relative_to(brownfield).as_posix(),
            "ownership_type": "FILE",
            "selector": None,
            "last_applied_hash": sha256_bytes(b"old-stub\n"),
            "generated_hash": sha256_bytes(b"old-stub\n"),
            "producer": "ges",
            "capability_ids": ["speckit.specify"],
        }
    )
    write_json(brownfield / ".ges" / "install-receipt.json", receipt)
    apply_recommended(brownfield)
    assert not stub.is_file()
    assert (brownfield / skill_rel("specify")).is_file()


# @lat: [[closure-tests#TEST-A-SKM-002]]
def test_a_skm_002_drifted_stub_blocks(brownfield, offline_cache):
    apply_recommended(brownfield)
    stub = brownfield / ".specify" / ".ges" / "runtime" / "scripts" / "specify.py"
    write_bytes(stub, b"old-stub\n")
    receipt = read_receipt(brownfield)
    receipt["managed_artifacts"].append(
        {
            "path": stub.relative_to(brownfield).as_posix(),
            "ownership_type": "FILE",
            "selector": None,
            "last_applied_hash": sha256_bytes(b"old-stub\n"),
            "generated_hash": sha256_bytes(b"old-stub\n"),
            "producer": "ges",
            "capability_ids": ["speckit.specify"],
        }
    )
    write_json(brownfield / ".ges" / "install-receipt.json", receipt)
    stub.write_bytes(b"drifted\n")
    before = consumer_tree(brownfield)
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == MANAGED_CONTENT_MODIFIED
    assert consumer_tree(brownfield) == before


def test_cursor_probe_unwraps_cli_result_envelope():
    inner = {"probe": PROBE_ID, "skills": {"grill-with-docs": True, "speckit-specify": True, "writing-plans": True}}
    stdout = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(inner)})
    assert _parse_probe_json(stdout)["probe"] == PROBE_ID


# @lat: [[closure-tests#TEST-A-CURSOR-STRUCT-001]]
def test_a_cursor_struct_001(brownfield, offline_cache):
    apply_recommended(brownfield)
    result = structural_discovery(brownfield)
    assert result["status"] == "PASS"
    assert result["skills"]["speckit-specify"]["name"] == "speckit-specify"


def _init_git(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "ges@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "GES"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)


# @lat: [[closure-tests#TEST-A-GOLDEN-001]]
def test_a_golden_001_head_resolves(tmp_path):
    repo = tmp_path / "golden"
    repo.mkdir()
    (repo / "README.md").write_text("golden\n", encoding="utf-8")
    _init_git(repo)
    head = resolve_consumer_head(repo)
    assert len(head) == 40


# @lat: [[closure-tests#TEST-A-GOLDEN-002]]
def test_a_golden_002_dirty_source_continues(tmp_path):
    repo = tmp_path / "golden"
    repo.mkdir()
    (repo / "README.md").write_text("golden\n", encoding="utf-8")
    _init_git(repo)
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    dirty, _, _ = source_dirty_status(repo)
    assert dirty
    head = resolve_consumer_head(repo)
    worktree = create_detached_worktree(repo, head)
    try:
        assert worktree_clean(worktree)
        assert not (worktree / "dirty.txt").exists()
    finally:
        remove_worktree(repo, worktree)


# @lat: [[closure-tests#TEST-A-GOLDEN-005]]
def test_a_golden_005_source_preserved(tmp_path):
    repo = tmp_path / "golden"
    repo.mkdir()
    (repo / "README.md").write_text("golden\n", encoding="utf-8")
    _init_git(repo)
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    before = workspace_identity(repo)
    head = resolve_consumer_head(repo)
    worktree = create_detached_worktree(repo, head)
    remove_worktree(repo, worktree)
    assert workspace_identity(repo) == before


# @lat: [[closure-tests#TEST-A-EVID-001]]
def test_a_evid_001_commit_binding(tmp_path):
    payload_dir = tmp_path / "evid"
    acceptances = [
        record(item[0], "PASS", "synthetic", 0, "PASS", "PASS") for item in REQUIRED_ACCEPTANCES
    ]
    out = write_closure_evidence(
        run_id="test-bind",
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ges_head="a" * 40,
        ges_branch="feat/ges-v6.0",
        consumer={
            "source_path": r"E:\git\smc-copilot-desktop",
            "repo_identity": "loudon84/smc-copilot-desktop",
            "source_branch": "main",
            "commit_sha": "b" * 40,
            "source_worktree_dirty": False,
            "source_worktree_status_digest": "c" * 64,
            "test_worktree_path": str(tmp_path),
            "test_worktree_clean_at_start": True,
        },
        spec_kit=None,
        cursor={
            "executable": "agent",
            "version": "0",
            "structural_discovery": "PASS",
            "runtime_discovery": "BLOCKED",
        },
        acceptances=acceptances,
        root=payload_dir,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ges"]["commit_sha"] == "a" * 40
    assert payload["golden_consumer"]["commit_sha"] == "b" * 40


# @lat: [[closure-tests#TEST-A-EVID-002]]
def test_a_evid_002_per_ac_fields(tmp_path):
    acceptances = [
        record(item[0], "PASS", "synthetic", 0, "PASS", "PASS") for item in REQUIRED_ACCEPTANCES
    ]
    out = write_closure_evidence(
        run_id="test-fields",
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ges_head="a" * 40,
        ges_branch="feat/ges-v6.0",
        consumer={
            "source_path": r"E:\git\smc-copilot-desktop",
            "repo_identity": "loudon84/smc-copilot-desktop",
            "source_branch": "main",
            "commit_sha": "b" * 40,
            "source_worktree_dirty": True,
            "source_worktree_status_digest": "c" * 64,
            "test_worktree_path": str(tmp_path),
            "test_worktree_clean_at_start": True,
        },
        spec_kit=None,
        cursor={
            "executable": "agent",
            "version": "0",
            "structural_discovery": "PASS",
            "runtime_discovery": "BLOCKED",
        },
        acceptances=acceptances,
        root=tmp_path,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    required = {"requirement_ids", "test_ids", "command", "exit_code", "oracle", "evidence_files"}
    for item in payload["acceptances"]:
        assert required <= set(item)
        assert "expected" in item["oracle"] and "actual" in item["oracle"]


# @lat: [[closure-tests#TEST-NEG-SK-001]]
def test_neg_sk_001_traversal_rejected(tmp_path, brownfield, offline_cache):
    from ges.source_adapters.speckit_render import _reject_traversal

    before = consumer_tree(brownfield)
    with pytest.raises(GesError) as captured:
        _reject_traversal("../secret")
    assert captured.value.code == SPEC_KIT_OFFICIAL_RENDER_FAILED
    assert consumer_tree(brownfield) == before


# @lat: [[closure-tests#TEST-NEG-SK-002]]
def test_neg_sk_002_version_mismatch(tmp_path, monkeypatch):
    fixture = tmp_path / "bad-cli"
    fixture.mkdir()
    (fixture / "specify-cli-version.txt").write_text("9.9.9\n", encoding="utf-8")
    monkeypatch.setenv("GES_SPECKIT_STAGING_FIXTURE", str(fixture))
    with pytest.raises(GesError) as captured:
        verify_specify_cli()
    assert captured.value.code == SPEC_KIT_CLI_IDENTITY_MISMATCH
