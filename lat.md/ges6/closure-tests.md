---
lat:
  require-code-mention: true
---
# Bootstrap Closure Tests

Synthetic and isolated-worktree oracles for official Spec Kit staging, stub migration, Cursor structure, Golden HEAD isolation, and closure evidence.

The Golden runner also executes A-SKM-001/002 on the detached consumer worktree and unwraps Cursor CLI result JSON.

## TEST-A-SK-001

Official pinned specify-cli identity is 1.0.8.dev0 and selected cursor-agent skills exist after staging.

## TEST-A-SK-002

Each projected selected Spec Kit skill hash equals the corresponding official staging file hash.

## TEST-A-SK-003

Official specify init / staging leaves the consumer tree byte-identical.

## TEST-A-SKM-001

An unmodified GES-owned stub is removed and the official `.cursor/skills` projection exists.

## TEST-A-SKM-002

A drifted GES-owned stub blocks apply with `MANAGED_CONTENT_MODIFIED` and zero mutation.

## TEST-A-CURSOR-STRUCT-001

Required probe skills have valid SKILL.md frontmatter and `name` equals the parent directory.

## TEST-A-GOLDEN-001

The Golden Consumer path resolves a 40-character committed HEAD.

## TEST-A-GOLDEN-002

A dirty source checkout does not block creating a clean detached worktree from HEAD.

## TEST-A-GOLDEN-005

Adding and removing the detached worktree leaves the original workspace file identity unchanged except `.git` admin metadata.

## TEST-A-EVID-001

Closure evidence `ges.commit_sha` and `golden_consumer.commit_sha` bind to the tested HEADs.

## TEST-A-EVID-002

Every required Acceptance record includes requirement ids, test ids, command, exit code and oracle fields.

## TEST-NEG-SK-001

A staged path containing `..` is rejected with zero consumer mutation.

## TEST-NEG-SK-002

A specify-cli version other than 1.0.8.dev0 raises `SPEC_KIT_CLI_IDENTITY_MISMATCH`.
