# Capability Governance

Alpha.4 adds a consumer overlay and `ges capability` for the parallel RTK layer only. Composer freeze, Gate A/B, and evidence-snapshot stay unchanged.

Product is `6.0.0-alpha.4` through Closure; Alpha.5 Release Gate bumps to `6.0.0-alpha.5`. Overlay files live under `.ges/capabilities/` and are created only by `add`/`remove`. `ges init` still prints the Alpha.3 recommendation and must not create overlay files. Doctor and check ignore overlay for overall. See [[capability-resolver]] and [[capability-governance-tests]].

## Overlay

Installed ids and hand-edited policy live beside Composer state, not inside lock or receipt.

`installed.yaml` is `ges.capability-installed.v1`. `policy.yaml` is `ges.capability-policy.v1`. First add seeds policy from the resolver level when policy is missing. Remove drops the installed id only, keeps an empty installed file, and never deletes policy. Implementation is [[ges/providers/overlay.py#add_installed]] and [[ges/providers/overlay.py#remove_installed]].

## Catalog Guard

The parallel catalog stays isolated from Composer `capabilities.yaml`.

Only `command-output.rtk` is registered. Duplicate provider ids BLOCK. The package incompatible matrix is readable and empty this slice. See [[ges/catalog/providers.py#load_providers]] and [[ges/providers/compat.py#package_incompatible]].

## CLI

`ges capability` is the only write path for the overlay.

`list` prints one RTK row and always exits 0. `add` registers then probes. `remove` drops the installed row. `doctor <id>` probes without writes and works without overlay. Composer ids raise `COMPOSER_CAPABILITY_FROZEN`. Unknown ids raise `CAPABILITY_NOT_FOUND`. Prohibited add raises `CAPABILITY_PROHIBITED`. Missing remove raises `CAPABILITY_NOT_INSTALLED`. See [[ges/cli/capability.py#run_list]], [[ges/cli/capability.py#run_add]], [[ges/cli/capability.py#run_remove]], and [[ges/cli/capability.py#run_doctor]].

## Policy Override

Hand-edited policy buckets override resolver level. Reason stays the analyzer `kind`.

Effective level walks prohibited, required, recommended, then optional in the overlay. If policy is absent, list falls back to the resolver bucket. Implementation is [[ges/providers/overlay.py#effective_level]].

## Inherited Contracts

Init, doctor, check, and preflight keep Alpha.3 contracts.

Init renders the plan before confirm and does not create `.ges/capabilities/`. Doctor may warn on recommended RTK and must not BLOCK overall for required or recommended RTK. Check and preflight ignore RTK and overlay. See [[ges/cli/init.py#run]], [[ges/doctor.py#run_doctor]], and [[ges/check.py#run_check]].

## Golden

Detached lifecycle proves list → add → doctor → add → remove → list without thawing Composer.

Source missing/dirty prints `GOLDEN_CAPABILITY_GOVERNANCE_BLOCKED`. Overlay/source/composer mutation prints FAIL. Success prints `GOLDEN_CAPABILITY_GOVERNANCE_PASS`. See [[ges/acceptance/run_golden_capability_governance.py#main]].
