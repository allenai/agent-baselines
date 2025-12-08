#!/bin/bash
# Run the SQA solver on just the sqa_dev task

set -euo pipefail

if [ -z "$MODAL_TOKEN" ]; then
    echo "MODAL_TOKEN must be set"
fi
if [ -z "${MODAL_TOKEN_SECRET:-}" ]; then
    echo "Warning: MODAL_TOKEN_SECRET must be set"
fi
if [ -z "${ASTA_TOOL_KEY:-}" ]; then
    echo "Warning: ASTA_TOOL_KEY must be set"
fi


uv run inspect eval \
--solver agent_baselines/solvers/sqa/sqa.py@sqa_solver \
--limit 1 \
$* \
astabench/sqa_dev
