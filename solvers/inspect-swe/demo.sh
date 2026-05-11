#!/bin/bash
# Runs the inspect_swe solver on one sample from each task of the validation set.
# Pass any astabench eval args (or a specific task) as positional args, e.g.
# `demo.sh astabench/litqa2_validation`.
#
# Required env:
#   AGENT              - one of: claude_code, codex_cli, gemini_cli, mini_swe_agent
#   MODEL              - model passed to Inspect, e.g. anthropic/claude-sonnet-4-6,
#                        openai/gpt-5-mini. inspect_swe proxies the agent CLI's
#                        HTTP calls back to Inspect's get_model(), so any agent
#                        can run against any model the matching provider key is
#                        set for.
#   ASTA_TOOL_KEY      - for astabench's asta MCP corpus tools
#   <provider>_API_KEY - matching the MODEL prefix (ANTHROPIC_API_KEY,
#                        OPENAI_API_KEY, GOOGLE_API_KEY, ...)
#
# Optional env:
#   ASTA_IMAGE         - asta-plugins image tag (default ghcr.io/allenai/asta:v0.16.0)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [ -z "${AGENT:-}" ]; then
    echo "AGENT is not set (one of: claude_code, codex_cli, gemini_cli, mini_swe_agent)" >&2
    exit 1
fi
if [ -z "${MODEL:-}" ]; then
    echo "MODEL is not set (e.g. anthropic/claude-sonnet-4-6, openai/gpt-5-mini)" >&2
    exit 1
fi

# Validate the right provider key for the chosen model.
case "${MODEL%%/*}" in
    anthropic) need_key=ANTHROPIC_API_KEY ;;
    openai) need_key=OPENAI_API_KEY ;;
    google|gemini) need_key=GOOGLE_API_KEY ;;
    *) need_key="" ;;
esac
if [ -n "${need_key}" ] && [ -z "${!need_key:-}" ]; then
    echo "${need_key} is not set (required for model ${MODEL})" >&2
    exit 1
fi
if [ -z "${ASTA_TOOL_KEY:-}" ]; then
    echo "ASTA_TOOL_KEY is not set (needed for asta MCP search tools)" >&2
    exit 1
fi

# If ASTA_TOKEN is set, sanity-check that it looks like a JWT. A common
# failure mode: `asta auth print-token --raw --refresh` writes its
# "❌ Not authenticated" error to stdout when the host has no asta auth,
# and a `$(...)` capture happily promotes the error string to ASTA_TOKEN.
# That then gets shipped into the agent container as a fake token and
# fails opaquely (latin-1 codec error on the ❌ when urllib builds the
# Authorization header).
if [ -n "${ASTA_TOKEN:-}" ] && [[ "${ASTA_TOKEN}" != eyJ* ]]; then
    echo "ASTA_TOKEN doesn't look like a JWT (expected to start with 'eyJ')." >&2
    echo "  Got: ${ASTA_TOKEN:0:80}..." >&2
    echo "  Likely cause: 'asta auth' on the host isn't configured. Run" >&2
    echo "    asta auth login" >&2
    echo "  on the host, then re-export ASTA_TOKEN before running demo.sh." >&2
    exit 1
fi

solver_args=(
    -S "agent=${AGENT}"
)

# Compose path is repo-relative; pass absolute so inspect resolves it correctly
# regardless of where the task lives.
COMPOSE="${repo_root}/solvers/inspect-swe/sandbox_compose.yaml"

uv run --project "solvers/inspect-swe" --python 3.11 --frozen -- astabench eval \
    --split validation \
    --solver agent_baselines/solvers/inspect_swe/agent.py@inspect_swe_solver \
    --model "${MODEL}" \
    --sandbox "docker:${COMPOSE}" \
    --limit 1 \
    "${solver_args[@]}" \
    "$@"
