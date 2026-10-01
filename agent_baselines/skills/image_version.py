"""Pre-flight version check for the Asta image and loaded skills."""

import os
import re
from pathlib import Path

_PLUGIN_VERSION_RE = re.compile(r"PLUGIN_VERSION=([\d.]+)")
# The ``-tex`` image carries the same plugin version as the base image.
_ASTA_IMAGE_VERSION_RE = re.compile(r":v(\d+(?:\.\d+)*)(?:-tex)?\Z")


def _check_plugin_image_version_match(skill_dirs: list[Path]) -> None:
    """Raise if a versioned ``ASTA_IMAGE`` differs from skill ``PLUGIN_VERSION``.

    Skip when no skills or version are available, or the image tag is not a
    release tag (``:vX.Y.Z`` or ``:vX.Y.Z-tex``).
    """
    if not skill_dirs:
        return
    image = os.environ.get("ASTA_IMAGE", "")
    m = _ASTA_IMAGE_VERSION_RE.search(image)
    if not m:
        return
    image_version = m.group(1)

    plugin_versions: set[str] = set()
    for skill_dir in skill_dirs:
        skill_md = Path(skill_dir) / "SKILL.md"
        try:
            text = skill_md.read_text()
        except Exception:
            continue
        if match := _PLUGIN_VERSION_RE.search(text):
            plugin_versions.add(match.group(1))

    if len(plugin_versions) != 1:
        return
    plugin_version = plugin_versions.pop()
    if plugin_version != image_version:
        raise ValueError(
            f"asta image version (v{image_version}) doesn't match skill "
            f"PLUGIN_VERSION ({plugin_version}); the skills' bash snippets "
            f"would bail to a slow self-upgrade inside the sandbox. "
            f"Pin matching versions (e.g. `ASTA_IMAGE=ghcr.io/allenai/asta:v{plugin_version}`)."
        )
