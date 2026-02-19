# Scorer (frozen scoring environment)

This is a dedicated uv sub-project for **scoring** Inspect logs with a frozen
`inspect_ai` version. It is **not** a solver implementation.

## Dependencies

This environment is configured as a per‑solver uv sub‑project in
`solvers/scorer/pyproject.toml`.

It is pinned to `inspect_ai==0.3.179` and uses a uv override so scoring can run
on this frozen Inspect version even though `astabench==0.3.1` pins
`inspect_ai==0.3.114`.

Version policy: the scorer env tracks a single pinned Inspect version (currently
the latest stable we have validated in this repo). This version may be older or
newer than solver env versions; compatibility is verified by solve→score smoke
tests.

Install deps with:
```bash
./solvers/scorer/setup.sh
```

## Usage

For best cross-version compatibility, generate logs with `--log-format json`.

### Recommended workflow
Use the wrapper script from the repo root:

```bash
./scripts/eval_then_score.sh paper_finder --log-dir ./logs/paper_finder_two_phase -- \
  --split validation --solver <solver_spec> --model <model> --limit 1
```

This handles the full workflow:
1. Solve in `solvers/<solver>` with `astabench eval --no-score --log-format json`
2. Materialize scores in `solvers/scorer` with `inspect score --overwrite`
3. Aggregate in `solvers/scorer` with `astabench score`

### Manual scoring commands (reference)
If you already have unscored logs from `astabench eval --no-score`, use
`inspect score` in this frozen scorer env to materialize scores into the logs.

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
jq -r 'keys[]' "<log_dir>/logs.json" \
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
