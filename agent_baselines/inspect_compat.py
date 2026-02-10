"""InspectAI compatibility helpers.

This repo sometimes needs to run against multiple `inspect_ai` versions (one per
solver uv sub-project). A few `inspect_ai` APIs we rely on are not part of the
public stable surface (e.g. internal modules), so we centralize fallbacks here
to avoid scattering version-specific branches throughout solver code.
"""

from __future__ import annotations

from typing import Type

try:
    # Preferred public import path (0.3.x).
    from inspect_ai.log import transcript as transcript
except Exception:  # pragma: no cover
    # Fallback for older/changed layouts.
    from inspect_ai.log._transcript import transcript as transcript  # type: ignore

try:
    # Preferred public import path (0.3.x).
    from inspect_ai.model import execute_tools as execute_tools
except Exception:  # pragma: no cover
    # Fallback for older/changed layouts.
    from inspect_ai.model._call_tools import execute_tools as execute_tools  # type: ignore


def perplexity_api_class() -> Type[object]:
    """Return the Perplexity provider API class used by the SQA solver.

    Note: Inspect doesn't currently expose this via a public import path, so we
    centralize the internal import here.
    """

    try:
        from inspect_ai.model._providers.perplexity import PerplexityAPI
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "Perplexity provider API not found in installed inspect_ai; "
            "this solver requires an inspect_ai version that includes the Perplexity provider."
        ) from exc

    return PerplexityAPI
