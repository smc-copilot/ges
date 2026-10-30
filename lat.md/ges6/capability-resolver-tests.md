---
lat:
  require-code-mention: true
---
# Capability Resolver Tests

Synthetic oracles for the parallel Capability Plan, RTK probe, doctor warnings, and Composer freeze isolation.

## Plan

Same analyzer facts must produce the same ephemeral plan without LLM calls.

### Same facts same plan

Repeating resolve on identical lifecycle, layout, and kind yields equal plan bytes.

### Zero LLM tokens

`llm_token_usage` is always 0.

### Brownfield recommends RTK

Brownfield or monorepo places `command-output.rtk` in recommended with reason equal to `kind`.

### Greenfield single is optional

Greenfield plus single layout places RTK in optional, not recommended.

### Plan does not mutate requested

Building a plan leaves `lock.requested` unchanged and does not raise RECONFIGURE_NOT_SUPPORTED.

## Probe

PATH and `--version` classify missing, NOT_READY, and READY.

### Missing rtk

No `rtk` on PATH yields status `missing`.

### Invalid version

A binary whose `--version` fails yields `NOT_READY`.

### Ready version

A successful `--version` parse yields `READY` and a non-empty version.

## Doctor

Doctor JSON carries capabilities without blocking overall on recommended RTK.

### Doctor lists capabilities

`run_doctor` includes a `command-output.rtk` row in `capabilities`.

### Missing is warning not blocked

Recommended missing adds a WARNING and overall is not BLOCKED because of RTK.

## Init

Init prints the recommendation and does not treat missing RTK as FAIL.

### Init prints recommendation

Rendered init text contains `Capability Recommendation`.

## Isolation

Governance evidence schema must stay free of capability fields.

### Evidence snapshot unchanged

`ges.evidence-snapshot.v1` still forbids extra properties and has no capabilities field.
