# Large Repo Snapshot

Business Source Guard v2 uses a Git index plus a dirty/untracked overlay so `ges init` cost follows Git-visible source, not ignored physical trees.

Clean tracked identity is `mode + blob OID + path`. Dirty tracked and non-ignored untracked files keep exact-byte hashes. `apps/knowledge` and Composer write-allow paths (`.ges`, `.agents/skills`, `.specify`, `.cursor`, `.codex`, `docs/agents`, `AGENTS.md`, `CLAUDE.md`) are skip prefixes so projection writes do not trip the guard on empty-root repos. See [[ges/reconciler/business_guard.py#capture_business_snapshot]] and [[ges/analyzer/git_index.py#build_git_file_index]].

Analyzer detectors reuse the same GitFileIndex. Non-Git evidence discovery uses a pruned `os.walk`. Git inventory failure falls back to full SHA256 and never skips the guard. A same-set `ges init` NOOP rewrites a pre-overlay per-file fingerprint to the current snapshot so `ges check` can compare like with like. `LARGE_REPO_GUARD_V2_READY` is not claimed until required Golden ACs PASS.
