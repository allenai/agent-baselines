"""Bridge to autogen's MagenticOne implementation using Inspect's bridge().

This solver wraps autogen's MagenticOneGroupChat to run it within Inspect's
framework, automatically capturing all LLM calls via bridge(). The key approach:

1. Configure autogen's OpenAIChatCompletionClient with model="inspect" and
   explicit model_info (to bypass autogen's model validation)
2. Use full_state_bridge() to patch OpenAI calls and route them through Inspect
3. Convert between Inspect and autogen formats

This allows direct comparison with the native magentic_outer_loop implementation.
"""

from logging import getLogger

from astabench.util.state import full_state_bridge
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import MagenticOneGroupChat
from autogen_core import CancellationToken
from autogen_core.models import ModelFamily
from autogen_core.tools import FunctionTool
from autogen_ext.models.openai import OpenAIChatCompletionClient
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, ToolDef

logger = getLogger(__name__)


def _wrap_inspect_tool_as_autogen(inspect_tool: Tool) -> FunctionTool:
    """Wrap an Inspect tool as an autogen FunctionTool.

    This creates a callable autogen tool that executes the Inspect tool
    and returns its result in autogen format.

    Note: This includes type mapping logic similar to
    SandboxToolManager._construct_tool_py_signature(). In the future,
    this could be extracted to a shared utility in astabench.
    """
    from typing import Annotated, Union

    tool_def = ToolDef(inspect_tool)

    # Map JSON schema types to Python types (same as SandboxToolManager)
    TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }

    # Get parameter information from the tool schema
    param_names = []
    param_annotations = {}

    if tool_def.parameters and tool_def.parameters.properties:
        for param_name, param_schema in tool_def.parameters.properties.items():
            param_names.append(param_name)
            param_desc = param_schema.description or ""

            # Determine the Python type for this parameter
            param_type: type

            if param_schema.anyOf:
                # Handle union types (e.g., number|integer)
                types_in_union = []
                for schema in param_schema.anyOf:
                    if schema.type and schema.type in TYPE_MAP:
                        types_in_union.append(TYPE_MAP[schema.type])

                if len(types_in_union) == 1:
                    param_type = types_in_union[0]
                elif len(types_in_union) > 1:
                    # Create a Union type for multiple types
                    # For numeric types (int|float), prefer float as most general
                    if set(types_in_union) <= {int, float}:
                        param_type = float
                    else:
                        # Use Union for truly different types
                        param_type = Union[tuple(types_in_union)]  # type: ignore
                else:
                    # Fallback if no valid types found
                    param_type = str
            elif param_schema.type and param_schema.type in TYPE_MAP:
                param_type = TYPE_MAP[param_schema.type]
            else:
                # Fallback for unknown types
                param_type = str

            param_annotations[param_name] = Annotated[param_type, param_desc]

    # Dynamically create the wrapper function with proper signature
    # We use exec to create a function with the exact parameters needed
    # The wrapper constructs a ToolCall and uses execute_tools() to ensure
    # proper ToolEvent logging in the Inspect transcript
    params_str = ", ".join(param_names)
    func_code = f"""
async def tool_wrapper({params_str}) -> str:
    '''Execute the Inspect tool via execute_tools() for proper event logging.'''
    from inspect_ai.tool import ToolCall
    from inspect_ai.model import ChatMessageAssistant
    from inspect_ai.model._call_tools import execute_tools
    import uuid

    # Build the arguments dict
    kwargs = {{{", ".join(f'"{p}": {p}' for p in param_names)}}}

    # Generate a unique ID for this tool call
    call_id = str(uuid.uuid4())

    # Construct a ToolCall object
    tool_call = ToolCall(
        id=call_id,
        function=tool_def.name,
        arguments=kwargs,
    )

    # Create a ChatMessageAssistant with this tool call
    message = ChatMessageAssistant(
        content="",  # Empty content, just tool call
        tool_calls=[tool_call],
    )

    try:
        # Use execute_tools() which handles ToolEvent logging
        result = await execute_tools([message], [inspect_tool])

        # Extract the result from the returned ChatMessageTool
        if result.messages and len(result.messages) > 0:
            tool_message = result.messages[0]
            if hasattr(tool_message, 'content'):
                content = tool_message.content
                if isinstance(content, str):
                    return content
                else:
                    return str(content)
            else:
                return str(tool_message)
        else:
            return "No result from tool execution"

    except Exception as e:
        logger.error(f"Error executing tool {{tool_def.name}}: {{e}}", exc_info=True)
        return f"Error: {{str(e)}}"
"""

    # Create the function in a namespace that has access to what we need
    namespace = {
        "inspect_tool": inspect_tool,
        "logger": logger,
        "tool_def": tool_def,
    }
    exec(func_code, namespace)
    tool_wrapper = namespace["tool_wrapper"]

    # Set function name and annotations
    tool_wrapper.__name__ = tool_def.name
    param_annotations["return"] = str
    tool_wrapper.__annotations__ = param_annotations

    # Create the autogen FunctionTool
    return FunctionTool(
        tool_wrapper,
        description=tool_def.description or f"Tool: {tool_def.name}",
        name=tool_def.name,
    )


@solver
def magentic_autogen_bridge(
    *,
    max_turns: int = 20,
    max_stalls: int = 3,
    model_override: str | None = None,
) -> Solver:
    """Bridge to autogen's MagenticOne using Inspect's bridge().

    This solver runs autogen's MagenticOneGroupChat with a single AssistantAgent,
    automatically capturing all LLM calls through Inspect's bridge() mechanism.

    Key implementation details:
    - Uses model="inspect" with explicit model_info to work with bridge()
    - Wraps the solver with full_state_bridge() to patch OpenAI calls
    - Single assistant agent (not full multi-agent team)
    - Tools are described to the agent but not yet executed through autogen

    Args:
        max_turns: Maximum number of turns before terminating. This is the total
            number of agent messages across all outer loop iterations.
        max_stalls: Maximum number of stalls before re-planning. When the
            orchestrator detects the agent is stuck, it triggers outer loop
            re-planning. Defaults to 3.
        model_override: Optional model name override. If not provided, uses
            the default model from Inspect's configuration.

    Returns:
        Solver that runs autogen's MagenticOne implementation.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        """Run autogen's MagenticOne within Inspect's framework."""

        # Get the actual model name to use
        # When using bridge(), the model name should be "inspect" or "inspect/<model>"
        # to trigger the bridge's interception
        if model_override:
            # Allow explicit model like "inspect/gpt-4o"
            model_name = (
                model_override
                if model_override.startswith("inspect")
                else f"inspect/{model_override}"
            )
        else:
            # Use plain "inspect" which will use Inspect's default model
            model_name = "inspect"

        logger.info(f"Creating autogen MagenticOne with model: {model_name}")

        # Create OpenAI client with explicit model_info to bypass autogen's validation
        # The model_info tells autogen what capabilities the model has
        # NOTE: structured_output is disabled because bridge() doesn't support
        # OpenAI's response_format/json_schema feature
        model_client = OpenAIChatCompletionClient(
            model=model_name,
            api_key="dummy",  # Not used since bridge() intercepts calls
            model_info={
                "vision": False,
                "function_calling": True,
                "json_output": True,
                # Use UNKNOWN family so autogen doesn't make assumptions about the
                # underlying model. Since bridge() intercepts all calls and routes
                # through Inspect's model system, the actual model type (GPT-4, Claude,
                # Gemini, etc.) is determined by Inspect's configuration, not autogen.
                # Using UNKNOWN prevents autogen from applying model-specific message
                # transformations that would be inappropriate for the actual model.
                "family": ModelFamily.UNKNOWN,
                "structured_output": False,  # Disabled - not compatible with bridge()
                "multiple_system_messages": True,
            },
        )

        # Convert Inspect tools to autogen FunctionTools
        autogen_tools = [_wrap_inspect_tool_as_autogen(tool) for tool in state.tools]

        logger.info(f"Wrapped {len(autogen_tools)} Inspect tools for autogen")

        system_message = (
            "You are a helpful assistant that can solve problems using available tools."
        )

        # Create a single assistant agent with the wrapped tools
        # In the future, could add more specialized agents (FileSurfer, WebSurfer, etc.)
        assistant = AssistantAgent(
            name="Assistant",
            model_client=model_client,
            description="A helpful assistant that can solve problems",
            system_message=system_message,
            tools=autogen_tools,  # Provide the wrapped Inspect tools
        )

        # Create MagenticOne team with single agent
        team = MagenticOneGroupChat(
            participants=[assistant],
            model_client=model_client,
            max_turns=max_turns,
            max_stalls=max_stalls,
        )

        # Run the task
        logger.info(f"Running autogen MagenticOne on task: {state.input_text[:100]}...")
        try:
            result = await team.run(
                task=state.input_text,
                cancellation_token=CancellationToken(),
            )

            # Extract the final answer from the result
            # The last message should contain the final answer
            if result.messages:
                last_message = result.messages[-1]
                if hasattr(last_message, "content"):
                    state.output.completion = last_message.content
                else:
                    state.output.completion = str(last_message)
            else:
                state.output.completion = "No response generated"

            state.completed = True
            logger.info(
                f"Autogen MagenticOne completed. Stop reason: {result.stop_reason}"
            )

        except Exception as e:
            logger.error(f"Error running autogen MagenticOne: {e}", exc_info=True)
            state.output.completion = f"Error: {str(e)}"
            state.completed = True

        return state

    # Wrap with full_state_bridge to enable OpenAI call interception
    return full_state_bridge(solve)
