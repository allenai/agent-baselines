"""Magentic-One style agent with outer loop orchestration.

This implements a simplified version of the Magentic-One architecture with an outer
loop (orchestrator) monitoring progress of an inner loop (sub-agent execution).
Unlike the full Magentic-One, this uses a single assistant agent rather than a
dynamic team assembly.

The outer loop maintains a task ledger (facts and plan) and monitors progress,
while the inner loop executes tool calls. When the agent stalls, the outer loop
re-plans and restarts the inner loop with an updated ledger.
"""

from logging import getLogger
from typing import Literal

from astabench.evals.utils import extract_json_from_response
from astabench.tools import ToolsetConfig
from astabench.tools.stateful_python import get_sandbox_jupyter
from autogen_agentchat.teams._group_chat._magentic_one._prompts import (
    ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT,
    ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT,
)
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    Model,
    execute_tools,
    get_model,
)
from inspect_ai.solver import Generate, Solver, TaskState, chain, solver
from inspect_ai.tool import Tool, ToolDef, ToolError
from inspect_ai.util import LimitExceededError, StoreModel
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_baselines.solvers.react.basic_agent import (
    DEFAULT_SUBMIT_DESCRIPTION,
    DEFAULT_SUBMIT_NAME,
    TEXT_TOOL_CALLS_PROMPT,
    native_add_tool_responses,
    native_extract_tool_calls,
    resolve_agent_initializer_args,
    text_add_tool_responses,
    text_extract_tool_calls,
    tools_to_prompt_text,
)

logger = getLogger(__name__)

SUBAGENT_SYSTEM_MESSAGE = """You are a helpful assistant.  You have several functions available to help with finding the answer. Each message may may perform one function call. You will see the result of the function right after sending the message. If you need to perform multiple actions, you can always send more messages with subsequent function calls. Do some reasoning before your actions, describing what function calls you are going to use and how they fit into your plan."""

ORCHESTRATOR_FINAL_ANSWER_PROMPT = """
We are working on the following task:
{task}

We have completed the task.

The above messages contain the conversation that took place to complete the task.

Based on the information gathered, provide the final answer to the original request.
"""

ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT = """Please briefly explain what went wrong on this last run (the root cause of the failure), and then come up with a new plan that takes steps and/or includes hints to overcome prior challenges and especially avoids repeating the same mistakes. As before, the new plan should be concise, be expressed in bullet-point form."""

ORCHESTRATOR_PROGRESS_LEDGER_PROMPT = """
Recall we are working on the following request:

{task}

And we are working with team who has access to the following tools:

{tools}

To make progress on the request, please answer the following questions, including necessary reasoning:

    - Is the request fully satisfied? (True if complete, or False if the original request has yet to be SUCCESSFULLY and FULLY addressed)
    - Are we in a loop where we are repeating the same requests and / or getting the same responses as before? Loops can span multiple turns, and can include repeated actions like scrolling up or down more than a handful of times.
    - Are we making forward progress? (True if just starting, or recent messages are adding value. False if recent messages show evidence of being stuck in a loop or if there is evidence of significant barriers to success such as the inability to read from a required file)
    - Who should speak next? (select from: {names}; if there's only one team member, select them)
    - What instruction or question would you give this team member? (Phrase as if speaking directly to them, and include any specific information they may need)

Please output an answer in pure JSON format according to the following schema. The JSON object must be parsable as-is. DO NOT OUTPUT ANYTHING OTHER THAN JSON, AND DO NOT DEVIATE FROM THIS SCHEMA:

    {{
       "is_request_satisfied": {{
            "reason": string,
            "answer": boolean
        }},
        "is_in_loop": {{
            "reason": string,
            "answer": boolean
        }},
        "is_progress_being_made": {{
            "reason": string,
            "answer": boolean
        }},
        "next_speaker": {{
            "reason": string,
            "answer": string (select from: {names})
        }},
        "instruction_or_question": {{
            "reason": string,
            "answer": string
        }}
    }}
"""

ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT = """Fantastic. To address this request we have hired an assistant who has access to various tools needed to solve the task.  Tools:

{tools}

Based on the available tools and the known and unknown facts, please devise a short bullet-point plan for addressing the original request.  Remember, there is no requirement to involve all tools -- a tool's particular capability may not be needed for this task."""


ORCHESTRATOR_TASK_LEDGER_FULL_PROMPT = """
We are working to address the following user request:

{task}

To answer this request our assistant has access to the following tools:

{tools}

Here is an initial fact sheet to consider:

{facts}

Here is the plan to follow as best as possible:

{plan}
"""


class MagenticSubAgentState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    system_message: str
    tools: list[Tool]
    messages: list[ChatMessageUser | ChatMessageAssistant] = Field(default_factory=list)
    max_tool_call_steps: int = 10
    current_tool_call_step: int = 0
    tool_call_format: Literal["text", "native"] = "native"
    completed: bool = False

    def reset_messages(self):
        self.messages = [ChatMessageSystem(content=self.system_message)]


class MagenticState(StoreModel):
    # required at init
    task: str = ""
    facts: str = ""
    plan: str = ""
    tools: str = ""

    orchestrator_messages: list[ChatMessageUser | ChatMessageAssistant] = Field(
        default_factory=list
    )
    current_inner_loop_steps: int = 0
    max_inner_loop_steps: int = 10
    current_total_tool_call_steps: int = 0
    max_total_tool_call_steps: int = 100
    max_stalls: int = 3
    stall_counter: int = 0
    sub_agents: list[MagenticSubAgentState] = Field(default_factory=list)
    completed: bool = False


async def _create_initial_ledger(state: TaskState, model: Model) -> None:
    """Create an initial task ledger based on the task description."""
    prompt = ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT.format(task=state.input_text)
    messages = [ChatMessageUser(content=prompt)]
    output = await model.generate(
        input=messages,
        tools=[],
    )
    facts = output.choices[0].message.content
    messages.append(output.choices[0].message)

    tools_summary = tools_to_prompt_text(state.tools)
    prompt = ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT.format(
        tools=tools_summary,
    )
    messages.append(ChatMessageUser(content=prompt))
    output = await model.generate(
        input=messages,
        tools=[],
    )
    plan = output.choices[0].message.content
    messages.append(output.choices[0].message)

    mstate = state.store_as(MagenticState)

    mstate.task = state.input_text
    mstate.facts = facts
    mstate.plan = plan
    mstate.tools = tools_summary
    mstate.orchestrator_messages = messages


async def _outer_loop_preamble(
    state: TaskState, model: Model, mstate: MagenticState
) -> TaskState:

    # Reset the chat history
    for sa in mstate.sub_agents:
        sa.reset_messages()
    mstate.orchestrator_messages.clear()

    # Note: The autogen implementation
    # (https://github.com/microsoft/autogen/blob/13e144e5476a76ca0d76bf4f07a6401d133a03ed/python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_magentic_one/_magentic_one_orchestrator.py#L402)
    # doesn't seem to reset the stall counter on an outer loop reset.  But that
    # causes it to keep trying to do error recovery in an infinite loop when it
    # gets stuck, so we reset the counter here.
    mstate.stall_counter = 0

    ledger_prompt = ORCHESTRATOR_TASK_LEDGER_FULL_PROMPT.format(
        task=state.input_text,
        tools=mstate.tools,
        facts=mstate.facts,
        plan=mstate.plan,
    )
    logger.info(
        "Outer loop for sample %s, tc %d/%d: %s",
        state.sample_id,
        mstate.current_total_tool_call_steps,
        mstate.max_total_tool_call_steps,
        ledger_prompt,
    )

    mstate.orchestrator_messages.append(ChatMessageUser(content=ledger_prompt))

    # This is a broadcast, so we also need to add the ledger to each sub-agent
    for sa in mstate.sub_agents:
        sa.messages.append(ChatMessageUser(content=ledger_prompt))


async def _run_sub_agent_loop(
    state: TaskState,
    model: Model,
    sub_agent_state: MagenticSubAgentState,
    tool_call_format,
    mstate: MagenticState,
) -> ChatMessageAssistant:
    # Set up tool calling functions based on format
    if sub_agent_state.tool_call_format == "text":
        extract_tool_calls_fn = text_extract_tool_calls
        add_tool_responses_fn = text_add_tool_responses
        tools_for_generate = []
    elif sub_agent_state.tool_call_format == "native":
        extract_tool_calls_fn = native_extract_tool_calls
        add_tool_responses_fn = native_add_tool_responses
        tools_for_generate = sub_agent_state.tools
    else:
        raise ValueError(f"Unknown tool_call_format: {tool_call_format}")

    # main agent loop
    cur_steps = 0
    sub_agent_state.completed = False
    max_tool_call_steps = min(
        sub_agent_state.max_tool_call_steps,
        mstate.max_total_tool_call_steps - mstate.current_total_tool_call_steps,
    )
    while not sub_agent_state.completed:
        cur_steps += 1
        mstate.current_total_tool_call_steps += 1
        if cur_steps > max_tool_call_steps:
            raise LimitExceededError(
                type="custom",
                value=cur_steps,
                limit=sub_agent_state.max_tool_call_steps,
                message=f"Reached max steps ({max_tool_call_steps}).  Aborting.",
            )
        if cur_steps == max_tool_call_steps:
            sub_agent_state.messages.append(
                ChatMessageUser(
                    content="You have reached the maximum number of reasoning steps. Submit your final answer immediately; you will not get another chance."
                )
            )
        # generate output and append assistant message
        output = await model.generate(
            input=sub_agent_state.messages,
            tools=tools_for_generate,
        )
        sub_agent_state.messages.append(output.message)

        # check for context window overflow
        if output.stop_reason == "model_length":
            logger.warning("Model context window exceeded, terminating agent")
            sub_agent_state.messages[
                -1
            ].content += "\n\n[Model context window exceeded, terminating agent]"
            break

        # Extract tool calls
        try:
            tool_calls = extract_tool_calls_fn(output.message)
        except ToolError as e:
            sub_agent_state.messages.append(
                ChatMessageUser(
                    content=f"The tool calls from your last message could not be processed due to an error: {e}."
                )
            )
            continue

        # resolve tools calls (if any)
        if tool_calls:
            tool_result = await execute_tools(
                # execute_tools wants a message, so we make one up
                [ChatMessageAssistant(content="", tool_calls=tool_calls)],
                sub_agent_state.tools,
            )

            sub_agent_state.messages = add_tool_responses_fn(
                tool_result.messages, sub_agent_state.messages
            )

        # no tool calls, sub-agent is done
        else:
            sub_agent_state.completed = True
            break

    return sub_agent_state.messages[-1]


class ProgressLedgerBoolItem(BaseModel):
    reason: str
    answer: bool


class ProgressLedgerStringItem(BaseModel):
    reason: str
    answer: str


class ProgressLedger(BaseModel):
    is_request_satisfied: ProgressLedgerBoolItem
    is_in_loop: ProgressLedgerBoolItem
    is_progress_being_made: ProgressLedgerBoolItem
    next_speaker: ProgressLedgerStringItem
    instruction_or_question: ProgressLedgerStringItem


async def _update_inner_loop_progress(
    state: TaskState, model: Model, mstate: MagenticState
) -> bool:
    """Check if the inner loop is making progress, and if not, mark as stuck.

    Returns True if the inner loop is stuck and should be restarted.
    """
    tmp_messages = mstate.orchestrator_messages.copy()
    tmp_messages.append(
        ChatMessageUser(
            content=ORCHESTRATOR_PROGRESS_LEDGER_PROMPT.format(
                task=mstate.task,
                tools=mstate.tools,
                names=", ".join([sa.name for sa in mstate.sub_agents]),
            )
        )
    )
    max_json_retries = 3
    for nth_retry in range(max_json_retries):
        if nth_retry > 0:
            tmp_messages.append(
                ChatMessageUser(
                    content="The response could not be parsed as JSON. Please try again, ensuring the response is valid JSON with the requested schema."
                )
            )
        output = await model.generate(
            input=tmp_messages,
            tools=[],
        )
        tmp_messages.append(output.choices[0].message)

        progress_ledger = extract_json_from_response(output.choices[0].message.content)
        if not progress_ledger:
            continue
        try:
            ledger = ProgressLedger.model_validate(progress_ledger)
            break
        except ValidationError:
            continue
    else:
        raise ValueError(
            "Could not extract valid JSON from model response for progress ledger."
        )

    if ledger.is_request_satisfied.answer:
        await _prepare_final_answer(state, model, mstate, ledger)
        return False

    logger.info(
        "Progress ledger (sample %s, tc %d/%d): %s",
        state.sample_id,
        mstate.current_total_tool_call_steps,
        mstate.max_total_tool_call_steps,
        ledger,
    )
    if ledger.is_in_loop.answer or not ledger.is_progress_being_made.answer:
        mstate.stall_counter += 1
    else:
        # the autogen_agentchat Magentic-ONE implementation decrements if
        # progress is being made; we follow that here, despite it being
        # different from what's described in the paper
        mstate.stall_counter = max(0, mstate.stall_counter - 1)

    if mstate.stall_counter >= mstate.max_stalls:
        # stuck, need to restart inner loop
        return True

    # Broadcast the instruction to all agents, including ourselves
    instruction_msg = ledger.instruction_or_question.answer
    for sa in mstate.sub_agents:
        sa.messages.append(ChatMessageUser(content=instruction_msg))
    mstate.orchestrator_messages.append(ChatMessageAssistant(content=instruction_msg))

    return False


async def _prepare_final_answer(
    state: TaskState, model: Model, mstate: MagenticState, ledger: ProgressLedger
) -> None:
    """Prepare the final answer based on the ledger and mark the state as completed."""
    final_prompt = ORCHESTRATOR_FINAL_ANSWER_PROMPT.format(
        task=mstate.task,
    )
    mstate.orchestrator_messages.append(ChatMessageUser(content=final_prompt))
    output = await model.generate(
        input=mstate.orchestrator_messages,
        tools=[],
    )
    mstate.orchestrator_messages.append(output.choices[0].message)
    state.output.completion = output.choices[0].message.content
    mstate.completed = True
    state.completed = True


async def _update_ledger_for_stuck_recovery(
    state: TaskState, model: Model, mstate: MagenticState
) -> None:
    """Update the ledger to reflect a stuck recovery."""
    facts_update_prompt = ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT.format(
        task=state.input_text,
        facts=mstate.facts,
    )
    mstate.orchestrator_messages.append(ChatMessageUser(content=facts_update_prompt))
    output = await model.generate(
        input=mstate.orchestrator_messages,
        tools=[],
    )
    mstate.orchestrator_messages.append(output.choices[0].message)
    mstate.facts = output.choices[0].message.content

    plan_update_prompt = ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT
    mstate.orchestrator_messages.append(ChatMessageUser(content=plan_update_prompt))
    output = await model.generate(
        input=mstate.orchestrator_messages,
        tools=[],
    )
    mstate.orchestrator_messages.append(output.choices[0].message)
    mstate.plan = output.choices[0].message.content


@solver
def init_python_mcp():
    """If python_session is provided, aenter the underlying sandboxjupyter as
    through we were doing `async with`; this should always be paired with
    close_python_mcp at the other end of the solver chain."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if any(ToolDef(t).name == "python_session" for t in state.tools):
            sbj = await get_sandbox_jupyter()
            if sbj._exit_stack:
                logger.warning(
                    "sandboxjupyter already has an active context; this may indicate a missing close_python_mcp in the solver chain.  Closing before re-entering."
                )
                await sbj.__aexit__(None, None, None)
            await sbj.__aenter__()
        return state

    return solve


@solver
def close_python_mcp():
    """If python_session is provided, aexit the underlying sandboxjupyter as
    through we were doing `async with`; this should always be paired with
    init_python_mcp at the start of the solver chain."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if any(ToolDef(t).name == "python_session" for t in state.tools):
            try:
                await (await get_sandbox_jupyter()).__aexit__(None, None, None)
            except RuntimeError:
                # We log and carry on; RuntimeError is often related to docker
                # issues if the container/server crashed before we tried to
                # kill it, but since it's a shutdown operation there's no
                # reason to kill the whole sample over it
                logger.exception("Error closing python_session:")
        return state

    return solve


@solver
def magentic_outer_loop(
    *,
    init: Solver | list[Solver] | None = None,
    tools: list[Tool] | None = None,
    max_steps: int = 10,
    max_stalls: int = 3,
    max_outer_loop_steps: int = 5,
    submit_name: str = DEFAULT_SUBMIT_NAME,
    submit_description: str = DEFAULT_SUBMIT_DESCRIPTION,
    tool_call_format: Literal["text", "native"] = "native",
    model_override: str | Model | None = None,
) -> Solver:
    """Magentic-One style agent with outer loop orchestration.

    Implements a two-loop architecture inspired by Magentic-One:
    - **Outer loop (Orchestrator)**: Maintains a task ledger (facts + plan), monitors
      progress, and handles re-planning when the agent stalls
    - **Inner loop (Sub-agent)**: Executes tool calls to make progress on the task

    Unlike the full Magentic-One, this uses a single assistant agent rather than
    dynamic multi-agent team assembly (primarily using the outer loop to detect
    lack of progress and recover from errors), and some prompts have been
    adjusted to reflect this.

    Note that the inner loop sub-agent can do multiple tool calls before
    returning, so outer loop interventions may be a bit less frequent than in
    the normal magnetic-one.

    Args:
       init: Agent initialisation (defaults to system_message with basic ReAct prompt)
       tools: Tools available for the agent.
       max_steps: Maximum number of total inner loop steps before terminating
          (total across all outer loop iterations).
       max_stalls: Maximum number of stalls allowed before re-planning. The stall
          counter increments when the agent is stuck or in a loop, and decrements
          when progress is made. When reaching max_stalls, the outer loop triggers
          re-planning.
       max_outer_loop_steps: Maximum number of outer loop steps before
          terminating (each outer loop step restarts the inner loop with
          a refreshed ledger; in short, this is how many times the agent can
          completely stall out before terminating).
       submit_name: Name for tool used to make submissions (defaults to 'submit')
       submit_description: Description of submit tool (defaults to
          'Submit an answer for evaluation')
       tool_call_format: Format for tool calls in user messages. If 'text',
          the llm will be instructed to output tool calls as plain text in its
          messages and will receive responses as plain text.  If 'native', the
          llm will use the built-in tool calling mechanism, e.g. attaching
          calls to the tool_calls field of it's messages and receiving
          responses as ToolMessages.
        model_override: Optional model override. If provided, will use this
            model instead of the default one (prefer `--model` instead of this,
            unless this agent is being used in a multi-agent system).

    Returns:
        Solver implementing the outer loop orchestration.
    """

    @solver
    def outer_loop_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await init_python_mcp()(state, generate)
            initial_model = get_model(model_override)
            await _create_initial_ledger(state, initial_model)

            mstate = state.store_as(MagenticState)
            mstate.max_stalls = max_stalls

            subagent_sys_msg = SUBAGENT_SYSTEM_MESSAGE
            if tool_call_format == "text":
                subagent_sys_msg += f"\n\n{TEXT_TOOL_CALLS_PROMPT}\n\nThe tools available are:\n{tools_to_prompt_text(state.tools)}"
            # Just one sub-agent
            mstate.sub_agents.append(
                MagenticSubAgentState(
                    name="Assistant",
                    system_message=subagent_sys_msg,
                    tools=state.tools,
                    tool_call_format=tool_call_format,
                    max_tool_call_steps=10,
                )
            )
            mstate.max_inner_loop_steps = max_steps
            mstate.max_total_tool_call_steps = max_steps

            # outer loop
            n_outer_steps = 0
            while (
                not state.completed
                and n_outer_steps < max_outer_loop_steps
                and mstate.current_inner_loop_steps < mstate.max_inner_loop_steps
                and mstate.current_total_tool_call_steps
                < mstate.max_total_tool_call_steps
            ):
                n_outer_steps += 1
                await _outer_loop_preamble(state, initial_model, mstate)

                # inner loop (each step the orchestrator checks progress and picks the next instruction for the subagent)
                while (
                    not state.completed
                    and mstate.current_inner_loop_steps < mstate.max_inner_loop_steps
                    and mstate.current_total_tool_call_steps
                    < mstate.max_total_tool_call_steps
                ):
                    mstate.current_inner_loop_steps += 1

                    # Checks if we're stuck and selects the next instruction for the agent
                    is_stuck = await _update_inner_loop_progress(
                        state, initial_model, mstate
                    )
                    if state.completed:
                        break
                    elif is_stuck:
                        if n_outer_steps >= max_outer_loop_steps:
                            state.output.completion = "The agent has stalled out and reached the maximum number of outer loop restarts."
                            state.completed = True
                            break
                        await _update_ledger_for_stuck_recovery(
                            state, initial_model, mstate
                        )
                        break

                    # There's no actual selection since we currently support only one sub-agent
                    sub_agent_state = mstate.sub_agents[0]

                    sub_agent_result = await _run_sub_agent_loop(
                        state, initial_model, sub_agent_state, tool_call_format, mstate
                    )

                    # We need to convert it to a "user" message for the orchestrator
                    mstate.orchestrator_messages.append(
                        ChatMessageUser(content=sub_agent_result.content)
                    )
            await close_python_mcp()(state, generate)

            if not state.completed:
                state.output.completion = (
                    "An internal limit was reached with no answer submitted."
                )
                state.completed = True
            return state

        return solve

    return chain(
        resolve_agent_initializer_args(
            init=init,
            tools=tools,
            add_submit_tool=False,
            submit_name=submit_name,
            submit_description=submit_description,
        )
        + [outer_loop_solver()]
    )


@solver
def magentic_init(
    max_steps: int = 10,
    max_stalls: int = 3,
    model_override: str | Model | None = None,
    **tool_options,
):
    """Basic ReAct agent with configurable tools.

    Args:
        max_steps: Maximum number of reasoning steps before terminating.
        max_stalls: Maximum number of stalls allowed before re-planning. Defaults to 3.
        model_override: Optional model override. If provided, will use this
            model instead of the default one (prefer `--model` instead of this,
            unless this agent is being used in a multi-agent system).
        **tool_options: Tool configuration options. See ToolsetConfig in
            astabench.tools for available options (with_search_tools,
            with_stateful_python, with_report_editor, with_table_editor,
            with_thinking_tool, with_editor_submit).  **Note:** the set of
            configured tools will be merged with the set provided by the task,
            and task tools will override selected ones where they overlap
            (necessary to maintain e.g. date restrictions on search tools where
            they apply)
    """
    config = ToolsetConfig.model_validate(tool_options)
    tools = config.create_tools()

    logger.info("Tool configuration: %s", config.pretty_format())

    return magentic_outer_loop(
        init=None,
        tools=tools,
        tool_call_format="native",
        max_steps=max_steps,
        max_stalls=max_stalls,
        model_override=model_override,
    )
