---
name: ges-setup
description: >-
  Prepare a business repository for GES Composer first-install readiness
  (projection-ready .ges lock/receipt and managed skills). Use when the user
  invokes ges-setup or /ges-setup, asks to set up GES in this repo, or wants
  Cursor Composer first-install without pip-installing the engine themselves.
disable-model-invocation: true
---

# /ges-setup

Bring the **current business repo** to today's Composer projection-ready
state. The user already installed this skill. Do not ask them to
`pip install` or run `ges init` themselves.

## Recommended install (skills path only)

This skill belongs in the business repo because someone ran:

```bash
npx skills@latest add smc-copilot/ges -a cursor --path skills
```

That command copies **only** `skills/ges-setup`. It must never clone the
smc-copilot/ges repository — including the `ges/` Python tree — into
`.cursor` or `.agents`.

If `.cursor/ges/` looks like the Python package (`cli/main.py`,
`pyproject.toml`), stop. Tell the user to remove that tree and reinstall
with the command above.

## Do not do these things

- Do not hand-copy files into `.cursor` or `.agents`. Projection goes
  through Composer/reconcile only (`ges init --yes` via the script).
- Do not treat the GES product repo (`smc-copilot/ges`, this engine
  checkout) as the Golden / business target unless the user **explicitly
  names** that path.
- Do not run `ges governance init`, central registry onboarding, or
  any cross-repo / GUIDE.md flow.
- Do not tell the user to follow old GUIDE commands.
- Do not claim READY when doctor reports `BOOTSTRAP_PENDING`.

## Orchestration

`SKILL_DIR` is the folder that contains this `SKILL.md` (usually
`.cursor/skills/ges-setup` or `.agents/skills/ges-setup`).

### 1. Confirm the target is a business repo

Default target: the workspace root.

- If the workspace is the GES product repo (`ges/cli/main.py` **and**
  `skills/ges-setup/SKILL.md` at repo root, or `pyproject.toml` name
  `ges` plus the engine tree), **stop** and ask the user to name a
  business-repo path.
- Only pass `--allow-product-repo` when the user explicitly named this
  product checkout as the target.

### 2. Acquire the locked `ges` CLI (user-unaware)

Run the skill script. It reads `engine.lock.json` and installs the
pinned engine into a **user-local** venv. Users should not see a pip
ritual, a pin tag, or "run `pip install -e .`".

```bash
python3 "$SKILL_DIR/scripts/ges_setup.py" --repo "$TARGET"
```

Use `python` if `python3` is missing. The script:

1. Rejects whole-repo-in-`.cursor` and (unless allowed) the product repo.
2. Acquires the locked CLI (`scripts/acquire_ges_cli.py`).
3. Runs Composer first install: `ges init --yes` on `$TARGET`.
4. Runs `ges check` and `ges doctor`.
5. Prints a report plus a `--- ges-setup-result ---` JSON block.

If `ges_setup.py` is unavailable, run `acquire_ges_cli.py` first, then
the same three `ges` commands with the printed `ges_cli` path. Still do
not copy files yourself.

### 3. Report results

Read the script report. Quote overall readiness from `ges doctor`.

Success is **Composer first-install readiness**: `.ges` lock/receipt,
managed skills, and a passing `ges check` — equivalent to a successful
`ges init`, without the user touching GUIDE commands.

### 4. `BOOTSTRAP_PENDING` is recoverable, not READY

If Matt project-level setup is incomplete (`matt_project_bootstrap`
PENDING) and overall is `BOOTSTRAP_PENDING`:

- Say so plainly. Do **not** fake READY.
- Next step: run the already-projected `setup-matt-pocock-skills`
  skill in this business repo, then re-run `/ges-setup` or `ges doctor`.

If overall is `BLOCKED`, show the failing checks and stop.

## Maintainer pin (do not show unless asked)

`engine.lock.json` is a scheme A self-referential tag pin. Current
locked release: `tag-1.0` (`ref_kind` `tag`, `ref` `tag-1.0`,
requirement `ges @ git+https://github.com/smc-copilot/ges.git@tag-1.0`).
Update `ref`, `ref_kind`, and `requirement` together when cutting the
next `tag-<major>.<minor>`. Users never install that pin themselves.
