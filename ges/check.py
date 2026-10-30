from __future__ import annotations

from pathlib import Path

from ges.catalog.loader import load_catalog
from ges.compose import compose
from ges.errors import GES_CHECK_FAILED, GES_CHECK_PASS, GesError
from ges.harness_adapters.agents_md import count_markers, read_agents, section_hash
from ges.io import sha256_file
from ges.reconciler.business_guard import is_overlay_fingerprint
from ges.reconciler.guard import assert_allowed, assert_not_business_source
from ges.reconciler.hashes import artifact_index
from ges.reconciler.state import read_lock, read_profile, read_project, read_receipt, validate_payload
from ges.resolver.capability_graph import detect_conflicts
from ges.resolver.selection import resolve_selection
from ges.source_adapters.cache import ensure_source, verify_manifest
from ges.source_adapters.speckit_render import SELECTED_COMMANDS, skill_rel
from ges.stagelog import CHECK, emit


def run_check(repo: Path) -> str:
    emit(CHECK, "start", repo=str(repo))
    repo = repo.expanduser().resolve()
    project = read_project(repo)
    profile = read_profile(repo)
    lock = read_lock(repo)
    receipt = read_receipt(repo)
    if not all([project, profile, lock, receipt]):
        raise GesError(GES_CHECK_FAILED, "missing .ges project state (project/profile/lock/receipt)")
    validate_payload("ges.project.v2.json", project, code=GES_CHECK_FAILED)
    validate_payload("ges.repo-profile.v2.json", profile, code=GES_CHECK_FAILED)
    validate_payload("ges.lock.v1.json", lock, code=GES_CHECK_FAILED)
    validate_payload("ges.install-receipt.v2.json", receipt, code=GES_CHECK_FAILED)

    catalog = load_catalog()
    product = catalog.profiles[project.get("profile") or "brownfield-product-app"]
    requested = list((project.get("capabilities") or {}).get("requested") or [])
    resolution = resolve_selection(catalog, product, requested=requested)
    closed = list(lock.get("resolved_capabilities") or lock.get("capabilities") or [])
    if resolution.closed != closed:
        raise GesError(GES_CHECK_FAILED, "desired closure does not match lock")
    conflicts = detect_conflicts(catalog, closed)
    if conflicts:
        raise GesError(GES_CHECK_FAILED, "ownership conflict present in lock", details={"conflicts": conflicts})

    for source_id, meta in (lock.get("sources") or {}).items():
        pin = catalog.sources[source_id]
        if meta.get("commit_sha") != pin.commit_sha:
            raise GesError(GES_CHECK_FAILED, f"lock SHA for {source_id} does not match catalog pin")
        root = ensure_source(pin)
        verify_manifest(root, pin)

    for cap_id in closed:
        cap = catalog.get(cap_id)
        if cap.projection_type == "virtual" or not cap.skill_name:
            continue
        skill_dir = (
            repo / ".cursor" / "skills" / cap.skill_name
            if cap.projection_type == "speckit-capability"
            else repo / ".agents" / "skills" / cap.skill_name
        )
        if not skill_dir.exists():
            raise GesError(GES_CHECK_FAILED, f"capability {cap_id} is not projected")

    for command in SELECTED_COMMANDS:
        if f"speckit.{command}" not in closed:
            continue
        if not (repo / skill_rel(command)).is_file():
            raise GesError(GES_CHECK_FAILED, f"Spec Kit runtime missing: {skill_rel(command)}")

    for rel, meta in artifact_index(receipt).items():
        path = repo / rel
        if not path.is_file():
            raise GesError(GES_CHECK_FAILED, f"managed file missing: {rel}")
        current = (
            section_hash(path.read_text(encoding="utf-8"))
            if meta.get("ownership_type") == "SECTION" or rel == "AGENTS.md"
            else sha256_file(path)
        )
        if current != meta.get("last_applied_hash"):
            raise GesError(GES_CHECK_FAILED, f"managed hash mismatch: {rel}")
        assert_allowed(rel)
        assert_not_business_source(rel)

    agents = read_agents(repo)
    if count_markers(agents) != 1:
        raise GesError(GES_CHECK_FAILED, "AGENTS.md must contain exactly one GES marker")

    stored = lock.get("business_source_fingerprint")
    if stored and not is_overlay_fingerprint(stored):
        raise GesError(
            GES_CHECK_FAILED,
            "business source fingerprint schema is stale; run ges init --yes",
        )

    ctx = compose(repo, persist_profile=False)
    if not ctx.plan.noop:
        raise GesError(GES_CHECK_FAILED, "working tree is not reconciled to desired state")

    emit(CHECK, "pass")
    return GES_CHECK_PASS
