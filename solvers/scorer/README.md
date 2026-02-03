# Scorer (frozen scoring environment)

This is a dedicated uv sub-project for **scoring** Inspect logs with a frozen
`inspect_ai` version. It is **not** a solver implementation.

## Dependencies

This environment is configured as a per‑solver uv sub‑project in
`solvers/scorer/pyproject.toml`.

It is pinned to `inspect_ai==0.3.114` (matches the `astabench==0.3.1` released
pin), so scoring remains stable even if solvers use other Inspect versions.

Install deps with:
```bash
./solvers/scorer/setup.sh
```

## Usage

For best cross-version compatibility, generate logs with `--log-format json`.

Score a directory of logs:
```bash
./scripts/solver_uv.sh run scorer -- astabench score <log_dir>
```

Or score a single log file:
```bash
./scripts/solver_uv.sh run scorer -- inspect score <log_file>
```

## Example: cross-version solve → score

Solve in a solver env (example uses `paper_finder`, which pins a newer Inspect):
```bash
./scripts/solver_uv.sh run paper_finder -- astabench eval --no-score --log-format json --log-dir ./logs/paper_finder ...
```

Score logs in the frozen scorer env:
```bash
./scripts/solver_uv.sh run scorer -- astabench score ./logs/paper_finder
```
