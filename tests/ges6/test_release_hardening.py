from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ges.acceptance.closure_evidence import REQUIRED_ACCEPTANCES, record, write_closure_evidence
from ges.acceptance.release_evidence import (
    artifact_inside_candidate,
    release_gate_from_parts,
    require_artifact,
    resolve_artifact_dir,
    verify_artifact_digest,
    write_release_manifest,
)
from ges.acceptance.release_gate import assert_current_status_current, missing_pre_tag_status, verify_tag_target
from ges.acceptance.speckit_smoke import FORBIDDEN_REPAIR_PROMPT, feature_state_error, smoke_invocation_record, smoke_prompt
from ges.cursor_probe import (
    PROBE_ID,
    REQUIRED_SKILLS,
    expected_skill_description,
    native_discovery,
    native_probe_prompt,
    prompt_leaks_skill_paths,
)
from ges.errors import CURSOR_SKILL_METADATA_MISMATCH, EVIDENCE_ARTIFACT_MISSING, RELEASE_DOCUMENTATION_STALE, RELEASE_TAG_COMMIT_MISMATCH, GesError
from ges.io import sha256_file
from ges.reconciler.state import validate_payload


def _write_skills(repo: Path, *, description: str = "declared-description") -> None:
    mapping = {
        "grill-with-docs": Path(".agents/skills/grill-with-docs/SKILL.md"),
        "speckit-specify": Path(".cursor/skills/speckit-specify/SKILL.md"),
        "writing-plans": Path(".agents/skills/writing-plans/SKILL.md"),
    }
    for name, rel in mapping.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: {description}\n---\nbody\n", encoding="utf-8")


def _closure_kwargs(tmp_path: Path) -> dict:
    return {
        "run_id": "rh-test",
        "started_at": datetime.now(timezone.utc),
        "ges_head": "a" * 40,
        "ges_branch": "feat/ges-v6.0",
        "consumer": {
            "source_path": r"E:\git\smc-copilot-desktop",
            "repo_identity": "loudon84/smc-copilot-desktop",
            "source_branch": "main",
            "commit_sha": "b" * 40,
            "source_worktree_dirty": False,
            "source_worktree_status_digest": "c" * 64,
            "test_worktree_path": str(tmp_path),
            "test_worktree_clean_at_start": True,
        },
        "spec_kit": None,
        "cursor": {
            "executable": "agent",
            "version": "0",
            "structural_discovery": "PASS",
            "runtime_discovery": "PASS",
        },
        "acceptances": [record(item[0], "PASS", "synthetic", 0, "PASS", "PASS") for item in REQUIRED_ACCEPTANCES],
    }


# @lat: [[release-hardening-tests#External evidence#Candidate SHA unchanged after evidence write]]
def test_candidate_sha_unchanged_after_evidence_write(tmp_path):
    candidate = tmp_path / "candidate"
    artifact = tmp_path / "artifact"
    candidate.mkdir()
    out = write_closure_evidence(root=candidate, artifact_dir=artifact, **_closure_kwargs(tmp_path))
    assert out.resolve().is_relative_to(artifact.resolve())
    assert not (candidate / "audit").exists()


# @lat: [[release-hardening-tests#External evidence#Evidence path is outside candidate]]
def test_evidence_path_is_outside_candidate(tmp_path, monkeypatch):
    candidate = tmp_path / "repo"
    candidate.mkdir()
    monkeypatch.delenv("GES_RELEASE_EVIDENCE_DIR", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    artifact = resolve_artifact_dir(tmp_path / "release-evidence")
    assert not artifact_inside_candidate(artifact, candidate)


# @lat: [[release-hardening-tests#External evidence#Manifest schema is valid]]
def test_manifest_schema_is_valid(tmp_path):
    digest = "d" * 64
    out = write_release_manifest(
        artifact_dir=tmp_path,
        candidate_sha="a" * 40,
        branch="feat/ges-v6.0",
        consumer_sha="b" * 40,
        synthetic={"status": "PASS", "workflow_run_id": "1", "artifact_name": "syn", "sha256": digest},
        golden={"status": "PASS", "workflow_run_id": "2", "artifact_name": "gold", "evidence_sha256": digest},
        documentation_status="PASS",
        release_gate="PASS",
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    validate_payload("ges.release-evidence-manifest.v1.json", payload)
    extra = dict(payload)
    extra["unexpected"] = True
    with pytest.raises(GesError):
        validate_payload("ges.release-evidence-manifest.v1.json", extra)


# @lat: [[release-hardening-tests#External evidence#Artifact digest matches manifest]]
def test_artifact_digest_matches_manifest(tmp_path):
    path = tmp_path / "golden" / "evidence.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"ok":true}\n', encoding="utf-8")
    digest = sha256_file(path)
    assert verify_artifact_digest(path, digest) == digest
    with pytest.raises(GesError) as captured:
        verify_artifact_digest(path, "0" * 64)
    assert captured.value.code == EVIDENCE_ARTIFACT_MISSING
    with pytest.raises(GesError) as missing:
        require_artifact(tmp_path / "absent.json")
    assert missing.value.code == EVIDENCE_ARTIFACT_MISSING


# @lat: [[release-hardening-tests#External evidence#Synthetic failure blocks release]]
def test_synthetic_failure_blocks_release():
    assert release_gate_from_parts(synthetic="FAIL", golden="PASS", documentation="PASS") != "PASS"
    assert release_gate_from_parts(synthetic="PASS", golden="PASS", documentation="PASS") == "PASS"
    assert release_gate_from_parts(synthetic="PASS", golden="PASS", documentation="PASS", candidate_moved=True) == "STALE"
    assert release_gate_from_parts(synthetic="PASS", golden="PASS", documentation="PASS", artifact_missing=True) == "BLOCKED"


# @lat: [[release-hardening-tests#Strict smoke#Missing feature state fails]]
def test_missing_feature_state_fails(tmp_path):
    assert feature_state_error(tmp_path, "run1") == "SPEC_KIT_SMOKE_FEATURE_STATE_MISSING"


# @lat: [[release-hardening-tests#Strict smoke#Invalid feature directory fails]]
def test_invalid_feature_directory_fails(tmp_path):
    path = tmp_path / ".specify" / "feature.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"feature_directory":"specs/_ges-smoke/other"}\n', encoding="utf-8")
    assert feature_state_error(tmp_path, "run1") == "SPEC_KIT_SMOKE_FEATURE_STATE_INVALID"


# @lat: [[release-hardening-tests#Strict smoke#Repair prompt is absent]]
def test_repair_prompt_is_absent():
    root = Path(__file__).resolve().parents[2] / "ges"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN_REPAIR_PROMPT not in text:
            continue
        assert path.name == "speckit_smoke.py"
        assert "FORBIDDEN_REPAIR_PROMPT" in text
    assert FORBIDDEN_REPAIR_PROMPT not in smoke_prompt("20260916T000000Z")


# @lat: [[release-hardening-tests#Strict smoke#Repair invocation count is zero]]
def test_repair_invocation_count_is_zero():
    record = smoke_invocation_record()
    assert record["primary_invocation_count"] == 1
    assert record["repair_invocation_count"] == 0


# @lat: [[release-hardening-tests#Native Cursor discovery#Probe prompt has no skill paths]]
def test_probe_prompt_has_no_skill_paths():
    for name in REQUIRED_SKILLS:
        prompt = native_probe_prompt(name)
        assert not prompt_leaks_skill_paths(prompt)
        assert PROBE_ID in prompt


# @lat: [[release-hardening-tests#Native Cursor discovery#Expected description is not in the prompt]]
def test_expected_description_is_not_in_the_prompt(tmp_path):
    _write_skills(tmp_path, description="unique-frontmatter-description")
    expected = expected_skill_description(tmp_path, "speckit-specify")
    assert expected
    assert expected not in native_probe_prompt("speckit-specify")


# @lat: [[release-hardening-tests#Native Cursor discovery#Metadata mismatch raises]]
def test_metadata_mismatch_raises(tmp_path, monkeypatch):
    _write_skills(tmp_path, description="declared-description")

    def fake_run(argv, *, cwd, timeout=None):
        prompt = argv[-1]
        skill = next(name for name in REQUIRED_SKILLS if f'requested_skill must be "{name}"' in prompt)
        payload = {
            "probe": PROBE_ID,
            "requested_skill": skill,
            "available": True,
            "recognized_name": skill,
            "description": "wrong-description",
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr("ges.cursor_probe.resolve_cursor_cli", lambda: "agent")
    monkeypatch.setattr("ges.cursor_probe._cli_version", lambda _exe: "0")
    monkeypatch.setattr("ges.cursor_probe._supports_ask", lambda _exe: False)
    monkeypatch.setattr("ges.cursor_probe._run_cli", fake_run)
    with pytest.raises(GesError) as captured:
        native_discovery(tmp_path)
    assert captured.value.code == CURSOR_SKILL_METADATA_MISMATCH


# @lat: [[release-hardening-tests#Native Cursor discovery#Path leak is detected]]
def test_path_leak_is_detected():
    assert prompt_leaks_skill_paths("read .cursor/skills/speckit-specify/SKILL.md")
    assert not prompt_leaks_skill_paths(native_probe_prompt("speckit-specify"))


# @lat: [[release-hardening-tests#Documentation truth#Stale Golden BLOCKED phrases fail]]
def test_stale_golden_blocked_phrases_fail(tmp_path):
    page = tmp_path / "lat.md" / "ges6" / "ges6.md"
    page.parent.mkdir(parents=True)
    page.write_text("Golden Consumer: BLOCKED\n", encoding="utf-8")
    with pytest.raises(GesError) as captured:
        assert_current_status_current(tmp_path)
    assert captured.value.code == RELEASE_DOCUMENTATION_STALE


# @lat: [[release-hardening-tests#Documentation truth#Current status required phrases exist]]
def test_current_status_required_phrases_exist():
    root = Path(__file__).resolve().parents[2]
    assert missing_pre_tag_status(root) == []
    assert_current_status_current(root)


# @lat: [[release-hardening-tests#Tag and CI contracts#Tag mismatch raises]]
def test_tag_mismatch_raises(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("tag\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "ges@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "GES"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "tag", "ges-v6.0.0-alpha.1"], cwd=repo, check=True, capture_output=True)
    with pytest.raises(GesError) as captured:
        verify_tag_target(repo, "0" * 40)
    assert captured.value.code == RELEASE_TAG_COMMIT_MISMATCH


# @lat: [[release-hardening-tests#Tag and CI contracts#Workflows pin candidate SHA]]
def test_workflows_pin_candidate_sha():
    root = Path(__file__).resolve().parents[2]
    synthetic = (root / ".github" / "workflows" / "ges-alpha1-ci.yml").read_text(encoding="utf-8")
    golden = (root / ".github" / "workflows" / "ges-alpha1-golden.yml").read_text(encoding="utf-8")
    assert "python -m pytest tests/ges6" in synthetic
    assert "GES_SOURCE_OFFLINE" in synthetic
    assert "cursor" not in synthetic.lower() or "GES_CURSOR" not in synthetic
    assert "workflow_dispatch" in golden
    assert "candidate_sha" in golden
    assert "ref: ${{ inputs.candidate_sha }}" in golden
    assert "Never commit evidence" in golden
    assert "git diff --exit-code" in golden
