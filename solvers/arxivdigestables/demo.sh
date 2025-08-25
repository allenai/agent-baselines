#!/bin/bash
# Run the solver on just the arxivdigestables task

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


uv run inspect eval \
--solver agent_baselines/solvers/arxivdigestables/asta_table_agent.py@tables_solver \
--model openai/gpt-4.1 \
--limit 1 \
$* \
astabench/arxivdigestables_validation
