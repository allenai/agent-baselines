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

### Materialize scores (recommended)
If you ran `astabench eval` with `--no-score`, the log files will not contain
scores yet. Use `inspect score` in this frozen scorer env to materialize scores
into the logs.

Score a single log file (overwrite in place):
```bash
uv run --project "solvers/scorer" --python 3.11 --frozen -- inspect score --overwrite <log_file>
```
If Inspect can't infer the scorer from the log, pass it explicitly:
```bash
uv run --project "solvers/scorer" --python 3.11 --frozen -- inspect score --scorer path/to/task.py@scorer_fn --overwrite <log_file>
```

Score all logs in a log dir (uses Inspect's `logs.json` manifest):
```bash
LOG_DIR="<log_dir>" python -c 'import json, os; from pathlib import Path; p = Path(os.environ["LOG_DIR"]) / "logs.json"; m = json.loads(p.read_text(encoding="utf-8")); print("\n".join(m.keys()))' \
  | while IFS= read -r log_file; do
      [ -z "${log_file}" ] && continue
      uv run --project "solvers/scorer" --python 3.11 --frozen -- inspect score --overwrite "<log_dir>/${log_file}"
    done
```

### Aggregate (optional)
After log files contain scores, you can aggregate them with:
```bash
uv run --project "solvers/scorer" --python 3.11 --frozen -- astabench score <log_dir>
```

## Example: cross-version solve → score

Solve in a solver env (example uses `paper_finder`, which pins a newer Inspect):
```bash
uv run --project "solvers/paper_finder" --python 3.11 --frozen -- astabench eval --no-score --log-format json --log-dir ./logs/paper_finder ...
```

Materialize scores in the frozen scorer env:
```bash
uv run --project "solvers/scorer" --python 3.11 --frozen -- inspect score --overwrite ./logs/paper_finder/<log_file>
```

Optionally aggregate the scored logs:
```bash
uv run --project "solvers/scorer" --python 3.11 --frozen -- astabench score ./logs/paper_finder
```
