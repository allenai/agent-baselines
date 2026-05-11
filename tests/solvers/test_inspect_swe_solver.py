"""Tests for the inspect_swe_solver wiring contract.

Cover the kwargs the solver passes to the underlying ``inspect_swe``
agent constructor: bridge filter wired by default, host
``ASTA_TOKEN`` propagated into the agent env only when set, and
``state.metadata["insertion_date"]`` translated into the matching
asta CLI date-cutoff vars.

Need the inspect_ai version that ships ``GenerateFilter`` and
``BridgedToolsSpec``; skip cleanly when run against the older
top-venv inspect_ai.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from inspect_ai.agent import BridgedToolsSpec  # noqa: F401
    from inspect_ai.model._model import GenerateInput  # noqa: F401
    from inspect_ai.tool import ToolDef
except ImportError:  # pragma: no cover
    pytest.skip(
        "inspect_swe solver tests require the newer inspect_ai; run via "
        "solvers/inspect-swe subproject venv",
        allow_module_level=True,
    )


def _run_solver(
    agent_kwargs=None,
    state_metadata=None,
    state_tools=None,
    fake_skill_dirs=None,
    **solver_kwargs,
):
    """Invoke ``inspect_swe_solver(...)`` with ``inspect_swe.claude_code``
    mocked. Returns the constructor's call kwargs.

    When ``install_asta_skills`` is set, ``_resolve_bundled_skills`` is
    patched to return ``fake_skill_dirs`` (defaults to a stub list with
    one entry) so tests don't depend on ``setup.sh`` having run.
    """
    from agent_baselines.solvers.inspect_swe.agent import inspect_swe_solver

    mock_agent = AsyncMock(return_value=MagicMock())

    with (
        patch("inspect_swe.claude_code") as mock_cc,
        patch(
            "agent_baselines.solvers.inspect_swe.agent._resolve_bundled_skills",
            return_value=fake_skill_dirs if fake_skill_dirs is not None else [],
        ),
    ):
        mock_cc.return_value = mock_agent
        solver = inspect_swe_solver(**(solver_kwargs or {}))
        state = MagicMock()
        state.metadata = dict(state_metadata or {})
        state.tools = list(state_tools or [])
        import asyncio

        asyncio.run(solver(state, AsyncMock()))
        return mock_cc.call_args.kwargs


class TestFilterWiring:
    def test_filter_wired_by_default(self):
        from agent_baselines.solvers.inspect_swe._filters import (
            deny_external_web_tools,
        )

        kwargs = _run_solver()
        assert kwargs.get("filter") is deny_external_web_tools

    def test_disable_knob(self):
        kwargs = _run_solver(deny_external_web=False)
        assert "filter" not in kwargs

    def test_explicit_filter_wins(self):
        """A caller passing ``filter=...`` directly via agent_kwargs gets to
        keep their filter; the default doesn't override."""

        async def custom(*a, **k):
            return None

        # agent_kwargs flows through **kwargs to the solver
        kwargs = _run_solver(filter=custom)
        assert kwargs.get("filter") is custom


class TestTokenPropagation:
    def test_host_asta_token_reaches_agent_env(self):
        """The agent legitimately needs ASTA_TOKEN to talk to the asta
        gateway. The solver propagates the host-set token into the agent
        process env."""
        with patch.dict(os.environ, {"ASTA_TOKEN": "host-token"}):
            kwargs = _run_solver()
        env_arg = kwargs.get("env") or {}
        assert env_arg.get("ASTA_TOKEN") == "host-token"

    def test_no_token_when_host_unset(self):
        """If the host has no ASTA_TOKEN, the solver doesn't fabricate one."""
        env_before = dict(os.environ)
        os.environ.pop("ASTA_TOKEN", None)
        try:
            kwargs = _run_solver()
        finally:
            os.environ.clear()
            os.environ.update(env_before)
        env_arg = kwargs.get("env") or {}
        assert "ASTA_TOKEN" not in env_arg


class TestInsertionDatePropagation:
    """Per-sample date cutoffs: when the task exposes
    ``state.metadata["insertion_date"]`` (asta-bench's
    ``set_insertion_date`` helper), the solver seeds the agent's env
    with the matching asta CLI vars. Caller-supplied env wins."""

    def test_metadata_drives_env(self):
        kwargs = _run_solver(state_metadata={"insertion_date": "2024-10-17"})
        env = kwargs.get("env") or {}
        assert env.get("ASTA_INSERTED_BEFORE") == "2024-10-17"
        assert env.get("ASTA_PUBLICATION_DATE_RANGE") == ":2024-10-17"

    def test_no_metadata_no_env(self):
        kwargs = _run_solver(state_metadata={})
        env = kwargs.get("env") or {}
        assert "ASTA_INSERTED_BEFORE" not in env
        assert "ASTA_PUBLICATION_DATE_RANGE" not in env

    def test_caller_env_wins(self):
        kwargs = _run_solver(
            state_metadata={"insertion_date": "2024-10-17"},
            extra_env={
                "ASTA_INSERTED_BEFORE": "2023-01-01",
                "ASTA_PUBLICATION_DATE_RANGE": "2020-",
            },
        )
        env = kwargs.get("env") or {}
        assert env["ASTA_INSERTED_BEFORE"] == "2023-01-01"
        assert env["ASTA_PUBLICATION_DATE_RANGE"] == "2020-"


class TestInstallAstaSkills:
    """``install_asta_skills`` enables a skill-driven paper-search surface.
    The solver resolves bundled skill dirs from the host-side
    ``.vendor/asta-plugins`` clone and passes them through inspect_swe's
    standard ``skills=`` plumbing — per-agent installation path handled
    by inspect_swe. Paper-search MCP tools with a CLI equivalent are
    filtered from the bridge; non-paper tools and MCP tools without a
    CLI counterpart (get_paper_batch, search_paper_by_title) keep the
    MCP path."""

    def _named_tool(self, name: str):
        from inspect_ai.tool import ToolDef
        from inspect_ai.tool._tool_info import ToolParams

        async def _impl() -> str:
            return ""

        return ToolDef(
            tool=_impl, name=name, description="stub", parameters=ToolParams()
        ).as_tool()

    def test_default_bridges_all_state_tools_no_skills(self):
        kwargs = _run_solver(state_tools=[self._named_tool("snippet_search")])
        assert "bridged_tools" in kwargs
        assert [ToolDef(t).name for t in kwargs["bridged_tools"][0].tools] == [
            "snippet_search"
        ]
        assert kwargs.get("skills") is None

    def test_asta_passes_skill_dirs_and_filters_paper_tools(self, tmp_path):
        fake_dirs = [tmp_path / "semantic-scholar", tmp_path / "preview"]
        kwargs = _run_solver(
            install_asta_skills="asta",
            fake_skill_dirs=fake_dirs,
            state_tools=[
                self._named_tool("snippet_search"),
                self._named_tool("get_paper"),
                self._named_tool("table_editor"),
            ],
        )
        assert kwargs["skills"] == fake_dirs
        # Paper-search tools filtered; table_editor passes through.
        assert [ToolDef(t).name for t in kwargs["bridged_tools"][0].tools] == [
            "table_editor"
        ]

    def test_uncovered_mcp_tools_pass_through_when_skills_installed(self, tmp_path):
        """get_paper_batch and search_paper_by_title have no asta CLI
        equivalent — they keep the MCP path even when skills install."""
        kwargs = _run_solver(
            install_asta_skills="asta",
            fake_skill_dirs=[tmp_path / "semantic-scholar"],
            state_tools=[
                self._named_tool("get_paper_batch"),
                self._named_tool("search_paper_by_title"),
            ],
        )
        names = [ToolDef(t).name for t in kwargs["bridged_tools"][0].tools]
        assert set(names) == {"get_paper_batch", "search_paper_by_title"}

    def test_missing_vendor_dir_raises(self):
        """If setup.sh wasn't run, fail loudly before the eval starts."""
        from agent_baselines.solvers.inspect_swe.agent import inspect_swe_solver

        with (
            patch("inspect_swe.claude_code"),
            patch(
                "agent_baselines.solvers.inspect_swe.agent._resolve_bundled_skills",
                side_effect=FileNotFoundError("setup.sh not run"),
            ),
        ):
            with pytest.raises(FileNotFoundError):
                inspect_swe_solver(install_asta_skills="asta")

    def test_bridge_off_disables_everything(self):
        kwargs = _run_solver(
            bridge_astabench_tools=False,
            state_tools=[self._named_tool("snippet_search")],
        )
        assert "bridged_tools" not in kwargs
