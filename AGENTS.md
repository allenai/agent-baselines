# Repository Guidelines

## Project Structure & Module Organization
- Source lives in `agent_baselines/` with solver implementations under `agent_baselines/solvers/<solver>/`.
- Per-solver run artifacts live in `solvers/<solver>/` (docs + `setup.sh` + `demo.sh` + `env` listing required env vars). New work uses per-solver sub‑projects (`solvers/<solver>/pyproject.toml` + `uv.lock`) to isolate dependencies.
- This repo depends on `astabench` (pinned in `pyproject.toml`) for tasks, tools, and scoring; most runs invoke `astabench eval` / `inspect eval` against `astabench/<task>` task names.
- Tests live in `tests/` and `tests/solvers/`.
- Tooling/config: `Makefile`, `pyproject.toml`, `setup.cfg`; Docker files in `docker/`.
- DVC is present (`dvc.yaml`, `dvc.lock`); don’t commit large data or generated artifacts.

## Build, Test, and Development Commands
- Build container: `make build-image` (optionally `SOLVER=code_agent`).
- Dev shell in container: `make shell` (mounts repo; respects `.env` and `solvers/<solver>/env`).
- Typical local flow for a solver: `./solvers/<solver>/setup.sh` then `./solvers/<solver>/demo.sh` (both are intended to be run from repo root).
- uv sub-project helpers:
  - Lock/update deps: `./scripts/solver_uv.sh lock <solver>`
  - Sync env: `./scripts/solver_uv.sh sync <solver>`
  - Run in env: `./scripts/solver_uv.sh run <solver> -- <cmd ...>`
  - New solver scaffold: `./scripts/new_solver.sh <solver>`
  - Smoke test all uv sub-projects: `make smoke-solvers`
- Run tests: `make test` (skips `expensive` by default) or `make test-expensive`.
- Lint/format: `make format` (Black), `make flake` (Flake8), `make mypy` (type checks).
- Extra pytest args: `make test PYTEST_ARGS="-k asta_router -q"`.

## Coding Style & Naming Conventions
- Python 3.11+. Use 4‑space indentation, `snake_case` for modules/functions, `CamelCase` for classes.
- Formatting: Black; keep imports tidy (isort/autoflake acceptable).
- Linting: Flake8 with repo rules (see `pyproject.toml`); resolve all F/E findings before PR.
- Typing: Mypy (configured in `setup.cfg`); prefer typed function signatures and return types.

## Testing Guidelines
- Framework: Pytest (configured in `pyproject.toml`).
- Naming: `tests/test_*.py` and `tests/solvers/test_*.py`; keep tests fast and deterministic.
- Markers: use `@pytest.mark.expensive` for long runs; skipped unless `make test-expensive`.
- Example: `uv run -m pytest -vv tests/solvers/test_code_agent.py::test_basic`.

## Commit & Pull Request Guidelines
- Commits: imperative mood, concise subject; scope when helpful (e.g., `solvers/code_agent: fix tool parsing`).
- PRs: include summary, rationale, linked issues, and screenshots/logs for behavior changes. Note any `expensive` tests.
- Gate: ensure `make format flake mypy test` pass locally before request for review.

## Security & Configuration Tips
- Required env vars are listed in `solvers/<solver>/env`. Do not commit secrets.
- Never commit secrets, large caches, or derived data; respect `.gitignore`/DVC.
- New solvers go under `agent_baselines/solvers/<name>/` with matching tests in `tests/solvers/`.
- Do **not** `git push` automatically — leave that to the user.
