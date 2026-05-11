"""inspect_swe-backed coding agent solvers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

from inspect_ai.agent import BridgedToolsSpec
from inspect_ai.solver import Generate, Solver, TaskState, solver

from agent_baselines.solvers.inspect_swe._filters import deny_external_web_tools

logger = logging.getLogger(__name__)

AgentName = Literal["claude_code", "codex_cli", "gemini_cli", "mini_swe_agent"]
AstaPlugin = Literal["asta", "asta-preview"]

_VENDOR_ASTA_PLUGINS = (
    Path(__file__).resolve().parents[3]
    / "solvers"
    / "inspect-swe"
    / ".vendor"
    / "asta-plugins"
)

# MCP paper-search tools with a 1:1 `asta papers` CLI subcommand;
# filtered from the bridge when bundled asta skills are installed.
_ASTA_MCP_PAPER_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "snippet_search",
        "search_papers_by_relevance",
        "get_paper",
        "get_citations",
        "search_authors_by_name",
        "get_author_papers",
    }
)


def _resolve_bundled_skills(plugin: AstaPlugin) -> list[Path]:
    plugin_dir = _VENDOR_ASTA_PLUGINS / "plugins" / plugin / "skills"
    if not plugin_dir.is_dir():
        raise FileNotFoundError(
            f"Bundled skills not found at {plugin_dir}. "
            f"Run solvers/inspect-swe/setup.sh to clone asta-plugins."
        )
    return sorted(d for d in plugin_dir.iterdir() if (d / "SKILL.md").is_file())


@solver
def inspect_swe_solver(
    agent: AgentName = "claude_code",
    install_asta_skills: AstaPlugin | None = None,
    bridge_astabench_tools: bool = True,
    deny_external_web: bool = True,
    system_prompt: str | None = None,
    max_attempts: int = 1,
    sandbox_name: str | None = None,
    extra_env: dict[str, str] | None = None,
    **agent_kwargs: Any,
) -> Solver:
    try:
        from inspect_swe import claude_code, codex_cli, gemini_cli, mini_swe_agent
    except ImportError as e:
        logger.error(
            "inspect_swe import failed (%s). Invoke via "
            "`uv run --project solvers/inspect-swe`.",
            e,
        )
        raise

    constructors = {
        "claude_code": claude_code,
        "codex_cli": codex_cli,
        "gemini_cli": gemini_cli,
        "mini_swe_agent": mini_swe_agent,
    }
    if agent not in constructors:
        raise ValueError(f"Unknown agent {agent!r}; choose from {sorted(constructors)}")
    constructor = constructors[agent]

    skill_dirs: list[Path] | None = None
    if install_asta_skills is not None:
        skill_dirs = _resolve_bundled_skills(install_asta_skills)

    base_env: dict[str, str] = dict(extra_env or {})
    if asta_token := os.environ.get("ASTA_TOKEN"):
        base_env.setdefault("ASTA_TOKEN", asta_token)

    async def execute(state: TaskState, generate: Generate) -> TaskState:
        env = dict(base_env)
        if insertion_date := state.metadata.get("insertion_date"):
            env.setdefault("ASTA_INSERTED_BEFORE", str(insertion_date))
            env.setdefault("ASTA_PUBLICATION_DATE_RANGE", f":{insertion_date}")

        kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "attempts": max_attempts,
            "env": env or None,
            "skills": skill_dirs,
            **agent_kwargs,
        }
        if deny_external_web:
            kwargs.setdefault("filter", deny_external_web_tools)
        if sandbox_name is not None:
            kwargs["sandbox"] = sandbox_name

        if bridge_astabench_tools and state.tools:
            tools_to_bridge = list(state.tools)
            if install_asta_skills is not None:
                from inspect_ai.tool import ToolDef

                tools_to_bridge = [
                    t
                    for t in tools_to_bridge
                    if ToolDef(t).name not in _ASTA_MCP_PAPER_TOOL_NAMES
                ]
            if tools_to_bridge:
                kwargs["bridged_tools"] = [
                    BridgedToolsSpec(name="astabench", tools=tools_to_bridge)
                ]

        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        agent_obj = constructor(**kwargs)
        return await agent_obj(state)

    return execute


@solver
def claude_code_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="claude_code", **kwargs)


@solver
def codex_cli_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="codex_cli", **kwargs)


@solver
def gemini_cli_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="gemini_cli", **kwargs)


@solver
def mini_swe_agent_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="mini_swe_agent", **kwargs)
