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

### Version identity

These are one mapping, not three products:

| Identity | Value | Where |
|---|---|---|
| Public product tag | `tag-1.0` | Git tag, GitHub Release, `engine.lock.json` `ref` |
| Engine product version | `6.0.0-alpha.5` | `pyproject.toml` `[project].version`, `ges.__product_version__`, lock `product_version` |
| Distribution version | `1.2.1` | `ges.__distribution_version__` (parenthetical in `ges --version`) |

`tag-1.0` **is** the first public pin. It ships engine `6.0.0-alpha.5`
(distribution `1.2.1`). Do not rename the tag to `v1.0`, `v1.0.0`, or
`tag-1.0.0`.

### Locked engine pin (scheme A)

Current locked release: **`tag-1.0`**.

`skills/ges-setup/engine.lock.json` is a self-referential tag pin:

- `ref_kind`: `tag`
- `ref`: `tag-1.0`
- `requirement`: `ges @ git+https://github.com/smc-copilot/ges.git@tag-1.0`

Installing `tag-1.0` means the lock file comes from the same tree the
tag points at. Do not pin a SHA in the lock while marketing a different
tag name.

`/ges-setup` acquires that pin into a user-local venv
(`~/.local/share/ges/engines/tag-1.0`). It prefers the GitHub Release
wheel `ges-6.0.0a5-py3-none-any.whl` on `tag-1.0` when that asset
exists, then falls back to the git requirement above. **`tag-1.0` is
valid as a git pin even when the Release has no wheel yet**; attach a
wheel later without changing the tag name. Users should not need to
know the pin.

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

`pip install -e .` is for people changing this package, not for business-repo
onboarding.

### Cutting the next locked release

1. Keep `product_version` == `pyproject.toml` `[project].version` ==
   `ges.__product_version__`.
2. On the `main` commit that already has acquire/setup support, set
   `engine.lock.json` to the next scheme A tag (`tag-1.1`, …) **before**
   creating the tag. `ref`, `ref_kind`, and `requirement` must name that
   same tag.
3. Merge that commit to `main`.
4. Tag **that** commit and push:

   ```bash
   git checkout main && git pull
   git tag tag-X.Y
   git push origin tag-X.Y
   ```

5. Create the GitHub Release for the same tag. Explain skills +
   `/ges-setup`. State that the engine pin is that tag. Do not teach
   users to dump this repository into `.cursor`. Attach a wheel when
   you have one (`python -m build --wheel`); acquire will prefer it.

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
