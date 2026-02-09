"""Unit tests for scripts/solver_uv.sh.

These tests are deterministic and network-free: they use a fake `uv` shim that
logs invocations to a file so we can assert the exact commands/flags without
actually creating environments or installing dependencies.
"""

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
    return Path(__file__).resolve().parents[1] / "scripts" / "solver_uv.sh"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo_root(root: Path) -> None:
    _write(root / "pyproject.toml", "[project]\nname='tmp'\n")
    (root / "solvers").mkdir(parents=True, exist_ok=True)


def _make_solver(root: Path, solver: str, *, with_lock: bool) -> None:
    solver_dir = root / "solvers" / solver
    _write(
        solver_dir / "pyproject.toml",
        "[project]\nname='tmp-solver'\nrequires-python='>=3.11'\n",
    )
    if with_lock:
        _write(solver_dir / "uv.lock", "version = 1\n")


def _make_fake_uv(bin_dir: Path, log_file: Path) -> None:
    uv = bin_dir / "uv"
    _write(
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
            ]
        )
        + "\n",
    )
    uv.chmod(0o755)


def _run_solver_uv(
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


def _read_uv_calls(log_file: Path) -> list[list[str]]:
    if not log_file.exists():
        return []
    return [
        shlex.split(line) for line in log_file.read_text(encoding="utf-8").splitlines()
    ]


class _UvHarness:
    """Shared test harness: fake repo root, fake uv binary, env dict."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "repo"
        _make_repo_root(self.root)

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        self.log_file = tmp_path / "uv.log"
        _make_fake_uv(bin_dir, self.log_file)

        self.env = os.environ.copy()
        self.env["PATH"] = f"{bin_dir}{os.pathsep}{self.env['PATH']}"
        self.env["UV_LOG_FILE"] = str(self.log_file)

    def add_solver(self, name: str, *, with_lock: bool) -> None:
        _make_solver(self.root, name, with_lock=with_lock)

    def run(
        self, args: list[str], *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return _run_solver_uv(cwd=cwd or self.root, env=self.env, args=args)

    def uv_calls(self) -> list[list[str]]:
        return _read_uv_calls(self.log_file)


@pytest.fixture
def harness(tmp_path: Path) -> _UvHarness:
    return _UvHarness(tmp_path)


def test_sync_calls_lock_when_lockfile_missing(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=False)

    result = harness.run(["sync", "foo"])
    assert result.returncode == 0, result.stderr

    calls = harness.uv_calls()
    assert len(calls) == 2
    assert calls[0][0:2] == ["uv", "lock"]
    assert calls[0][2:6] == ["--project", "solvers/foo", "--python", "3.11"]
    assert calls[1][0:2] == ["uv", "sync"]
    assert calls[1][2:6] == ["--project", "solvers/foo", "--python", "3.11"]


def test_sync_skips_lock_when_lockfile_present(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=True)

    result = harness.run(["sync", "foo"])
    assert result.returncode == 0, result.stderr

    calls = harness.uv_calls()
    assert len(calls) == 1
    assert calls[0][0:2] == ["uv", "sync"]


def test_lock_action_calls_uv_lock(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=False)

    result = harness.run(["lock", "foo"])
    assert result.returncode == 0, result.stderr

    calls = harness.uv_calls()
    assert len(calls) == 1
    assert calls[0][0:2] == ["uv", "lock"]
    assert calls[0][2:6] == ["--project", "solvers/foo", "--python", "3.11"]


def test_run_action_calls_uv_run_with_frozen(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=True)

    result = harness.run(["run", "foo", "--", "echo", "hi"])
    assert result.returncode == 0, result.stderr

    calls = harness.uv_calls()
    assert len(calls) == 1
    assert calls[0][0:2] == ["uv", "run"]
    assert calls[0][2:6] == ["--project", "solvers/foo", "--python", "3.11"]
    assert calls[0][6] == "--frozen"
    assert calls[0][-2:] == ["echo", "hi"]


def test_run_action_calls_uv_run_without_separator(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=True)

    result = harness.run(["run", "foo", "echo", "hi"])
    assert result.returncode == 0, result.stderr

    calls = harness.uv_calls()
    assert len(calls) == 1
    assert calls[0][0:2] == ["uv", "run"]
    assert calls[0][2:6] == ["--project", "solvers/foo", "--python", "3.11"]
    assert calls[0][6] == "--frozen"
    assert calls[0][-2:] == ["echo", "hi"]


def test_run_requires_command(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=True)

    result = harness.run(["run", "foo"])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_missing_solver_pyproject_errors(harness: _UvHarness) -> None:
    result = harness.run(["sync", "missing"])
    assert result.returncode == 2
    assert "missing solvers/missing/pyproject.toml" in result.stderr


def test_not_repo_root_errors(tmp_path: Path) -> None:
    root = tmp_path / "not_repo_root"
    root.mkdir()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "uv.log"
    _make_fake_uv(bin_dir, log_file)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["UV_LOG_FILE"] = str(log_file)

    result = _run_solver_uv(cwd=root, env=env, args=["sync", "foo"])
    assert result.returncode == 2
    assert "must run from within the repo" in result.stderr


def test_works_from_solver_subdir(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=True)

    solver_subdir = harness.root / "solvers" / "foo"
    result = harness.run(["sync", "foo"], cwd=solver_subdir)
    assert result.returncode == 0, result.stderr

    calls = harness.uv_calls()
    assert len(calls) == 1
    assert calls[0][0:2] == ["uv", "sync"]
    assert calls[0][2:6] == ["--project", "solvers/foo", "--python", "3.11"]


def test_missing_uv_errors(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)
    _make_solver(root, "foo", with_lock=True)

    env = os.environ.copy()
    env["PATH"] = str(tmp_path / "empty_path")
    env.pop("UV_LOG_FILE", None)

    result = _run_solver_uv(cwd=root, env=env, args=["sync", "foo"])
    assert result.returncode == 127
    assert "uv not found on PATH" in result.stderr


def test_solver_uv_python_override(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=True)
    harness.env["SOLVER_UV_PYTHON"] = "3.12"

    result = harness.run(["sync", "foo"])
    assert result.returncode == 0, result.stderr

    calls = harness.uv_calls()
    assert len(calls) == 1
    assert calls[0][0:2] == ["uv", "sync"]
    assert calls[0][2:6] == ["--project", "solvers/foo", "--python", "3.12"]


def test_invalid_action_shows_usage(harness: _UvHarness) -> None:
    harness.add_solver("foo", with_lock=True)

    result = harness.run(["nope", "foo"])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_no_args_shows_usage(harness: _UvHarness) -> None:
    result = harness.run([])
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_sync_requires_solver_name(harness: _UvHarness) -> None:
    result = harness.run(["sync"])
    assert result.returncode == 2
    assert "Usage:" in result.stderr
