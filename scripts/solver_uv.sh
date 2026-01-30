#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage:
  scripts/solver_uv.sh sync <solver>
  scripts/solver_uv.sh lock <solver>
  scripts/solver_uv.sh run  <solver> -- <command...>

Environment:
  SOLVER_UV_PYTHON   Python version for uv (default: 3.11)

Notes:
  - Run from repo root.
  - Requires: uv
  - Expects: solvers/<solver>/pyproject.toml
EOF
}

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv not found on PATH" >&2
  exit 127
fi

if [ ! -f "pyproject.toml" ] || [ ! -d "solvers" ]; then
  echo "error: must run from repo root (expected ./pyproject.toml and ./solvers/)" >&2
  exit 2
fi

uv_python="${SOLVER_UV_PYTHON:-3.11}"
uv_python_args=(--python "${uv_python}")

if [ $# -lt 2 ]; then
  usage
  exit 2
fi

action="$1"
solver="$2"
project_dir="solvers/${solver}"
project_pyproject="${project_dir}/pyproject.toml"
project_lock="${project_dir}/uv.lock"

if [ ! -f "${project_pyproject}" ]; then
  echo "error: missing ${project_pyproject} (solver '${solver}' is not a uv sub-project yet)" >&2
  exit 2
fi

case "${action}" in
  lock)
    uv lock --project "${project_dir}" "${uv_python_args[@]}"
    ;;
  sync)
    if [ ! -f "${project_lock}" ]; then
      uv lock --project "${project_dir}" "${uv_python_args[@]}"
    fi
    uv sync --project "${project_dir}" "${uv_python_args[@]}"
    ;;
  run)
    shift 2
    if [ "${1:-}" = "--" ]; then
      shift
    fi
    if [ $# -eq 0 ]; then
      usage
      exit 2
    fi
    uv run --project "${project_dir}" "${uv_python_args[@]}" --frozen "$@"
    ;;
  *)
    usage
    exit 2
    ;;
esac
