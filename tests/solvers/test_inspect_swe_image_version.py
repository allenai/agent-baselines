import pytest

from agent_baselines.solvers.inspect_swe.agent import (
    _check_plugin_image_version_match,
)


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "SKILL.md").write_text("PLUGIN_VERSION=0.105.0\n")
    return tmp_path


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/allenai/asta:v0.104.1",
        "ghcr.io/allenai/asta:v0.104.1-tex",
    ],
)
def test_mismatched_tag_raises(monkeypatch, skill_dir, image):
    monkeypatch.setenv("ASTA_IMAGE", image)
    with pytest.raises(ValueError, match=r"v0\.104\.1"):
        _check_plugin_image_version_match([skill_dir])


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/allenai/asta:v0.105.0",
        "ghcr.io/allenai/asta:v0.105.0-tex",
        "ghcr.io/allenai/asta:latest",
        "ghcr.io/allenai/asta:latest-tex",
        "ghcr.io/allenai/asta@sha256:" + "0" * 64,
    ],
)
def test_matching_or_unversioned_tag_passes(monkeypatch, skill_dir, image):
    monkeypatch.setenv("ASTA_IMAGE", image)
    _check_plugin_image_version_match([skill_dir])
