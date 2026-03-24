from pathlib import Path

from agent_baselines.solvers.sqa.sqa import (
    REQUIRED_SQA_ENV_VARS,
    missing_required_env_vars,
)


def test_missing_required_env_vars_loads_repo_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "MODAL_TOKEN=test-modal-token",
                "MODAL_TOKEN_SECRET='test-modal-secret'",
                'ASTA_TOOL_KEY="test-asta-key"',
            ]
        )
    )

    for key in REQUIRED_SQA_ENV_VARS:
        monkeypatch.delenv(key, raising=False)

    missing = missing_required_env_vars(env_path)

    assert missing == []
    assert Path(env_path).exists()


def test_missing_required_env_vars_reports_unset_keys(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("MODAL_TOKEN=present\n")

    for key in REQUIRED_SQA_ENV_VARS:
        monkeypatch.delenv(key, raising=False)

    missing = missing_required_env_vars(env_path)

    assert missing == ["MODAL_TOKEN_SECRET", "ASTA_TOOL_KEY"]
