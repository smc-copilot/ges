---
lat:
  require-code-mention: true
---
# GES 6 Acceptance Tests

A01–A26 prove the spec-hardened Composer on a synthetic brownfield fixture. A27 records the Golden Consumer detached-HEAD contract.

## A01 — Brownfield Detection

The analyzer must classify the Golden-shaped fixture as a brownfield monorepo without calling an LLM.

## A02 — Harness Detection

Cursor and Codex must be detected from `.cursor/` and `.codex/` so both harness adapters can project.

## A03 — Existing AGENTS Preservation

Bytes outside the GES marker must stay identical across apply so user routing text is never overwritten.

## A04 — Existing Spec Kit Preservation

An existing `.specify/` tree must be adopted. Constitution and user templates are not reinitialized.

## A05 — Legacy Detection

v5 lock presence must set `legacy_ges` and classify owned, absent and unknown files without deleting them on init.

## A06 — Capability Recommendation

The recommended set must come from the repo profile plus the brownfield-product-app catalog profile.

## A07 — Capability Exclusion

Removing a recommended capability must keep resolution legal and persist the exclusion in desired state.

## A08 — Dependency Closure

Selecting `matt.grill-with-docs` must automatically include `matt.grilling` and `matt.domain-modeling`.

## A09 — Ownership Conflict

Two Feature Spec owners at once must raise `CAPABILITY_OWNERSHIP_CONFLICT` and block apply.

## A10 — Selective Install

Unresolved Matt, Spec Kit and Superpowers skills must not be materialized by Composer.

## A11 — Upstream Lock

Matt, Spec Kit and Superpowers must each lock a 40-character immutable commit SHA.

## A12 — Idempotent Apply

The first apply writes changes; the second apply is `GES_RECONCILE_NOOP` with zero content change.

## A13 — Managed Update

A pinned skill upgrade may change only GES-managed content. Business source and user AGENTS text stay intact.

## A14 — User Modification Conflict

A user edit to the GES marker section must raise `MANAGED_CONTENT_MODIFIED` and must not be overwritten.

## A15 — Remove

`ges remove` deletes GES-owned projection and keeps user `.specify`, AGENTS body, third-party skills and governance kit.

## A16 — Business Source Guard

`apps/`, `services/`, `src/`, `packages/` and `contracts/` must stay byte-identical across apply, second apply and remove.

## A17 — Preview / Read-only Command Purity

analyze, diff, check, legacy inspect and init-before-confirm must leave the consumer tree byte-identical.

## A18 — Desired State Authority

When `project.yaml` requested is X, Product Profile defaults must not add a missing Y on diff or apply.

## A19 — Optional Selection Semantics

`superpowers.executing-plans` stays out of the initial requested set until the user explicitly enables it.

## A20 — Section-scoped Hashing

Edits outside the AGENTS marker must not raise `MANAGED_CONTENT_MODIFIED`; edits inside the marker must.

## A21 — Failure Atomicity

Injected apply failures after writes must restore the exact T0 snapshot, including a pre-existing `.ges` tree.

## A22 — Remove Drift Protection

Remove must abort with zero mutations when a managed FILE no longer matches `last_applied_hash`.

## A23 — Source Cache Integrity / Provenance

A tampered offline cache file must raise `SOURCE_CACHE_INTEGRITY_FAILED` and must not be trusted.

## A24 — Projection Collision

Two producers writing the same path with different content must raise `PROJECTION_PATH_CONFLICT` before apply.

## A25 — Analyzer Schema + Script Detection

Nested `package.json` scripts and tsconfig paths must be recorded; TypeScript requires real evidence.

## A26 — Spec Kit Pinned Adoption

Selected Spec Kit commands live under `.specify/.ges/commands` and wrappers cite repo, SHA and source path.

## A27 — Golden Consumer

Detached Golden HEAD on `smc-copilot-desktop` is the current consumer contract. Current status must not say the Golden Consumer is BLOCKED.
