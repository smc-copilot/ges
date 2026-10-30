---
lat:
  require-code-mention: true
---
# Capability Governance Tests

Synthetic oracles for the parallel overlay, `ges capability` CLI, policy override, and Composer freeze.

## Catalog

Package catalog remains RTK-only and rejects duplicate ids.

### Only RTK and duplicate block

Catalog load returns only `command-output.rtk`. A `providers.yaml` with a duplicate id raises BLOCK. Empty incompatible stays readable.

## Init

Composer apply must not create the consumer overlay.

### Init does not create overlay

`ges init` and compose leave `.ges/capabilities/` absent.

## Overlay

Add and remove write installed rows without thawing Composer.

### Add creates overlay and is idempotent

First add creates overlay files. Second add keeps a single installed id and leaves `lock.requested` unchanged.

### Composer add is frozen

Adding a `matt.*`, `speckit.*`, or `superpowers.*` id raises `COMPOSER_CAPABILITY_FROZEN`.

### Unknown id is not found

An id absent from `providers.yaml` raises `CAPABILITY_NOT_FOUND`.

### Prohibited add is blocked

Policy prohibited rejects add with `CAPABILITY_PROHIBITED`.

### Remove missing and last remove

Remove of a missing installed id errors. Successful remove keeps policy. Last remove leaves an empty installed file.

## List

List is read-only observation and always exits 0.

### List columns and exit zero

List prints id, resolver level, policy level, installed, status, and reason. Required-not-installed still exits 0 and writes nothing.

### Policy overrides resolver

A hand-edited policy bucket replaces the resolver level while reason stays analyzer `kind`.

## Doctor

Capability doctor is probe-only. Repo doctor overall ignores RTK overlay.

### Doctor id writes nothing

`ges capability doctor <id>` prints status JSON, writes no overlay, and works when overlay is absent.

### Doctor overall ignores RTK

Required or recommended RTK missing does not set doctor overall to BLOCKED.

## Isolation

Governance evidence and check stay free of capability overlay fields.

### Evidence snapshot unchanged

`ges.evidence-snapshot.v1` still forbids extra properties and has no capabilities field.
