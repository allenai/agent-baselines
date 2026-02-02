#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage:
  scripts/smoke_solvers.sh [solver ...]

Runs a basic smoke check for each solver uv sub-project (solvers/<solver>/pyproject.toml):
  1) uv sync (via scripts/solver_uv.sh)
  2) Import + version print for astabench, inspect_ai, agent_baselines

If no solver args are provided, solvers are auto-discovered from:
  solvers/*/pyproject.toml

Environment:
  SOLVER_UV_PYTHON   Python version for uv (default: 3.11)

Notes:
  - Run from repo root.
  - Requires: uv
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ ! -f "pyproject.toml" ] || [ ! -d "solvers" ]; then
  echo "error: must run from repo root (expected ./pyproject.toml and ./solvers/)" >&2
  exit 2
fi

solvers=()
if [ $# -gt 0 ]; then
  solvers=("$@")
else
  while IFS= read -r -d '' pyproject; do
    solver_dir="$(dirname "${pyproject}")"
    solvers+=("$(basename "${solver_dir}")")
  done < <(find solvers -mindepth 2 -maxdepth 2 -name pyproject.toml -print0 | sort -z)
fi

if [ ${#solvers[@]} -eq 0 ]; then
  echo "no solver uv sub-projects found (no solvers/*/pyproject.toml)" >&2
  exit 2
fi

current_solver=""
trap 'echo "error: smoke failed for solver: ${current_solver}" >&2' ERR

for solver in "${solvers[@]}"; do
  current_solver="${solver}"
  echo "== smoke: ${solver}"

  ./scripts/solver_uv.sh sync "${solver}"

  ./scripts/solver_uv.sh run "${solver}" -- python - <<PY
import sys

import agent_baselines
import agent_baselines.solvers
import astabench
import inspect_ai

print("python:", sys.version.split()[0], "executable:", sys.executable)
print("agent_baselines:", getattr(agent_baselines, "__version__", "unknown"), list(agent_baselines.__path__))
print("agent_baselines.solvers:", agent_baselines.solvers.__file__)
print("astabench:", getattr(astabench, "__version__", "unknown"), astabench.__file__)
print("inspect_ai:", getattr(inspect_ai, "__version__", "unknown"), inspect_ai.__file__)
PY
done

echo "== smoke: passed ${#solvers[@]} solver(s)"
