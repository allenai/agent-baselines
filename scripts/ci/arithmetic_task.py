"""Tiny Inspect task for CI solve→score smoke.

This task is intentionally minimal and keyless. It exists so we can generate
Inspect logs in a solver environment (potentially with a different Inspect
version) without depending on any external services.
"""

from __future__ import annotations

import re

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver


@solver
def not_implemented_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        raise NotImplementedError(
            "This is a placeholder solver. Please specify a solver via --solver."
        )

    return solve


@scorer(metrics=[accuracy(), stderr()])
def check_arithmetic() -> Scorer:
    """Parse `{\"answer\": <number>}` and compare to the target."""

    async def score(state: TaskState, target: Target) -> Score:
        raw_output = state.output.completion
        explanation = "<Failed to parse output>"
        is_correct = False

        match = re.search(r"\"answer\":\s*(?P<answer>-?\d+(\.\d+)?)", raw_output)
        if match is not None:
            answer = float(match.group("answer"))
            explanation = f"Parsed answer: {answer} (correct answer = {target.text})"
            is_correct = abs(answer - float(target.text)) < 1e-6

        return Score(
            value=CORRECT if is_correct else INCORRECT,
            answer=raw_output,
            explanation=explanation,
        )

    return score


@task
def arithmetic_smoke() -> Task:
    prompt = (
        'Answer the given arithmetic question. Output your answer as JSON like {"answer": 1234}.\n\n'
        "Compute 4.6 + 2.1*2"
    )
    return Task(
        dataset=[Sample(id="1", input=prompt, target="8.8")],
        solver=not_implemented_solver(),
        scorer=check_arithmetic(),
    )
