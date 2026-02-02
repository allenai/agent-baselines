from __future__ import annotations

import re
from pathlib import Path


def test_inspect_compat_exports() -> None:
    from agent_baselines import inspect_compat

    assert callable(inspect_compat.transcript)
    assert callable(inspect_compat.execute_tools)
    assert callable(inspect_compat.perplexity_api_class)


def test_perplexity_api_class_errors_cleanly_when_unavailable() -> None:
    from agent_baselines import inspect_compat

    try:
        cls = inspect_compat.perplexity_api_class()
    except ImportError as exc:
        assert "Perplexity" in str(exc)
    else:
        assert isinstance(cls, type)


def test_no_private_inspect_imports_outside_compat() -> None:
    root = Path(__file__).resolve().parents[1] / "agent_baselines"
    offenders: list[str] = []

    for path in root.rglob("*.py"):
        if path.name == "inspect_compat.py":
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"inspect_ai\.[a-zA-Z0-9_\.]*\._", text):
            offenders.append(str(path.relative_to(root)))

    assert not offenders, "Private inspect_ai imports found outside inspect_compat:\n" + "\n".join(
        offenders
    )
