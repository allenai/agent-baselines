from __future__ import annotations

import shlex
import shutil
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
