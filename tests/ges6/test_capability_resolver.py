from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path

from ges.acceptance.harness import apply_recommended
from ges.acceptance.run_golden_capability import main as golden_capability_main
from ges.catalog.providers import RTK_ID, load_providers
from ges.check import run_check
from ges.cli import init as init_cli
from ges.cli.render import render_capability_plan
from ges.compose import compose
from ges.doctor import BLOCKED, run_doctor
from ges.errors import GES_CHECK_PASS
from ges.paths import SCHEMA_DIR
from ges.providers.resolve import build_capability_plan
from ges.providers.rtk import probe_rtk
from ges.reconciler.state import read_lock, read_project, read_receipt


BROWNFIELD = {
    "repository_lifecycle": "brownfield",
    "layout": "single",
    "kind": "brownfield",
}
MONOREPO = {
    "repository_lifecycle": "greenfield",
    "layout": "monorepo",
    "kind": "greenfield-monorepo",
}
GREENFIELD_SINGLE = {
    "repository_lifecycle": "greenfield",
    "layout": "single",
    "kind": "greenfield",
}


# @lat: [[capability-resolver-tests#Plan#Same facts same plan]]
def test_same_facts_same_plan():
    first = build_capability_plan(BROWNFIELD, ["speckit.specify"])
    second = build_capability_plan(BROWNFIELD, ["speckit.specify"])
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["required"] == ["speckit"]


# @lat: [[capability-resolver-tests#Plan#Zero LLM tokens]]
def test_zero_llm_tokens():
    plan = build_capability_plan(BROWNFIELD)
    assert plan["llm_token_usage"] == 0


# @lat: [[capability-resolver-tests#Plan#Brownfield recommends RTK]]
def test_brownfield_and_monorepo_recommend_rtk():
    brownfield = build_capability_plan(BROWNFIELD)
    monorepo = build_capability_plan(MONOREPO)
    assert brownfield["recommended"] == [RTK_ID]
    assert brownfield["reasons"][RTK_ID] == "brownfield"
    assert monorepo["recommended"] == [RTK_ID]
    assert monorepo["reasons"][RTK_ID] == "greenfield-monorepo"
    assert RTK_ID not in brownfield["optional"]
    assert load_providers()[RTK_ID].incompatible == ()


# @lat: [[capability-resolver-tests#Plan#Greenfield single is optional]]
def test_greenfield_single_is_optional():
    plan = build_capability_plan(GREENFIELD_SINGLE)
    assert plan["optional"] == [RTK_ID]
    assert RTK_ID not in plan["recommended"]
    assert RTK_ID not in plan["reasons"]


# @lat: [[capability-resolver-tests#Plan#Plan does not mutate requested]]
def test_plan_does_not_mutate_requested(brownfield, offline_cache):
    apply_recommended(brownfield)
    before_lock = read_lock(brownfield)
    before_project = read_project(brownfield)
    before_receipt = read_receipt(brownfield)
    requested = list((before_lock or {}).get("requested") or [])
    build_capability_plan(BROWNFIELD, requested)
    compose(brownfield)
    assert read_lock(brownfield) == before_lock
    assert read_project(brownfield) == before_project
    assert read_receipt(brownfield) == before_receipt
    assert (read_lock(brownfield) or {}).get("requested") == requested


# @lat: [[capability-resolver-tests#Probe#Missing rtk]]
def test_missing_rtk(monkeypatch):
    monkeypatch.setattr("ges.providers.rtk.shutil.which", lambda _name: None)
    status = probe_rtk()
    assert status["status"] == "missing"
    assert status["capability_id"] == RTK_ID
    assert all(row["status"] == "FAIL" for row in status["health_checks"])


# @lat: [[capability-resolver-tests#Probe#Invalid version]]
def test_invalid_version(monkeypatch):
    monkeypatch.setattr("ges.providers.rtk.shutil.which", lambda _name: r"C:\fake\rtk.exe")
    monkeypatch.setattr(
        "ges.providers.rtk.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["rtk", "--version"],
            returncode=1,
            stdout="",
            stderr="unparseable",
        ),
    )
    status = probe_rtk()
    assert status["status"] == "NOT_READY"
    assert status["health_checks"][0]["status"] == "PASS"
    assert status["health_checks"][1]["status"] == "FAIL"


# @lat: [[capability-resolver-tests#Probe#Ready version]]
def test_ready_version(monkeypatch):
    monkeypatch.setattr("ges.providers.rtk.shutil.which", lambda _name: r"C:\fake\rtk.exe")
    monkeypatch.setattr(
        "ges.providers.rtk.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["rtk", "--version"],
            returncode=0,
            stdout="rtk 1.2.3\n",
            stderr="",
        ),
    )
    status = probe_rtk()
    assert status["status"] == "READY"
    assert status["version"]
    assert all(row["status"] == "PASS" for row in status["health_checks"])
    names = [row["name"] for row in status["health_checks"]]
    assert names == list(load_providers()[RTK_ID].health_checks)
    assert "integration" not in names


def test_ready_does_not_fabricate_integration(monkeypatch):
    monkeypatch.setattr("ges.providers.rtk.shutil.which", lambda _name: r"C:\fake\rtk.exe")
    monkeypatch.setattr(
        "ges.providers.rtk.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["rtk", "--version"],
            returncode=0,
            stdout="rtk 1.2.3\n",
            stderr="",
        ),
    )
    status = probe_rtk()
    assert not any(row["name"] == "integration" for row in status["health_checks"])
    assert list(load_providers()[RTK_ID].health_checks) == ["binary", "version"]


# @lat: [[capability-resolver-tests#Doctor#Doctor lists capabilities]]
def test_doctor_lists_capabilities(brownfield, offline_cache, monkeypatch):
    monkeypatch.setattr("ges.providers.rtk.shutil.which", lambda _name: None)
    apply_recommended(brownfield)
    payload = run_doctor(brownfield)
    ids = [row["capability_id"] for row in payload.get("capabilities") or []]
    assert RTK_ID in ids


# @lat: [[capability-resolver-tests#Doctor#Missing is warning not blocked]]
def test_missing_is_warning_not_blocked(brownfield, offline_cache, monkeypatch):
    monkeypatch.setattr("ges.providers.rtk.shutil.which", lambda _name: None)
    apply_recommended(brownfield)
    payload = run_doctor(brownfield)
    assert any("RECOMMENDED_PROVIDER_MISSING" in item for item in payload.get("warnings") or [])
    assert payload["overall"] != BLOCKED
    assert run_check(brownfield) == GES_CHECK_PASS


def test_excluded_superpowers_does_not_fail_doctor(brownfield, offline_cache, monkeypatch):
    monkeypatch.setattr("ges.providers.rtk.shutil.which", lambda _name: None)
    from ges.compose import compose, prepare_apply
    from ges.reconciler.apply import apply_plan

    ctx = compose(
        brownfield,
        exclude=[
            "superpowers.execution",
            "superpowers.finishing-a-development-branch",
            "superpowers.receiving-code-review",
            "superpowers.requesting-code-review",
            "superpowers.subagent-driven-development",
            "superpowers.systematic-debugging",
            "superpowers.test-driven-development",
            "superpowers.using-git-worktrees",
            "superpowers.verification-before-completion",
            "superpowers.writing-plans",
        ],
    )
    prepare_apply(ctx)
    apply_plan(brownfield, ctx.plan, ctx.desired, project=ctx.project, profile=ctx.profile, lock=ctx.lock)
    payload = run_doctor(brownfield)
    assert payload["checks"]["superpowers_skills"] == "PASS"
    assert payload["overall"] != BLOCKED


# @lat: [[capability-resolver-tests#Init#Init prints recommendation]]
def test_init_prints_recommendation(brownfield, offline_cache, capsys, monkeypatch):
    monkeypatch.setattr(init_cli, "_confirm", lambda _args: False)
    args = Namespace(repo=str(brownfield), exclude=[], enable=[], yes=False, non_interactive=False)
    assert init_cli.run(args) == 0
    output = capsys.readouterr().out
    assert "Capability Recommendation" in output
    text = render_capability_plan(build_capability_plan(BROWNFIELD))
    assert "FAIL" not in text
    text.encode("gbk")


# @lat: [[capability-resolver-tests#Isolation#Evidence snapshot unchanged]]
def test_evidence_snapshot_unchanged():
    schema = json.loads((SCHEMA_DIR / "ges.evidence-snapshot.v1.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert "capabilities" not in schema["properties"]
    assert set(schema["required"]) == {
        "schema",
        "work_id",
        "repo",
        "pr_number",
        "subject_sha",
        "review",
        "checks",
    }


def test_golden_blocked_is_not_synth_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GES_ALPHA3_GOLDEN_REPO", str(tmp_path / "missing-consumer"))
    assert golden_capability_main([]) == 3
    output = capsys.readouterr().out
    assert "GOLDEN_CAPABILITY_BLOCKED" in output
    assert "READY" not in output
