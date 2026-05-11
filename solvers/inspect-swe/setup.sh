#!/bin/bash
# Sync the inspect_swe solver's dependencies and vendor asta-plugins.
#
# The asta-plugins clone provides the bundled skill trees the solver
# can install into the agent's sandbox via inspect_swe's standard
# ``skills=`` plumbing. Pin to a tag that matches your asta image so
# the skills line up with what the image is built from.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../.." && pwd)"
cd "${repo_root}"

uv sync --project "solvers/inspect-swe" --python 3.11

# Vendor asta-plugins for host-side skill resolution. ASTA_PLUGINS_REF
# defaults to the asta image tag (kept in sync with ASTA_IMAGE) so
# bundled skills match what's baked into the image.
ASTA_IMAGE="${ASTA_IMAGE:-ghcr.io/allenai/asta:v0.16.0}"
ASTA_PLUGINS_REF="${ASTA_PLUGINS_REF:-${ASTA_IMAGE##*:}}"
vendor="${here}/.vendor/asta-plugins"
if [ ! -d "${vendor}/.git" ]; then
    rm -rf "${vendor}"
    mkdir -p "$(dirname "${vendor}")"
    git clone --depth 1 --branch "${ASTA_PLUGINS_REF}" \
        https://github.com/allenai/asta-plugins.git "${vendor}"
else
    git -C "${vendor}" fetch --depth 1 origin "${ASTA_PLUGINS_REF}"
    git -C "${vendor}" checkout FETCH_HEAD
fi
