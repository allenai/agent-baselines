#!/bin/bash
# Run the SQA solver on just the sqa_dev task

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
if [ -z "${PAPER_FINDER_URL:-}" ]; then
    echo "Warning: PAPER_FINDER_URL must be set for paper-finder"
fi

# Note the use of 'mockllm/model' because models are directly configured for
# each sub-agent, top-level `--model` settings will not be applied.

./scripts/solver_uv.sh run asta-v0 -- astabench eval \
--solver agent_baselines/solvers/asta/v0/asta.py@fewshot_textsim_router \
--model mockllm/model \
--split validation \
--ignore-git \
--limit 1 \
"$@"
