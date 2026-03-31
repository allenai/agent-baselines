# Per‑Solver Environments (Sub‑Projects + Lockfiles)

This repo uses **one uv sub‑project per solver**, each with its own
`pyproject.toml` and `uv.lock`. The goal is to let each solver pin a different
Inspect version (and related deps) without impacting other solvers.

## Goals
- **Isolation:** each solver has an independent dependency graph.
- **Reproducibility:** solver lockfiles are versioned per solver.
- **Minimal coupling:** solver envs should not depend on the root `pyproject.toml`.

## Constraints / Notes
- Most solvers import `astabench`; the per-solver projects in this repo still
  default to `astabench==0.3.1`, which pins `inspect_ai==0.3.114`. Changing
  Inspect versions there still requires an override or an `astabench` fork.
- Separately, the repo-root dev/test environment in [`pyproject.toml`](../pyproject.toml)
  is pinned to `inspect_ai==0.3.143`. That override block now calls out which
  entries are hard conflicts versus shared-env compatibility pins so we can
  reevaluate them later.
- Solver code lives under `agent_baselines/solvers/…` in the repo root; we rely on
  running from repo root so Python can import `agent_baselines` without installing
  it as a package. Solver `setup.sh` and `demo.sh` `cd` to repo root to make this
  reliable.
- You cannot mix multiple `inspect_ai` versions **in the same Python process**.
  Per-solver isolation works because we run each solver as its own process/env.
- For Inspect upgrade risk review, check `agent_baselines/inspect_compat.py`
  (centralized private/internal Inspect imports) and
  `tests/test_inspect_compat.py` (guards against private imports outside compat).

## Standard uv Commands
Use direct `uv` commands with the solver sub-project:
- `uv lock --project "solvers/<solver>" --python 3.11`
- `uv sync --project "solvers/<solver>" --python 3.11`
- `uv run --project "solvers/<solver>" --python 3.11 --frozen -- <command...>`

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

## Example: React solver
`solvers/react/pyproject.toml` declares the deps for the React solver, including
its chosen Inspect version. The lockfile should be generated via:
```
uv lock --project "solvers/react" --python 3.11
```
and committed as `solvers/react/uv.lock`.

Run the solver using the per‑solver project:
```
uv sync --project "solvers/react" --python 3.11
uv run --project "solvers/react" --python 3.11 --frozen -- astabench eval ...
```

## Adding a new solver sub‑project
The recommended way is:
```
./scripts/new_solver.sh <solver>
```
Then review/edit the generated files and generate a lockfile:
```
uv lock --project "solvers/<solver>" --python 3.11
```

1. Create `solvers/<solver>/pyproject.toml` with `astabench` and any solver‑specific deps.
2. Run `uv lock --project "solvers/<solver>" --python 3.11` to create `solvers/<solver>/uv.lock`.
3. Create `solvers/<solver>/setup.sh` calling `uv sync --project "solvers/<solver>" --python 3.11`.
4. Create `solvers/<solver>/demo.sh` calling `uv run --project "solvers/<solver>" --python 3.11 --frozen -- …`.
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

You may also need to pin transitive dependencies that `inspect_ai` pulls in
(e.g. `openai`), since their compatible versions can change across Inspect
releases. Add these to `override-dependencies` as needed.

Then regenerate the solver lockfile and re-sync:
```
uv lock --project "solvers/<solver>" --python 3.11
uv sync --project "solvers/<solver>" --python 3.11
```

Concrete example in this repo:
- `solvers/react` pins `inspect_ai==0.3.114` (matches `astabench`'s pin).
- `solvers/paper_finder` uses an override to run with `inspect_ai==0.3.169`.

### Forking `astabench` (last resort)
If you need a version of `astabench` that relaxes its Inspect pin (or adds APIs),
use a fork via uv sources (git or local path). This is higher maintenance and
should be used sparingly.

## Verify per-solver isolation (different Inspect versions)
This is a simple “proof” that two solvers can run with different `inspect_ai`
versions, as long as they run in separate environments/processes.

From repo root:
```
uv sync --project "solvers/react" --python 3.11
uv sync --project "solvers/paper_finder" --python 3.11

uv run --project "solvers/react" --python 3.11 --frozen -- python -c 'import inspect_ai; print(inspect_ai.__version__)'
uv run --project "solvers/paper_finder" --python 3.11 --frozen -- python -c 'import inspect_ai; print(inspect_ai.__version__)'
```

Expected output (as of 2026-02-02):
- `react` prints `0.3.114`
- `paper_finder` prints `0.3.169`

(Expected versions should match what’s pinned in `solvers/<solver>/pyproject.toml`.)

## Smoke test (all solver sub‑projects)
Run:
```
make smoke-solvers
```
This iterates `solvers/*/pyproject.toml`, syncs each solver environment, and verifies
imports for `astabench`, `inspect_ai`, and `agent_baselines`.

## New solver checklist (uv sub-project)
Use this checklist when adding a new solver.

1. Scaffold
   - Run: `./scripts/new_solver.sh <solver>`
   - Review generated files (including `agent_baselines/solvers/<solver>/`), then commit the initial scaffold.
2. Dependencies + lockfile
   - Review/edit: `solvers/<solver>/pyproject.toml`
   - Generate lockfile: `uv lock --project "solvers/<solver>" --python 3.11` (commit `solvers/<solver>/uv.lock`)
   - If you need a different `inspect_ai` than `astabench` pins, add `[tool.uv].override-dependencies` (see above), then re-lock.
3. Setup + demo scripts
   - Ensure `solvers/<solver>/setup.sh` calls `uv sync --project "solvers/<solver>" --python 3.11`
   - Ensure `solvers/<solver>/demo.sh` uses `uv run --project "solvers/<solver>" --python 3.11 --frozen -- ...`
4. Env vars
   - List required env vars in `solvers/<solver>/env`
   - If running in Docker via `make shell SOLVER=<solver>`, this file is loaded automatically.
5. Verify it works
   - Run the solver’s demo: `./solvers/<solver>/demo.sh`
   - Run smoke checks: `make smoke-solvers`
