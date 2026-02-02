#!/bin/bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

./scripts/solver_uv.sh sync e2e_discovery
