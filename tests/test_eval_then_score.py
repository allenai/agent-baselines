"""Unit tests for scripts/eval_then_score.sh.

These tests are deterministic and network-free: they create a fake repo root
and a fake `uv` shim that logs invocations so we can assert the wrapper calls
solve+score with the expected arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
from pathlib import Path

import pytest

from tests._test_helpers import (
    bash_path,
    make_fake_uv,
    make_repo_root,
    make_solver_project,
    read_shell_calls,
)


def _source_script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "eval_then_score.sh"


def _run_eval_then_score(
    *,
    script_path: Path,
    cwd: Path,
    env: dict[str, str],
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [bash_path(), str(script_path), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@dataclass(frozen=True)
class EvalThenScoreEnv:
    root: Path
    env: dict[str, str]
    uv_log: Path
    script_path: Path


def _make_eval_env(
    tmp_path: Path,
    *,
    include_solver: bool = True,
    include_scorer: bool = True,
) -> EvalThenScoreEnv:
    root = tmp_path / "repo"
    make_repo_root(root)
    source_script = _source_script_path()
    script_path = root / "scripts" / "eval_then_score.sh"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
    script_path.chmod(0o755)

    if include_solver:
        make_solver_project(root, "react")
    if include_scorer:
        make_solver_project(root, "scorer")

    uv_log = tmp_path / "uv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, uv_log)

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(uv_log)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return EvalThenScoreEnv(root=root, env=env, uv_log=uv_log, script_path=script_path)


@pytest.fixture
def eval_env(tmp_path: Path) -> EvalThenScoreEnv:
    return _make_eval_env(tmp_path)


def test_calls_solve_then_score_with_log_dir(eval_env: EvalThenScoreEnv) -> None:

    result = _run_eval_then_score(
        script_path=eval_env.script_path,
        cwd=eval_env.root,
        env=eval_env.env,
        args=[
            "react",
            "--log-dir",
            "logs/out",
            "--",
            "--split",
            "validation",
            "--config-only",
        ],
    )
    assert result.returncode == 0, result.stderr

    calls = read_shell_calls(eval_env.uv_log)
    assert len(calls) == 3

    # Solve phase uses the solver env and enforces --no-score + --log-format json
    assert calls[0][0:2] == ["uv", "run"]
    assert calls[0][2:6] == ["--project", "solvers/react", "--python", "3.11"]
    assert "--frozen" in calls[0]
    assert "--" in calls[0]
    assert "astabench" in calls[0]
    assert "eval" in calls[0]
    assert "--log-dir" in calls[0]
    assert "logs/out" in calls[0]
    assert "--no-score" in calls[0]
    assert "--log-format" in calls[0]
    assert "json" in calls[0]

    # Score phase uses frozen scorer env to score generated logs.
    assert calls[1][0:2] == ["uv", "run"]
    assert calls[1][2:6] == ["--project", "solvers/scorer", "--python", "3.11"]
    assert "inspect" in calls[1]
    assert "score" in calls[1]
    assert "--overwrite" in calls[1]
    assert calls[1][-1] == "logs/out/run.json"

    # Aggregation phase still runs astabench score on the log directory.
    assert calls[2][0:2] == ["uv", "run"]
    assert calls[2][2:6] == ["--project", "solvers/scorer", "--python", "3.11"]
    assert "astabench" in calls[2]
    assert "score" in calls[2]
    assert calls[2][-1] == "logs/out"


def test_works_from_subdir(eval_env: EvalThenScoreEnv) -> None:
    subdir = eval_env.root / "solvers" / "foo" / "nested"
    subdir.mkdir(parents=True)

    result = _run_eval_then_score(
        script_path=eval_env.script_path,
        cwd=subdir,
        env=eval_env.env,
        args=[
            "react",
            "--log-dir",
            "logs/out",
            "--",
            "--config-only",
        ],
    )
    assert result.returncode == 0, result.stderr


def test_requires_solver_project(tmp_path: Path) -> None:
    test_env = _make_eval_env(tmp_path, include_solver=False, include_scorer=True)

    result = _run_eval_then_score(
        script_path=test_env.script_path,
        cwd=test_env.root,
        env=test_env.env,
        args=["react", "--", "--config-only"],
    )
    assert result.returncode == 2
    assert "unknown solver env 'react'" in result.stderr


def test_requires_scorer_project(tmp_path: Path) -> None:
    test_env = _make_eval_env(tmp_path, include_solver=True, include_scorer=False)

    result = _run_eval_then_score(
        script_path=test_env.script_path,
        cwd=test_env.root,
        env=test_env.env,
        args=["react", "--", "--config-only"],
    )
    assert result.returncode == 2
    assert "missing scorer env" in result.stderr
