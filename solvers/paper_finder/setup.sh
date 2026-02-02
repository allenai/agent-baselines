#!/bin/bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [ -z "${PAPER_FINDER_URL:-}" ]; then
    echo "Warning: PAPER_FINDER_URL is not set." >&2
    echo "Bringing up an instance of PaperFinder is required for running PaperFinder solver, see asta-paper-finder repo for guidance." >&2
fi

if [ -z "${ASTA_TOOL_KEY:-}" ]; then
    echo "Warning: ASTA_TOOL_KEY is not set. This key is required for running the PaperFindingBench task" >&2
fi


./scripts/solver_uv.sh sync paper_finder
