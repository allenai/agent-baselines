"""GenerateFilter that strips agent-CLI-built-in web tools from model API requests."""

from __future__ import annotations

from typing import Any

from inspect_ai.model import ChatMessage, GenerateConfig, GenerateInput, Model
from inspect_ai.tool import ToolChoice, ToolInfo

# Tool names server-side web tools register under in each agent CLI's
# model API request payload. `web_search` is in inspect_swe's codex_cli
# `disallowed_tools` Literal; the others come from each provider's
# product docs (Anthropic's claude_code, Google's gemini_cli).
_BLOCKED_WEB_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # claude_code (Anthropic)
        "WebSearch",
        "WebFetch",
        # codex_cli (OpenAI)
        "web_search",
        "web_fetch",
        # gemini_cli (Google)
        "google_web_search",
    }
)


async def deny_external_web_tools(
    model: Model | None,
    messages: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice | None,
    config: GenerateConfig,
) -> Any:
    filtered = [t for t in tools if t.name not in _BLOCKED_WEB_TOOL_NAMES]
    if len(filtered) == len(tools):
        return None
    return GenerateInput(
        input=messages, tools=filtered, tool_choice=tool_choice, config=config
    )
