"""Unit tests for scripts/inspect_log_convert.sh.

Deterministic and network-free: create a fake repo root and a stub
`scripts/solver_uv.sh` that logs invocations so we can assert correct wiring.
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
    return Path(__file__).resolve().parents[1] / "scripts" / "inspect_log_convert.sh"


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
                '  echo \"CALLS_LOG not set\" >&2',
                "  exit 2",
                "fi",
                'printf \"%q \" \"$0\" \"$@\" >> \"$CALLS_LOG\"',
                'printf \"\\n\" >> \"$CALLS_LOG\"',
            ]
        )
        + "\n",
    )
    solver_uv.chmod(0o755)
    log_file.parent.mkdir(parents=True, exist_ok=True)


def _run_script(
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


def test_calls_solver_uv_with_inspect_log_convert_args(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    calls_log = tmp_path / "calls.log"
    _make_fake_solver_uv(root, calls_log)

    env = os.environ.copy()
    env["CALLS_LOG"] = str(calls_log)

    result = _run_script(
        cwd=root,
        env=env,
        args=[
            "paper_finder",
            "--to",
            "json",
            "--output-dir",
            "out",
            "logs/in",
        ],
    )
    assert result.returncode == 0, result.stderr

    calls = _read_calls(calls_log)
    assert len(calls) == 1
    assert calls[0][1:4] == ["run", "paper_finder", "--"]
    assert calls[0][4:7] == ["inspect", "log", "convert"]
    assert calls[0][-5:] == ["--to", "json", "--output-dir", "out", "logs/in"]


def test_requires_env_and_args(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)
    _make_fake_solver_uv(root, tmp_path / "calls.log")

    env = os.environ.copy()
    env["CALLS_LOG"] = str(tmp_path / "calls.log")

    result = _run_script(cwd=root, env=env, args=[])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_requires_convert_args(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)
    _make_fake_solver_uv(root, tmp_path / "calls.log")

    env = os.environ.copy()
    env["CALLS_LOG"] = str(tmp_path / "calls.log")

    result = _run_script(cwd=root, env=env, args=["paper_finder"])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_works_from_subdir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    calls_log = tmp_path / "calls.log"
    _make_fake_solver_uv(root, calls_log)

    env = os.environ.copy()
    env["CALLS_LOG"] = str(calls_log)

    subdir = root / "solvers" / "foo" / "nested"
    subdir.mkdir(parents=True)

    result = _run_script(
        cwd=subdir,
        env=env,
        args=[
            "scorer",
            "--to",
            "json",
            "--output-dir",
            "out",
            "logs/in",
        ],
    )
    assert result.returncode == 0, result.stderr


def test_help_flag_works_outside_repo(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["CALLS_LOG"] = str(tmp_path / "calls.log")

    result = _run_script(cwd=tmp_path, env=env, args=["--help"])
    assert result.returncode == 0
    assert "Usage:" in result.stderr


def test_requires_repo_root(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["CALLS_LOG"] = str(tmp_path / "calls.log")

    result = _run_script(
        cwd=tmp_path,
        env=env,
        args=["scorer", "--to", "json", "--output-dir", "out", "logs/in"],
    )
    assert result.returncode == 2
    assert "must run from within the repo" in result.stderr
