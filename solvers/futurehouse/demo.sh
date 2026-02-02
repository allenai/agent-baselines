#!/bin/bash
# Run the FutureHouse solver on one sample of the sqa_dev task

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [ -z "${FUTUREHOUSE_API_KEY:-}" ] && [ -z "${FH_API_KEY:-}" ]; then
    echo "Warning: FUTUREHOUSE_API_KEY or FH_API_KEY must be set"
fi

if [ -z "${ASTA_TOOL_KEY:-}" ]; then
    echo "Warning: ASTA_TOOL_KEY must be set"
fi

./scripts/solver_uv.sh run futurehouse -- inspect eval \
--solver agent_baselines/solvers/futurehouse/futurehouse_solver.py@futurehouse_solver \
--model openai/gpt-4.1-nano \
--limit 1 \
"$@" \
astabench/sqa_dev
