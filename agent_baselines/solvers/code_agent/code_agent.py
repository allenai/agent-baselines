import json
from typing import Optional, Type

from astabench.util.sandbox.sandbox_jupyter import SandboxJupyter
from inspect_ai.model import Model, get_model

from agent_baselines.solvers.code_agent.environment import EditACI, Environment
from agent_baselines.solvers.code_agent.llm_agent import Agent


class CodeAgent:
    """Base CodeAgent implementation for ReACT and other variants.

    Attributes:
        prompt: The input query or prompt used to initialize the ReACT agent.
        llm: The underlying LLM agent used in ReACT with utilities
            for storing different details of the ReACT trajectory.
        env: The underlying environment for executing actions
            and receiving observations.

    """

    def __init__(
        self,
        prompt: str,
        prompt_config_path: Optional[str] = None,
        json_output: Optional[bool] = False,
        precompute_cells: Optional[list] = [],
        cell_timeout: Optional[int] = 500,
        model_override: str | Model | None = None,
        **kwargs,
    ) -> None:
        """Creates instance with acccess to an execution environment (`env`) with
        code editing functionality, as well as a llm agent.

        Arguments:
            prompt: The input query or prompt used to initialize the ReACT agent.
            prompt_config_path: A configuration file consisting of system prompt specification
                and other in-context example data.
            json_output: Switch that restricts final output to json (default=false).
            *kwargs: All other environment and agent keyword arguments.

        """
        self._prompt = prompt
        self.llm = Agent(
            task=prompt,
            prompt_config_path=prompt_config_path,
            model_engine=get_model().name,
            json_output=json_output,
            model_override=model_override,
            **kwargs,
        )
        self.env = Environment(**kwargs)
        self.env.register_action_type("edit", EditACI(self.env))
        self.precompute_cells = precompute_cells
        self.cell_timeout = cell_timeout

    @property
    def prompt(self) -> str:
        """Returns the initial prompt or query to the coding agent."""
        return self._prompt


class ReactAgent(CodeAgent):
    """Async ReACT agent implementation

    Attributes:
        prompt: The input query or prompt used to initialize the ReACT agent.
        llm: The underlying LLM agent used in ReACT with utilities
            for storing different details of the ReACT trajectory. Defaults to
            `prompt.yaml` here locally, which is a yaml file with the following
            structure:

            ```yaml
            system_prompt: | <system prompt details>
            commands: | <details of the provided commands and tools>
            edit_demonstration: | <details of edit command>
            ```

        env: The underlying environment for executing actions
            and receiving observations.

    """

    async def run(self, max_tries: Optional[int] = 30) -> str:
        """Async run loop for ReACT agent. As in normal ReACT, first elicits an
        `action` from `self.llm` then takesn a `step` in `self.env`, retries output
        and continues until the number of `max_tries` runs out or the agent decides to stop.

        Args:
            max_tries: the number of steps allowed in ReACT

        Returns:
           A json parseable string with all solve outputs and representation
               of result rejectory.

        """
        async with SandboxJupyter(cell_timeout=self.cell_timeout) as notebook:
            ## switch to wdir
            if self.env.work_dir:
                await notebook.run_code(code=f"!mkdir -p {self.env.work_dir}")
                await notebook.run_code(code=f"%cd {self.env.work_dir}")

            for cell in self.precompute_cells:
                step = await self.env.step(json.loads(cell), notebook)
                self.llm.step_completed(step)

            for i in range(max_tries):
                action = await self.llm.next_action()
                step = await self.env.step(action, notebook)
                self.llm.step_completed(step)
                if step.done:
                    break

        metrics = self.env.final_result
        return json.dumps(metrics)


class ReflexionAgent(CodeAgent):
    """Async Reflexion code agent implementation"""

    async def run(self, max_tries: Optional[int] = 30) -> str:
        """Implement of reflexion agent"""
        raise NotImplementedError("Reflexion not implemented yet.")


def InteractiveCodeAgent(
    agent_type: str,
    prompt: str,
    prompt_config_path: Optional[str] = None,
    json_output: Optional[bool] = False,
    precompute_cells: Optional[bool] = [],
    **kwargs,
) -> Type[CodeAgent]:
    """Factory method for building code agent. Currenly only react agent is implemented, but
    additional agent implementations can be added here.

     Arguments:
        agent_type: the particular agent implementation.
        prompt: The input query or prompt used to initialize the ReACT agent.
        prompt_config_path: A configuration file consisting of system prompt specification
            and other in-context example data.
        *kwargs: All other environment and agent keyword arguments.

    raises:
       `ValueError` on wrong agent type.

    """
    if agent_type != "react":
        raise ValueError(f"Code agent type not implemented: {agent_type}")
    return ReactAgent(
        prompt,
        prompt_config_path=prompt_config_path,
        json_output=json_output,
        precompute_cells=precompute_cells,
        **kwargs,
    )
