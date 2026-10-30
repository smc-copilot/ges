---
lat:
  require-code-mention: true
---
# Governance Tests

Synthetic oracles for Alpha.2 Work registry, artifacts, policy, GitHub-backed evidence, gates, and Composer isolation.

## Governance init

Init must create a valid policy and works directory without touching Composer files.

### Init creates policy and works

`ges governance init` writes schema-valid policy.yaml and an empty works directory.

### Init is idempotent

A second init raises GOVERNANCE_ALREADY_INITIALIZED and changes no bytes.

## Work registry

Work IDs are explicit and CLOSED work is immutable.

### Create valid work

create with id/title/owner/risk/--host writes ges.work.v2 FEATURE/OPEN.

### Duplicate work is rejected

The same ID fails with WORK_ALREADY_EXISTS and original bytes unchanged.

### Closed work cannot update

update on CLOSED raises WORK_CLOSED_IMMUTABLE.

### Closed cannot reopen

A second close raises WORK_STATE_TRANSITION_INVALID.

## Artifacts

SPEC and PLAN bindings store exact raw SHA256 pointers.

### Link stores exact digest

Stored digest equals sha256 of the file bytes.

### Drift fails intake

Changing one byte makes gate intake FAIL with ARTIFACT_STALE.

### Path escape rejected

`../` is rejected with ARTIFACT_PATH_INVALID and no work mutation.

## Policy

Policy is a closed schema; HIGH cannot merge.

### Unknown field rejected

An extra executable field raises POLICY_SCHEMA_INVALID.

### HIGH blocks merge

HIGH risk yields BLOCKED and APPROVAL_REQUIRED_UNSUPPORTED.

### LOW may reach merge ready

Valid LOW facts can produce MERGE_READY when the PR fixture is green.

## Evidence

Evidence is provider-backed and bound to PR head.

### Success maps pass

SUCCESS checks become CI_CHECK PASS when subject equals head.

### Manual add unsupported

`ges evidence add` is UNSUPPORTED_OPERATION.

## Trace

Trace always emits required edges.

### Complete graph

A green fixture includes WORK SPEC PLAN PR COMMIT CI_CHECK REVIEW_DECISION.

### Missing review visible

A missing review decision still emits the graph with review status MISSING.

## Gates

Intake and merge return the PRD verdicts and exit codes.

### Intake work ready

Current SPEC and PLAN yield WORK_READY.

### Intake missing plan

A work without PLAN fails intake.

### Review missing

Merge without APPROVED is FAIL REVIEW_REQUIRED.

### Dirty tree

A tracked modification fails merge with WORKTREE_DIRTY.

### Pending check

A pending check fails merge with CI_CHECK_PENDING.

### Explain deterministic

The same snapshot yields identical reason codes and order.

## Read-only

Read-only commands do not write the consumer tree.

### Intake does not write

gate intake leaves consumer_tree unchanged.

## Composer isolation

Composer remove and apply rollback must not destroy governance files.

### Remove preserves governance

run_remove keeps `.ges/governance/works`.

### Snapshot excludes governance

snapshot_managed_scope does not record governance work files.

## External evidence

Backplane evidence binds the candidate SHA outside the candidate tree.

### Manifest binds candidate

write_backplane_evidence records the candidate SHA and schema-valid payload.
