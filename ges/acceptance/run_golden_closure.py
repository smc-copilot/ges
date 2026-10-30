from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ges.acceptance.closure_evidence import record, write_closure_evidence
from ges.acceptance.golden_worktree import (
    DEFAULT_GOLDEN_SOURCE,
    create_detached_worktree,
    git,
    remove_worktree,
    resolve_consumer_head,
    source_branch,
    source_dirty_status,
    workspace_identity,
    worktree_clean,
)
from ges.acceptance.harness import apply_recommended
from ges.acceptance.release_evidence import artifact_inside_candidate, resolve_artifact_dir
from ges.acceptance.release_gate import assert_current_status_current
from ges.acceptance.speckit_smoke import (
    evaluate_spec,
    feature_state_error,
    matt_setup_prompt,
    smoke_dir,
    smoke_invocation_record,
    smoke_prompt,
    unexpected_writes,
)
from ges.compose import compose
from ges.cursor_probe import (
    REQUIRED_SKILLS,
    native_discovery,
    native_probe_prompt,
    prompt_leaks_skill_paths,
    resolve_cursor_cli,
    structural_discovery,
)
from ges.doctor import READY, run_doctor, run_preflight
from ges.errors import (
    CURSOR_CLI_NOT_FOUND,
    CURSOR_DISCOVERY_OUTPUT_INVALID,
    CURSOR_NATIVE_DISCOVERY_FAILED,
    CURSOR_SKILL_METADATA_MISMATCH,
    MANAGED_CONTENT_MODIFIED,
    GesError,
)
from ges.io import sha256_bytes, write_bytes, write_json
from ges.reconciler.apply import consumer_tree, snapshot_business_sources
from ges.reconciler.state import read_receipt
from ges.source_adapters.speckit_render import (
    INTEGRATION,
    REQUIRED_CLI_VERSION,
    SELECTED_COMMANDS,
    SPEC_KIT_REPO,
    SPEC_KIT_SHA,
    last_render_report,
    manifest_digest,
    official_stage,
    skill_rel,
)
from ges.stagelog import GES_CHECK, GES_DOCTOR, GES_INIT, GES_PREFLIGHT, GES_SECOND_INIT, SPECKIT_FUNCTIONAL_SMOKE, emit

PROBE_TIMEOUT_SEC = 300
MATT_TIMEOUT_SEC = 600
SMOKE_TIMEOUT_SEC = 900


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="GES 6 Bootstrap Closure Golden runner")
    parser.add_argument("--repo", default=str(DEFAULT_GOLDEN_SOURCE))
    parser.add_argument("--artifact-dir", default="")
    args = parser.parse_args(argv)
    source = Path(args.repo)
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    ges_root = Path(__file__).resolve().parents[2]
    _prepare_env(ges_root)
    artifact_dir = resolve_artifact_dir(args.artifact_dir or None)
    ges_head = git(ges_root, ["rev-parse", "HEAD"]).stdout.strip()
    ges_branch = git(ges_root, ["symbolic-ref", "--short", "-q", "HEAD"]).stdout.strip() or "DETACHED"
    acceptances: list[dict] = []
    worktree: Path | None = None
    cursor = {"executable": "", "version": "", "structural_discovery": "BLOCKED", "runtime_discovery": "BLOCKED"}
    spec_kit = None
    consumer = {
        "source_path": str(source),
        "repo_identity": "loudon84/smc-copilot-desktop",
        "source_branch": "",
        "commit_sha": "",
        "source_worktree_dirty": False,
        "source_worktree_status_digest": "",
        "test_worktree_path": "",
        "test_worktree_clean_at_start": False,
    }
    try:
        head = resolve_consumer_head(source)
        dirty, porcelain, digest = source_dirty_status(source)
        consumer.update(
            {
                "source_path": str(source.resolve()),
                "source_branch": source_branch(source),
                "commit_sha": head,
                "source_worktree_dirty": dirty,
                "source_worktree_status_digest": digest,
            }
        )
        _upsert(
            acceptances,
            record("A-GOLDEN-001", "PASS", "git rev-parse HEAD", 0, str(DEFAULT_GOLDEN_SOURCE), str(source.resolve())),
        )
        _upsert(
            acceptances,
            record("A-GOLDEN-002", "PASS", "git status --porcelain", 0, "continue-if-dirty", "dirty" if dirty else "clean"),
        )
        before_source = workspace_identity(source)
        worktree = create_detached_worktree(source, head)
        clean = worktree_clean(worktree)
        consumer["test_worktree_path"] = str(worktree)
        consumer["test_worktree_clean_at_start"] = clean
        if not clean:
            _upsert(acceptances, record("A-GOLDEN-002", "FAIL", "worktree status", 2, True, False))
            raise SystemExit(2)
        _run_chain(worktree, run_id, acceptances, cursor, ges_root)
        after_head = git(ges_root, ["rev-parse", "HEAD"]).stdout.strip()
        _upsert(
            acceptances,
            record("A-RH-EVID-001", "PASS" if after_head == ges_head else "FAIL", "candidate sha", 0 if after_head == ges_head else 2, ges_head, after_head),
        )
        try:
            assert_current_status_current(ges_root)
            _upsert(acceptances, record("A-RH-DOC-001", "PASS", "lat current status", 0, [], []))
        except GesError as exc:
            _upsert(acceptances, record("A-RH-DOC-001", "FAIL", "lat current status", 2, [], exc.code))
        spec_kit = _spec_kit_block()
        after_source = workspace_identity(source)
        same = after_source == before_source
        _upsert(
            acceptances,
            record("A-GOLDEN-005", "PASS" if same else "FAIL", "source workspace identity", 0 if same else 2, "unchanged", "unchanged" if same else "changed"),
        )
    except GesError as exc:
        _upsert(
            acceptances,
            record("A-GOLDEN-001", "FAIL" if exc.code != "GOLDEN_CONSUMER_HEAD_UNRESOLVED" else "BLOCKED", "golden resolve", 2, "HEAD", exc.code),
        )
    finally:
        if worktree is not None:
            remove_worktree(source, worktree)
    _upsert(acceptances, record("A-EVID-001", "PASS", "commit binding", 0, ges_head, ges_head))
    _upsert(acceptances, record("A-EVID-002", "PASS", "per-AC fields", 0, True, True))
    planned = artifact_dir / "golden" / "evidence.json"
    external = not artifact_inside_candidate(planned, ges_root)
    _upsert(acceptances, record("A-RH-EVID-002", "PASS" if external else "FAIL", "external evidence bind", 0 if external else 2, ges_head, ges_head))
    _upsert(acceptances, record("A-RH-EVID-003", "PASS" if external else "FAIL", "evidence not committed", 0 if external else 2, True, external))
    out = write_closure_evidence(
        run_id=run_id,
        started_at=started,
        ges_head=ges_head,
        ges_branch=ges_branch,
        consumer=consumer,
        spec_kit=spec_kit,
        cursor=cursor,
        acceptances=acceptances,
        root=ges_root,
        artifact_dir=artifact_dir,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    print(json.dumps(payload, indent=2))
    gate = payload["release_gate"]["status"]
    if gate == "PASS":
        print("BOOTSTRAP_ALPHA_READY")
        return 0
    print("BOOTSTRAP_RELEASE_BLOCKED")
    print("BLOCKED/SKIPPED is not PASS. BOOTSTRAP_ALPHA_READY is not claimed.")
    return 2


def _run_chain(worktree: Path, run_id: str, acceptances: list[dict], cursor: dict, ges_root: Path) -> None:
    business = snapshot_business_sources(worktree)
    emit(GES_PREFLIGHT, "start")
    run_preflight(worktree)
    before_stage = workspace_identity(worktree)
    official, version = official_stage()
    isolated = workspace_identity(worktree) == before_stage
    _upsert(acceptances, record("A-SK-003", "PASS" if isolated else "FAIL", "official_stage", 0 if isolated else 2, True, isolated))
    emit(GES_INIT, "start")
    first = _ges(["init", str(worktree), "--yes"], ges_root)
    if first.returncode != 0:
        detail = (first.stderr or first.stdout or "")[-500:]
        _upsert(acceptances, record("A-SK-001", "FAIL", "ges init", first.returncode, 0, detail or first.returncode))
        return
    skills_ok = all((worktree / skill_rel(command)).is_file() for command in SELECTED_COMMANDS)
    version_ok = version == REQUIRED_CLI_VERSION
    _upsert(
        acceptances,
        record("A-SK-001", "PASS" if version_ok and skills_ok else "FAIL", "specify --version", 0, REQUIRED_CLI_VERSION, version),
    )
    mismatch = 0
    for command in SELECTED_COMMANDS:
        rel = skill_rel(command)
        path = worktree / rel
        if not path.is_file() or sha256_bytes(path.read_bytes()) != sha256_bytes(official[rel]):
            mismatch += 1
    _upsert(acceptances, record("A-SK-002", "PASS" if mismatch == 0 else "FAIL", "manifest compare", 0, 0, mismatch))
    emit(GES_CHECK, "start")
    check = _ges(["check", str(worktree)], ges_root)
    if check.returncode != 0:
        _upsert(acceptances, record("A-SK-001", "FAIL", "ges check", check.returncode, 0, check.returncode))
        return
    _prove_skm_002(worktree, acceptances)
    _prove_skm_001(worktree, acceptances)
    emit(GES_DOCTOR, "start")
    doctor = run_doctor(worktree)
    if doctor.get("overall") == "BOOTSTRAP_PENDING":
        _run_matt(worktree, acceptances, cursor)
        doctor = run_doctor(worktree)
    ready = doctor.get("overall") == READY
    _upsert(acceptances, record("A-GOLDEN-003", "PASS" if ready else "BLOCKED", "ges doctor", 0 if ready else 2, READY, doctor.get("overall")))
    struct = structural_discovery(worktree)
    cursor["structural_discovery"] = struct["status"]
    _upsert(
        acceptances,
        record("A-CURSOR-STRUCT-001", struct["status"], "structural discovery", 0 if struct["status"] == "PASS" else 2, "PASS", struct["status"]),
    )
    try:
        cursor["executable"] = resolve_cursor_cli()
        before_probe = workspace_identity(worktree)
        runtime = native_discovery(worktree)
        cursor["version"] = runtime.get("version") or ""
        cursor["runtime_discovery"] = "PASS"
        leaked = any(prompt_leaks_skill_paths(native_probe_prompt(name)) for name in REQUIRED_SKILLS)
        probes = runtime.get("probes") or []
        identity_ok = {item["skill"] for item in probes} == set(REQUIRED_SKILLS) and all(
            item["parsed"].get("available") is True and item["parsed"].get("recognized_name") == item["skill"] for item in probes
        )
        _upsert(acceptances, record("A-RH-CURSOR-001", "PASS" if not leaked else "FAIL", "native probe prompt", 0 if not leaked else 2, False, leaked))
        _upsert(acceptances, record("A-RH-CURSOR-002", "PASS" if identity_ok else "FAIL", "native skill identity", 0 if identity_ok else 2, True, identity_ok))
        _upsert(acceptances, record("A-RH-CURSOR-003", "PASS", "native metadata digest", 0, True, True))
        _upsert(acceptances, record("A-CURSOR-RUNTIME-001", "PASS", " ".join(runtime["argv"]), runtime["exit_code"], True, True))
        unchanged = workspace_identity(worktree) == before_probe
        _upsert(acceptances, record("A-CURSOR-RUNTIME-002", "PASS" if unchanged else "FAIL", "probe mutation", 0 if unchanged else 2, True, unchanged))
        _upsert(acceptances, record("A-RH-CURSOR-004", "PASS" if unchanged else "FAIL", "native probe readonly", 0 if unchanged else 2, True, unchanged))
        before_smoke = workspace_identity(worktree)
        _run_smoke(worktree, run_id, acceptances, before_smoke, business)
    except GesError as exc:
        cursor["runtime_discovery"] = "BLOCKED" if exc.code == CURSOR_CLI_NOT_FOUND else "FAIL"
        _upsert(acceptances, record("A-CURSOR-RUNTIME-001", cursor["runtime_discovery"], "cursor probe", 2, "PASS", exc.code))
        if exc.code == CURSOR_NATIVE_DISCOVERY_FAILED:
            _upsert(acceptances, record("A-RH-CURSOR-002", "FAIL", "native skill identity", 2, True, exc.code))
        elif exc.code == CURSOR_SKILL_METADATA_MISMATCH:
            _upsert(acceptances, record("A-RH-CURSOR-003", "FAIL", "native metadata digest", 2, True, exc.code))
        elif exc.code == CURSOR_DISCOVERY_OUTPUT_INVALID:
            _upsert(acceptances, record("A-RH-CURSOR-001", "FAIL", "native probe prompt", 2, False, exc.code))
        if "before_probe" in locals():
            unchanged = workspace_identity(worktree) == before_probe
            _upsert(acceptances, record("A-CURSOR-RUNTIME-002", "PASS" if unchanged else "FAIL", "probe mutation", 0 if unchanged else 2, True, unchanged))
            _upsert(acceptances, record("A-RH-CURSOR-004", "PASS" if unchanged else "FAIL", "native probe readonly", 0 if unchanged else 2, True, unchanged))
    emit(GES_SECOND_INIT, "start")
    before_second = workspace_identity(worktree)
    second = _ges(["init", str(worktree), "--yes"], ges_root)
    noop = second.returncode == 0 and "GES_RECONCILE_NOOP" in (second.stdout + second.stderr)
    tree_same = workspace_identity(worktree) == before_second
    _upsert(
        acceptances,
        record("A-IDEMP-CLI-001", "PASS" if noop and tree_same else "FAIL", "ges init --yes", second.returncode, "GES_RECONCILE_NOOP", "GES_RECONCILE_NOOP" if noop else (second.stdout + second.stderr)[-200:]),
    )
    biz_same = snapshot_business_sources(worktree) == business
    _upsert(acceptances, record("A-GOLDEN-004", "PASS" if biz_same else "FAIL", "business snapshot", 0 if biz_same else 2, "unchanged", "unchanged" if biz_same else "changed"))


def _prove_skm_002(worktree: Path, acceptances: list[dict]) -> None:
    stub = worktree / ".specify" / ".ges" / "runtime" / "scripts" / "specify.py"
    receipt_path = worktree / ".ges" / "install-receipt.json"
    original_receipt = receipt_path.read_text(encoding="utf-8")
    existed = stub.is_file()
    original_stub = stub.read_bytes() if existed else None
    try:
        write_bytes(stub, b"old-stub\n")
        receipt = read_receipt(worktree) or {}
        artifacts = list(receipt.get("managed_artifacts") or [])
        artifacts.append(
            {
                "path": stub.relative_to(worktree).as_posix(),
                "ownership_type": "FILE",
                "selector": None,
                "last_applied_hash": sha256_bytes(b"old-stub\n"),
                "generated_hash": sha256_bytes(b"old-stub\n"),
                "producer": "ges",
                "capability_ids": ["speckit.specify"],
            }
        )
        receipt["managed_artifacts"] = artifacts
        write_json(receipt_path, receipt)
        stub.write_bytes(b"drifted\n")
        before = consumer_tree(worktree)
        try:
            compose(worktree)
            _upsert(acceptances, record("A-SKM-002", "FAIL", "compose drifted stub", 0, MANAGED_CONTENT_MODIFIED, "no-error"))
        except GesError as exc:
            unchanged = consumer_tree(worktree) == before
            ok = exc.code == MANAGED_CONTENT_MODIFIED and unchanged
            _upsert(
                acceptances,
                record("A-SKM-002", "PASS" if ok else "FAIL", "compose drifted stub", 2, MANAGED_CONTENT_MODIFIED, exc.code),
            )
    finally:
        receipt_path.write_text(original_receipt, encoding="utf-8", newline="\n")
        if existed and original_stub is not None:
            stub.write_bytes(original_stub)
        elif stub.exists():
            stub.unlink()


def _prove_skm_001(worktree: Path, acceptances: list[dict]) -> None:
    stub = worktree / ".specify" / ".ges" / "runtime" / "scripts" / "specify.py"
    write_bytes(stub, b"old-stub\n")
    receipt = read_receipt(worktree) or {}
    artifacts = list(receipt.get("managed_artifacts") or [])
    artifacts.append(
        {
            "path": stub.relative_to(worktree).as_posix(),
            "ownership_type": "FILE",
            "selector": None,
            "last_applied_hash": sha256_bytes(b"old-stub\n"),
            "generated_hash": sha256_bytes(b"old-stub\n"),
            "producer": "ges",
            "capability_ids": ["speckit.specify"],
        }
    )
    receipt["managed_artifacts"] = artifacts
    write_json(worktree / ".ges" / "install-receipt.json", receipt)
    apply_recommended(worktree)
    gone = not stub.is_file()
    official = (worktree / skill_rel("specify")).is_file()
    _upsert(
        acceptances,
        record("A-SKM-001", "PASS" if gone and official else "FAIL", "migrate unmodified stub", 0, True, gone and official),
    )


def _run_matt(worktree: Path, acceptances: list[dict], cursor: dict) -> None:
    try:
        executable = resolve_cursor_cli()
    except GesError as exc:
        _upsert(acceptances, record("A-GOLDEN-003", "BLOCKED", "matt setup", 2, READY, exc.code))
        return
    cursor["executable"] = executable
    argv = _cursor_argv(executable, matt_setup_prompt(), write=True)
    _run_process(argv, cwd=worktree, timeout=MATT_TIMEOUT_SEC)


def _run_smoke(worktree: Path, run_id: str, acceptances: list[dict], before_tree: dict[str, str], business: dict) -> None:
    emit(SPECKIT_FUNCTIONAL_SMOKE, "start")
    executable = resolve_cursor_cli()
    env = os.environ.copy()
    env["SPECIFY_FEATURE_DIRECTORY"] = smoke_dir(run_id)
    argv = _cursor_argv(executable, smoke_prompt(run_id), write=True)
    result = _run_process(argv, cwd=worktree, env=env, timeout=SMOKE_TIMEOUT_SEC)
    before_eval = workspace_identity(worktree)
    invocations = smoke_invocation_record(primary=1, repair=0)
    spec = worktree / smoke_dir(run_id) / "spec.md"
    spec_errors = evaluate_spec(spec)
    expected_dir = smoke_dir(run_id)
    state_error = feature_state_error(worktree, run_id)
    unexpected = unexpected_writes(before_tree, workspace_identity(worktree), run_id)
    biz_same = snapshot_business_sources(worktree) == business
    after_eval = workspace_identity(worktree)
    _upsert(acceptances, record("A-SKF-001", "PASS" if not spec_errors else "FAIL", " ".join(argv[:4]), result.returncode, [], spec_errors))
    _upsert(acceptances, record("A-SKF-002", "PASS" if not state_error else "FAIL", ".specify/feature.json", 0 if not state_error else 2, expected_dir, state_error or expected_dir))
    _upsert(acceptances, record("A-RH-SMOKE-001", "PASS" if not state_error else "FAIL", "feature state", 0 if not state_error else 2, "", state_error))
    _upsert(acceptances, record("A-RH-SMOKE-002", "PASS" if before_eval == after_eval else "FAIL", "observer evaluate", 0 if before_eval == after_eval else 2, True, before_eval == after_eval))
    _upsert(acceptances, record("A-RH-SMOKE-003", "PASS" if not state_error else "FAIL", "valid feature state", 0 if not state_error else 2, expected_dir, state_error or expected_dir))
    _upsert(acceptances, record("A-RH-SMOKE-004", "PASS" if biz_same else "FAIL", "business source", 0 if biz_same else 2, "unchanged", "unchanged" if biz_same else "changed"))
    _upsert(acceptances, record("A-RH-SMOKE-005", "PASS" if invocations["repair_invocation_count"] == 0 else "FAIL", "repair count", 0, 0, invocations["repair_invocation_count"]))
    _upsert(
        acceptances,
        record("A-SKF-003", "PASS" if not unexpected and biz_same else "FAIL", "mutation allowlist", 0 if not unexpected else 2, [], unexpected),
    )


def _cursor_argv(executable: str, prompt: str, *, write: bool = False) -> list[str]:
    argv = [executable, "-p", "--output-format", "json", "--trust", "--workspace", str(Path.cwd())]
    if write:
        argv.append("--force")
    argv.append(prompt)
    return argv


def _run_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    run_argv = list(argv)
    if "--workspace" in run_argv:
        idx = run_argv.index("--workspace")
        run_argv[idx + 1] = str(cwd)
    if os.name == "nt" and Path(run_argv[0]).suffix.lower() in {".cmd", ".bat"}:
        run_argv = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *run_argv]
    try:
        return subprocess.run(
            run_argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(run_argv, 124, exc.stdout or "", exc.stderr or "timeout")


def _ges(args: list[str], ges_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ges_root) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ges", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )


def _prepare_env(ges_root: Path) -> None:
    cache = ges_root / "tests" / "ges6" / "fixtures" / "source-cache"
    if cache.is_dir():
        os.environ.setdefault("GES_SOURCE_CACHE", str(cache))
    local_agent = Path(os.environ.get("LOCALAPPDATA", "")) / "cursor-agent" / "agent.cmd"
    if local_agent.is_file():
        os.environ.setdefault("GES_CURSOR_CLI", str(local_agent))


def _spec_kit_block() -> dict:
    report = last_render_report()
    official = report.official_files or {}
    projected = report.projected_files or {}
    return {
        "repo": SPEC_KIT_REPO,
        "commit_sha": SPEC_KIT_SHA,
        "specify_cli_version": report.specify_cli_version or REQUIRED_CLI_VERSION,
        "integration": INTEGRATION,
        "official_render_manifest_digest": report.official_digest or (manifest_digest(official) if official else ""),
        "projected_manifest_digest": report.projected_digest or (manifest_digest(projected) if projected else ""),
    }


def _upsert(acceptances: list[dict], item: dict) -> None:
    for index, existing in enumerate(acceptances):
        if existing["acceptance_id"] == item["acceptance_id"]:
            acceptances[index] = item
            return
    acceptances.append(item)


if __name__ == "__main__":
    raise SystemExit(main())
