---
lat:
  require-code-mention: true
---
# Large Repo Snapshot Tests

Synthetic oracles for Git-aware Business Source Guard v2, dirty/untracked overlays, write ledger, analyzer index, and fallback safety.

## Git inventory

NUL-safe Git inventory must expose only Git-visible business paths.

### Tracked index ignores generated trees

A repo with many ignored files still returns only the Git-visible tracked set.

### NUL-safe path parser

Space, unicode, and newline paths survive porcelain/ls-files `-z` parsing.

## Snapshot

Clean tracked files must not be rehashed; overlay protects dirty and untracked bytes.

### Clean tracked skips content hash

Ten thousand clean tracked files produce zero clean-tracked content hash calls.

### Clean tracked mutation fails

Editing a clean tracked file between T0 and T1 fails the compare.

### Dirty overlay unchanged passes

A pre-existing dirty file that stays byte-identical remains UNCHANGED.

### Dirty overlay byte change fails

A dirty file whose Git status stays modified but whose bytes change fails.

### Dirty file deletion fails

Deleting a dirty tracked file fails the compare.

### Untracked overlay unchanged passes

An existing non-ignored untracked file that stays identical remains UNCHANGED.

### Untracked create change remove fails

New, changed, or removed non-ignored untracked source fails.

## Special paths

Symlink identity is the link text; dirty submodules cannot silent PASS.

### Symlink uses link text

External target bytes may change; only a changed link string changes the snapshot.

### Dirty submodule blocks

An unresolvable dirty gitlink raises SUBMODULE_SOURCE_STATE_UNRESOLVED.

### Knowledge tree is skipped

`apps/knowledge` must not be content-hashed or walked; snapshot continues without reading that tree.

### Composer writes are skipped

Empty-root repos may still write `.ges`, skills, Spec Kit, `docs/agents`, and `AGENTS.md` without changing the business snapshot.

## Consistency

HEAD, index, and protected-byte races rollback or block.

### HEAD race blocks

A HEAD change after T0 raises BUSINESS_GIT_HEAD_CHANGED_DURING_APPLY.

### Index race blocks

An index change after T0 raises BUSINESS_GIT_INDEX_CHANGED_DURING_APPLY.

### Protected byte mutation blocks

Protected source mutation raises BUSINESS_SOURCE_MODIFICATION_FORBIDDEN.

## Write boundary

Ignored business paths stay unwritable.

### Ignored node_modules write denied

Writing `apps/**/node_modules/**` is rejected before mutation.

### Ledger has zero business writes

A successful mutation ledger records `business_root_write_count == 0`.

## Fallback

Guard failure is fail-closed.

### Non-git uses full exact guard

A non-Git fixture uses `full-sha256-fallback` and still detects byte changes.

### Git failure falls back

Injected Git inventory failure activates fallback and does not skip the guard.

## Upgrade

Older locks stored a per-file hash map. Check must not treat that as a current overlay snapshot.

### Legacy fingerprint is stale

A path-map fingerprint fails check with a stale-schema message, not a silent byte mismatch.

### Init noop refreshes overlay fingerprint

Same-set `ges init --yes` rewrites the lock fingerprint to the current overlay snapshot.

### Post-install business commits do not fail check

After install, ordinary business-source commits or untracked files must not fail `ges check` or `ges_core`.

## Analyzer

Detectors must not walk ignored trees.

### Git mode skips ignored trees

Analyzer ignored-tree traversal count is zero when a GitFileIndex is bound.

### Detector semantics hold

Controlled fixtures still report the same TypeScript and package.json evidence.

### Evidence order is stable

Repeated analyzer runs return the same sorted evidence paths.

### Non-git walker prunes caches

The non-Git walker does not enter `node_modules`, `dist`, or `.cache`.

## Performance

Telemetry exists and the synthetic operation budget is a hard gate.

### Telemetry fields present

Guard telemetry includes strategy, counts, bytes, and elapsed without path contents.

### Synthetic operation budget

The large synthetic fixture hashes no clean tracked file and no ignored file, and overlays at most 200 files.
