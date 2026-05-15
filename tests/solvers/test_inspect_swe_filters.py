"""Tests for the bridge-level GenerateFilter that strips agent-CLI-built-in
web tools from model API requests.

The filter is the only chokepoint that can stop the agent from using
provider-executed web tools (claude_code's ``WebSearch``, OpenAI's
``web_search``, Gemini's ``google_web_search``, etc.) since those run
on the model provider's infrastructure and never touch the sandbox.

It deliberately only matches the unprefixed built-in names — tools
wired via ``state.tools`` reach the agent as ``mcp__astabench_*`` and
must pass through, so tasks can grant cutoff-aware web search via
``make_native_search_tools(...)`` and have it survive the filter.
"""

import asyncio

import pytest

# The filter targets inspect_ai>=0.3.130 (when GenerateFilter / GenerateInput
# landed). The repo's top-level venv pins an older inspect_ai for compatibility
# with other solvers; the inspect-swe subproject pins the newer one. Skip
# this whole module when run against an inspect_ai that pre-dates the filter
# API, so CI on the top venv stays green. Run manually in the subproject venv
# (`solvers/inspect-swe/.venv/bin/pytest tests/solvers/test_inspect_swe_filters.py`)
# before commit.
try:
    from inspect_ai.model._model import GenerateInput
except ImportError:  # pragma: no cover
    pytest.skip(
        "filter tests require inspect_ai with GenerateFilter API; run via "
        "solvers/inspect-swe subproject venv",
        allow_module_level=True,
    )


def _tool_info(name: str):
    """Build a minimal ToolInfo. The constructor needs ``name`` and
    ``description`` plus ``parameters`` (defaults are fine)."""
    from inspect_ai.tool import ToolInfo
    from inspect_ai.tool._tool_info import ToolParams

    return ToolInfo(name=name, description=f"stub for {name}", parameters=ToolParams())


def _generate_config():
    from inspect_ai.model import GenerateConfig

    return GenerateConfig()


class TestDenyExternalWebTools:
    @pytest.fixture
    def filter_fn(self):
        from agent_baselines.solvers.inspect_swe._filters import (
            deny_external_web_tools,
        )

        return deny_external_web_tools

    def test_strips_anthropic_web_tools(self, filter_fn):
        tools = [
            _tool_info("Bash"),
            _tool_info("WebSearch"),
            _tool_info("WebFetch"),
            _tool_info("Read"),
        ]
        result = asyncio.run(filter_fn(None, [], tools, None, _generate_config()))
        assert isinstance(result, GenerateInput)
        kept = [t.name for t in result.tools]
        assert kept == ["Bash", "Read"]

    def test_strips_lowercase_provider_variants(self, filter_fn):
        """OpenAI and others tend to use snake_case names."""
        from inspect_ai.model._model import GenerateInput

        tools = [
            _tool_info("shell"),
            _tool_info("web_search"),
            _tool_info("web_fetch"),
        ]
        result = asyncio.run(filter_fn(None, [], tools, None, _generate_config()))
        assert isinstance(result, GenerateInput)
        assert [t.name for t in result.tools] == ["shell"]

    def test_strips_gemini_variant(self, filter_fn):
        from inspect_ai.model._model import GenerateInput

        tools = [
            _tool_info("run_shell_command"),
            _tool_info("google_web_search"),
        ]
        result = asyncio.run(filter_fn(None, [], tools, None, _generate_config()))
        assert isinstance(result, GenerateInput)
        assert [t.name for t in result.tools] == ["run_shell_command"]

    def test_returns_none_when_nothing_to_strip(self, filter_fn):
        """No-op fast path: return None so inspect_ai uses the original input."""
        tools = [_tool_info("Bash"), _tool_info("Read")]
        result = asyncio.run(filter_fn(None, [], tools, None, _generate_config()))
        assert result is None

    def test_bridged_mcp_tools_pass_through(self, filter_fn):
        """Tools wired by tasks via ``state.tools`` reach the agent as
        ``mcp__astabench_<name>`` and must survive the filter — that's
        how cutoff-aware web search from ``make_native_search_tools``
        gets to the agent without being mistaken for a built-in."""
        tools = [
            _tool_info("Bash"),
            _tool_info("mcp__astabench_web_search"),
            _tool_info("mcp__astabench_snippet_search"),
        ]
        # No built-in web tool present → fast path returns None.
        result = asyncio.run(filter_fn(None, [], tools, None, _generate_config()))
        assert result is None

    def test_preserves_messages_and_config(self, filter_fn):
        """Filter only modifies tools; messages and config pass through."""
        from inspect_ai.model._model import GenerateInput

        cfg = _generate_config()
        msgs: list = []
        tools = [_tool_info("Bash"), _tool_info("WebSearch")]
        result = asyncio.run(filter_fn(None, msgs, tools, None, cfg))
        assert isinstance(result, GenerateInput)
        assert result.input is msgs
        assert result.config is cfg
        assert result.tool_choice is None
