---
lat:
  require-code-mention: true
---
# Release Hardening Tests

Synthetic oracles for immutable evidence, strict smoke, native Cursor discovery, CI contracts, and documentation truth.

## External evidence

Helpers keep the candidate SHA unchanged and write evidence outside the candidate tree.

### Candidate SHA unchanged after evidence write

Writing closure evidence into an artifact directory must not require a new candidate commit.

### Evidence path is outside candidate

The resolved artifact directory must sit outside the candidate Git tree.

### Manifest schema is valid

`ges.release-evidence-manifest.v1` writes all required fields and rejects extra keys.

### Artifact digest matches manifest

Computed SHA256 of a stored artifact must equal the digest recorded in the manifest.

### Synthetic failure blocks release

A FAIL synthetic status must make the combined release gate something other than PASS.

## Strict smoke

The acceptance observer evaluates Spec Kit output and must not repair the system under test.

### Missing feature state fails

Absent `.specify/feature.json` returns `SPEC_KIT_SMOKE_FEATURE_STATE_MISSING`.

### Invalid feature directory fails

A present feature.json whose directory is not the smoke run id returns `SPEC_KIT_SMOKE_FEATURE_STATE_INVALID`.

### Repair prompt is absent

GES acceptance sources must not contain the corrective `Write only .specify/feature.json` prompt.

### Repair invocation count is zero

The smoke invocation record defaults to one primary call and zero repair calls.

## Native Cursor discovery

Name-only probes prove skill identity without leaking filesystem paths.

### Probe prompt has no skill paths

The V2 native prompt must omit `.agents/skills`, `.cursor/skills`, and `SKILL.md`.

### Expected description is not in the prompt

The probe must not include the SKILL.md frontmatter description text.

### Metadata mismatch raises

A returned description whose SHA256 differs from frontmatter raises `CURSOR_SKILL_METADATA_MISMATCH`.

### Path leak is detected

`prompt_leaks_skill_paths` is true when a prompt names a skill file path.

## Documentation truth

Current status pages must match the functionally complete, tag-pending gate.

### Stale Golden BLOCKED phrases fail

A LAT current-status page that still says Golden BLOCKED raises `RELEASE_DOCUMENTATION_STALE`.

### Current status required phrases exist

`lat.md/ges6/ges6.md` must contain Functionally Complete and PENDING RELEASE HARDENING.

## Tag and CI contracts

Tag verification and workflow files encode the immutable candidate checkout.

### Tag mismatch raises

A tag that points at a different SHA raises `RELEASE_TAG_COMMIT_MISMATCH`.

### Workflows pin candidate SHA

Synthetic CI runs offline pytest; Golden CI checks out the explicit candidate SHA and does not commit evidence.
