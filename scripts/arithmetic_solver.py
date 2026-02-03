"""Deterministic, keyless solver for CI smoke tests.

This solver is intentionally tiny and avoids model calls. It is used by the
cross-version solve→score smoke to generate Inspect logs without requiring any
API keys or external services.
"""

from __future__ import annotations

import ast
import json
import operator
import re
from typing import Any, Callable

from inspect_ai.solver import Generate, Solver, TaskState, solver


def _extract_expression(text: str) -> str:
    # Find an arithmetic expression inside the prompt. The astabench demo task
    # prompts contain a single expression (e.g. "2+2" or "4.6 + 2.1*2").
    match = re.search(r"(-?\d[\d\.\s+\-*/()]*\d)", text)
    if not match:
        raise ValueError("No arithmetic expression found in prompt.")
    return match.group(1).strip()


_BINOPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARYOPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: lambda x: x,
    ast.USub: operator.neg,
}


def _safe_eval(expr: str) -> float:
    """Safely evaluate a numeric arithmetic expression."""

    def eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](eval_node(node.left), eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
            return _UNARYOPS[type(node.op)](eval_node(node.operand))
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    tree = ast.parse(expr, mode="eval")
    return eval_node(tree)


@solver
def arithmetic_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate  # deterministic, no model calls

        expr = _extract_expression(state.input_text)
        value = _safe_eval(expr)
        answer: Any = int(value) if float(value).is_integer() else value

        state.output.completion = json.dumps({"answer": answer})
        return state

    return solve

