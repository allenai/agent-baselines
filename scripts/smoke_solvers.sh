#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage:
  scripts/smoke_solvers.sh [solver ...]

Runs a basic smoke check for each solver uv sub-project (solvers/<solver>/pyproject.toml):
  1) uv sync --project solvers/<solver> --python 3.11
  2) Import + version print for astabench, inspect_ai, agent_baselines

If no solver args are provided, solvers are auto-discovered from:
  solvers/*/pyproject.toml

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

  uv sync --project "solvers/${solver}" --python 3.11

  uv run --project "solvers/${solver}" --python 3.11 --frozen -- python - <<PY
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

# Lock-coherence gate. inspect_ai enforces a minimum Anthropic SDK version at
# provider *construction* — not through package metadata — so an internally
# incoherent lock (inspect_ai bumped, anthropic left stale) sails past both
# ``uv lock --check`` and the plain imports above, then fails only deep inside
# an eval with "Anthropic API requires at least version X of package anthropic"
# (allenai/gas2own#430). Construct the provider here so CI trips that gate in
# seconds instead. Solvers whose env has no anthropic are skipped.
try:
    import anthropic
except ImportError:
    print("anthropic: not in this solver env; skipping provider-construction gate")
else:
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-smoke-placeholder-not-a-real-key")
    from inspect_ai.model import get_model

    try:
        get_model("anthropic/claude-sonnet-4-6")
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        # Only the version floor is a lock-coherence failure; a missing key or
        # network hiccup means we got *past* the gate, which is all we assert.
        if "at least version" in message or "Upgrade with" in message:
            raise
        print("anthropic provider: reached past version gate (non-version note:", message, ")")
    else:
        print("anthropic provider: constructs cleanly with anthropic", anthropic.__version__)
PY
done

echo "== smoke: passed ${#solvers[@]} solver(s)"
