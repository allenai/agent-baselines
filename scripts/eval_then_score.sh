#!/usr/bin/env bash

# Two-phase "solve then score" wrapper.
#
# Runs:
#  1) Solve in a solver uv env with `--no-score --log-format json` to produce logs
#  2) Score those logs in the frozen `scorer` uv env
#
# This exists to decouple scoring from solver dependency stacks (notably
# `inspect_ai`): solvers can run with whatever Inspect version they need, while
# scoring remains pinned to a known-good Inspect version in `solvers/scorer/`.

set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage:
  scripts/eval_then_score.sh <solver> [--log-dir <dir>] [--scorer <scorer_spec>] [--] <astabench eval args...>

Examples:
  # Solve+score a small validation run, writing logs to a known directory
  scripts/eval_then_score.sh react --log-dir logs/react_two_phase -- \
    --split validation --solver agent_baselines/solvers/react/basic_agent.py@instantiated_basic_agent \
    --model openai/gpt-4.1-nano --limit 1

Notes:
  - The eval phase enforces `--no-score --log-format json` for later scoring.
  - For custom/non-registered scorers, pass `--scorer <path.py@scorer_name>`.
  - The score phase runs in the frozen scorer env via:
      1) `inspect score --overwrite` per log file
      2) `astabench score <log_dir>` aggregation
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -f "${repo_root}/pyproject.toml" ] || [ ! -d "${repo_root}/solvers" ]; then
  echo "error: could not determine repo root from script path (${repo_root})" >&2
  exit 2
fi

cd "${repo_root}"

if [ $# -lt 1 ]; then
  usage
  exit 2
fi

solver="$1"
shift

if [ ! -f "solvers/${solver}/pyproject.toml" ]; then
  echo "error: unknown solver env '${solver}' (missing solvers/${solver}/pyproject.toml)" >&2
  exit 2
fi
if [ ! -f "solvers/scorer/pyproject.toml" ]; then
  echo "error: missing scorer env (solvers/scorer/pyproject.toml)" >&2
  exit 2
fi

log_dir=""
score_scorer=""
while [ $# -gt 0 ]; do
  case "$1" in
    --log-dir)
      if [ $# -lt 2 ]; then
        echo "error: --log-dir requires a value" >&2
        exit 2
      fi
      log_dir="$2"
      shift 2
      ;;
    --log-dir=*)
      log_dir="${1#--log-dir=}"
      shift
      ;;
    --scorer)
      if [ $# -lt 2 ]; then
        echo "error: --scorer requires a value" >&2
        exit 2
      fi
      score_scorer="$2"
      shift 2
      ;;
    --scorer=*)
      score_scorer="${1#--scorer=}"
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [ -z "${log_dir}" ]; then
  ts="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
  log_dir="logs/${solver}_two_phase_${ts}"
fi

mkdir -p "${log_dir}"

eval_args=("$@")

echo "== solve: ${solver} -> ${log_dir}" >&2
uv run --project "solvers/${solver}" --python 3.11 --frozen -- astabench eval \
  --log-dir "${log_dir}" \
  --no-score \
  --log-format json \
  "${eval_args[@]}"

echo "== score: inspect score (scorer env)" >&2
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
  score_cmd=(
    uv run --project "solvers/scorer" --python 3.11 --frozen -- inspect score
  )
  if [ -n "${score_scorer}" ]; then
    score_cmd+=(--scorer "${score_scorer}")
  fi
  score_cmd+=(--overwrite)
  score_cmd+=("${log_dir}/${log_file}")
  "${score_cmd[@]}"
done <<<"${log_files}"

echo "== score: aggregate ${log_dir} (scorer env)" >&2
# Note: --scorer applies to inspect score above; astabench score only aggregates.
# Required by astabench score: prep_litellm_cost_map() raises without this.
LITELLM_LOCAL_MODEL_COST_MAP=True uv run --project "solvers/scorer" --python 3.11 --frozen -- astabench score "${log_dir}"

echo "== done: scored logs in ${log_dir}" >&2
