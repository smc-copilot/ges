# Governance Backplane

Alpha.2 adds a Git/GitHub grounded runtime that computes WORK_READY and MERGE_READY from Work, SPEC/PLAN digests, and provider-backed evidence.

Composer state stays orthogonal under `.ges/` root files. Governance lives in `.ges/governance/**`. CLI entry is [[ges/cli/main.py#build_parser]]. Gate evaluation is [[ges/governance/gates.py#evaluate_intake]] and [[ges/governance/gates.py#evaluate_merge]].

Pointer-only artifacts live in [[ges/governance/domain.py#ArtifactRef]]. Evidence is stdout-only. HIGH risk can be WORK_READY and cannot be MERGE_READY.

Operator Golden checklist: on the consumer repo, `ges init`, `ges governance init`, create a FEATURE work, link SPEC/PLAN, commit `.ges/governance/**`, open a PR whose body contains exact `GES-Work: <id>`, obtain APPROVED plus at least one SUCCESS check, authenticate `gh`, then set `GES_ALPHA2_GOLDEN_PR` and `GES_ALPHA2_GOLDEN_WORK_ID`.

Live merge observation on `loudon84/copilot-work` was stopped by operator decision. Gate A was `WORK_READY` on PR #2 (`GES-Work: WI-GES-A2-GOLDEN`). Live Gate B is not pursued. Synthetic merge oracles still apply. `BACKPLANE_ALPHA2_READY` is not claimed.
