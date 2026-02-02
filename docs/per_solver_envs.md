# Per‑Solver Environments (Sub‑Projects + Lockfiles)

This repo is moving to **one uv sub‑project per solver**, each with its own
`pyproject.toml` and `uv.lock`. The goal is to let each solver pin a different
Inspect version (and related deps) without impacting other solvers.

## Goals
- **Isolation:** each solver has an independent dependency graph.
- **Reproducibility:** solver lockfiles are versioned per solver.
- **Minimal coupling:** solver envs should not depend on the root `pyproject.toml`.

## Constraints / Notes
- Most solvers import `astabench`; `astabench` pins `inspect_ai` in its own
  dependencies (currently an **exact** pin). On PyPI today, all released
  `astabench` versions pin `inspect_ai==0.3.114` (as of 2026-02-02), so changing
  Inspect versions requires an override or an `astabench` fork.
- Solver code lives under `agent_baselines/solvers/…` in the repo root; we rely on
  running from repo root so Python can import `agent_baselines` without installing
  it as a package.
- You cannot mix multiple `inspect_ai` versions **in the same Python process**.
  Per-solver isolation works because we run each solver as its own process/env.

## Layout (per solver)
```
solvers/<solver>/
  pyproject.toml
  uv.lock
  setup.sh
  demo.sh
  README.md
  env
```

## React pilot (initial scaffold)
`solvers/react/pyproject.toml` declares the deps for the React solver, including
its chosen Inspect version. The lockfile should be generated via:
```
./scripts/solver_uv.sh lock react
```
and committed as `solvers/react/uv.lock`.

Run the solver using the per‑solver project:
```
./scripts/solver_uv.sh sync react
./scripts/solver_uv.sh run react -- astabench eval ...
```

## Adding a new solver sub‑project
1. Create `solvers/<solver>/pyproject.toml` with `astabench` and any solver‑specific deps.
2. Run `./scripts/solver_uv.sh lock <solver>` to create `solvers/<solver>/uv.lock`.
3. Create `solvers/<solver>/setup.sh` calling `./scripts/solver_uv.sh sync <solver>`.
4. Create `solvers/<solver>/demo.sh` calling `./scripts/solver_uv.sh run <solver> -- …`.
5. Document required env vars in `solvers/<solver>/env`.

## Choosing `inspect_ai` (and `astabench`) versions

### Default (recommended)
Pin the repo-default `astabench` (and matching `inspect_ai`) in your solver
sub-project:
```toml
[project]
dependencies = [
  "astabench==0.3.1",
  "inspect_ai==0.3.114",
]
```

### Diverging from `astabench`'s `inspect_ai` pin (supported, but compatibility is on you)
Because `astabench` pins `inspect_ai` exactly, you must use a uv override to pick a
different Inspect version in a solver env. The override tells uv to ignore
`astabench`'s pin; the direct dependency records the intended Inspect version in
the solver's own dependency list:
```toml
[project]
dependencies = [
  "astabench==0.3.1",
  "inspect_ai==0.3.169",
]

[tool.uv]
override-dependencies = [
  "inspect_ai==0.3.169",
]
```

Then regenerate the solver lockfile and re-sync:
```
./scripts/solver_uv.sh lock <solver>
./scripts/solver_uv.sh sync <solver>
```

Concrete example in this repo:
- `solvers/react` pins `inspect_ai==0.3.114` (matches `astabench`'s pin).
- `solvers/paper_finder` uses an override to run with `inspect_ai==0.3.169`.

### Forking `astabench` (last resort)
If you need a version of `astabench` that relaxes its Inspect pin (or adds APIs),
use a fork via uv sources (git or local path). This is higher maintenance and
should be used sparingly.

## Smoke test (all solver sub‑projects)
Run:
```
make smoke-solvers
```
This iterates `solvers/*/pyproject.toml`, syncs each solver environment, and verifies
imports for `astabench`, `inspect_ai`, and `agent_baselines`.
