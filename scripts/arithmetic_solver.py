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

from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver


def _is_expression_candidate(expr: str) -> bool:
    candidate = expr.strip()
    if not candidate:
        return False
    if re.fullmatch(r"[0-9+\-*/().\s]+", candidate) is None:
        return False
    if re.search(r"\d", candidate) is None:
        return False
    if re.search(r"[+\-*/]", candidate) is None:
        return False
    return True


def _extract_expression(text: str) -> str:
    # Prefer explicit "Compute ..." lines to avoid picking up numeric examples
    # from prompt instructions (e.g. {"answer": 1234}).
    compute_match = re.search(
        r"(?im)^\s*(?:compute|calculate)\s+(?P<expr>.+?)\s*$",
        text,
    )
    if compute_match:
        expr = compute_match.group("expr").strip()
        if _is_expression_candidate(expr):
            return expr

    # Fallback: choose the last arithmetic-like token span in the prompt.
    matches: list[str] = []
    for line in text.splitlines():
        for match in re.finditer(r"[0-9+\-*/().\s]+", line):
            candidate = match.group(0).strip()
            if _is_expression_candidate(candidate):
                matches.append(candidate)

    if not matches:
        raise ValueError("No arithmetic expression found in prompt.")
    return matches[-1].strip()


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

        completion = json.dumps({"answer": answer})
        # Use ModelOutput.from_content so the serialized log carries the answer
        # in output.choices (compatible with older scorer Inspect versions).
        state.output = ModelOutput.from_content(
            model=str(state.model),
            content=completion,
        )
        return state

    return solve
