from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest
from inspect_ai.model import ChatMessageUser, ModelOutput
from inspect_ai.scorer import Target
from inspect_ai.solver import TaskState


def _load_arithmetic_solver_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "arithmetic_solver.py"
    spec = importlib.util.spec_from_file_location("arithmetic_solver", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


arithmetic_solver = _load_arithmetic_solver_module()


def test_extract_expression_prefers_compute_line_over_example_json() -> None:
    prompt = (
        'Answer the given arithmetic question. Output your answer as JSON like {"answer": 1234}.\n\n'
        "Compute 4.6 + 2.1*2"
    )
    assert arithmetic_solver._extract_expression(prompt) == "4.6 + 2.1*2"


def test_extract_expression_fallback_uses_last_match() -> None:
    text = "Example: 2+2\nNow solve this one: 3*4"
    assert arithmetic_solver._extract_expression(text) == "3*4"


def test_safe_eval_on_extracted_expression() -> None:
    prompt = (
        'Format as {"answer": 1234}.\n'
        "Compute 4.6 + 2.1*2"
    )
    expr = arithmetic_solver._extract_expression(prompt)
    assert arithmetic_solver._safe_eval(expr) == pytest.approx(8.8)


def test_extract_expression_handles_parenthesized_compute_line() -> None:
    expr = arithmetic_solver._extract_expression("Compute (1+2)*3")
    assert expr == "(1+2)*3"
    assert arithmetic_solver._safe_eval(expr) == pytest.approx(9.0)


def test_extract_expression_raises_when_missing() -> None:
    with pytest.raises(ValueError, match="No arithmetic expression found"):
        arithmetic_solver._extract_expression("No arithmetic here.")


def test_solver_populates_choices_for_cross_version_scoring() -> None:
    solve = arithmetic_solver.arithmetic_solver()
    state = TaskState(
        model="mockllm/model",
        sample_id="1",
        epoch=1,
        input="Compute 4.6 + 2.1*2",
        messages=[ChatMessageUser(content="Compute 4.6 + 2.1*2")],
        target=Target(target="8.8"),
        choices=None,
        output=ModelOutput(model="mockllm/model"),
        metadata={},
    )

    async def _generate(task_state: TaskState) -> TaskState:
        return task_state

    solved = asyncio.run(solve(state, _generate))
    assert solved.output.completion == '{"answer": 8.8}'
    assert len(solved.output.choices) == 1
    assert solved.output.model_dump()["choices"]
