from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from ges.acceptance.harness import (
    SPEC_CONSTITUTION,
    THIRD_PARTY,
    USER_AGENTS,
    apply_recommended,
    business_fingerprint,
)
from ges.analyzer.repo_profile import analyze_repo
from ges.catalog.loader import load_catalog
from ges.check import run_check
from ges.cli import analyze as analyze_cli
from ges.cli import diff as diff_cli
from ges.cli import init as init_cli
from ges.cli import legacy as legacy_cli
from ges.compose import compose, prepare_apply
from ges.errors import (
    CAPABILITY_OWNERSHIP_CONFLICT,
    DESIRED_STATE_INVALID,
    GES_CHECK_FAILED,
    GES_CHECK_PASS,
    MANAGED_CONTENT_MODIFIED,
    PROJECTION_PATH_CONFLICT,
    RECONFIGURE_NOT_SUPPORTED,
    SOURCE_CACHE_INTEGRITY_FAILED,
    GesError,
)
from ges.harness_adapters.agents_md import outside_bytes
from ges.io import write_text
from ges.legacy.v5 import LEGACY_OWNERSHIP_UNKNOWN, OWNED_ABSENT, OWNED_UNMODIFIED, inspect_legacy
from ges.paths import AGENTS_BEGIN
from ges.reconciler.apply import apply_plan, consumer_tree
from ges.reconciler.state import read_lock, read_project
from ges.remove import run_remove
from ges.source_adapters.base import ProjectedFile, Projection
from ges.source_adapters.cache import write_manifest


# @lat: [[ges6-tests#A01 — Brownfield Detection]]
def test_a01_brownfield_detection(brownfield):
    profile = analyze_repo(brownfield)
    assert profile["repository_kind"] == "brownfield-monorepo"
    assert profile["llm_token_usage"] == 0


# @lat: [[ges6-tests#A02 — Harness Detection]]
def test_a02_harness_detection(brownfield):
    profile = analyze_repo(brownfield)
    assert "cursor" in profile["agents"]
    assert "codex" in profile["agents"]


# @lat: [[ges6-tests#A03 — Existing AGENTS Preservation]]
def test_a03_agents_preservation(brownfield, offline_cache):
    before = outside_bytes((brownfield / "AGENTS.md").read_text(encoding="utf-8"))
    apply_recommended(brownfield)
    after = outside_bytes((brownfield / "AGENTS.md").read_text(encoding="utf-8"))
    assert after == before
    assert USER_AGENTS.strip() in (brownfield / "AGENTS.md").read_text(encoding="utf-8")
    assert AGENTS_BEGIN in (brownfield / "AGENTS.md").read_text(encoding="utf-8")


# @lat: [[ges6-tests#A04 — Existing Spec Kit Preservation]]
def test_a04_specify_preservation(brownfield, offline_cache):
    apply_recommended(brownfield)
    assert (brownfield / ".specify" / "constitution.md").read_text(encoding="utf-8") == SPEC_CONSTITUTION
    assert (brownfield / ".specify" / "templates" / "spec-template.md").is_file()


# @lat: [[ges6-tests#A05 — Legacy Detection]]
def test_a05_legacy_detection(brownfield, offline_cache):
    profile = analyze_repo(brownfield)
    assert profile["legacy_ges"] is True
    report = inspect_legacy(brownfield)
    assert report.detected is True
    statuses = {entry.path: entry.status for entry in report.entries}
    assert statuses[".agents/skills/using-superpowers/SKILL.md"] == OWNED_UNMODIFIED
    assert statuses[".agents/ges/domain-packs/backend/pack.json"] == OWNED_ABSENT
    assert statuses[".cursor/skills/smc-work-router/SKILL.md"] == LEGACY_OWNERSHIP_UNKNOWN
    apply_recommended(brownfield)
    assert (brownfield / ".agents" / "skills" / "using-superpowers" / "SKILL.md").is_file()
    assert (brownfield / ".cursor" / "skills" / "smc-work-router" / "SKILL.md").is_file()


# @lat: [[ges6-tests#A06 — Capability Recommendation]]
def test_a06_capability_recommendation(brownfield, offline_cache):
    ctx = compose(brownfield)
    assert ctx.resolution.profile == "brownfield-product-app"
    assert "matt.grill-with-docs" in ctx.resolution.closed
    assert "speckit.specify" in ctx.resolution.closed
    assert "superpowers.test-driven-development" in ctx.resolution.closed


# @lat: [[ges6-tests#A07 — Capability Exclusion]]
def test_a07_capability_exclusion(brownfield, offline_cache):
    ctx, _, _ = apply_recommended(brownfield, exclude=["superpowers.writing-plans"])
    assert "superpowers.writing-plans" not in ctx.resolution.closed
    project = read_project(brownfield)
    assert "superpowers.writing-plans" in project["capabilities"]["explicitly_disabled"]
    assert "superpowers.writing-plans" not in project["capabilities"]["requested"]
    assert "superpowers.test-driven-development" in project["capabilities"]["requested"]


# @lat: [[ges6-tests#A08 — Dependency Closure]]
def test_a08_dependency_closure(brownfield, offline_cache):
    ctx = compose(brownfield)
    assert "matt.grill-with-docs" in ctx.resolution.closed
    assert "matt.grilling" in ctx.resolution.closed
    assert "matt.domain-modeling" in ctx.resolution.closed


# @lat: [[ges6-tests#A09 — Ownership Conflict]]
def test_a09_ownership_conflict(brownfield, offline_cache):
    ctx = compose(brownfield, extra=["matt.to-spec"])
    with pytest.raises(GesError) as captured:
        prepare_apply(ctx)
    assert captured.value.code == CAPABILITY_OWNERSHIP_CONFLICT


# @lat: [[ges6-tests#A10 — Selective Install]]
def test_a10_selective_install(brownfield, offline_cache):
    ctx, _, _ = apply_recommended(brownfield)
    skills = {path.name for path in (brownfield / ".agents" / "skills").iterdir() if path.is_dir()}
    assert "brainstorming" not in skills
    assert "to-spec" not in skills
    assert "using-superpowers" in skills  # pre-existing user/legacy, not GES-installed
    assert "grill-with-docs" in skills
    assert "writing-plans" in skills
    assert "speckit-specify" not in skills
    assert (brownfield / ".cursor" / "skills" / "speckit-specify" / "SKILL.md").is_file()
    for cap_id in ("matt.to-spec", "matt.implement", "speckit.implement", "superpowers.brainstorming"):
        assert cap_id not in ctx.resolution.closed


# @lat: [[ges6-tests#A11 — Upstream Lock]]
def test_a11_upstream_lock(brownfield, offline_cache):
    apply_recommended(brownfield)
    lock = read_lock(brownfield)
    for source in ("matt", "spec-kit", "superpowers"):
        sha = lock["sources"][source]["commit_sha"]
        assert len(sha) == 40
        assert all(ch in "0123456789abcdef" for ch in sha)


# @lat: [[ges6-tests#A12 — Idempotent Apply]]
def test_a12_idempotent_apply(brownfield, offline_cache):
    ctx1, _, noop1 = apply_recommended(brownfield)
    assert noop1 is False
    assert any(entry.action in {"ADD", "UPDATE"} for entry in ctx1.plan.entries)
    ctx2, _, noop2 = apply_recommended(brownfield)
    assert noop2 is True
    assert ctx2.plan.noop is True


# @lat: [[ges6-tests#A13 — Managed Update]]
def test_a13_managed_update(brownfield, offline_cache):
    apply_recommended(brownfield)
    business = business_fingerprint(brownfield)
    outside = outside_bytes((brownfield / "AGENTS.md").read_text(encoding="utf-8"))
    _upgrade_cached_skill(offline_cache)
    ctx, _, noop = apply_recommended(brownfield)
    assert noop is False
    updated = [entry.path for entry in ctx.plan.entries if entry.action == "UPDATE"]
    assert any(path.startswith(".agents/skills/grill-with-docs/") for path in updated)
    assert all(not path.startswith("apps/") for path in updated)
    assert business_fingerprint(brownfield) == business
    assert outside_bytes((brownfield / "AGENTS.md").read_text(encoding="utf-8")) == outside


# @lat: [[ges6-tests#A14 — User Modification Conflict]]
def test_a14_user_modification_conflict(brownfield, offline_cache):
    apply_recommended(brownfield)
    text = (brownfield / "AGENTS.md").read_text(encoding="utf-8")
    (brownfield / "AGENTS.md").write_text(
        text.replace("grill-with-docs", "USER CHANGED THIS"),
        encoding="utf-8",
    )
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == MANAGED_CONTENT_MODIFIED


# @lat: [[ges6-tests#A15 — Remove]]
def test_a15_remove(brownfield, offline_cache):
    apply_recommended(brownfield)
    run_remove(brownfield)
    assert not (brownfield / ".ges").exists()
    assert not (brownfield / ".agents" / "skills" / "grill-with-docs").exists()
    assert not (brownfield / ".cursor" / "ges").exists()
    assert (brownfield / ".agents" / "skills" / "third-party" / "SKILL.md").read_text(encoding="utf-8") == THIRD_PARTY
    assert (brownfield / ".agents" / "governance" / "kit.md").is_file()
    assert (brownfield / ".specify" / "constitution.md").read_text(encoding="utf-8") == SPEC_CONSTITUTION
    agents = (brownfield / "AGENTS.md").read_text(encoding="utf-8")
    assert AGENTS_BEGIN not in agents
    assert "User-owned routing rules." in agents


# @lat: [[ges6-tests#A16 — Business Source Guard]]
def test_a16_business_source_guard(brownfield, offline_cache):
    before = business_fingerprint(brownfield)
    apply_recommended(brownfield)
    assert business_fingerprint(brownfield) == before
    apply_recommended(brownfield)
    assert business_fingerprint(brownfield) == before
    run_remove(brownfield)
    assert business_fingerprint(brownfield) == before
    apply_recommended(brownfield)
    assert run_check(brownfield) == GES_CHECK_PASS


def _upgrade_cached_skill(offline_cache: Path) -> None:
    pin = load_catalog().sources["matt"]
    skill = (
        offline_cache
        / pin.cache_key
        / pin.commit_sha
        / "skills"
        / "engineering"
        / "grill-with-docs"
        / "SKILL.md"
    )
    skill.write_bytes(skill.read_bytes() + b"\n# upgraded\n")
    write_manifest(offline_cache / pin.cache_key / pin.commit_sha, pin)


# @lat: [[ges6-tests#A17 — Preview / Read-only Command Purity]]
def test_a17_read_only_command_purity(brownfield, offline_cache, monkeypatch):
    before = consumer_tree(brownfield)
    analyze_cli.run(Namespace(repo=str(brownfield)))
    diff_cli.run(Namespace(repo=str(brownfield), exclude=[], enable=[], json=False))
    legacy_cli.run_inspect(Namespace(repo=str(brownfield)))
    with pytest.raises(GesError) as captured:
        run_check(brownfield)
    assert captured.value.code == GES_CHECK_FAILED
    monkeypatch.setattr(init_cli, "_confirm", lambda args: False)
    init_cli.run(Namespace(repo=str(brownfield), exclude=[], enable=[], yes=False, non_interactive=False))
    assert consumer_tree(brownfield) == before


# @lat: [[ges6-tests#A18 — Desired State Authority]]
def test_a18_desired_state_authority(brownfield, offline_cache):
    apply_recommended(brownfield)
    before = consumer_tree(brownfield)
    with pytest.raises(GesError) as captured:
        compose(brownfield, exclude=["matt.to-tickets"])
    assert captured.value.code == RECONFIGURE_NOT_SUPPORTED
    assert consumer_tree(brownfield) == before


# @lat: [[ges6-tests#A19 — Optional Selection Semantics]]
def test_a19_optional_selection_semantics(brownfield, offline_cache):
    ctx = compose(brownfield)
    assert "superpowers.executing-plans" not in ctx.resolution.selected
    assert "superpowers.executing-plans" not in ctx.project["capabilities"]["requested"]
    with pytest.raises(GesError) as captured:
        compose(brownfield, exclude=["matt.setup"])
    assert captured.value.code == DESIRED_STATE_INVALID
    enabled = compose(brownfield, extra=["superpowers.executing-plans"])
    assert "superpowers.executing-plans" in enabled.resolution.selected
    assert "superpowers.executing-plans" in enabled.project["capabilities"]["requested"]


# @lat: [[ges6-tests#A20 — Section-scoped Hashing]]
def test_a20_section_scoped_hashing(brownfield, offline_cache):
    apply_recommended(brownfield)
    text = (brownfield / "AGENTS.md").read_text(encoding="utf-8")
    (brownfield / "AGENTS.md").write_text(
        text.replace("User-owned routing rules.", "NEW USER ROUTING TEXT"),
        encoding="utf-8",
    )
    ctx = compose(brownfield)
    assert ctx.plan.noop is True
    assert run_check(brownfield) == GES_CHECK_PASS
    apply_recommended(brownfield)
    assert "NEW USER ROUTING TEXT" in (brownfield / "AGENTS.md").read_text(encoding="utf-8")
    mutated = (brownfield / "AGENTS.md").read_text(encoding="utf-8")
    (brownfield / "AGENTS.md").write_text(
        mutated.replace("grill-with-docs", "USER CHANGED THIS"),
        encoding="utf-8",
    )
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == MANAGED_CONTENT_MODIFIED


# @lat: [[ges6-tests#A21 — Failure Atomicity]]
def test_a21_failure_atomicity(brownfield, offline_cache):
    apply_recommended(brownfield)
    _upgrade_cached_skill(offline_cache)
    t0 = consumer_tree(brownfield)
    ctx = compose(brownfield)
    prepare_apply(ctx)
    assert ctx.plan.noop is False
    for fail_at in ("after_first_write", "after_nth_write", "before_receipt", "post_verify"):
        with pytest.raises(RuntimeError, match="injected failure"):
            apply_plan(
                brownfield,
                ctx.plan,
                ctx.desired,
                project=ctx.project,
                profile=ctx.profile,
                lock=ctx.lock,
                fail_at=fail_at,
                fail_after_writes=3,
            )
        assert consumer_tree(brownfield) == t0
        assert (brownfield / ".ges" / "project.yaml").is_file()


# @lat: [[ges6-tests#A22 — Remove Drift Protection]]
def test_a22_remove_drift_protection(brownfield, offline_cache):
    apply_recommended(brownfield)
    skill = brownfield / ".agents" / "skills" / "grill-with-docs" / "SKILL.md"
    original = skill.read_bytes()
    skill.write_bytes(original + b"\nuser edit\n")
    before = consumer_tree(brownfield)
    with pytest.raises(GesError) as captured:
        run_remove(brownfield)
    assert captured.value.code == MANAGED_CONTENT_MODIFIED
    assert consumer_tree(brownfield) == before
    assert skill.read_bytes() == original + b"\nuser edit\n"
    assert (brownfield / ".ges" / "project.yaml").is_file()


# @lat: [[ges6-tests#A23 — Source Cache Integrity / Provenance]]
def test_a23_source_cache_integrity(brownfield, offline_cache):
    apply_recommended(brownfield)
    pin = load_catalog().sources["matt"]
    skill = (
        offline_cache
        / pin.cache_key
        / pin.commit_sha
        / "skills"
        / "engineering"
        / "grill-with-docs"
        / "SKILL.md"
    )
    skill.write_bytes(skill.read_bytes() + b"\n# tampered\n")
    with pytest.raises(GesError) as captured:
        compose(brownfield)
    assert captured.value.code == SOURCE_CACHE_INTEGRITY_FAILED


# @lat: [[ges6-tests#A24 — Projection Collision]]
def test_a24_projection_collision(brownfield, offline_cache):
    before = consumer_tree(brownfield)
    projection = Projection()
    projection.add(
        ProjectedFile("AGENTS.md", b"one", None, "alpha", None, "skill", ownership_type="FILE")
    )
    with pytest.raises(GesError) as captured:
        projection.add(
            ProjectedFile("AGENTS.md", b"two", None, "beta", None, "skill", ownership_type="FILE")
        )
    assert captured.value.code == PROJECTION_PATH_CONFLICT
    assert consumer_tree(brownfield) == before


# @lat: [[ges6-tests#A25 — Analyzer Schema + Script Detection]]
def test_a25_analyzer_schema_and_scripts(tmp_path):
    web = tmp_path / "web-app"
    write_text(
        web / "apps" / "web" / "package.json",
        '{"name":"web","scripts":{"test":"vitest","build":"vite build","lint":"eslint ."}}\n',
    )
    write_text(web / "apps" / "web" / "tsconfig.json", "{}\n")
    write_text(web / "apps" / "web" / "src" / "main.ts", "export const n = 1;\n")
    profile = analyze_repo(web)
    assert profile["schema"] == "ges.repo-profile.v2"
    assert profile["llm_token_usage"] == 0
    assert "typescript" in profile["languages"]
    assert profile["scripts"]["test"] == ["apps/web/package.json"]
    assert profile["scripts"]["build"] == ["apps/web/package.json"]
    assert profile["scripts"]["lint"] == ["apps/web/package.json"]
    assert "apps/web/tsconfig.json" in profile["tsconfig_evidence"]

    empty = tmp_path / "apps-only"
    write_text(empty / "apps" / "docs" / "README.md", "# apps\n")
    empty_profile = analyze_repo(empty)
    assert "typescript" not in empty_profile["languages"]


# @lat: [[ges6-tests#A26 — Spec Kit Pinned Adoption]]
def test_a26_spec_kit_pinned_adoption(brownfield, offline_cache):
    apply_recommended(brownfield)
    assert (brownfield / ".specify" / "constitution.md").read_text(encoding="utf-8") == SPEC_CONSTITUTION
    skill = brownfield / ".cursor" / "skills" / "speckit-specify" / "SKILL.md"
    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: speckit-specify" in text
    assert not (brownfield / ".agents" / "skills" / "speckit-specify" / "SKILL.md").exists()


# @lat: [[ges6-tests#A27 — Golden Consumer]]
def test_a27_golden_consumer_current():
    from ges.acceptance.release_gate import assert_current_status_current

    assert_current_status_current(Path(__file__).resolve().parents[2])

