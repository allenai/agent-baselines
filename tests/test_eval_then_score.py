"""Unit tests for scripts/eval_then_score.sh.

These tests are deterministic and network-free: they create a fake repo root
and a fake `uv` shim that logs invocations so we can assert the wrapper calls
solve+score with the expected arguments.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.conftest import (
    bash_path,
    make_fake_uv,
    make_repo_root,
    make_solver_project,
    read_shell_calls,
)


def _script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "eval_then_score.sh"


def _run_eval_then_score(
    *,
    cwd: Path,
    env: dict[str, str],
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [bash_path(), str(_script_path()), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_calls_solve_then_score_with_log_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "react")
    make_solver_project(root, "scorer")

    uv_log = tmp_path / "uv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, uv_log)

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(uv_log)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(
        cwd=root,
        env=env,
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

    calls = read_shell_calls(uv_log)
    assert len(calls) == 2

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

    # Score phase uses frozen scorer env to score the same log dir
    assert calls[1][0:2] == ["uv", "run"]
    assert calls[1][2:6] == ["--project", "solvers/scorer", "--python", "3.11"]
    assert "astabench" in calls[1]
    assert "score" in calls[1]
    assert calls[1][-1] == "logs/out"


def test_requires_solver_name(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, tmp_path / "uv.log")

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(cwd=root, env=env, args=[])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_log_dir_equals_syntax(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "react")
    make_solver_project(root, "scorer")

    uv_log = tmp_path / "uv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, uv_log)

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(uv_log)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(
        cwd=root,
        env=env,
        args=[
            "react",
            "--log-dir=logs/out",
            "--",
            "--config-only",
        ],
    )
    assert result.returncode == 0, result.stderr

    calls = read_shell_calls(uv_log)
    assert len(calls) == 2
    assert "logs/out" in calls[0]
    assert calls[1][-1] == "logs/out"


def test_default_log_dir_includes_solver_prefix(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "react")
    make_solver_project(root, "scorer")

    uv_log = tmp_path / "uv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, uv_log)

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(uv_log)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(
        cwd=root,
        env=env,
        args=[
            "react",
            "--",
            "--config-only",
        ],
    )
    assert result.returncode == 0, result.stderr

    calls = read_shell_calls(uv_log)
    assert len(calls) == 2

    log_dir_index = calls[0].index("--log-dir")
    log_dir = calls[0][log_dir_index + 1]
    assert log_dir.startswith("logs/react_two_phase_")

    assert calls[1][-1] == log_dir


def test_works_from_subdir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "react")
    make_solver_project(root, "scorer")

    uv_log = tmp_path / "uv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, uv_log)

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(uv_log)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    subdir = root / "solvers" / "foo" / "nested"
    subdir.mkdir(parents=True)

    result = _run_eval_then_score(
        cwd=subdir,
        env=env,
        args=[
            "react",
            "--log-dir",
            "logs/out",
            "--",
            "--config-only",
        ],
    )
    assert result.returncode == 0, result.stderr


def test_help_flag_works_outside_repo(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(cwd=tmp_path, env=env, args=["--help"])
    assert result.returncode == 0
    assert "Usage:" in result.stderr


def test_log_dir_requires_value(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "react")
    make_solver_project(root, "scorer")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, tmp_path / "uv.log")

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(
        cwd=root,
        env=env,
        args=["react", "--log-dir"],
    )
    assert result.returncode == 2
    assert "--log-dir requires a value" in result.stderr


def test_requires_repo_root(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(
        cwd=tmp_path,
        env=env,
        args=["react", "--", "--config-only"],
    )
    assert result.returncode == 2
    assert "must run from within the repo" in result.stderr


def test_requires_solver_project(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "scorer")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, tmp_path / "uv.log")

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(
        cwd=root,
        env=env,
        args=["react", "--", "--config-only"],
    )
    assert result.returncode == 2
    assert "unknown solver env 'react'" in result.stderr


def test_requires_scorer_project(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "react")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, tmp_path / "uv.log")

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_eval_then_score(
        cwd=root,
        env=env,
        args=["react", "--", "--config-only"],
    )
    assert result.returncode == 2
    assert "missing scorer env" in result.stderr
