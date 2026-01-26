#!/bin/bash

set -euo pipefail

if [ ! -f solvers/react/uv.lock ]; then
    uv lock --project solvers/react
fi

uv sync --project solvers/react
