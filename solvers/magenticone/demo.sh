#!/bin/bash
# Run the magentic_autogen_bridge solver on one sample of the arithmetic_demo task

set -euo pipefail

uv run inspect eval \
--solver agent_baselines/solvers/magenticone/magentic_autogen_bridge.py@magentic_autogen_bridge \
--model openai/gpt-4o-mini \
--limit 1 \
$* \
arithmetic_demo
