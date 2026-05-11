"""Resolve local skill directories with provenance.

Each ``refs`` entry is a path (absolute or relative) to a directory
containing SKILL.md trees. The resolver lists those skill dirs and emits
a lock describing what was resolved (source path, content hash, skill
names, git state, image stamp) for inclusion in the eval log via
``state.metadata["skills"]``.

The pinned-case happy path through this file is:

    resolve_skills
      → _resolve_path
          → _list_skill_dirs   (find SKILL.md trees)
          → _git_state         (origin, sha, path_in_repo)
          → detect_provenance_gaps  (no-op in pinned case)
          → _content_hash      (fingerprint installer payload)
      → dedup skill names, assemble lock

Edge-case machinery (image-stamp staleness, gitignored payload folding,
working-tree porcelain dirty detection, HEAD-side deletion detection)
lives in ``_provenance_checks`` — inert when inputs are pinned, but
required to keep the lock truthful and ``strict_reproducibility`` real
when they aren't.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent_baselines.skills._internals import _is_installed_skill_file, _run_git
from agent_baselines.skills._provenance_checks import detect_provenance_gaps

logger = logging.getLogger(__name__)

# VCS metadata dirs are excluded from content_sha256 and skill discovery —
# their internals change across clones / GC / packs even when skill content
# is identical, which would make the lock's reproducibility hash unstable.
_VCS_DIR_NAMES = frozenset({".git", ".hg", ".svn"})


def _in_vcs_dir(rel: Path) -> bool:
    return any(part in _VCS_DIR_NAMES for part in rel.parts)


# Strip any ``userinfo@`` from HTTP-family remotes — for these schemes,
# even a passwordless ``user@`` can be a PAT (e.g. Azure DevOps
# ``https://<pat>@dev.azure.com/o/r.git``), so distinguishing
# "identity" from "credential" by colon presence isn't safe.
_HTTP_USERINFO_RE = re.compile(
    r"^((?:[a-zA-Z][a-zA-Z0-9.\-]*\+)?https?://)[^/@\s]+@",
    re.IGNORECASE,
)
# Strip ``user:password@`` (password form) from any other URL scheme.
# Preserves passwordless ``user@`` because SSH-style remotes
# (``ssh://git@github.com/...``) need the username to clone.
_REMOTE_PASSWORD_USERINFO_RE = re.compile(
    r"^([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/@\s]*:[^/@\s]*@"
)


def _sanitize_remote_url(url: str) -> str:
    """Strip embedded passwords/tokens from a remote URL before stamping
    it into the eval log. CI environments commonly use credentialed
    remotes like ``https://x-access-token:<TOKEN>@github.com/org/repo.git``,
    ``https://<token>@dev.azure.com/o/r.git``, or
    ``ssh://user:secret@host/org/repo.git``; persisting those in
    ``state.metadata["skills"]`` would leak the credential to anyone
    with log access.

    Strip rules:

    - HTTP-family schemes (``http``, ``https``, ``git+http``,
      ``git+https``): any ``userinfo@`` is stripped, since even
      passwordless ``user@`` is typically a token here.
    - Other URL schemes (``ssh``, ``git``, ...): only the
      ``user:password@`` form is stripped. Passwordless ``user@`` is
      preserved — required for SSH-style remotes like
      ``ssh://git@github.com/...`` to remain cloneable.
    - SCP-like ``git@host:path``: no ``://``, so neither regex matches;
      preserved verbatim (no password component)."""
    return _REMOTE_PASSWORD_USERINFO_RE.sub(r"\1", _HTTP_USERINFO_RE.sub(r"\1", url))


@dataclass
class ResolvedSkills:
    skill_dirs: list[Path] = field(default_factory=list)
    lock: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class _GitCoreState:
    """Pinned-case git facts: SHA, origin, path-relative-to-repo-root.
    Excludes ``path_dirty`` — that's computed by ``detect_provenance_gaps``
    so the dirty-detection machinery lives next to the other gap
    detectors rather than inline with the core sha/origin lookups."""

    origin: str | None
    sha: str
    path_in_repo: str
    repo_root: Path


def _git_listed_files(root: Path) -> frozenset[Path] | None:
    """Absolute paths of files under ``root`` that git tracks or considers
    untracked-but-not-ignored. Returns None if ``root`` isn't in a git
    working tree (caller falls back to walking everything except VCS dirs).

    Used to keep gitignored noise (`.DS_Store`, `__pycache__/`, editor
    backups) out of the content hash and skill discovery — those won't be
    restored by ``git checkout <sha>`` and would otherwise make the lock
    machine-dependent and un-reproducible.
    """
    stdout = _run_git(
        root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."
    )
    if stdout is None:
        return None
    root_resolved = root.resolve()
    return frozenset((root_resolved / r).resolve() for r in stdout.split("\0") if r)


def _content_hash(
    root: Path,
    dirs: list[Path],
    included: frozenset[Path] | None = None,
) -> str:
    """SHA-256 over the installer-relevant files under each skill dir in
    ``dirs``: SKILL.md plus non-hidden/non-underscore files under
    ``scripts/`` / ``references/`` / ``assets/`` (matching inspect_ai's
    own install behavior at ``inspect_ai/tool/_tools/_skill/read.py``).

    Files outside any skill dir, and files inside a skill dir that
    inspect's installer wouldn't copy (top-level ``notes.md``,
    ``.DS_Store``, ``scripts/__pycache__/``, …), are excluded —
    they don't affect what the agent receives, so they mustn't affect
    the lock's fingerprint either.

    When ``included`` is set (root is in a git working tree), tracked-
    or-explicitly-folded-in files only; otherwise everything that
    matches the install predicate.

    Paths are recorded as ``<skill-name>/<path-within-skill>`` so the
    hash depends only on the installed payload — not on which ancestor
    the caller happened to pass. Two refs pointing at the same skill
    (one at the skill dir itself, one at a parent) produce identical
    hashes for identical bytes.
    """
    h = hashlib.sha256()
    entries: list[tuple[Path, str]] = []
    for d in dirs:
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if _in_vcs_dir(p.relative_to(d)):
                continue
            if not _is_installed_skill_file(d, p):
                continue
            if included is not None and p.resolve() not in included:
                continue
            rel = f"{d.name}/{p.relative_to(d).as_posix()}"
            entries.append((p, rel))
    for p, rel in sorted(entries, key=lambda e: e[1]):
        h.update(rel.encode() + b"\0")
        file_h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                file_h.update(chunk)
        h.update(file_h.hexdigest().encode() + b"\n")
    return h.hexdigest()


def _list_skill_dirs(root: Path, included: frozenset[Path] | None = None) -> list[Path]:
    return sorted(
        {
            p.parent
            for p in root.rglob("SKILL.md")
            if not _in_vcs_dir(p.relative_to(root))
            and (included is None or p.resolve() in included)
        }
    )


def _git_state(path: Path) -> _GitCoreState | None:
    """If ``path`` is inside a git working tree, return its core git
    state — origin (sanitized), HEAD sha, path-relative-to-repo-root,
    and the resolved repo root.

    ``path_dirty`` is computed separately by ``detect_provenance_gaps``
    so the dirty-detection logic lives next to the other gap detectors
    (image-stamp staleness, gitignored payload, HEAD-side deletions).
    Returns None if ``path`` isn't a git working tree, or git is
    unavailable.
    """
    sha = _run_git(path, "rev-parse", "HEAD")
    if sha is None:
        return None
    # ``check=False``: a repo without an ``origin`` remote returns non-zero
    # here; we record the absent origin rather than treat the whole path
    # as non-git.
    origin_raw = (
        _run_git(path, "remote", "get-url", "origin", check=False) or ""
    ).strip()
    origin = _sanitize_remote_url(origin_raw) if origin_raw else None
    repo_root = _run_git(path, "rev-parse", "--show-toplevel")
    if repo_root is None:
        return None
    repo_root_path = Path(repo_root.strip()).resolve()
    path_in_repo = str(Path(path).resolve().relative_to(repo_root_path))
    if path_in_repo == ".":
        path_in_repo = ""
    return _GitCoreState(
        origin=origin,
        sha=sha.strip(),
        path_in_repo=path_in_repo,
        repo_root=repo_root_path,
    )


def _resolve_path(ref: str) -> tuple[list[Path], dict]:
    root = Path(ref).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    included = _git_listed_files(root)
    entirely_ignored = included is not None and not included
    if entirely_ignored:
        # Root is inside a git working tree but entirely git-ignored
        # (e.g. caller pointed at a ``build/`` output dir). Treat as
        # outside-git so the explicitly-referenced skills still
        # discover and hash — the alternative is silently dropping
        # every SKILL.md because no file is in the tracked set.
        logger.warning(
            "skills: %s is inside a git working tree but entirely git-ignored; "
            "including all files. content_sha256 won't be portable across "
            "clones — commit the skills directory for reproducibility.",
            root,
        )
        included = None

    dirs = _list_skill_dirs(root, included)
    if not dirs:
        # Caller explicitly pointed at a path; finding zero SKILL.md
        # under it is almost certainly a typo or a wrong path. Silently
        # running with an empty skill set would mask the bug — the eval
        # would proceed without the skills the operator believed were
        # loaded.
        raise FileNotFoundError(
            f"skills: {root} contains no SKILL.md files. Check the path "
            f"and that SKILL.md trees live directly under it."
        )

    git_core = _git_state(root)
    gaps = detect_provenance_gaps(
        root,
        dirs,
        included,
        repo_root=git_core.repo_root if git_core else None,
        entirely_ignored=entirely_ignored,
    )

    git_lock: dict | None = None
    if git_core is not None:
        git_lock = {
            "origin": git_core.origin,
            "sha": git_core.sha,
            "path_in_repo": git_core.path_in_repo,
            "path_dirty": gaps.path_dirty,
        }
        if gaps.path_dirty:
            logger.warning(
                "skills: %s has uncommitted changes (sha=%s); commit for "
                "forward reproducibility",
                root,
                git_core.sha[:7],
            )

    entry: dict = {
        "source": str(root),
        "content_sha256": _content_hash(root, dirs, gaps.effective_included),
        "skills": [d.name for d in dirs],
        **({"image_id": gaps.image_id} if gaps.image_id else {}),
        **({"git": git_lock} if git_lock else {}),
    }
    return dirs, entry


def resolve_skills(refs: list[str]) -> ResolvedSkills:
    """Resolve refs to local SKILL.md directories + per-ref lock entries.

    Raises:
        ValueError: if the same skill name appears more than once across
            all resolved refs — whether two refs each contain a
            ``semantic-scholar`` skill or a single ref points at a parent
            with two ``semantic-scholar`` subtrees (e.g. ``asta/skills/``
            + ``asta-preview/skills/``). inspect_swe's ``install_skills``
            keys by skill name, so duplicates silently overwrite each
            other while the lock claims both shipped.
    """
    if not refs:
        return ResolvedSkills()

    results = [_resolve_path(r) for r in refs]

    skill_dirs: list[Path] = []
    lock: list[dict] = []
    seen: dict[str, Path] = {}
    for dirs, entry in results:
        for d in dirs:
            prior = seen.get(d.name)
            if prior is not None:
                raise ValueError(
                    f"skill {d.name!r} resolved from two locations: "
                    f"{prior} and {d}; namespacing not yet supported. "
                    f"Point ``skills=`` at the specific skill-tree root "
                    f"(e.g. ``plugins/asta/skills``) rather than a parent."
                )
            seen[d.name] = d
        skill_dirs.extend(dirs)
        lock.append(entry)
    return ResolvedSkills(skill_dirs=skill_dirs, lock=lock)
