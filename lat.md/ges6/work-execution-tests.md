---
lat:
  require-code-mention: true
---
# Work Execution Tests

Synthetic oracles for Work v2, migration, work-local capabilities, host binding, Execution Gate, and Alpha.4/5 closure markers.

## Work v2

Create emits a v2 contract; unknown and Composer ids never write.

### Create emits v2 with host

`create_work` writes `ges.work.v2` with `ges-native` profile, explicit host, and empty `required`.

### Unknown capability rejected

Adding an id absent from `providers.yaml` raises `WORK_CAPABILITY_NOT_FOUND` with zero tree mutation.

### Composer capability rejected

`matt.*` / `speckit.*` / `superpowers.*` raise `WORK_CAPABILITY_UNSUPPORTED` with zero mutation.

## Migrate

Migration is explicit and atomic; reads never rewrite v1.

### Explicit migrate preserves fields

`migrate_work` keeps title/owner/artifacts and adds v2 capabilities/execution; repeat raises `WORK_ALREADY_V2`.

### Show does not migrate

`ges work show` leaves v1 file bytes unchanged.

## Work capability

Add/remove is idempotent and never edits project policy.

### Add remove idempotent

First add records RTK once; repeat keeps one row; remove clears; remove-missing raises `WORK_CAPABILITY_NOT_BOUND`.

### Policy digest unchanged

Work capability mutation leaves `.ges/capabilities/policy.yaml` bytes unchanged.

## Create CLI

Host is mandatory at the CLI boundary.

### Host required

`ges work create` without `--host` exits via argparse validation.

## Binding

Host probes classify Cursor/Codex/Hermes registration without writes.

### Cursor bound

Valid Cursor hooks with resolvable RTK rewrite yield `BOUND`.

### Codex bound

Valid Codex hooks with RTK rewrite yield `BOUND`.

### Hermes bound

Hermes plugin present and enabled yields `BOUND`.

### Invalid registration unbound

Hook file without valid RTK rewrite is `UNBOUND` or `UNPROVEN`, never `BOUND`.

### Probe writes nothing

Binding probe leaves the consumer tree digest unchanged.

### Identity changes detected

Distinct observation digests produce distinct binding identities.

## Execution gate

Effective required, FAIL vs BLOCKED, and readiness JSON.

### Empty required may pass

Gate A PASS with empty effective required yields `EXECUTION_READY`.

### V1 is blocked

Evaluating execution on v1 returns `WORK_EXECUTION_CONTRACT_MISSING`.

### Policy union

Project `required` unions into `effective_required` when work required is empty.

### Prohibited fails

Prohibited ∩ effective required yields FAIL.

### Missing installed blocks

Required but not installed yields `WORK_CAPABILITY_REQUIRED_MISSING` BLOCKED.

### JSON schema

Execution payload uses `ges.execution-readiness.v1`.

### Ready path

Installed + READY + BOUND with Gate A PASS yields `EXECUTION_READY` exit 0.

### CLI execution

`ges gate execution` prints readiness JSON and returns the gate exit code.

## Regression

Prior Gate A verdicts and evidence-snapshot stay frozen.

### Gate A verdicts preserved

Valid SPEC+PLAN intake still returns `WORK_READY`.

### Unchanged

`ges.evidence-snapshot.v1` still forbids a capabilities field.

## Alpha4 closure

Required AC set is frozen; READY is withheld on BLOCKED.

### Required set frozen

`REQUIRED_ALPHA4_ACCEPTANCES` is exactly the Binding Q17 eleven ids.

### Blocked withholds ready

Missing Golden consumer never prints `ALPHA4_CAPABILITY_GOVERNANCE_READY`.

## Alpha5 golden

G2 environment gaps are BLOCKED, not a READY claim.

### Blocked is not ready

Missing Golden consumer prints `GOLDEN_ALPHA5_EXECUTION_BLOCKED` without `ALPHA5_WORK_EXECUTION_READY`.
