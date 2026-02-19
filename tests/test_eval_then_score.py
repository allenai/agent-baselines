"""Unit tests for scripts/eval_then_score.sh.

These tests are deterministic and network-free: they create a fake repo root
and a fake `uv` shim that logs invocations so we can assert the wrapper calls
solve+score with the expected arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


def bash_path() -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    return bash


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo_root(root: Path) -> None:
    write_file(root / "pyproject.toml", "[project]\nname='tmp'\n")
    (root / "solvers").mkdir(parents=True, exist_ok=True)


def make_solver_project(root: Path, solver: str) -> None:
    write_file(
        root / "solvers" / solver / "pyproject.toml",
        "[project]\nname='tmp-solver'\nrequires-python='>=3.11'\n",
    )


def make_fake_uv(bin_dir: Path, log_file: Path) -> None:
    uv = bin_dir / "uv"
    write_file(
        uv,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'if [ -z "${UV_LOG_FILE:-}" ]; then',
                '  echo "UV_LOG_FILE not set" >&2',
                "  exit 2",
                "fi",
                'printf "%q " uv "$@" >> "$UV_LOG_FILE"',
                'printf "\\n" >> "$UV_LOG_FILE"',
                "",
                "# Simulate eval output artifacts for scripts that score later.",
                'args=("$@")',
                "is_eval=0",
                'log_dir=""',
                "for ((i=0; i<${#args[@]}; i++)); do",
                '  if [ "${args[$i]}" = "astabench" ] && [ $((i + 1)) -lt ${#args[@]} ] && [ "${args[$((i + 1))]}" = "eval" ]; then',
                "    is_eval=1",
                "  fi",
                '  if [ "${args[$i]}" = "--log-dir" ] && [ $((i + 1)) -lt ${#args[@]} ]; then',
                '    log_dir="${args[$((i + 1))]}"',
                "  fi",
                "done",
                'if [ "$is_eval" = "1" ] && [ -n "$log_dir" ]; then',
                '  mkdir -p "$log_dir"',
                "  cat > \"$log_dir/logs.json\" <<'JSON'",
                '{"run.json": {}}',
                "JSON",
                '  echo "{}" > "$log_dir/run.json"',
                "fi",
            ]
        )
        + "\n",
    )
    uv.chmod(0o755)
    log_file.parent.mkdir(parents=True, exist_ok=True)


def read_shell_calls(log_file: Path) -> list[list[str]]:
    if not log_file.exists():
        return []
    return [
        shlex.split(line) for line in log_file.read_text(encoding="utf-8").splitlines()
    ]


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
