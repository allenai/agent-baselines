#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage:
  scripts/new_solver.sh <name>

Creates a standard solver scaffold:
  - solvers/<name>/{README.md,env,setup.sh,demo.sh,pyproject.toml}
  - agent_baselines/solvers/<name>/{__init__.py,solver.py}

Notes:
  - Run from repo root.
  - Name must match: ^[a-z][a-z0-9_]*$
  - The generated solver defaults to astabench's pinned Inspect version. See
    docs/per_solver_envs.md for how to override inspect_ai with uv.
EOF
}

die() {
  echo "error: $*" >&2
  exit 2
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ $# -ne 1 ]; then
  usage
  exit 2
fi

solver="$1"

if [[ ! "${solver}" =~ ^[a-z][a-z0-9_]*$ ]]; then
  die "invalid solver name '${solver}' (expected ^[a-z][a-z0-9_]*$)"
fi

if [ ! -f "pyproject.toml" ] || [ ! -d "solvers" ] || [ ! -d "agent_baselines/solvers" ]; then
  die "must run from repo root (expected ./pyproject.toml, ./solvers/, ./agent_baselines/solvers/)"
fi

if [ ! -f "scripts/solver_uv.sh" ]; then
  die "missing scripts/solver_uv.sh"
fi

solver_dir="solvers/${solver}"
code_dir="agent_baselines/solvers/${solver}"

if [ -e "${solver_dir}" ]; then
  die "already exists: ${solver_dir}"
fi

if [ -e "${code_dir}" ]; then
  die "already exists: ${code_dir}"
fi

project_name_suffix="${solver//_/-}"
project_name="agent-baselines-${project_name_suffix}"

mkdir -p "${solver_dir}"
mkdir -p "${code_dir}"

cat > "${solver_dir}/pyproject.toml" <<EOF
[build-system]
requires = ["setuptools>=61", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "${project_name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "astabench==0.3.1",
    "inspect_ai==0.3.114",
]

# To diverge from astabench's exact Inspect pin, use a uv override:
#
# [tool.uv]
# override-dependencies = [
#     "inspect_ai==0.3.169",
# ]
EOF

cat > "${solver_dir}/setup.sh" <<EOF
#!/usr/bin/env bash

set -euo pipefail

./scripts/solver_uv.sh sync ${solver}
EOF

cat > "${solver_dir}/demo.sh" <<EOF
#!/usr/bin/env bash

set -euo pipefail

# Runs a tiny eval using inspect's built-in mock model so it works without API keys.
./scripts/solver_uv.sh run ${solver} -- inspect eval \\
  astabench/evals/demo/arithmetic/task.py \\
  --model mockllm/model \\
  --solver agent_baselines/solvers/${solver}/solver.py@demo_solver \\
  --limit 1 \\
  "\$@"
EOF

cat > "${solver_dir}/env" <<'EOF'
ASTA_TOOL_KEY
EOF

cat > "${solver_dir}/README.md" <<EOF
# ${solver}

This directory contains **run artifacts** for the \`${solver}\` solver (scripts, env var
list, and per-solver dependencies).

## Quick start
From repo root:
1. \`./solvers/${solver}/setup.sh\`
2. \`./solvers/${solver}/demo.sh\`

## Dependencies
- \`solvers/${solver}/pyproject.toml\` pins per-solver deps (including \`astabench\` and \`inspect_ai\`).
- Generate/update the lockfile with: \`./scripts/solver_uv.sh lock ${solver}\`

See \`docs/per_solver_envs.md\` for per-solver dependency workflow and Inspect override strategy.
EOF

cat > "${code_dir}/__init__.py" <<'EOF'
EOF

cat > "${code_dir}/solver.py" <<'EOF'
from inspect_ai.solver import Solver, solver

from agent_baselines.solvers.llm import llm_with_prompt


@solver
def demo_solver() -> Solver:
    """Minimal starter solver used by solvers/<name>/demo.sh."""

    return llm_with_prompt(system_prompt="You are a helpful assistant.")
EOF

chmod +x "${solver_dir}/setup.sh" "${solver_dir}/demo.sh"

echo "created ${solver_dir}/ and ${code_dir}/"
echo "next: ./scripts/solver_uv.sh lock ${solver}"
