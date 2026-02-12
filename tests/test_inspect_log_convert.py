"""Unit tests for scripts/inspect_log_convert.sh.

Deterministic and network-free: create a fake repo root and a stub
`uv` that logs invocations so we can assert correct wiring.
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
    return Path(__file__).resolve().parents[1] / "scripts" / "inspect_log_convert.sh"


def _run_script(
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


def test_calls_uv_run_with_inspect_log_convert_args(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "paper_finder")

    uv_log = tmp_path / "uv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, uv_log)

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(uv_log)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

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

    calls = read_shell_calls(uv_log)
    assert len(calls) == 1
    assert calls[0][0:2] == ["uv", "run"]
    assert calls[0][2:6] == ["--project", "solvers/paper_finder", "--python", "3.11"]
    assert calls[0][8:11] == ["inspect", "log", "convert"]
    assert calls[0][-5:] == ["--to", "json", "--output-dir", "out", "logs/in"]


def test_requires_env_and_args(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, tmp_path / "uv.log")

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_script(cwd=root, env=env, args=[])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_requires_convert_args(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    make_solver_project(root, "paper_finder")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, tmp_path / "uv.log")

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_script(cwd=root, env=env, args=["paper_finder"])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_works_from_subdir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
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
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    result = _run_script(cwd=tmp_path, env=env, args=["--help"])
    assert result.returncode == 0
    assert "Usage:" in result.stderr


def test_requires_repo_root(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    result = _run_script(
        cwd=tmp_path,
        env=env,
        args=["scorer", "--to", "json", "--output-dir", "out", "logs/in"],
    )
    assert result.returncode == 2
    assert "must run from within the repo" in result.stderr


def test_requires_known_env_project(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_repo_root(root)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_uv(bin_dir, tmp_path / "uv.log")

    env = os.environ.copy()
    env["UV_LOG_FILE"] = str(tmp_path / "uv.log")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = _run_script(
        cwd=root,
        env=env,
        args=["unknown", "--to", "json", "--output-dir", "out", "logs/in"],
    )
    assert result.returncode == 2
    assert "unknown env 'unknown'" in result.stderr
