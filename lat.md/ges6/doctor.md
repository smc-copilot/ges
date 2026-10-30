# Doctor

`ges doctor` observes runtime readiness without writing the consumer. Preflight does not require `.ges` state.

`--preflight` checks Python, git and Cursor. `spec_kit_runtime` is official projection identity, not stub script execution. Doctor is not Spec Kit Functional Ready. Implementation is [[ges/doctor.py#run_doctor]] and [[ges/doctor.py#run_preflight]].

Alpha.3 adds ephemeral `capabilities[]` and `warnings[]` for RTK verify. Missing recommended RTK is WARNING and does not BLOCK overall. A closed set with no `superpowers.*` IDs is not a Superpowers FAIL. Alpha.4 overlay is not read for overall. `ges_core` is `ges check`; a GES_CHECK_FAILED reason is copied into `warnings`. Post-install business Git drift is not a core FAIL. See [[capability-resolver]] and [[capability-governance]].
