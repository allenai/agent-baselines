#!/bin/bash

if [ -z "$MODAL_TOKEN" ]; then
    echo "Warning: MODAL_TOKEN is not set. This token is required for running SQA"
fi

uv sync --extra sqa
