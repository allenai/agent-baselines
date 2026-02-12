#!/usr/bin/env bash

# Cross-version solve→score smoke.
#
# This proves:
# - Solving can run in a solver env with one Inspect version (e.g. paper_finder)
# - Scoring can run in a separate, frozen scorer env with a different Inspect
#   version (solvers/scorer)
# - The artifact boundary is stable logs (enforce JSON logs + --no-score)
#
# This is intended for CI and should be keyless/offline (deterministic solver).

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

solver="${1:-paper_finder}"
solver_project="solvers/${solver}"
scorer_project="solvers/scorer"

config_path="scripts/ci/two_phase_smoke.yml"
solver_spec="scripts/arithmetic_solver.py@arithmetic_solver"
model="mockllm/model"

if [ ! -f "${solver_project}/pyproject.toml" ]; then
  echo "error: unknown solver env '${solver}' (missing ${solver_project}/pyproject.toml)" >&2
  exit 2
fi
if [ ! -f "${scorer_project}/pyproject.toml" ]; then
  echo "error: missing scorer env (${scorer_project}/pyproject.toml)" >&2
  exit 2
fi

solver_inspect_version="$(uv run --project "${solver_project}" --python 3.11 --frozen -- python -c 'import inspect_ai; print(inspect_ai.__version__)')"
scorer_inspect_version="$(uv run --project "${scorer_project}" --python 3.11 --frozen -- python -c 'import inspect_ai; print(inspect_ai.__version__)')"

echo "== inspect versions: solver=${solver}(${solver_inspect_version}) scorer(${scorer_inspect_version})" >&2
if [ "${solver_inspect_version}" = "${scorer_inspect_version}" ]; then
  echo "error: expected solver Inspect version to differ from scorer Inspect version" >&2
  exit 1
fi

if command -v mktemp >/dev/null 2>&1; then
  # macOS: mktemp -d -t prefix ; Linux: mktemp -d
  log_dir="$(mktemp -d -t solve-score-XXXXXXXX 2>/dev/null || mktemp -d)"
else
  ts="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
  log_dir="logs/solve_score_smoke_${ts}"
  mkdir -p "${log_dir}"
fi

cleanup() {
  if [ "${log_dir:-}" != "" ] && [[ "${log_dir}" == /tmp/* || "${log_dir}" == /var/folders/* ]]; then
    rm -rf "${log_dir}"
  fi
}
trap cleanup EXIT

echo "== solve: ${solver} -> ${log_dir}" >&2
uv run --project "${solver_project}" --python 3.11 --frozen -- astabench eval \
  --log-dir "${log_dir}" \
  --config-path "${config_path}" \
  --split validation \
  --ignore-git \
  --solver "${solver_spec}" \
  --model "${model}" \
  --limit 1 \
  --no-score \
  --log-format json

echo "== score: inspect score (scorer env)" >&2
scorer_spec="scripts/ci/arithmetic_task.py@check_arithmetic"
if [ ! -f "${log_dir}/logs.json" ]; then
  echo "error: ${log_dir}/logs.json not found" >&2
  exit 1
fi
log_files="$(LOG_DIR="${log_dir}" python -c 'import json, os; from pathlib import Path; p = Path(os.environ["LOG_DIR"]) / "logs.json"; manifest = json.loads(p.read_text(encoding="utf-8")); print("\n".join(manifest.keys()))')"
if [ -z "${log_files}" ]; then
  echo "error: no log files listed in ${log_dir}/logs.json" >&2
  exit 1
fi

while IFS= read -r log_file; do
  [ -z "${log_file}" ] && continue
  uv run --project "${scorer_project}" --python 3.11 --frozen -- inspect score \
    --scorer "${scorer_spec}" \
    --overwrite \
    "${log_dir}/${log_file}"
done <<<"${log_files}"

echo "== score: aggregate (astabench score)" >&2
# Disable LiteLLM cost lookups for scoring (keyless CI smoke; mockllm has no costs).
LITELLM_LOCAL_MODEL_COST_MAP=True uv run --project "${scorer_project}" --python 3.11 --frozen -- astabench score "${log_dir}"

echo "== smoke: ok" >&2
