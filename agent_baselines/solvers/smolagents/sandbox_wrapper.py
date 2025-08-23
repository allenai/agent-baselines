import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from inspect_ai.tool import ToolDef
from inspect_ai.util import sandbox
from smolagents import Tool as SmolTool
from smolagents.utils import BASE_BUILTIN_MODULES

from astabench.util.sandbox import SandboxJupyter, SandboxToolManager

logger = logging.getLogger(__name__)


class InspectAiSandboxExecutor:
    """
    Wrapper that allows smolagent agents to use inspect_ai's sandbox to run code.

    This is largely based on the
    [E2BExecutor](https://github.com/huggingface/smolagents/blob/12c923e03bdbb2e6e5139bde26d9fce69cdba599/src/smolagents/e2b_executor.py#L38)
    class from smolagents, with a changes to how the output is captured and how
    the code is actually run (Jupyter in Inspect's sandbox via MCP instead of
    the E2B remote execution).
    """

    def __init__(
        self,
        loop,
        additional_imports: List[str],
        logger,
        sandbox_name: str = "default",
        smolagent_tools: List[SmolTool] | None = None,
        inspect_tools: List[ToolDef] | None = None,
        env_vars: Dict[str, str] | None = None,
    ):
        self.custom_tools: dict[str, Any] = {}
        self.final_answer = False
        self.loop = loop
        self.sandbox = sandbox(sandbox_name)
        self.logger = logger
        self.additional_imports = additional_imports

        # Some smolagents infra likes this to exist; we don't use it
        self.state: dict[str, Any] = dict()

        # json is needed for wrapper code, but isn't in BASE_BUILTIN_MODULES
        if "json" not in self.additional_imports:
            self.additional_imports.append("json")

        self.smolagent_tools = smolagent_tools or []
        self.inspect_tools = inspect_tools or []

        self.inspect_tool_manager = SandboxToolManager(
            self.sandbox,
            tools=self.inspect_tools,
            include_final_answer_tool=True,
        )

        self.jupyter_client = SandboxJupyter(sandbox_name=sandbox_name)

    async def ainit(self):
        # Make tools available for code in the sandbox
        await self.inspect_tool_manager.setup_tool_environment()
        await self.jupyter_client.run_code(
            self.inspect_tool_manager.get_sandbox_preamble()
        )

        await self.jupyter_client.run_code(
            "\n".join(
                [
                    f"import {module}"
                    for module in BASE_BUILTIN_MODULES + self.additional_imports
                ]
            )
        )

    def send_variables(self, variables: dict):
        if variables:
            raise ValueError(
                "Sending variables is not currently supported in InspectAiSandboxExecutor."
            )

    def send_tools(self, tools: dict):
        # Smolagents always includes the final_answer tool, but we provide our own so that's okay
        if len(set(tools.keys()) - {"final_answer"}) != 0:
            raise ValueError(
                "InspectAiSandboxExecutor does not support sending custom SmolAgents tools.  Use `SandboxToolManager` to provide Inspect tools to the agent."
            )

    async def acall(
        self, code_action: str, additional_args: Optional[Dict] = None
    ) -> Tuple[Any, Any, bool]:
        """
        Execute code in the sandbox.

        Args:
            code_action (str): The code to execute
            additional_args (Dict, optional): Additional arguments to pass to the code

        Returns:
            Tuple[Any, Any]: The result and logs from the execution
        """
        try:
            if len(additional_args or {}) > 0:
                raise NotImplementedError

            # Warn if attempting to execute code after final answer has been submitted
            if self.final_answer:
                logger.warning(
                    "Executing code after final_answer has already been called. This may lead to unexpected behavior."
                )

            cell_output = await self.jupyter_client.run_code(code_action)

            result = None
            if await self.inspect_tool_manager.has_final_answer():
                result = await self.inspect_tool_manager.get_final_answer()
                # explicitly track self.final_answer, in case result is None
                self.final_answer = True
            return result, cell_output, self.final_answer
        except Exception as e:
            logger.exception(f"Error executing code in sandbox:")
            raise e

    def __call__(
        self, code_action: str, additional_args: Optional[Dict] = None
    ) -> Tuple[Any, Any, bool]:
        coro = self.acall(code_action, additional_args)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()
