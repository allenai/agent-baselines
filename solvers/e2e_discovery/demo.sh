#!/bin/bash
# Run the Asta Panda solver on just the e2e_discovery_dev task

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

# Note the use of 'mockllm/model' because results are cached, no model is actually used.

./scripts/solver_uv.sh run e2e_discovery -- inspect eval \
--solver agent_baselines/solvers/e2e_discovery/autoasta/autoasta_cached.py@autoasta_cached_solver \
--model mockllm/model \
--limit 1 \
"$@" \
astabench/e2e_discovery_validation
