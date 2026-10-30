# Release Hardening

Alpha.1 tag requires an immutable candidate SHA proven by external evidence, strict smoke, native Cursor discovery, and current docs.

This is not a new Composer capability. Historical `audit/ges6/bootstrap-closure` is HISTORICAL_ONLY. Do not claim `RELEASE_READY` or create `ges-v6.0.0-alpha.1` until all RH gates PASS on a frozen Candidate C.

## External Evidence

Final evidence must bind the candidate SHA from outside the candidate Git tree. Writer is [[ges/acceptance/release_evidence.py#write_release_manifest]].

## Strict Spec Kit Smoke

The acceptance observer must not repair `.specify/feature.json`. Missing or invalid feature state fails. See [[ges/acceptance/speckit_smoke.py#feature_state_error]].

## Native Cursor Discovery

Name-only `GES_CURSOR_NATIVE_SKILL_PROBE_V2` probes prove skill identity and description digest. Implementation is [[ges/cursor_probe.py#native_discovery]].

## Documentation Truth

Current-status LAT pages must not claim Golden BLOCKED while Bootstrap is functionally complete. Scanner is [[ges/acceptance/release_gate.py#assert_current_status_current]].

## Tag Gate

`ges-v6.0.0-alpha.1` may be created only after gates PASS and must point at the frozen candidate. Verifier is [[ges/acceptance/release_gate.py#verify_tag_target]].
