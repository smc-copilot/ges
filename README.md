# GES

GES prepares a **business repository** for Cursor Composer: a projection-ready
first-install state (`.ges` lock/receipt, managed skills).

This repository is the thin Cursor-facing onboarding product. The central
control plane stays in
[smc-copilot/governance-engineering](https://github.com/smc-copilot/governance-engineering).
The published engine artifact is the Python package `ges`.

## Use GES in a business repo

**1. Install only the Cursor skill** (run this from the business repo):

```bash
npx skills@latest add smc-copilot/ges -a cursor --path skills
```

That is the **only recommended** install. `--path skills` copies
`skills/ges-setup` and nothing else.

**2. In Cursor, run `/ges-setup`.**

The skill acquires the locked `ges` CLI (you do not pip-install it), runs
Composer first-install on the business repo, then reports `ges check` /
`ges doctor`.

Done. Success looks like today's Composer projection-ready state. Matt
project-level setup may still be `BOOTSTRAP_PENDING` — that is recoverable,
not READY.

### Do not

- Clone this repository into the business repo's `.cursor` or `.agents`
- Install the `ges/` Python tree as a Cursor skill
- Start with `pip install` / `ges init` as the first human step
- Run `ges governance init` or any central-registry / cross-repo flow
  during first install

Those paths are unsupported. `/ges-setup` is the first touchpoint.

## What first install does not do

Composer first-install readiness **only**. It does not onboard the central
registry, enable cross-repo features, or run `ges governance init`.

## Maintainers / engine developers

Secondary to the Cursor path above. The published artifact remains the
`ges` Python package (`6.0.0-alpha.5`) with console script
`ges = ges.cli.main:main`.

```bash
python -m pip install -e ".[dev]"
ges --help
ges --version
python -m pytest -q
```

Offline GES 6 acceptances (no GitHub token):

```bash
GES_SOURCE_OFFLINE=1 python -m pytest tests/ges6 -q
```

Product-surface smoke (skill frontmatter, pin, business-repo guards):

```bash
python -m pytest tests/product -q
```

`/ges-setup` fetches the locked engine from
`skills/ges-setup/engine.lock.json` into a user-local venv
(`~/.local/share/ges/engines/<ref>`). Update `ref` and `requirement`
together when cutting a CLI release. Users should not need to know the pin.

`pip install -e .` is for people changing this package, not for business-repo
onboarding.

### Layout

```text
skills/ges-setup/    Cursor product skill (/ges-setup) + locked engine pin
ges/                 Published Composer + backplane + CLI (unchanged artifact)
tests/ges6/          Synthetic acceptances + offline fixtures
tests/product/       Skill / pin / guard smoke
lat.md/ges6/         GES 6 LAT pages required by release-doc oracles
```

The Python wheel still packages only `ges*`. Cursor install must use
`--path skills` so fixture `SKILL.md` files under `tests/` and the engine
tree never land in a business repo's `.cursor`.

### Follow-up in governance-engineering

1. Depend on this package instead of the vendored `ges/` tree.
2. Point operators at `/ges-setup` instead of GUIDE.md `ges init` as the
   consumer first step.
3. Keep the central control plane (`registry/`, `features/`, `programs/`,
   governance `tools/`) there.
4. Do not fold central registry onboarding into this product's first install.
