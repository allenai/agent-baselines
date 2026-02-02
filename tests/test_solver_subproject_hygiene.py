"""Unit tests that enforce the per-solver uv sub-project conventions.

These are intentionally fast and network-free: they only validate repository
structure and scripts for solvers that opt into uv sub-projects via
`solvers/<solver>/pyproject.toml`.
"""

from __future__ import annotations

import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _solver_dirs_with_pyproject(root: Path) -> list[Path]:
    solvers_dir = root / "solvers"
    if not solvers_dir.exists():
        return []
    return sorted(p.parent for p in solvers_dir.glob("*/pyproject.toml"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_uv_subprojects_have_required_files() -> None:
    root = _repo_root()
    missing: list[str] = []

    for solver_dir in _solver_dirs_with_pyproject(root):
        for rel in ("uv.lock", "setup.sh", "demo.sh", "env", "README.md"):
            if not (solver_dir / rel).exists():
                missing.append(f"{solver_dir.name}: missing solvers/{solver_dir.name}/{rel}")

    assert not missing, "Missing required per-solver files:\n" + "\n".join(missing)


def test_uv_subproject_setup_uses_solver_uv_sync() -> None:
    root = _repo_root()
    offenders: list[str] = []

    for solver_dir in _solver_dirs_with_pyproject(root):
        setup_sh = solver_dir / "setup.sh"
        if not setup_sh.exists():
            offenders.append(f"{solver_dir.name}: missing solvers/{solver_dir.name}/setup.sh")
            continue
        content = _read_text(setup_sh)

        # Require the canonical form: ./scripts/solver_uv.sh sync <solver>
        pattern = re.compile(
            rf"^\s*\./scripts/solver_uv\.sh\s+sync\s+{re.escape(solver_dir.name)}\s*$",
            re.MULTILINE,
        )
        if not pattern.search(content):
            offenders.append(f"{solver_dir.name}: setup.sh does not call `./scripts/solver_uv.sh sync {solver_dir.name}`")

    assert not offenders, "Invalid setup.sh for uv sub-project solvers:\n" + "\n".join(offenders)


def test_uv_subproject_demo_uses_solver_uv_run() -> None:
    root = _repo_root()
    offenders: list[str] = []

    for solver_dir in _solver_dirs_with_pyproject(root):
        demo_sh = solver_dir / "demo.sh"
        if not demo_sh.exists():
            offenders.append(f"{solver_dir.name}: missing solvers/{solver_dir.name}/demo.sh")
            continue
        content = _read_text(demo_sh)

        # Require the canonical form: ./scripts/solver_uv.sh run <solver> -- <cmd...>
        pattern = re.compile(
            rf"^\s*\./scripts/solver_uv\.sh\s+run\s+{re.escape(solver_dir.name)}\s+--\s+",
            re.MULTILINE,
        )
        if not pattern.search(content):
            offenders.append(f"{solver_dir.name}: demo.sh does not call `./scripts/solver_uv.sh run {solver_dir.name} -- ...`")

    assert not offenders, "Invalid demo.sh for uv sub-project solvers:\n" + "\n".join(offenders)


def test_uv_subproject_readme_mentions_pyproject() -> None:
    root = _repo_root()
    offenders: list[str] = []

    for solver_dir in _solver_dirs_with_pyproject(root):
        readme_md = solver_dir / "README.md"
        if not readme_md.exists():
            offenders.append(f"{solver_dir.name}: missing solvers/{solver_dir.name}/README.md")
            continue
        content = _read_text(readme_md)
        expected = f"solvers/{solver_dir.name}/pyproject.toml"
        if expected not in content:
            offenders.append(f"{solver_dir.name}: README.md does not mention `{expected}`")

    assert not offenders, "Invalid README.md for uv sub-project solvers:\n" + "\n".join(offenders)
