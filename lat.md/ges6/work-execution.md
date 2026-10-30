# Work Execution

Alpha.5 binds Work v2 capability requirements to host RTK registration and an Execution Gate that proves INSTALLED, READY, and BOUND before `EXECUTION_READY`.

Product bumps to `6.0.0-alpha.5` only after Alpha.5 Release Gate PASS. Gate A/B and `ges.evidence-snapshot.v1` are unchanged. See [[work-execution-tests]], [[capability-governance]], and [[governance-backplane]].

## Work v2

New work records carry `capabilities.required` and `execution.profile/host`.

`ges work create` requires `--host` (`cursor|codex|hermes`), defaults `required=[]`, and emits only `ges.work.v2`. Composer ids and unknown parallel ids are rejected before write. Implementation: [[ges/governance/registry.py#create_work]].

## Migration

Legacy v1 works migrate only through an explicit CLI.

`ges work migrate --host` preserves semantic fields and artifacts, adds the v2 contract, and never auto-runs on show/update. Failures roll back bytes. See [[ges/governance/registry.py#migrate_work]].

## Work capability

Work-local required ids are edited without touching project policy.

`ges work capability add|remove` mutates only the Work file. Prohibited ids fail closed. Remove of a missing binding raises `WORK_CAPABILITY_NOT_BOUND`. See [[ges/governance/registry.py#add_work_capability]].

## Host binding

Binding probes are read-only observations of Cursor, Codex, or Hermes RTK registration.

Statuses are `BOUND`, `UNBOUND`, `UNPROVEN`, or `UNSUPPORTED`. Digests only — no host config bodies in logs. Mid-gate digest change raises `CAPABILITY_BINDING_CHANGED_DURING_EVALUATION`. See [[ges/providers/rtk_binding.py#probe_binding]].

## Execution Gate

`ges gate execution` unions policy and work required ids, then requires installed + READY + BOUND.

Empty `effective_required` may PASS when Gate A PASS and the contract is valid v2. FAIL covers contract/policy conflicts; BLOCKED covers missing install, provider, or binding. Output schema is `ges.execution-readiness.v1`. See [[ges/governance/execution_gate.py#evaluate_execution]].

## Golden and release

Alpha.4 closure and Alpha.5 Golden prove real-consumer lifecycle without false READY.

Alpha.4 prints `ALPHA4_CAPABILITY_GOVERNANCE_READY` only when the frozen 11 ACs and regressions PASS. Alpha.5 Golden G1 (empty required) and G2 (real RTK+host BOUND) gate `ALPHA5_WORK_EXECUTION_READY` and the `6.0.0-alpha.5` bump. Runners: [[ges/acceptance/run_alpha4_closure.py#main]], [[ges/acceptance/run_golden_work_execution.py#main]], [[ges/acceptance/run_alpha5_release.py#main]].
