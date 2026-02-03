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
  scripts/eval_then_score.sh <solver> [--log-dir <dir>] [--] <astabench eval args...>

Examples:
  # Solve+score a small validation run, writing logs to a known directory
  scripts/eval_then_score.sh react --log-dir logs/react_two_phase -- \
    --split validation --solver agent_baselines/solvers/react/basic_agent.py@instantiated_basic_agent \
    --model openai/gpt-4.1-nano --limit 1

Notes:
  - The eval phase enforces `--no-score --log-format json` for later scoring.
  - The score phase runs in the frozen scorer env: `./scripts/solver_uv.sh run scorer -- astabench score <log_dir>`.
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

find_repo_root() {
  local dir="$PWD"
  while true; do
    if [ -f "${dir}/pyproject.toml" ] && [ -d "${dir}/solvers" ]; then
      printf '%s\n' "${dir}"
      return 0
    fi
    if [ "${dir}" = "/" ]; then
      return 1
    fi
    dir="$(dirname "${dir}")"
  done
}

repo_root="$(find_repo_root)" || {
  echo "error: must run from within the repo (expected an ancestor dir with pyproject.toml + solvers/)" >&2
  exit 2
}

cd "${repo_root}"

if [ $# -lt 1 ]; then
  usage
  exit 2
fi

solver="$1"
shift

log_dir=""
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
./scripts/solver_uv.sh run "${solver}" -- astabench eval \
  --log-dir "${log_dir}" \
  --no-score \
  --log-format json \
  "${eval_args[@]}"

echo "== score: ${log_dir} (scorer env)" >&2
./scripts/solver_uv.sh run scorer -- astabench score "${log_dir}"

echo "== done: scored logs in ${log_dir}" >&2
