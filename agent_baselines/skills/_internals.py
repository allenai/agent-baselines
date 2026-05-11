"""Internal utilities shared between ``resolver`` and
``_provenance_checks``.

Pulled out so the public ``resolver`` module can import from the
provenance-check module without creating an import cycle. Nothing
here is part of the package's public surface."""

from __future__ import annotations

import subprocess
from pathlib import Path

_GIT_TIMEOUT_SEC = 5


def _run_git(root: Path, *args: str, check: bool = True) -> str | None:
    """Run ``git -C <root> <args>`` and return stdout. Returns ``None`` on
    handled failure (missing git, timeout, non-zero exit when ``check``).
    Pass ``check=False`` when empty stdout on non-zero exit is meaningful
    (e.g. no origin remote configured)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=check,
            timeout=_GIT_TIMEOUT_SEC,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return None
    return result.stdout


# Subdirs of a skill dir whose (non-hidden) files inspect_swe's installer
# copies into the sandbox. Anything else under a skill dir (top-level
# ``notes.md``, hidden files, etc.) isn't installed, so it shouldn't
# affect the lock's fingerprint of what the agent ran.
_INSTALLED_SUBDIRS = frozenset({"scripts", "references", "assets"})


def _is_installed_skill_file(skill_dir: Path, path: Path) -> bool:
    """Whether inspect_ai's skill installer would copy ``path`` from
    ``skill_dir`` into the sandbox. Mirrors inspect's behavior at
    ``inspect_ai/tool/_tools/_skill/read.py``: SKILL.md plus files under
    ``scripts/`` / ``references/`` / ``assets/`` whose path parts don't
    start with ``.`` or ``_``. Skipping both prefixes matches inspect's
    own ``part.startswith((".", "_"))`` check — otherwise local-only
    cache files like ``scripts/__pycache__/foo.cpython-312.pyc`` would
    spuriously affect the lock and trip ``strict_reproducibility`` even
    though the agent never receives them.
    """
    try:
        rel = path.relative_to(skill_dir)
    except ValueError:
        return False
    parts = rel.parts
    if any(part.startswith((".", "_")) for part in parts):
        return False
    if parts == ("SKILL.md",):
        return True
    return len(parts) >= 2 and parts[0] in _INSTALLED_SUBDIRS
