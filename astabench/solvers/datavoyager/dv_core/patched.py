import asyncio
import base64
import sys
from io import BytesIO
from logging import Logger
from typing import List

import matplotlib
import matplotlib.pyplot as plt
import nest_asyncio
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import (
    HandoffMessage,
    MultiModalMessage,
    StopMessage,
    TextMessage,
    ToolCallExecutionEvent,
    ToolCallRequestEvent,
    ToolCallSummaryMessage,
)
from autogen_core import CancellationToken, Image
from autogen_core.models import AssistantMessage, LLMMessage, UserMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

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
