#!/bin/bash
# Run the solver on just the arxivdigestables task

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [ -z "${MODAL_TOKEN:-}" ]; then
    echo "MODAL_TOKEN must be set"
    exit 1
fi
if [ -z "${MODAL_TOKEN_SECRET:-}" ]; then
    echo "Warning: MODAL_TOKEN_SECRET must be set"
fi
if [ -z "${ASTA_TOOL_KEY:-}" ]; then
    echo "Warning: ASTA_TOOL_KEY must be set"
fi


./scripts/solver_uv.sh run arxivdigestables -- inspect eval \
--solver agent_baselines/solvers/arxivdigestables/asta_table_agent.py@tables_solver \
--model openai/gpt-4.1 \
--limit 1 \
"$@" \
astabench/arxivdigestables_validation
