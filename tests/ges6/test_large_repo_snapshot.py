from __future__ import annotations

import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from ges.acceptance.harness import apply_recommended
from ges.analyzer import detectors
from ges.analyzer.git_index import build_git_file_index, parse_ls_files_stage_z, parse_porcelain_v2_z, prune_walk
from ges.analyzer.repo_profile import analyze_repo
from ges.check import run_check
from ges.cli import init as init_cli
from ges.errors import (
    BUSINESS_GIT_HEAD_CHANGED_DURING_APPLY,
    BUSINESS_GIT_INDEX_CHANGED_DURING_APPLY,
    BUSINESS_GIT_INDEX_UNAVAILABLE,
    BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
    GES_CHECK_FAILED,
    GES_CHECK_PASS,
    SUBMODULE_SOURCE_STATE_UNRESOLVED,
    GesError,
)
from ges.reconciler.state import read_lock, write_lock
from ges.reconciler.business_guard import (
    HASH_STATS,
    capture_business_snapshot,
    compare_business_snapshots,
    format_guard_summary,
    reset_hash_stats,
    snapshot_business_sources,
)
from ges.reconciler.mutation import MutationLedger
from ges.stagelog import STAGES


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    _git(path, "config", "user.email", "ges@example.com")
    _git(path, "config", "user.name", "ges")
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit_src(repo: Path, rel: str, text: str) -> None:
    _write(repo / rel, text)
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", rel)


# @lat: [[large-repo-tests#Git inventory#Tracked index ignores generated trees]]
def test_tracked_index_ignores_generated_trees(tmp_path):
    repo = _repo(tmp_path / "inv")
    _commit_src(repo, "src/app.ts", "export const n = 1;\n")
    ignored = repo / "src" / "node_modules" / "pkg" / "index.js"
    _write(ignored, "ignored\n")
    _write(repo / ".gitignore", "node_modules/\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore")
    index = build_git_file_index(repo)
    paths = {item.path for item in index.tracked}
    assert "src/app.ts" in paths
    assert "src/node_modules/pkg/index.js" not in paths
    assert all("node_modules" not in item.path for item in index.tracked)


# @lat: [[large-repo-tests#Git inventory#NUL-safe path parser]]
def test_nul_safe_path_parser():
    staged = b"100644 " + b"a" * 40 + b" 0\tapps/weird name/\nfile.ts\0"
    tracked = parse_ls_files_stage_z(staged)
    assert tracked[0].path == "apps/weird name/\nfile.ts"
    status = b"1 AM N... 100644 100644 100644 " + b"a" * 40 + b" " + b"b" * 40 + b" src/spaced file.ts\0"
    status += b"? packages/unicode-\xe6\x96\x87.md\0"
    entries = parse_porcelain_v2_z(status)
    assert entries[0].path == "src/spaced file.ts"
    assert entries[1].path == "packages/unicode-文.md"


# @lat: [[large-repo-tests#Snapshot#Clean tracked skips content hash]]
def test_clean_tracked_skips_content_hash(tmp_path):
    repo = _repo(tmp_path / "clean")
    _write(repo / ".gitignore", "generated/\n")
    for i in range(200):
        _write(repo / "src" / "f" / f"{i}.txt", f"{i}\n")
    _write(repo / "src" / "generated" / "blob.bin", "nohash\n")
    _git(repo, "add", ".gitignore", "src")
    _git(repo, "commit", "-m", "bulk")
    reset_hash_stats()
    snap = capture_business_snapshot(repo)
    assert snap["strategy"] == "git-index-overlay"
    assert snap["counts"]["clean_tracked"] == 200
    assert HASH_STATS["calls"] == 0
    assert "src/generated/blob.bin" not in HASH_STATS["paths"]


# @lat: [[large-repo-tests#Snapshot#Clean tracked mutation fails]]
def test_clean_tracked_mutation_fails(tmp_path):
    repo = _repo(tmp_path / "mut")
    _commit_src(repo, "src/app.ts", "one\n")
    before = capture_business_snapshot(repo)
    (repo / "src" / "app.ts").write_text("two\n", encoding="utf-8")
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError) as captured:
        compare_business_snapshots(before, after)
    assert captured.value.code == BUSINESS_SOURCE_MODIFICATION_FORBIDDEN


# @lat: [[large-repo-tests#Snapshot#Dirty overlay unchanged passes]]
def test_dirty_overlay_unchanged_passes(tmp_path):
    repo = _repo(tmp_path / "dirty")
    _commit_src(repo, "src/app.ts", "base\n")
    (repo / "src" / "app.ts").write_text("dirty\n", encoding="utf-8")
    before = snapshot_business_sources(repo)
    after = snapshot_business_sources(repo)
    assert before == after


# @lat: [[large-repo-tests#Snapshot#Dirty overlay byte change fails]]
def test_dirty_overlay_byte_change_fails(tmp_path):
    repo = _repo(tmp_path / "dirty2")
    _commit_src(repo, "src/app.ts", "base\n")
    (repo / "src" / "app.ts").write_text("X\n", encoding="utf-8")
    before = capture_business_snapshot(repo)
    (repo / "src" / "app.ts").write_text("Y\n", encoding="utf-8")
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError) as captured:
        compare_business_snapshots(before, after)
    assert captured.value.code == BUSINESS_SOURCE_MODIFICATION_FORBIDDEN


# @lat: [[large-repo-tests#Snapshot#Dirty file deletion fails]]
def test_dirty_file_deletion_fails(tmp_path):
    repo = _repo(tmp_path / "del")
    _commit_src(repo, "src/app.ts", "base\n")
    (repo / "src" / "app.ts").write_text("dirty\n", encoding="utf-8")
    before = capture_business_snapshot(repo)
    (repo / "src" / "app.ts").unlink()
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError) as captured:
        compare_business_snapshots(before, after)
    assert captured.value.code == BUSINESS_SOURCE_MODIFICATION_FORBIDDEN


# @lat: [[large-repo-tests#Snapshot#Untracked overlay unchanged passes]]
def test_untracked_overlay_unchanged_passes(tmp_path):
    repo = _repo(tmp_path / "ut")
    _commit_src(repo, "src/keep.ts", "keep\n")
    _write(repo / "src" / "new.ts", "fresh\n")
    before = snapshot_business_sources(repo)
    after = snapshot_business_sources(repo)
    assert before == after


# @lat: [[large-repo-tests#Snapshot#Untracked create change remove fails]]
def test_untracked_create_change_remove_fails(tmp_path):
    repo = _repo(tmp_path / "ut2")
    _commit_src(repo, "src/keep.ts", "keep\n")
    _write(repo / "src" / "new.ts", "fresh\n")
    before = capture_business_snapshot(repo)
    (repo / "src" / "new.ts").write_text("changed\n", encoding="utf-8")
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError):
        compare_business_snapshots(before, after)
    (repo / "src" / "new.ts").unlink()
    removed = capture_business_snapshot(repo)
    with pytest.raises(GesError):
        compare_business_snapshots(before, removed)
    _write(repo / "src" / "other.ts", "other\n")
    created = capture_business_snapshot(repo)
    with pytest.raises(GesError):
        compare_business_snapshots(before, created)


# @lat: [[large-repo-tests#Special paths#Symlink uses link text]]
def test_symlink_uses_link_text(tmp_path):
    repo = _repo(tmp_path / "link")
    _commit_src(repo, "src/keep.ts", "keep\n")
    target = tmp_path / "outside.txt"
    target.write_text("alpha\n", encoding="utf-8")
    link = repo / "src" / "alias.ts"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    _git(repo, "add", "src/alias.ts")
    _git(repo, "commit", "-m", "link")
    before = snapshot_business_sources(repo)
    target.write_text("beta\n", encoding="utf-8")
    assert snapshot_business_sources(repo) == before
    link.unlink()
    other = tmp_path / "other.txt"
    other.write_text("alpha\n", encoding="utf-8")
    try:
        link.symlink_to(other)
    except OSError:
        pytest.skip("symlink recreation is unavailable")
    after = snapshot_business_sources(repo)
    if after != before:
        with pytest.raises(GesError):
            compare_business_snapshots(capture_business_snapshot(repo), before)


# @lat: [[large-repo-tests#Special paths#Dirty submodule blocks]]
def test_dirty_submodule_blocks(tmp_path):
    repo = _repo(tmp_path / "sub")
    _commit_src(repo, "src/keep.ts", "keep\n")
    oid = "a" * 40
    _git(repo, "update-index", "--add", "--cacheinfo", "160000", oid, "src/vendor")
    (repo / "src" / "vendor").mkdir(exist_ok=True)
    (repo / "src" / "vendor" / "README").write_text("no git\n", encoding="utf-8")
    staged = _git(repo, "ls-files", "--stage", "-z", "--", "src/vendor")
    assert "160000" in staged.stdout
    with pytest.raises(GesError) as captured:
        capture_business_snapshot(repo)
    assert captured.value.code in {SUBMODULE_SOURCE_STATE_UNRESOLVED, BUSINESS_GIT_INDEX_UNAVAILABLE}


# @lat: [[large-repo-tests#Special paths#Knowledge tree is skipped]]
def test_knowledge_tree_is_skipped(tmp_path):
    repo = _repo(tmp_path / "skip-knowledge")
    _commit_src(repo, "apps/other/app.ts", "ok\n")
    _write(repo / "apps" / "knowledge" / "secret.ts", "nope\n")
    reset_hash_stats()
    snap = capture_business_snapshot(repo)
    assert snap["strategy"] == "git-index-overlay"
    assert all(not path.replace("\\", "/").startswith("apps/knowledge") for path in HASH_STATS["paths"])


# @lat: [[large-repo-tests#Special paths#Composer writes are skipped]]
def test_composer_writes_are_skipped(tmp_path):
    repo = _repo(tmp_path / "skip-composer")
    _commit_src(repo, "README.md", "product\n")
    before = snapshot_business_sources(repo)
    _write(repo / "AGENTS.md", "stack\n")
    _write(repo / "CLAUDE.md", "claude\n")
    _write(repo / ".ges" / "project.yaml", "schema: ges.project.v2\n")
    _write(repo / ".agents" / "skills" / "grilling" / "SKILL.md", "grill\n")
    _write(repo / ".specify" / "memory" / "constitution.md", "const\n")
    _write(repo / "docs" / "agents" / "domain.md", "domain\n")
    after = snapshot_business_sources(repo)
    assert before == after


# @lat: [[large-repo-tests#Consistency#HEAD race blocks]]
def test_head_race_blocks(tmp_path):
    repo = _repo(tmp_path / "head")
    _commit_src(repo, "src/app.ts", "one\n")
    before = capture_business_snapshot(repo)
    _commit_src(repo, "src/more.ts", "two\n")
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError) as captured:
        compare_business_snapshots(before, after)
    assert captured.value.code == BUSINESS_GIT_HEAD_CHANGED_DURING_APPLY


# @lat: [[large-repo-tests#Consistency#Index race blocks]]
def test_index_race_blocks(tmp_path):
    repo = _repo(tmp_path / "idx")
    _commit_src(repo, "src/app.ts", "one\n")
    before = capture_business_snapshot(repo)
    _write(repo / "src" / "staged.ts", "staged\n")
    _git(repo, "add", "src/staged.ts")
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError) as captured:
        compare_business_snapshots(before, after)
    assert captured.value.code in {
        BUSINESS_GIT_INDEX_CHANGED_DURING_APPLY,
        BUSINESS_SOURCE_MODIFICATION_FORBIDDEN,
    }


# @lat: [[large-repo-tests#Consistency#Protected byte mutation blocks]]
def test_protected_byte_mutation_blocks(tmp_path):
    repo = _repo(tmp_path / "prot")
    _commit_src(repo, "src/app.ts", "one\n")
    before = capture_business_snapshot(repo)
    (repo / "src" / "app.ts").write_text("mutated\n", encoding="utf-8")
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError) as captured:
        compare_business_snapshots(before, after)
    assert captured.value.code == BUSINESS_SOURCE_MODIFICATION_FORBIDDEN


# @lat: [[large-repo-tests#Write boundary#Ignored node_modules write denied]]
def test_ignored_node_modules_write_denied(tmp_path):
    ledger = MutationLedger()
    with pytest.raises(GesError) as captured:
        ledger.write_file(tmp_path, "apps/work/node_modules/x.js", b"nope")
    assert captured.value.code == BUSINESS_SOURCE_MODIFICATION_FORBIDDEN
    assert not (tmp_path / "apps" / "work" / "node_modules" / "x.js").exists()


# @lat: [[large-repo-tests#Write boundary#Ledger has zero business writes]]
def test_ledger_has_zero_business_writes(tmp_path):
    ledger = MutationLedger()
    ledger.write_file(tmp_path, ".ges/lock.json", b"{}")
    assert ledger.business_root_write_count == 0
    assert ledger.entries[0]["path"] == ".ges/lock.json"


# @lat: [[large-repo-tests#Fallback#Non-git uses full exact guard]]
def test_non_git_uses_full_exact_guard(tmp_path):
    repo = tmp_path / "nongit"
    _write(repo / "src" / "app.ts", "one\n")
    before = capture_business_snapshot(repo)
    assert before["strategy"] == "full-sha256-fallback"
    (repo / "src" / "app.ts").write_text("two\n", encoding="utf-8")
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError) as captured:
        compare_business_snapshots(before, after)
    assert captured.value.code == BUSINESS_SOURCE_MODIFICATION_FORBIDDEN


# @lat: [[large-repo-tests#Fallback#Git failure falls back]]
def test_git_failure_falls_back(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "failgit")
    _commit_src(repo, "src/app.ts", "one\n")

    def boom(path, *, roots=None):
        raise GesError(BUSINESS_GIT_INDEX_UNAVAILABLE, "injected git failure")

    monkeypatch.setattr("ges.reconciler.business_guard.build_git_file_index", boom)
    snap = capture_business_snapshot(repo)
    assert snap["strategy"] == "full-sha256-fallback"
    assert snap.get("fallback_reason")
    (repo / "src" / "app.ts").write_text("two\n", encoding="utf-8")
    after = capture_business_snapshot(repo)
    with pytest.raises(GesError):
        compare_business_snapshots(snap, after)


# @lat: [[large-repo-tests#Analyzer#Git mode skips ignored trees]]
def test_git_mode_skips_ignored_trees(tmp_path):
    repo = _repo(tmp_path / "an")
    _write(repo / ".gitignore", "node_modules/\n")
    _write(repo / "apps" / "web" / "tsconfig.json", "{}\n")
    _write(repo / "apps" / "web" / "src" / "main.ts", "export {}\n")
    _write(repo / "apps" / "web" / "package.json", '{"name":"web"}\n')
    _write(repo / "apps" / "web" / "node_modules" / "pkg" / "tsconfig.json", "{}\n")
    _git(repo, "add", ".gitignore", "apps/web/tsconfig.json", "apps/web/src/main.ts", "apps/web/package.json")
    _git(repo, "commit", "-m", "web")
    profile = analyze_repo(repo)
    assert detectors.IGNORED_TREE_VISITS == 0
    assert "apps/web/node_modules/pkg/tsconfig.json" not in profile["tsconfig_evidence"]
    assert profile["tsconfig_evidence"] == ["apps/web/tsconfig.json"]


# @lat: [[large-repo-tests#Analyzer#Detector semantics hold]]
def test_detector_semantics_hold(tmp_path):
    repo = tmp_path / "parity"
    _write(repo / "apps" / "web" / "package.json", '{"name":"web","devDependencies":{"typescript":"5.0.0"}}\n')
    _write(repo / "apps" / "web" / "tsconfig.json", "{}\n")
    _write(repo / "apps" / "web" / "src" / "main.ts", "export const n = 1;\n")
    detectors.clear_file_inventory()
    profile = analyze_repo(repo)
    assert "typescript" in profile["languages"]
    assert profile["tsconfig_evidence"] == ["apps/web/tsconfig.json"]
    assert profile["scripts"]["test"] == []


# @lat: [[large-repo-tests#Analyzer#Evidence order is stable]]
def test_evidence_order_is_stable(tmp_path):
    repo = tmp_path / "order"
    for name in ("c.ts", "a.ts", "b.ts"):
        _write(repo / "src" / name, "export {}\n")
    first = analyze_repo(repo)["tsconfig_evidence"]
    second = analyze_repo(repo)["tsconfig_evidence"]
    assert first == second
    detectors.clear_file_inventory()
    sources = detectors.typescript_source_evidence(repo)
    assert sources == ["src/a.ts", "src/b.ts", "src/c.ts"]


# @lat: [[large-repo-tests#Analyzer#Non-git walker prunes caches]]
def test_non_git_walker_prunes_caches(tmp_path):
    repo = tmp_path / "walk"
    _write(repo / "src" / "app.ts", "export {}\n")
    _write(repo / "node_modules" / "pkg" / "index.ts", "export {}\n")
    _write(repo / "dist" / "out.js", "x\n")
    _write(repo / ".cache" / "x", "x\n")
    paths, visits = prune_walk(repo)
    assert visits >= 3
    assert all("node_modules" not in item and "dist" not in item and ".cache" not in item for item in paths)
    assert "src/app.ts" in paths


# @lat: [[large-repo-tests#Performance#Telemetry fields present]]
def test_telemetry_fields_present(tmp_path):
    repo = _repo(tmp_path / "tel")
    _commit_src(repo, "src/app.ts", "one\n")
    snap = capture_business_snapshot(repo)
    summary = format_guard_summary(snap, snap)
    for key in ("strategy", "counts", "bytes_hashed", "elapsed_ms", "snapshot_digest"):
        assert key in snap
    assert "Business Guard:" in summary
    assert "src/app.ts" not in summary
    assert "one" not in summary
    for stage in (
        "FILE_INDEX",
        "BUSINESS_SNAPSHOT_T0",
        "BUSINESS_SNAPSHOT_T1",
        "COMPOSER_APPLY",
        "BUSINESS_COMPARE",
        "ANALYZER_INDEX",
    ):
        assert stage in STAGES


# @lat: [[large-repo-tests#Performance#Synthetic operation budget]]
def test_synthetic_operation_budget(tmp_path):
    repo = _repo(tmp_path / "budget")
    _write(repo / ".gitignore", "generated/\n")
    for i in range(300):
        _write(repo / "src" / "clean" / f"{i}.txt", f"{i}\n")
    _git(repo, "add", ".gitignore", "src/clean")
    _git(repo, "commit", "-m", "clean")
    for i in range(20):
        (repo / "src" / "clean" / f"{i}.txt").write_text(f"dirty-{i}\n", encoding="utf-8")
        _write(repo / "src" / "extra" / f"{i}.txt", f"u{i}\n")
    for i in range(80):
        _write(repo / "src" / "generated" / f"{i}.bin", f"g{i}\n")
    reset_hash_stats()
    snap = capture_business_snapshot(repo)
    assert snap["strategy"] == "git-index-overlay"
    assert HASH_STATS["calls"] <= 40
    assert all("generated" not in path for path in HASH_STATS["paths"])
    assert snap["counts"]["overlay_content_hashed"] <= 200


# @lat: [[large-repo-tests#Upgrade#Legacy fingerprint is stale]]
def test_legacy_fingerprint_is_stale(brownfield, offline_cache):
    apply_recommended(brownfield)
    lock = read_lock(brownfield) or {}
    lock["business_source_fingerprint"] = {"apps/work/src/main.ts": {"size": 1, "sha256": "aa"}}
    write_lock(brownfield, lock)
    with pytest.raises(GesError) as exc:
        run_check(brownfield)
    assert exc.value.code == GES_CHECK_FAILED
    assert "stale" in exc.value.message


# @lat: [[large-repo-tests#Upgrade#Init noop refreshes overlay fingerprint]]
def test_init_noop_refreshes_overlay_fingerprint(brownfield, offline_cache, monkeypatch):
    apply_recommended(brownfield)
    lock = read_lock(brownfield) or {}
    lock["business_source_fingerprint"] = {"apps/work/src/main.ts": {"size": 1, "sha256": "aa"}}
    write_lock(brownfield, lock)
    monkeypatch.setattr(init_cli, "_confirm", lambda _args: True)
    args = Namespace(repo=str(brownfield), exclude=[], enable=[], yes=True, non_interactive=True)
    assert init_cli.run(args) == 0
    fingerprint = (read_lock(brownfield) or {}).get("business_source_fingerprint") or {}
    assert fingerprint.get("strategy")
    assert "snapshot_digest" in fingerprint
    assert run_check(brownfield) == GES_CHECK_PASS


# @lat: [[large-repo-tests#Upgrade#Post-install business commits do not fail check]]
def test_post_install_business_commits_do_not_fail_check(brownfield, offline_cache):
    apply_recommended(brownfield)
    (brownfield / "apps" / "work" / "src" / "main.ts").write_text("export const app = 2;\n", encoding="utf-8")
    assert run_check(brownfield) == GES_CHECK_PASS
    from ges.doctor import run_doctor

    payload = run_doctor(brownfield)
    assert payload["checks"]["ges_core"] == "PASS"
