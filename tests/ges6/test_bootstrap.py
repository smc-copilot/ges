from __future__ import annotations

import shutil
from argparse import Namespace
from pathlib import Path

import pytest

from ges import __distribution_version__, __product_version__
from ges.acceptance.harness import apply_recommended, build_brownfield
from ges.catalog.loader import load_catalog
from ges.check import run_check
from ges.cli import doctor as doctor_cli
from ges.compose import compose, prepare_apply
from ges.doctor import BOOTSTRAP_PENDING, READY, run_doctor, run_preflight
from ges.errors import (
    BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
    GES_CHECK_FAILED,
    GES_CHECK_PASS,
    MANAGED_CONTENT_MODIFIED,
    RECONFIGURE_NOT_SUPPORTED,
    SOURCE_CACHE_INTEGRITY_FAILED,
    SPEC_KIT_RUNTIME_INCOMPLETE,
    SPEC_KIT_UNRESOLVED_TOKEN,
    TRANSACTION_ROLLBACK_FAILED,
    UNMANAGED_PATH_CONFLICT,
    GesError,
)
from ges.harness_adapters.agents_md import STACK_BODY, count_markers, outside_bytes
from ges.io import write_bytes, write_text
from ges.reconciler.apply import apply_plan, consumer_tree
from ges.reconciler.plan import ADD, PlanEntry
from ges.reconciler.state import read_lock, read_receipt
from ges.source_adapters.base import ProjectedFile
from ges.source_adapters.cache import verify_manifest
from ges.source_adapters.speckit_render import leftover_tokens, skill_rel


# @lat: [[bootstrap-tests#TEST-A-BOOT-001]]
def test_a_boot_001_preflight_readonly(brownfield, offline_cache):
    before = consumer_tree(brownfield)
    payload = run_preflight(brownfield)
    assert payload["overall"] == "PASS"
    assert consumer_tree(brownfield) == before


# @lat: [[bootstrap-tests#TEST-A-CAP-001]]
def test_a_cap_001_exact_capability_set(brownfield, offline_cache):
    ctx = compose(brownfield)
    assert "superpowers.executing-plans" not in ctx.resolution.selected
    assert "matt.to-spec" not in ctx.resolution.closed
    assert "speckit.implement" not in ctx.resolution.closed
    assert "matt.setup" in ctx.resolution.closed
    assert "speckit.specify" in ctx.resolution.closed


# @lat: [[bootstrap-tests#TEST-A-CAP-002]]
def test_a_cap_002_dependency_closure(brownfield, offline_cache):
    ctx = compose(brownfield)
    assert "matt.grilling" in ctx.resolution.closed
    assert "matt.domain-modeling" in ctx.resolution.closed
    assert not ctx.resolution.conflicts


# @lat: [[bootstrap-tests#TEST-A-SPECKIT-001]]
def test_a_speckit_001_existing_specify_still_renders(brownfield, offline_cache):
    ctx = compose(brownfield)
    assert any(path.startswith(".cursor/skills/speckit-") for path in ctx.desired)
    assert any(path.startswith(".specify/scripts/") or path.startswith(".specify/templates/") for path in ctx.desired)


# @lat: [[bootstrap-tests#TEST-A-SPECKIT-002]]
def test_a_speckit_002_no_unresolved_tokens(brownfield, offline_cache):
    apply_recommended(brownfield)
    for command in ("constitution", "specify", "clarify", "plan"):
        text = (brownfield / ".cursor" / "skills" / f"speckit-{command}" / "SKILL.md").read_text(encoding="utf-8")
        assert leftover_tokens(text) == []


# @lat: [[bootstrap-tests#TEST-A-SPECKIT-003]]
def test_a_speckit_003_user_specify_preserved(brownfield, offline_cache):
    write_text(brownfield / ".specify" / "specs" / "kept.md", "user spec\n")
    before = (brownfield / ".specify" / "constitution.md").read_bytes()
    apply_recommended(brownfield)
    assert (brownfield / ".specify" / "constitution.md").read_bytes() == before
    assert (brownfield / ".specify" / "specs" / "kept.md").read_text(encoding="utf-8") == "user spec\n"


# @lat: [[bootstrap-tests#TEST-A-SPECKIT-004]]
def test_a_speckit_004_runtime_smoke(brownfield, offline_cache):
    apply_recommended(brownfield)
    readiness = run_doctor(brownfield)
    assert readiness["checks"]["spec_kit_runtime"] == "PASS"


# @lat: [[bootstrap-tests#TEST-A-COLLISION-001]]
def test_a_collision_001_unknown_different_file_blocks(brownfield, offline_cache):
    write_text(brownfield / ".agents" / "skills" / "grill-with-docs" / "SKILL.md", "user owned\n")
    before = consumer_tree(brownfield)
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == UNMANAGED_PATH_CONFLICT
    assert consumer_tree(brownfield) == before


# @lat: [[bootstrap-tests#TEST-A-COLLISION-002]]
def test_a_collision_002_identical_is_adopted(brownfield, offline_cache):
    ctx = compose(brownfield)
    skill = next(path for path in ctx.desired if path.startswith(".agents/skills/grill-with-docs/"))
    write_bytes(brownfield / skill, ctx.desired[skill].content)
    ctx2 = compose(brownfield)
    adopted = [entry for entry in ctx2.plan.entries if entry.path == skill]
    assert adopted
    assert adopted[0].reason == "adopt-identical"
    apply_recommended(brownfield)
    receipt = read_receipt(brownfield)
    assert any(item["path"] == skill for item in receipt["managed_artifacts"])


# @lat: [[bootstrap-tests#TEST-A-COLLISION-003]]
def test_a_collision_003_incompatible_ownership(brownfield, offline_cache):
    (brownfield / ".agents" / "skills" / "grill-with-docs" / "SKILL.md").mkdir(parents=True)
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == UNMANAGED_PATH_CONFLICT


# @lat: [[bootstrap-tests#TEST-A-MATT-001]]
def test_a_matt_001_setup_installed_not_autorun(brownfield, offline_cache):
    apply_recommended(brownfield)
    assert (brownfield / ".agents" / "skills" / "setup-matt-pocock-skills").exists()
    assert not (brownfield / "docs" / "agents").exists()
    assert run_doctor(brownfield)["overall"] == BOOTSTRAP_PENDING


# @lat: [[bootstrap-tests#TEST-A-MATT-002]]
def test_a_matt_002_bootstrap_ready_when_docs_exist(brownfield, offline_cache):
    write_text(brownfield / "docs" / "agents" / "issue-tracker.md", "tracker\n")
    write_text(brownfield / "docs" / "agents" / "domain.md", "domain\n")
    apply_recommended(brownfield)
    assert run_doctor(brownfield)["overall"] == READY
    assert run_doctor(brownfield)["checks"]["matt_project_bootstrap"] == "PASS"


# @lat: [[bootstrap-tests#TEST-A-ROUTE-001]]
def test_a_route_001_agents_routing(brownfield, offline_cache):
    apply_recommended(brownfield)
    text = (brownfield / "AGENTS.md").read_text(encoding="utf-8")
    assert "grill-with-docs" in text
    assert "speckit-specify" in text
    assert "writing-plans" in STACK_BODY


# @lat: [[bootstrap-tests#TEST-A-ROUTE-002]]
@pytest.mark.parametrize(
    "body",
    [
        "# Product Agents\nUser-owned routing rules.",
        "# Product Agents\nUser-owned routing rules.\n",
    ],
)
def test_a_route_002_outside_agents_preserved(tmp_path, offline_cache, body):
    repo = build_brownfield(tmp_path / "nl")
    (repo / "AGENTS.md").write_text(body, encoding="utf-8")
    before = outside_bytes((repo / "AGENTS.md").read_text(encoding="utf-8"))
    apply_recommended(repo)
    after = outside_bytes((repo / "AGENTS.md").read_text(encoding="utf-8"))
    assert after == before


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    import os

    from ges.acceptance.harness import configure_offline_cache
    from ges.source_adapters.cache import seed_fixture_manifests

    root = tmp_path_factory.mktemp("installed")
    src = Path(__file__).resolve().parents[2] / "tests" / "ges6" / "fixtures" / "source-cache"
    dest = root / "source-cache"
    if src.exists():
        shutil.copytree(src, dest)
    seed_fixture_manifests(dest, list(load_catalog().sources.values()))
    previous = {key: os.environ.get(key) for key in ("GES_SOURCE_CACHE", "GES_SOURCE_OFFLINE")}
    configure_offline_cache(dest)
    repo = build_brownfield(root)
    apply_recommended(repo)
    yield repo
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# @lat: [[bootstrap-tests#TEST-A-CHECK-001]]
def test_a_check_001_schemas(installed):
    assert run_check(installed) == GES_CHECK_PASS
    lock = read_lock(installed)
    assert lock["schema"] == "ges.lock.v1"
    assert read_receipt(installed)["schema"] == "ges.install-receipt.v2"


# @lat: [[bootstrap-tests#TEST-A-CHECK-002]]
def test_a_check_002_closure_equals_lock(installed):
    ctx = compose(installed, persist_profile=False)
    lock = read_lock(installed)
    assert ctx.resolution.closed == list(lock.get("resolved_capabilities") or lock.get("capabilities") or [])


# @lat: [[bootstrap-tests#TEST-A-CHECK-003]]
def test_a_check_003_lock_sha_matches_catalog(installed):
    lock = read_lock(installed)
    catalog = load_catalog()
    for source_id, meta in (lock.get("sources") or {}).items():
        assert meta.get("commit_sha") == catalog.sources[source_id].commit_sha


# @lat: [[bootstrap-tests#TEST-A-CHECK-004]]
def test_a_check_004_cache_provenance(installed):
    cache = installed.parent / "source-cache"
    catalog = load_catalog()
    for pin in catalog.sources.values():
        verify_manifest(cache / pin.cache_key / pin.commit_sha, pin)


# @lat: [[bootstrap-tests#TEST-A-CHECK-005]]
def test_a_check_005_managed_file_identity(installed):
    assert run_check(installed) == GES_CHECK_PASS
    skill = installed / ".agents" / "skills" / "grill-with-docs" / "SKILL.md"
    assert skill.is_file()


# @lat: [[bootstrap-tests#TEST-A-CHECK-006]]
def test_a_check_006_managed_section_identity(installed):
    assert run_check(installed) == GES_CHECK_PASS
    assert count_markers((installed / "AGENTS.md").read_text(encoding="utf-8")) == 1


# @lat: [[bootstrap-tests#TEST-A-CHECK-007]]
def test_a_check_007_selected_projection_exists(installed):
    assert (installed / ".agents" / "skills" / "grill-with-docs" / "SKILL.md").is_file()
    assert (installed / ".cursor" / "skills" / "speckit-specify" / "SKILL.md").is_file()
    assert (installed / ".agents" / "skills" / "writing-plans" / "SKILL.md").is_file()


# @lat: [[bootstrap-tests#TEST-A-CHECK-008]]
def test_a_check_008_speckit_runtime_exists(installed):
    for command in ("constitution", "specify", "clarify", "plan"):
        assert (installed / ".cursor" / "skills" / f"speckit-{command}" / "SKILL.md").is_file()


# @lat: [[bootstrap-tests#TEST-A-CHECK-009]]
def test_a_check_009_business_source_guard(installed):
    lock = read_lock(installed)
    assert lock["business_source_fingerprint"]
    assert run_check(installed) == GES_CHECK_PASS


# @lat: [[bootstrap-tests#TEST-A-CHECK-010]]
def test_a_check_010_recompose_noop(installed):
    ctx = compose(installed, persist_profile=False)
    assert ctx.plan.noop


# @lat: [[bootstrap-tests#TEST-A-DOCTOR-001]]
def test_a_doctor_001_preflight_cli(brownfield, offline_cache):
    before = consumer_tree(brownfield)
    assert doctor_cli.run(Namespace(repo=str(brownfield), preflight=True)) == 0
    assert consumer_tree(brownfield) == before


# @lat: [[bootstrap-tests#TEST-A-DOCTOR-002]]
def test_a_doctor_002_bootstrap_pending(brownfield, offline_cache):
    apply_recommended(brownfield)
    assert doctor_cli.run(Namespace(repo=str(brownfield), preflight=False)) == 0
    assert run_doctor(brownfield)["overall"] == BOOTSTRAP_PENDING


# @lat: [[bootstrap-tests#TEST-A-DOCTOR-003]]
def test_a_doctor_003_ready(brownfield, offline_cache):
    apply_recommended(brownfield)
    write_text(brownfield / "docs" / "agents" / "issue-tracker.md", "tracker\n")
    write_text(brownfield / "docs" / "agents" / "domain.md", "domain\n")
    assert run_doctor(brownfield)["overall"] == READY


# @lat: [[bootstrap-tests#TEST-A-TXN-001]]
def test_a_txn_001_before_commit(brownfield, offline_cache):
    ctx = compose(brownfield)
    prepare_apply(ctx)
    before = consumer_tree(brownfield)
    with pytest.raises(RuntimeError):
        apply_plan(
            brownfield,
            ctx.plan,
            ctx.desired,
            project=ctx.project,
            profile=ctx.profile,
            lock=ctx.lock,
            fail_at="before_commit",
        )
    assert consumer_tree(brownfield) == before


# @lat: [[bootstrap-tests#TEST-A-TXN-002]]
def test_a_txn_002_after_writes(brownfield, offline_cache):
    apply_recommended(brownfield)
    from ges.catalog.loader import load_catalog
    from ges.source_adapters.cache import write_manifest

    pin = load_catalog().sources["matt"]
    skill = offline_cache / pin.cache_key / pin.commit_sha / "skills" / "engineering" / "grill-with-docs" / "SKILL.md"
    skill.write_bytes(skill.read_bytes() + b"\n# upgraded\n")
    write_manifest(offline_cache / pin.cache_key / pin.commit_sha, pin)
    t0 = consumer_tree(brownfield)
    ctx = compose(brownfield)
    prepare_apply(ctx)
    with pytest.raises(RuntimeError):
        apply_plan(
            brownfield,
            ctx.plan,
            ctx.desired,
            project=ctx.project,
            profile=ctx.profile,
            lock=ctx.lock,
            fail_at="after_first_write",
        )
    assert consumer_tree(brownfield) == t0


# @lat: [[bootstrap-tests#TEST-A-TXN-003]]
def test_a_txn_003_post_check(brownfield, offline_cache):
    ctx = compose(brownfield)
    prepare_apply(ctx)
    before = consumer_tree(brownfield)
    with pytest.raises(RuntimeError, match="post_check"):
        apply_plan(
            brownfield,
            ctx.plan,
            ctx.desired,
            project=ctx.project,
            profile=ctx.profile,
            lock=ctx.lock,
            fail_at="post_check",
        )
    assert consumer_tree(brownfield) == before


# @lat: [[bootstrap-tests#TEST-A-TXN-004]]
def test_a_txn_004_rollback_failure_retains_backup(brownfield, offline_cache):
    ctx = compose(brownfield)
    prepare_apply(ctx)
    with pytest.raises(GesError) as captured:
        apply_plan(
            brownfield,
            ctx.plan,
            ctx.desired,
            project=ctx.project,
            profile=ctx.profile,
            lock=ctx.lock,
            fail_at="rollback_write_failure",
        )
    assert captured.value.code == TRANSACTION_ROLLBACK_FAILED
    backup = Path(captured.value.details["backup_location"])
    assert backup.exists()


# @lat: [[bootstrap-tests#TEST-A-STATE-001]]
def test_a_state_001_reconfigure_blocked(brownfield, offline_cache):
    apply_recommended(brownfield)
    before = consumer_tree(brownfield)
    with pytest.raises(GesError) as captured:
        compose(brownfield, extra=["superpowers.executing-plans"])
    assert captured.value.code == RECONFIGURE_NOT_SUPPORTED
    assert consumer_tree(brownfield) == before


# @lat: [[bootstrap-tests#TEST-A-PKG-001]]
def test_a_pkg_001_version_identity(brownfield, offline_cache):
    apply_recommended(brownfield)
    receipt = read_receipt(brownfield)
    assert receipt["ges_version"] == __product_version__
    assert receipt["distribution_version"] == __distribution_version__
    assert __product_version__ == "6.0.0-alpha.5"
    assert __distribution_version__ == "1.2.1"


# @lat: [[bootstrap-tests#TEST-NEG-001]]
def test_neg_001_unknown_skill_collision(brownfield, offline_cache):
    write_text(brownfield / ".agents" / "skills" / "writing-plans" / "SKILL.md", "nope\n")
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == UNMANAGED_PATH_CONFLICT


# @lat: [[bootstrap-tests#TEST-NEG-002]]
def test_neg_002_cache_tamper(brownfield, offline_cache):
    apply_recommended(brownfield)
    pin_root = next(offline_cache.glob("mattpocock-skills/*"))
    skill = next(pin_root.rglob("grill-with-docs/SKILL.md"))
    skill.write_bytes(skill.read_bytes() + b"tamper")
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == SOURCE_CACHE_INTEGRITY_FAILED


# @lat: [[bootstrap-tests#TEST-NEG-006]]
def test_neg_006_changed_capability_set(brownfield, offline_cache):
    apply_recommended(brownfield)
    with pytest.raises(GesError) as captured:
        compose(brownfield, exclude=["superpowers.writing-plans"])
    assert captured.value.code == RECONFIGURE_NOT_SUPPORTED


# @lat: [[bootstrap-tests#TEST-A-CURSOR-001]]
def test_a_cursor_001_skill_frontmatter(brownfield, offline_cache):
    from ges.cursor_probe import structural_discovery

    apply_recommended(brownfield)
    assert structural_discovery(brownfield)["status"] == "PASS"


# @lat: [[bootstrap-tests#TEST-A-IDEMP-001]]
def test_a_idemp_001_second_init_noop(brownfield, offline_cache):
    apply_recommended(brownfield)
    ctx = compose(brownfield, persist_profile=False)
    assert ctx.plan.noop
    assert count_markers((brownfield / "AGENTS.md").read_text(encoding="utf-8")) == 1


# @lat: [[bootstrap-tests#TEST-NEG-003]]
def test_neg_003_unresolved_speckit_token(brownfield, offline_cache, monkeypatch):
    from ges.source_adapters import speckit_render

    original = speckit_render.official_stage

    def tainted():
        files, version = original()
        files[speckit_render.skill_rel("specify")] = b"{SCRIPT}\n"
        speckit_render.validate_selected_skills(files)
        return files, version

    monkeypatch.setattr(speckit_render, "official_stage", tainted)
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == SPEC_KIT_UNRESOLVED_TOKEN


# @lat: [[bootstrap-tests#TEST-NEG-004]]
def test_neg_004_missing_speckit_runtime(brownfield, offline_cache, monkeypatch):
    from ges.source_adapters import speckit_render

    original = speckit_render.official_stage

    def incomplete():
        files, version = original()
        files.pop(skill_rel("specify"), None)
        speckit_render.validate_selected_skills(files)
        return files, version

    monkeypatch.setattr(speckit_render, "official_stage", incomplete)
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == SPEC_KIT_RUNTIME_INCOMPLETE


# @lat: [[bootstrap-tests#TEST-NEG-005]]
def test_neg_005_business_source_write(brownfield, offline_cache):
    ctx = compose(brownfield)
    rel = "apps/work/src/hacked.ts"
    ctx.desired[rel] = ProjectedFile(
        relpath=rel,
        content=b"export const hacked = 1;\n",
        capability="ges.forbidden",
        source="ges",
        source_sha="0",
        kind="file",
    )
    ctx.plan.entries.append(PlanEntry(path=rel, action=ADD, kind="file", reason="inject-business"))
    prepare_apply(ctx)
    before = consumer_tree(brownfield)
    with pytest.raises(GesError) as captured:
        apply_plan(
            brownfield,
            ctx.plan,
            ctx.desired,
            project=ctx.project,
            profile=ctx.profile,
            lock=ctx.lock,
        )
    assert captured.value.code == BUSINESS_SOURCE_MODIFICATION_FORBIDDEN
    assert consumer_tree(brownfield) == before


# @lat: [[bootstrap-tests#TEST-NEG-007]]
def test_neg_007_managed_drift(brownfield, offline_cache):
    apply_recommended(brownfield)
    skill = brownfield / ".agents" / "skills" / "grill-with-docs" / "SKILL.md"
    skill.write_bytes(skill.read_bytes() + b"\n# drifted\n")
    with pytest.raises(GesError) as captured:
        run_check(brownfield)
    assert captured.value.code in {GES_CHECK_FAILED, MANAGED_CONTENT_MODIFIED}
    with pytest.raises(GesError) as compose_error:
        compose(brownfield)
    assert compose_error.value.code == MANAGED_CONTENT_MODIFIED


# @lat: [[bootstrap-tests#TEST-B8]]
def test_b8_specify_absent_still_installs_runtime(brownfield, offline_cache):
    shutil.rmtree(brownfield / ".specify")
    apply_recommended(brownfield)
    assert (brownfield / ".cursor" / "skills" / "speckit-specify" / "SKILL.md").is_file()


# @lat: [[bootstrap-tests#TEST-B9]]
def test_b9_empty_runtime_still_installed(brownfield, offline_cache):
    assert not (brownfield / ".specify" / ".ges").exists()
    apply_recommended(brownfield)
    assert (brownfield / ".cursor" / "skills" / "speckit-plan" / "SKILL.md").is_file()


# @lat: [[bootstrap-tests#TEST-B10]]
def test_b10_user_specs_preserved(brownfield, offline_cache):
    write_text(brownfield / ".specify" / "specs" / "kept.md", "user spec\n")
    apply_recommended(brownfield)
    assert (brownfield / ".specify" / "specs" / "kept.md").read_text(encoding="utf-8") == "user spec\n"


# @lat: [[bootstrap-tests#TEST-B11]]
def test_b11_constitution_preserved_and_reported(brownfield, offline_cache):
    before = (brownfield / ".specify" / "constitution.md").read_bytes()
    ctx = compose(brownfield)
    assert (brownfield / ".specify" / "constitution.md").read_bytes() == before
    assert any("LEGACY_OR_USER_SPEC_STATE" in warning for warning in ctx.plan.warnings)


# @lat: [[bootstrap-tests#TEST-B12]]
def test_b12_requested_set_frozen(brownfield, offline_cache):
    apply_recommended(brownfield)
    before = consumer_tree(brownfield)
    with pytest.raises(GesError) as captured:
        compose(brownfield, extra=["superpowers.executing-plans"])
    assert captured.value.code == RECONFIGURE_NOT_SUPPORTED
    assert consumer_tree(brownfield) == before


def test_fi_after_nth_write_rolls_back(brownfield, offline_cache):
    ctx = compose(brownfield)
    prepare_apply(ctx)
    before = consumer_tree(brownfield)
    with pytest.raises(RuntimeError, match="after_nth_write"):
        apply_plan(
            brownfield,
            ctx.plan,
            ctx.desired,
            project=ctx.project,
            profile=ctx.profile,
            lock=ctx.lock,
            fail_at="after_nth_write",
            fail_after_writes=2,
        )
    assert consumer_tree(brownfield) == before


def test_fi_before_receipt_rolls_back(brownfield, offline_cache):
    ctx = compose(brownfield)
    prepare_apply(ctx)
    before = consumer_tree(brownfield)
    with pytest.raises(RuntimeError, match="before_receipt"):
        apply_plan(
            brownfield,
            ctx.plan,
            ctx.desired,
            project=ctx.project,
            profile=ctx.profile,
            lock=ctx.lock,
            fail_at="before_receipt",
        )
    assert consumer_tree(brownfield) == before
