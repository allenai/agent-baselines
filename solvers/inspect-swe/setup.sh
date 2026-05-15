#!/bin/bash
# Sync the inspect_swe solver's dependencies and vendor asta-plugins.
#
# Skill trees are extracted directly from the asta image's
# ``/opt/asta-plugins`` (the canonical source repo per the asta-plugins
# Dockerfile's ``COPY . /opt/asta-plugins``). One env var — ASTA_IMAGE —
# controls both the asta CLI inside the sandbox and the host-side
# skill trees the solver loads; skew between them is structurally
# impossible, so any ASTA_IMAGE (including ``:latest``) yields a
# self-consistent setup.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../.." && pwd)"
cd "${repo_root}"

uv sync --project "solvers/inspect-swe" --python 3.11

ASTA_IMAGE="${ASTA_IMAGE:-ghcr.io/allenai/asta:v0.16.0}"
vendor="${here}/.vendor/asta-plugins"
stamp="${vendor}/.image-id"

# Refresh the local cache against the registry. No-op when the local
# tag already matches; needed when ASTA_IMAGE is a mutable tag (e.g.
# :latest) that the registry may have re-pushed.
docker pull --quiet "${ASTA_IMAGE}" >/dev/null

# Image ID is the immutable content hash — re-extract only when the
# bytes change, regardless of whether the user pulled by tag or digest.
image_id="$(docker image inspect --format '{{.Id}}' "${ASTA_IMAGE}")"
existing_id="$(cat "${stamp}" 2>/dev/null || true)"
if [ "${existing_id}" != "${image_id}" ]; then
    rm -rf "${vendor}"
    mkdir -p "${vendor}"
    docker run --rm "${ASTA_IMAGE}" tar -cC /opt/asta-plugins . \
        | tar -xC "${vendor}"
    echo "${image_id}" > "${stamp}"
fi
