#!/bin/bash
# Run the magentic_autogen_bridge solver on one sample of the arithmetic_demo task

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

./scripts/solver_uv.sh run magenticone -- inspect eval \
--solver agent_baselines/solvers/magenticone/magentic_autogen_bridge.py@magentic_autogen_bridge \
--model openai/gpt-4o-mini \
--limit 1 \
"$@" \
arithmetic_demo
