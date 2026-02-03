"""Unit tests for scripts/eval_then_score.sh.

These tests are deterministic and network-free: they create a fake repo root
and a stub `scripts/solver_uv.sh` that logs invocations so we can assert the
wrapper calls solve+score with the expected arguments.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


def _bash_path() -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    return bash


def _script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "eval_then_score.sh"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo_root(root: Path) -> None:
    _write(root / "pyproject.toml", "[project]\nname='tmp'\n")
    (root / "solvers").mkdir(parents=True, exist_ok=True)


def _make_fake_solver_uv(root: Path, log_file: Path) -> None:
    solver_uv = root / "scripts" / "solver_uv.sh"
    _write(
        solver_uv,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'if [ -z "${CALLS_LOG:-}" ]; then',
                '  echo "CALLS_LOG not set" >&2',
                "  exit 2",
                "fi",
                'printf "%q " "$0" "$@" >> "$CALLS_LOG"',
                'printf "\\n" >> "$CALLS_LOG"',
            ]
        )
        + "\n",
    )
    solver_uv.chmod(0o755)
    log_file.parent.mkdir(parents=True, exist_ok=True)


def _run_eval_then_score(
    *,
    cwd: Path,
    env: dict[str, str],
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bash_path(), str(_script_path()), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _read_calls(log_file: Path) -> list[list[str]]:
    if not log_file.exists():
        return []
    return [
        shlex.split(line) for line in log_file.read_text(encoding="utf-8").splitlines()
    ]


def test_calls_solve_then_score_with_log_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    calls_log = tmp_path / "calls.log"
    _make_fake_solver_uv(root, calls_log)

    env = os.environ.copy()
    env["CALLS_LOG"] = str(calls_log)

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

    calls = _read_calls(calls_log)
    assert len(calls) == 2

    # Solve phase uses the solver env and enforces --no-score + --log-format json
    assert calls[0][1:4] == ["run", "react", "--"]
    assert calls[0][4:6] == ["astabench", "eval"]
    assert "--log-dir" in calls[0]
    assert "logs/out" in calls[0]
    assert "--no-score" in calls[0]
    assert "--log-format" in calls[0]
    assert "json" in calls[0]

    # Score phase uses frozen scorer env to score the same log dir
    assert calls[1][1:4] == ["run", "scorer", "--"]
    assert calls[1][4:6] == ["astabench", "score"]
    assert calls[1][-1] == "logs/out"


def test_requires_solver_name(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)
    _make_fake_solver_uv(root, tmp_path / "calls.log")

    env = os.environ.copy()
    env["CALLS_LOG"] = str(tmp_path / "calls.log")

    result = _run_eval_then_score(cwd=root, env=env, args=[])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_log_dir_equals_syntax(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    calls_log = tmp_path / "calls.log"
    _make_fake_solver_uv(root, calls_log)

    env = os.environ.copy()
    env["CALLS_LOG"] = str(calls_log)

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

    calls = _read_calls(calls_log)
    assert len(calls) == 2
    assert "logs/out" in calls[0]
    assert calls[1][-1] == "logs/out"


def test_default_log_dir_includes_solver_prefix(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    calls_log = tmp_path / "calls.log"
    _make_fake_solver_uv(root, calls_log)

    env = os.environ.copy()
    env["CALLS_LOG"] = str(calls_log)

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

    calls = _read_calls(calls_log)
    assert len(calls) == 2

    log_dir_index = calls[0].index("--log-dir")
    log_dir = calls[0][log_dir_index + 1]
    assert log_dir.startswith("logs/react_two_phase_")

    assert calls[1][-1] == log_dir


def test_works_from_subdir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    calls_log = tmp_path / "calls.log"
    _make_fake_solver_uv(root, calls_log)

    env = os.environ.copy()
    env["CALLS_LOG"] = str(calls_log)

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
    env["CALLS_LOG"] = str(tmp_path / "calls.log")

    result = _run_eval_then_score(cwd=tmp_path, env=env, args=["--help"])
    assert result.returncode == 0
    assert "Usage:" in result.stderr


def test_log_dir_requires_value(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)
    _make_fake_solver_uv(root, tmp_path / "calls.log")

    env = os.environ.copy()
    env["CALLS_LOG"] = str(tmp_path / "calls.log")

    result = _run_eval_then_score(
        cwd=root,
        env=env,
        args=["react", "--log-dir"],
    )
    assert result.returncode == 2
    assert "--log-dir requires a value" in result.stderr


def test_requires_repo_root(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["CALLS_LOG"] = str(tmp_path / "calls.log")

    result = _run_eval_then_score(
        cwd=tmp_path,
        env=env,
        args=["react", "--", "--config-only"],
    )
    assert result.returncode == 2
    assert "must run from within the repo" in result.stderr
