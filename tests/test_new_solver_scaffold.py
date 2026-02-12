import os
import subprocess
from pathlib import Path


def _script_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "scripts" / "new_solver.sh"


def _make_repo_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "solvers").mkdir()
    (root / "agent_baselines" / "solvers").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "tmp"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )


def _run_new_solver(
    *, cwd: Path, name: str
) -> subprocess.CompletedProcess[str]:  # pragma: no cover
    return subprocess.run(
        ["bash", str(_script_path()), name],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def test_scaffold_creates_expected_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    result = _run_new_solver(cwd=root, name="foo_bar")

    assert result.returncode == 0, result.stderr

    solver_dir = root / "solvers" / "foo_bar"
    code_dir = root / "agent_baselines" / "solvers" / "foo_bar"

    assert (solver_dir / "README.md").exists()
    assert (solver_dir / "demo.sh").exists()
    assert (solver_dir / "env").exists()
    assert (solver_dir / "pyproject.toml").exists()
    assert (solver_dir / "setup.sh").exists()

    assert (code_dir / "__init__.py").exists()
    assert (code_dir / "solver.py").exists()

    pyproject = (solver_dir / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "agent-baselines-foo-bar"' in pyproject
    assert '"astabench==0.3.1"' in pyproject
    assert '"inspect_ai==0.3.114"' in pyproject

    setup_sh = (solver_dir / "setup.sh").read_text(encoding="utf-8")
    assert 'uv sync --project "solvers/foo_bar" --python 3.11' in setup_sh

    demo_sh = (solver_dir / "demo.sh").read_text(encoding="utf-8")
    assert (
        'uv run --project "solvers/foo_bar" --python 3.11 --frozen -- inspect eval'
        in demo_sh
    )
    assert "--model mockllm/model" in demo_sh
    assert "--solver agent_baselines/solvers/foo_bar/solver.py@demo_solver" in demo_sh

    assert (solver_dir / "env").read_text(encoding="utf-8") == "ASTA_TOOL_KEY\n"

    solver_stub = (code_dir / "solver.py").read_text(encoding="utf-8")
    assert "def demo_solver" in solver_stub
    assert "llm_with_prompt" in solver_stub

    assert os.access(solver_dir / "setup.sh", os.X_OK)
    assert os.access(solver_dir / "demo.sh", os.X_OK)


def test_scaffold_hyphenated_name(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    result = _run_new_solver(cwd=root, name="asta-v0")
    assert result.returncode == 0, result.stderr

    solver_dir = root / "solvers" / "asta-v0"
    code_dir = root / "agent_baselines" / "solvers" / "asta-v0"

    assert (solver_dir / "pyproject.toml").exists()
    assert (code_dir / "solver.py").exists()
    assert 'name = "agent-baselines-asta-v0"' in (
        solver_dir / "pyproject.toml"
    ).read_text(encoding="utf-8")

    setup_sh = (solver_dir / "setup.sh").read_text(encoding="utf-8")
    assert 'uv sync --project "solvers/asta-v0" --python 3.11' in setup_sh

    demo_sh = (solver_dir / "demo.sh").read_text(encoding="utf-8")
    assert (
        'uv run --project "solvers/asta-v0" --python 3.11 --frozen -- inspect eval'
        in demo_sh
    )
    assert "agent_baselines/solvers/asta-v0/solver.py@demo_solver" in demo_sh


def test_scaffold_requires_repo_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    subdir = root / "solvers" / "nested"
    subdir.mkdir(parents=True)

    result = _run_new_solver(cwd=subdir, name="bar")
    assert result.returncode == 2
    assert "must run from repo root" in result.stderr
    assert not (root / "solvers" / "bar").exists()


def test_scaffold_outside_repo_errors(tmp_path: Path) -> None:
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()

    result = _run_new_solver(cwd=nowhere, name="foo")
    assert result.returncode == 2
    assert "must run from repo root" in result.stderr


def test_invalid_solver_name_errors(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    result = _run_new_solver(cwd=root, name="Foo")

    assert result.returncode == 2
    assert "invalid solver name" in result.stderr
    assert not (root / "solvers" / "Foo").exists()


def test_existing_solver_dir_errors(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    (root / "solvers" / "foo").mkdir(parents=True)
    result = _run_new_solver(cwd=root, name="foo")

    assert result.returncode == 2
    assert "already exists" in result.stderr


def test_existing_code_dir_errors(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _make_repo_root(root)

    (root / "agent_baselines" / "solvers" / "foo").mkdir(parents=True)
    result = _run_new_solver(cwd=root, name="foo")

    assert result.returncode == 2
    assert "already exists" in result.stderr
