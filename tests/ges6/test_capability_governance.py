from __future__ import annotations

import json
from argparse import Namespace

import pytest

from ges.acceptance.harness import apply_recommended
from ges.acceptance.run_golden_capability_governance import main as golden_governance_main
from ges.catalog.providers import RTK_ID, load_providers
from ges.check import run_check
from ges.cli import capability as cap_cli
from ges.cli import init as init_cli
from ges.cli.main import main
from ges.compose import compose
from ges.doctor import BLOCKED, run_doctor
from ges.errors import (
    CAPABILITY_NOT_FOUND,
    CAPABILITY_NOT_INSTALLED,
    CAPABILITY_PROHIBITED,
    COMPOSER_CAPABILITY_FROZEN,
    DESIRED_STATE_INVALID,
    GES_CHECK_PASS,
    GesError,
)
from ges.paths import SCHEMA_DIR, capability_policy_path, installed_path, repo_capabilities_dir
from ges.providers.compat import package_incompatible
from ges.providers.overlay import overlay_exists, read_installed, read_policy, write_policy
from ges.reconciler.apply import consumer_tree
from ges.reconciler.state import read_lock


def _missing_rtk(monkeypatch) -> None:
    monkeypatch.setattr("ges.providers.rtk.shutil.which", lambda _name: None)


# @lat: [[capability-governance-tests#Catalog#Only RTK and duplicate block]]
def test_only_rtk_and_duplicate_block(tmp_path):
    providers = load_providers()
    assert list(providers) == [RTK_ID]
    assert package_incompatible(RTK_ID) == ()
    dup = tmp_path / "providers.yaml"
    dup.write_text(
        "schema: ges.providers.v1\n"
        "providers:\n"
        "  - id: command-output.rtk\n"
        "    category: execution-efficiency\n"
        "    provider: rtk\n"
        "    default_level: recommended\n"
        "    incompatible: []\n"
        "    health_checks: [binary]\n"
        "  - id: command-output.rtk\n"
        "    category: execution-efficiency\n"
        "    provider: rtk\n"
        "    default_level: recommended\n"
        "    incompatible: []\n"
        "    health_checks: [binary]\n",
        encoding="utf-8",
    )
    with pytest.raises(GesError) as exc:
        load_providers(dup)
    assert exc.value.code == DESIRED_STATE_INVALID


# @lat: [[capability-governance-tests#Init#Init does not create overlay]]
def test_init_does_not_create_overlay(brownfield, offline_cache, monkeypatch):
    compose(brownfield)
    assert not overlay_exists(brownfield)
    monkeypatch.setattr(init_cli, "_confirm", lambda _args: True)
    args = Namespace(repo=str(brownfield), exclude=[], enable=[], yes=True, non_interactive=True)
    assert init_cli.run(args) == 0
    assert not overlay_exists(brownfield)
    assert not repo_capabilities_dir(brownfield).exists()


# @lat: [[capability-governance-tests#Overlay#Add creates overlay and is idempotent]]
def test_add_creates_overlay_and_is_idempotent(brownfield, offline_cache, monkeypatch):
    _missing_rtk(monkeypatch)
    apply_recommended(brownfield)
    requested = list((read_lock(brownfield) or {}).get("requested") or [])
    assert main(["capability", "add", RTK_ID, str(brownfield)]) == 0
    first = read_installed(brownfield)
    assert first["installed"] == [RTK_ID]
    assert capability_policy_path(brownfield).is_file()
    assert main(["capability", "add", RTK_ID, str(brownfield)]) == 0
    assert read_installed(brownfield)["installed"] == [RTK_ID]
    assert (read_lock(brownfield) or {}).get("requested") == requested


# @lat: [[capability-governance-tests#Overlay#Composer add is frozen]]
def test_composer_add_is_frozen(brownfield, offline_cache, capsys):
    assert main(["capability", "add", "matt.setup", str(brownfield)]) == 2
    err = capsys.readouterr().err
    assert COMPOSER_CAPABILITY_FROZEN in err
    assert not overlay_exists(brownfield)


# @lat: [[capability-governance-tests#Overlay#Unknown id is not found]]
def test_unknown_id_is_not_found(brownfield, offline_cache, capsys):
    assert main(["capability", "add", "unknown.provider", str(brownfield)]) == 2
    assert CAPABILITY_NOT_FOUND in capsys.readouterr().err
    assert not overlay_exists(brownfield)


# @lat: [[capability-governance-tests#Overlay#Prohibited add is blocked]]
def test_prohibited_add_is_blocked(brownfield, offline_cache, monkeypatch, capsys):
    _missing_rtk(monkeypatch)
    apply_recommended(brownfield)
    write_policy(brownfield, {"prohibited": [RTK_ID]})
    assert main(["capability", "add", RTK_ID, str(brownfield)]) == 2
    assert CAPABILITY_PROHIBITED in capsys.readouterr().err
    assert read_installed(brownfield)["installed"] == []


# @lat: [[capability-governance-tests#Overlay#Remove missing and last remove]]
def test_remove_missing_and_last_remove(brownfield, offline_cache, monkeypatch, capsys):
    _missing_rtk(monkeypatch)
    apply_recommended(brownfield)
    assert main(["capability", "remove", RTK_ID, str(brownfield)]) == 2
    assert CAPABILITY_NOT_INSTALLED in capsys.readouterr().err
    assert main(["capability", "add", RTK_ID, str(brownfield)]) == 0
    policy_before = read_policy(brownfield)
    assert main(["capability", "remove", RTK_ID, str(brownfield)]) == 0
    assert installed_path(brownfield).is_file()
    assert read_installed(brownfield)["installed"] == []
    assert read_policy(brownfield) == policy_before
    assert capability_policy_path(brownfield).is_file()


# @lat: [[capability-governance-tests#List#List columns and exit zero]]
def test_list_columns_and_exit_zero(brownfield, offline_cache, monkeypatch):
    _missing_rtk(monkeypatch)
    apply_recommended(brownfield)
    write_policy(brownfield, {"required": [RTK_ID]})
    before = consumer_tree(brownfield)
    assert cap_cli.run_list(Namespace(repo=str(brownfield), json=True)) == 0
    row = cap_cli._row(brownfield, RTK_ID)
    assert set(row) >= {"id", "resolver_level", "policy_level", "installed", "status", "reason"}
    assert row["id"] == RTK_ID
    assert row["installed"] is False
    assert row["policy_level"] == "required"
    assert main(["capability", "list", str(brownfield)]) == 0
    assert consumer_tree(brownfield) == before


# @lat: [[capability-governance-tests#List#Policy overrides resolver]]
def test_policy_overrides_resolver(brownfield, offline_cache, monkeypatch):
    _missing_rtk(monkeypatch)
    apply_recommended(brownfield)
    write_policy(brownfield, {"optional": [RTK_ID]})
    row = cap_cli._row(brownfield, RTK_ID)
    assert row["resolver_level"] == "recommended"
    assert row["policy_level"] == "optional"
    assert row["reason"] == "brownfield-monorepo"


# @lat: [[capability-governance-tests#Doctor#Doctor id writes nothing]]
def test_doctor_id_writes_nothing(tmp_path, monkeypatch, capsys):
    _missing_rtk(monkeypatch)
    repo = tmp_path / "bare"
    repo.mkdir()
    before = consumer_tree(repo)
    assert main(["capability", "doctor", RTK_ID, str(repo)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "ges.capability-status.v1"
    assert payload["capability_id"] == RTK_ID
    assert consumer_tree(repo) == before
    assert not overlay_exists(repo)


# @lat: [[capability-governance-tests#Doctor#Doctor overall ignores RTK]]
def test_doctor_overall_ignores_rtk(brownfield, offline_cache, monkeypatch):
    _missing_rtk(monkeypatch)
    apply_recommended(brownfield)
    write_policy(brownfield, {"required": [RTK_ID]})
    payload = run_doctor(brownfield)
    assert payload["overall"] != BLOCKED
    assert run_check(brownfield) == GES_CHECK_PASS


# @lat: [[capability-governance-tests#Isolation#Evidence snapshot unchanged]]
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


def test_golden_governance_blocked_is_not_synth_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GES_ALPHA4_GOLDEN_REPO", str(tmp_path / "missing-consumer"))
    assert golden_governance_main([]) == 3
    output = capsys.readouterr().out
    assert "GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED" in output
    assert "READY" not in output
