#!/bin/bash
# Scores a directory of Inspect logs using the frozen scorer environment.
#
# Note: most solvers use demo.sh as a minimal end-to-end example. For the
# scorer, this script is effectively the "score logs" entrypoint.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [ $# -lt 1 ]; then
  echo "Usage: ./solvers/scorer/demo.sh <log_dir> [score args...]" >&2
  echo "Example: ./solvers/scorer/demo.sh logs/react" >&2
  exit 2
fi

log_dir="$1"
shift

./scripts/solver_uv.sh run scorer -- astabench score "${log_dir}" "$@"
