#!/bin/bash
# Run the SQA solver on just the sqa_dev task

set -euo pipefail

if [ -z "$MODAL_TOKEN" ]; then
    echo "MODAL_TOKEN must be set"
    exit 1
fi
if [ -z "$MODAL_TOKEN_SECRET" ]; then
    echo "Warning: MODAL_TOKEN_SECRET must be set"
fi
if [ -z "S2_API_KEY" ]; then
    echo "Warning: S2_API_KEY must be set"
fi
if [ -z "MABOOL_URL" ]; then
    echo "Warning: MABOOL_URL must be set for paper-finder"
fi


uv run astabench eval \
--solver agent_baselines/solvers/asta/v0/asta.py@fewshot_textsim_router \
--model openai/gpt-4.1 \
--split validation \
--ignore-git \
--limit 1 \
$*
