#!/usr/bin/env bash

# Optional helper to convert Inspect log files between formats.
#
# `inspect log convert` must run in an environment that can *read* the source
# logs. This wrapper makes it easy to run conversion in a specific uv
# sub-project env (solver env or the frozen scorer env).
#
# For new runs, prefer producing JSON logs up front with:
#   astabench eval --log-format json

set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage:
  scripts/inspect_log_convert.sh <env> <inspect log convert args...>

Examples:
  # Convert a directory of logs to JSON, running conversion in the solver env
  scripts/inspect_log_convert.sh paper_finder --to json --output-dir logs_json ./logs/paper_finder

  # Convert a single log file to JSON, running conversion in the scorer env
  scripts/inspect_log_convert.sh scorer --to json --output-dir logs_json ./logs/run.json

Notes:
  - Run conversion in an env that can read the source logs (often the env that produced them).
  - For best cross-version scoring compatibility, use JSON logs (`--log-format json`).
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

# Keep in sync with scripts/eval_then_score.sh:find_repo_root.
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

if [ $# -lt 2 ]; then
  usage
  exit 2
fi

env_name="$1"
shift

if [ ! -f "solvers/${env_name}/pyproject.toml" ]; then
  echo "error: unknown env '${env_name}' (missing solvers/${env_name}/pyproject.toml)" >&2
  exit 2
fi

uv run --project "solvers/${env_name}" --python 3.11 --frozen -- inspect log convert "$@"
