---
lat:
  require-code-mention: true
---
# Bootstrap Acceptance Tests

Synthetic oracles for the Alpha.1 first-install loop: preflight, Spec Kit runtime, collision, doctor, transaction, and frozen Desired State.

## TEST-A-BOOT-001

`ges doctor --preflight` must leave the consumer tree byte-identical when prerequisites pass.

## TEST-A-CAP-001

Default resolve must expose the frozen Alpha.1 set and omit forbidden or optional capabilities.

## TEST-A-CAP-002

Selecting grill-with-docs must close grilling and domain-modeling without owner-domain conflicts.

## TEST-A-SPECKIT-001

An existing `.specify` directory must not skip selected Spec Kit runtime projection under `.specify/.ges`.

## TEST-A-SPECKIT-002

Rendered Spec Kit commands and scripts must contain no unresolved `{SCRIPT}` or `__SPECKIT_COMMAND_*` tokens.

## TEST-A-SPECKIT-003

User-owned `.specify/constitution.md` and `.specify/specs/**` must stay byte-identical across init.

## TEST-A-SPECKIT-004

Doctor must resolve selected constitution, specify and plan runtime dependencies without creating a feature.

## TEST-A-COLLISION-001

A pre-existing different skill file without receipt must raise `UNMANAGED_PATH_CONFLICT` with zero mutations.

## TEST-A-COLLISION-002

A pre-existing identical desired file must be adopted and recorded in the receipt.

## TEST-A-COLLISION-003

Same path with incompatible ownership, such as a directory where a FILE is required, must block.

## TEST-A-MATT-001

Matt setup skill is installed, `docs/agents` is not fabricated, and overall readiness is `BOOTSTRAP_PENDING`.

## TEST-A-MATT-002

When Matt project docs already exist, doctor reports `matt_project_bootstrap` PASS and overall READY.

## TEST-A-ROUTE-001

The AGENTS managed section must list the frozen Owner to Skill routing names.

## TEST-A-ROUTE-002

User bytes outside the AGENTS marker stay identical, including files without a trailing newline.

## TEST-A-CHECK-001

After apply, persisted project, profile, lock and receipt documents validate against their v2/v1 schemas.

## TEST-A-CHECK-002

Recomputed capability closure from the frozen requested set must equal the lock closure.

## TEST-A-CHECK-003

Every lock source SHA must equal the current catalog pin for that source.

## TEST-A-CHECK-004

Available offline cache provenance must verify against the pin manifest digest.

## TEST-A-CHECK-005

Every managed FILE identity must still match the receipt last-applied hash.

## TEST-A-CHECK-006

The AGENTS.md managed section identity must still match the receipt last-applied hash.

## TEST-A-CHECK-007

Every selected skill directory required by the closed set must exist on disk.

## TEST-A-CHECK-008

Selected Spec Kit command, script and template runtime files must exist under `.specify/.ges`.

## TEST-A-CHECK-009

The business-source fingerprint captured at apply must still match the working tree.

## TEST-A-CHECK-010

Recompose from the frozen Desired State after a successful apply must be a NOOP plan.

## TEST-A-DOCTOR-001

Doctor preflight observes Python, git and Cursor prerequisites and writes nothing.

## TEST-A-DOCTOR-002

After install without Matt project docs, doctor overall is `BOOTSTRAP_PENDING` with exit 0.

## TEST-A-DOCTOR-003

After Matt project docs exist, doctor overall is READY.

## TEST-A-TXN-001

Failure before commit leaves the consumer tree unchanged.

## TEST-A-TXN-002

Failure after the first consumer write rolls the managed scope back to T0.

## TEST-A-TXN-003

Failure after commit during post-check rolls the managed scope back to T0.

## TEST-A-TXN-004

Rollback failure raises `TRANSACTION_ROLLBACK_FAILED` and retains the T0 backup directory.

## TEST-A-STATE-001

Changing the requested set after first install raises `RECONFIGURE_NOT_SUPPORTED` with zero mutations.

## TEST-A-PKG-001

Receipt and package declare the same product and distribution versions.

## TEST-NEG-001

Unknown different skill content is an unmanaged collision.

## TEST-NEG-002

A tampered offline source cache fails provenance verification.

## TEST-NEG-003

A rendered Spec Kit artifact that still contains `{SCRIPT}` or `__SPECKIT_COMMAND_*` must raise `SPEC_KIT_UNRESOLVED_TOKEN`.

## TEST-NEG-004

A selected Spec Kit command missing its required runtime file must raise `SPEC_KIT_RUNTIME_INCOMPLETE`.

## TEST-NEG-005

An apply that attempts to write under a business-source root must raise `BUSINESS_SOURCE_MODIFICATION_FORBIDDEN`.

## TEST-NEG-006

`--exclude` after install is treated as unsupported reconfiguration.

## TEST-NEG-007

Editing a receipt-owned managed FILE after install must fail `ges check` or raise `MANAGED_CONTENT_MODIFIED`.

## TEST-B8

When `.specify` is absent, first install still materializes the selected Spec Kit runtime under `.specify/.ges`.

## TEST-B9

When `.specify` exists but its GES runtime is empty, first install still writes the required runtime files.

## TEST-B10

User-owned `.specify/specs/**` files stay byte-identical across a first install.

## TEST-B11

User-owned `.specify/constitution.md` is preserved and the plan reports `LEGACY_OR_USER_SPEC_STATE`.

## TEST-B12

After a receipt exists, changing the requested capability set is `RECONFIGURE_NOT_SUPPORTED` with zero mutations.

## TEST-A-CURSOR-001

Selected Matt, Spec Kit and Superpowers skills are present as Cursor-discoverable SKILL.md files.

## TEST-A-IDEMP-001

A second compose after a successful first install must be a NOOP with no duplicate AGENTS markers.
