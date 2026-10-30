# GES 6 Composer + Governance Backplane

Standalone Python package for **GES 6** (`6.0.0-alpha.5`): a Composer that
installs a pinned engineering stack into a business repository, plus a
Governance Backplane for work, policy, evidence, and execution gates.

This repository is extracted from
[smc-copilot/governance-engineering](https://github.com/smc-copilot/governance-engineering).
The central delivery control plane (`registry/`, `features/`, `programs/`,
governance `tools/`) stays in that repo. This package is only the `ges`
import tree, its CLI, schemas/catalog, and the GES 6 test suite.

## Install

Requires Python 3.11+.

```bash
python -m pip install -e .
```

With the test extra:

```bash
python -m pip install -e ".[dev]"
```

## CLI

The `ges` console script points at `ges.cli.main:main` (same entry point as
the vendored copy in governance-engineering):

```bash
ges --help
ges --version
python -m ges --help
```

Typical Composer flow against a business repo:

```bash
ges analyze /path/to/repo
ges init /path/to/repo
ges check /path/to/repo
ges doctor /path/to/repo
```

`ges --version` reports the product version (`6.0.0-alpha.5`) and the
historical distribution field still recorded as `1.2.1` from the parent
`smc-delivery-governance` package. That distribution string is leftover
vendoring metadata; follow-up can align it with this package's version.

## Tests

Synthetic GES 6 acceptances live under `tests/ges6` and use the offline
source-cache fixtures (no GitHub token required):

```bash
GES_SOURCE_OFFLINE=1 python -m pytest tests/ges6 -q
```

or simply:

```bash
python -m pytest -q
```

Golden Consumer / live release-gate jobs (self-hosted Windows runner,
`E:\git\smc-copilot-desktop`, Cursor CLI) are **not** run by default.
They need operator secrets and a Golden worktree. The
`.github/workflows/ges-alpha1-golden.yml` workflow remains the dispatch
entry for that path.

`tests/fixtures` from governance-engineering was **not** copied: those
YAML/JSON files are used only by central delivery-governance tests.

The official Spec Kit staging fixture in governance-engineering omitted
`.cursor/skills/` because that repo's `.gitignore` ignored all `.cursor`
paths. This package reconstructs those four selected skills
(`constitution`, `specify`, `clarify`, `plan`) from pinned spec-kit
`1d5106f59e1b148ee23ab136638932dd790ff1b6` so offline pytest can run
without `uvx` / network.

## Layout

```text
ges/                 Import package (Composer, backplane, CLI, schemas)
tests/ges6/          Synthetic acceptances + offline fixtures
lat.md/ges6/         GES 6 LAT pages required by release-doc oracles
.github/workflows/   Synthetic CI + Golden release-gate dispatch
```

## Follow-up in governance-engineering

Out of scope here. After this package lands:

1. Depend on `ges` (path, VCS, or published index) instead of the vendored
   `ges/` tree.
2. Remove the in-repo `ges/` package and `tests/ges6/` from
   governance-engineering.
3. Keep the central control-plane tools and registries there.
