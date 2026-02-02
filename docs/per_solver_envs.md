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
  dependencies. Changing Inspect versions typically implies changing the
  `astabench` version (or using a fork/local path).
- Solver code lives under `agent_baselines/solvers/…` in the repo root; we rely on
  running from repo root so Python can import `agent_baselines` without installing
  it as a package.

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
uv lock --project solvers/react
```
and committed as `solvers/react/uv.lock`.

Run the solver using the per‑solver project:
```
uv sync --project solvers/react
uv run --project solvers/react astabench eval ...
```

## Adding a new solver sub‑project
1. Create `solvers/<solver>/pyproject.toml` with `astabench` and any solver‑specific deps.
2. Run `uv lock --project solvers/<solver>` to create `solvers/<solver>/uv.lock`.
3. Update `solvers/<solver>/setup.sh` to call `uv sync --project solvers/<solver>`.
4. Update `solvers/<solver>/demo.sh` to call `uv run --project solvers/<solver> …`.
5. Document required env vars in `solvers/<solver>/env`.

## Smoke test (all solver sub‑projects)
Run:
```
make smoke-solvers
```
This iterates `solvers/*/pyproject.toml`, syncs each solver environment, and verifies
imports for `astabench`, `inspect_ai`, and `agent_baselines`.
