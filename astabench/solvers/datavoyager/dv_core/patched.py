import asyncio
import base64
import logging
import sys
import time
import uuid
from inspect import signature
from io import BytesIO
from logging import Logger
from typing import Any, AsyncGenerator, List, Optional, Sequence, Union

import matplotlib
import matplotlib.pyplot as plt
import nest_asyncio
from autogen_agentchat import EVENT_LOGGER_NAME
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import Response
from autogen_agentchat.messages import (
    BaseAgentEvent,
    BaseChatMessage,
    HandoffMessage,
    ModelClientStreamingChunkEvent,
    MultiModalMessage,
    StopMessage,
    TextMessage,
    ThoughtEvent,
    ToolCallExecutionEvent,
    ToolCallRequestEvent,
    ToolCallSummaryMessage,
)
from autogen_core import CancellationToken, FunctionCall, Image
from autogen_core.model_context import ChatCompletionContext
from autogen_core.models import (
    AssistantMessage,
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    SystemMessage,
    UserMessage,
)
from autogen_core.tools import BaseTool, Workbench
from autogen_ext.models.openai import OpenAIChatCompletionClient
from pydantic import BaseModel, create_model

from .models import ExecutePython, InstallPackages

event_logger = logging.getLogger(EVENT_LOGGER_NAME)

# TODO: add a good prompt
IMAGE_ANALYSER_PROMPT = """
I am an image analyser. I can help you interpret the plots you have generated.
"""

USER_PROXY_IMAGE_ANALYSER_PROMPT = """
Please analyze the given plot image and provide the following:

1. Plot Type: Identify the type of plot (e.g., heatmap, bar plot, scatter plot) and its purpose.
2. Axes:
    * Titles and labels, including units.
    * Value ranges for both axes.
3. Data Trends:
    * For scatter plots: note trends, clusters, or outliers.
    * For bar plots: highlight the tallest and shortest bars and patterns.
    * For heatmaps: identify areas of high and low values.
    etc...
4. Statistical Insights: Mention any relevant statistics if applicable.
5. Annotations and Legends: Describe key annotations or legends.
6. Overall Impression: Summarize insights and implications for further analysis.
7. Interpretation: Provide novel insights or perspectives based on the data presented. What conclusions can be drawn?
8. User Objective: If applicable, address the user's question or objective related to the image.
9. Limitations: Discuss any limitations or biases in the data that could affect conclusions.
"""


class AssistantAgentWithStructuredToolCalling(AssistantAgent):
    """
    Meant to be used by programmer to use Structured Outputs for function calling
    to make it more robust for o3-mini like models
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reflect_on_tool_use = False  # override it because that leads to OAI error

    async def on_messages_stream(
        self,
        messages: Sequence[BaseChatMessage],
        cancellation_token: CancellationToken,
    ) -> AsyncGenerator[Union[BaseAgentEvent, BaseChatMessage, Response], None]:
        """Process messages and stream the response.

        Args:
            messages: Sequence of messages to process
            cancellation_token: Token for cancelling operation

        Yields:
            Events, messages and final response during processing
        """

        # Gather all relevant state here
        agent_name = self.name
        model_context = self._model_context
        memory = self._memory
        system_messages = self._system_messages
        workbench = self._workbench
        handoff_tools = self._handoff_tools
        handoffs = self._handoffs
        model_client = self._model_client
        model_client_stream = self._model_client_stream
        reflect_on_tool_use = self._reflect_on_tool_use
        max_tool_iterations = self._max_tool_iterations
        tool_call_summary_format = self._tool_call_summary_format
        tool_call_summary_formatter = self._tool_call_summary_formatter
        output_content_type = self._output_content_type

        # STEP 1: Add new user/handoff messages to the model context
        await self._add_messages_to_context(
            model_context=model_context,
            messages=messages,
        )

        # STEP 2: Update model context with any relevant memory
        inner_messages: List[BaseAgentEvent | BaseChatMessage] = []
        for event_msg in await self._update_model_context_with_memory(
            memory=memory,
            model_context=model_context,
            agent_name=agent_name,
        ):
            inner_messages.append(event_msg)
            yield event_msg

        # STEP 3: Generate a message ID for correlation between streaming chunks and final message
        message_id = str(uuid.uuid4())

        # STEP 4: Run the first inference
        model_result = None
        async for inference_output in self._call_llm(
            model_client=model_client,
            model_client_stream=model_client_stream,
            system_messages=system_messages,
            model_context=model_context,
            workbench=workbench,
            handoff_tools=handoff_tools,
            agent_name=agent_name,
            cancellation_token=cancellation_token,
            output_content_type=output_content_type,
            message_id=message_id,
        ):
            if isinstance(inference_output, CreateResult):
                model_result = inference_output
            else:
                # Streaming chunk event
                yield inference_output

        # NOTE: Intercept the results and convert it to FunctionCall
        try:
            # we need to extract the code and make it a function call
            structured_tool_response = output_content_type.model_validate_json(
                model_result.content
            )
            if isinstance(structured_tool_response.tool, ExecutePython):
                tool_name = "exec_python"
            elif isinstance(structured_tool_response.tool, InstallPackages):
                tool_name = "install_packages"
            else:
                raise ValueError(f"Unknown tool type: {type(structured_tool_response)}")

            model_result.content = [
                FunctionCall(
                    id=f"tool_call_{int(time.time())}",
                    name=tool_name,
                    arguments=structured_tool_response.tool.model_dump_json(),
                )
            ]
        except Exception as e:
            print("Error while parsing structured tool call: ", e)

        assert model_result is not None, "No model result was produced."

        # --- NEW: If the model produced a hidden "thought," yield it as an event ---
        if model_result.thought:
            thought_event = ThoughtEvent(
                content=model_result.thought, source=agent_name
            )
            yield thought_event
            inner_messages.append(thought_event)

        # Add the assistant message to the model context (including thought if present)
        await model_context.add_message(
            AssistantMessage(
                content=model_result.content,
                source=agent_name,
                thought=getattr(model_result, "thought", None),
            )
        )

        # STEP 5: Process the model output
        async for output_event in self._process_model_result(
            model_result=model_result,
            inner_messages=inner_messages,
            cancellation_token=cancellation_token,
            agent_name=agent_name,
            system_messages=system_messages,
            model_context=model_context,
            workbench=workbench,
            handoff_tools=handoff_tools,
            handoffs=handoffs,
            model_client=model_client,
            model_client_stream=model_client_stream,
            reflect_on_tool_use=reflect_on_tool_use,
            max_tool_iterations=max_tool_iterations,
            tool_call_summary_format=tool_call_summary_format,
            tool_call_summary_formatter=tool_call_summary_formatter,
            output_content_type=output_content_type,
            message_id=message_id,
            format_string=self._output_content_type_format,
        ):
            yield output_event

    @classmethod
    async def _call_llm(
        cls,
        model_client: ChatCompletionClient,
        model_client_stream: bool,
        system_messages: List[SystemMessage],
        model_context: ChatCompletionContext,
        workbench: Sequence[Workbench],
        handoff_tools: List[BaseTool[Any, Any]],
        agent_name: str,
        cancellation_token: CancellationToken,
        output_content_type: type[BaseModel] | None,
        message_id: str,
    ) -> AsyncGenerator[Union[CreateResult, ModelClientStreamingChunkEvent], None]:
        """Call the language model with given context and configuration.

        Args:
            model_client: Client for model inference
            model_client_stream: Whether to stream responses
            system_messages: System messages to include
            model_context: Context containing message history
            workbench: Available workbenches
            handoff_tools: Tools for handling handoffs
            agent_name: Name of the agent
            cancellation_token: Token for cancelling operation
            output_content_type: Optional type for structured output

        Returns:
            Generator yielding model results or streaming chunks
        """
        all_messages = await model_context.get_messages()
        llm_messages = cls._get_compatible_context(
            model_client=model_client, messages=system_messages + all_messages
        )

        tools = (
            []
            if output_content_type
            else [tool for wb in workbench for tool in await wb.list_tools()]
            + handoff_tools
        )

        if model_client_stream:
            model_result: Optional[CreateResult] = None

            async for chunk in model_client.create_stream(
                llm_messages,
                tools=tools,
                json_output=output_content_type,
                cancellation_token=cancellation_token,
            ):
                if isinstance(chunk, CreateResult):
                    model_result = chunk
                elif isinstance(chunk, str):
                    yield ModelClientStreamingChunkEvent(
                        content=chunk, source=agent_name, full_message_id=message_id
                    )
                else:
                    raise RuntimeError(f"Invalid chunk type: {type(chunk)}")
            if model_result is None:
                raise RuntimeError("No final model result in streaming mode.")
            yield model_result
        else:
            model_result = await model_client.create(
                llm_messages,
                tools=tools,
                cancellation_token=cancellation_token,
                json_output=output_content_type,
            )
            yield model_result


class MagenticOnePromptPatcher:
    def __init__(self, prompts: dict):
        self.prompts = prompts
        self.patched_methods = {
            "ORCHESTRATOR_FINAL_ANSWER_PROMPT": self._final_answer_prompt,
            "ORCHESTRATOR_PROGRESS_LEDGER_PROMPT": self._get_progress_ledger_prompt,
            "ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT": self._get_task_ledger_facts_prompt,
            "ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT": self._get_task_ledger_facts_update_prompt,
            "ORCHESTRATOR_TASK_LEDGER_FULL_PROMPT": self._get_task_ledger_full_prompt,
            "ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT": self._get_task_ledger_plan_prompt,
            "ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT": self._get_task_ledger_plan_update_prompt,
        }

    def _get_task_ledger_facts_prompt(self, task: str) -> str:
        return self.prompts["ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT"].format(task=task)

    def _get_task_ledger_plan_prompt(self, team: str) -> str:
        return self.prompts["ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT"].format(team=team)

    def _get_task_ledger_full_prompt(
        self, task: str, team: str, facts: str, plan: str
    ) -> str:
        return self.prompts["ORCHESTRATOR_TASK_LEDGER_FULL_PROMPT"].format(
            task=task, team=team, facts=facts, plan=plan
        )

    def _get_progress_ledger_prompt(
        self, task: str, team: str, names: List[str]
    ) -> str:
        return self.prompts["ORCHESTRATOR_PROGRESS_LEDGER_PROMPT"].format(
            task=task, team=team, names=", ".join(names)
        )

    def _get_task_ledger_facts_update_prompt(self, task: str, facts: str) -> str:
        return self.prompts["ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT"].format(
            task=task, facts=facts
        )

    def _get_task_ledger_plan_update_prompt(self, team: str) -> str:
        return self.prompts["ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT"].format(
            team=team
        )

    def _final_answer_prompt(self, task: str) -> str:
        if (
            self._final_answer_prompt
            == self.prompts["ORCHESTRATOR_FINAL_ANSWER_PROMPT"]
        ):
            return self.prompts["ORCHESTRATOR_FINAL_ANSWER_PROMPT"].format(task=task)
        else:
            return self._final_answer_prompt

    def get_patched_method(self, key: str) -> callable:
        return self.patched_methods[key]


class PlotPatcher:
    def __init__(
        self,
        model_client: OpenAIChatCompletionClient,
        console_logger: Logger = None,
        image_analyser_prompt: str = IMAGE_ANALYSER_PROMPT,
        user_proxy_image_analyser_prompt: str = USER_PROXY_IMAGE_ANALYSER_PROMPT,
    ):
        self.console_logger = console_logger
        self.image_analyser_prompt = image_analyser_prompt
        self.user_proxy_image_analyser_prompt = user_proxy_image_analyser_prompt
        self.image_analyser = AssistantAgent(
            name="image_analyser",
            model_client=model_client,
            system_message=self.image_analyser_prompt,
        )

    def is_jupyter_notebook_env(self):
        # Check if IPython is available and
        # running in a notebook environment
        if "ipykernel" in sys.modules:
            return True
        return False

    def get_patched_plt_show(self):
        if self.is_jupyter_notebook_env():
            return self.notebook_plt_show()
        else:
            return self.console_plt_show()

    def console_plt_show(self):
        matplotlib.use("Agg")

        def sync_custom_plt_show():
            # check if any event loop is running
            cancellation_token = CancellationToken()

            response = ""
            # Iterate through figures
            for fig_num in plt.get_fignums():
                fig = plt.figure(fig_num)  # Get the current figure

                with BytesIO() as buf:
                    # Save figure to a buffer
                    fig.savefig(buf, dpi=200)
                    buf.seek(0)

                    # Convert to base64
                    img_data = buf.getvalue()
                    base64_str = base64.b64encode(img_data).decode("utf-8")

                    # Log the base64 string
                    if self.console_logger:
                        self.console_logger.log_json(
                            {"type": "image", "data": base64_str}
                        )

                    # Prepare the message
                    message = MultiModalMessage(
                        content=[
                            USER_PROXY_IMAGE_ANALYSER_PROMPT,
                            Image.from_base64(base64_str),
                        ],
                        source="user",
                    )

                    response = asyncio.run(
                        self.image_analyser.on_messages([message], cancellation_token)
                    )

                # Close the figure to release memory
                plt.close(fig)

            return response  # Ensure this is the final awaited result

        return sync_custom_plt_show

    def notebook_plt_show(self):
        nest_asyncio.apply()  # Allow nested event loops
        original_plt_show = plt.show  # Store the original plt.show function

        def sync_custom_plt_show():
            cancellation_token = CancellationToken()

            response = ""
            for fig_num in plt.get_fignums():
                fig = plt.figure(fig_num)

                with BytesIO() as buf:
                    fig.savefig(buf, dpi=200)
                    buf.seek(0)

                    img_data = buf.getvalue()
                    base64_str = base64.b64encode(img_data).decode("utf-8")

                    # Log the base64 string
                    if self.console_logger:
                        self.console_logger.log_json(
                            {"type": "image", "data": base64_str}
                        )

                    message = MultiModalMessage(
                        content=[
                            USER_PROXY_IMAGE_ANALYSER_PROMPT,
                            Image.from_base64(base64_str),
                        ],
                        source="user",
                    )

                    # Await the coroutine returned by `on_messages`
                    response += f"Interpretation for Plot {fig_num}:\n"
                    plot_interpretation = asyncio.run(
                        self.image_analyser.on_messages([message], cancellation_token)
                    )
                    response += plot_interpretation.chat_message.content + "\n"

                original_plt_show()  # Will close the figure after plotting

            # TODO: Find a way to inject the response
            # in groupchat
            return response

        return sync_custom_plt_show


class MagenticOneOrchestratorPatch:
    # need to patch the method to remove an assertion
    # that is causing the orchestrator to crash
    def _thread_to_context(self) -> List[LLMMessage]:
        """Convert the message thread to a context for the model."""
        context: List[LLMMessage] = []
        for m in self._message_thread:
            if isinstance(m, ToolCallRequestEvent | ToolCallExecutionEvent):
                # Ignore tool call messages.
                continue
            elif isinstance(m, StopMessage | HandoffMessage):
                context.append(UserMessage(content=m.content, source=m.source))
            elif m.source == self._name:
                assert isinstance(m, TextMessage | ToolCallSummaryMessage)
                context.append(AssistantMessage(content=m.content, source=m.source))
            else:
                context.append(UserMessage(content=m.content, source=m.source))
        return context
