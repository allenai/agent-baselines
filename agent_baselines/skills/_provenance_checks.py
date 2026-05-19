"""Detect ways the resolver's lock could lie about reproducibility.

In the pinned case (clean checkout at a committed SHA, no ``.image-id``
stamp, no gitignored installer payload), every detector here returns
no-op output and ``detect_provenance_gaps`` returns an all-defaults
``ProvenanceGaps``. The whole module is inert.

The detectors earn their keep when inputs aren't pinned: post-setup
edits to a vendor tree invalidate the image stamp, gitignored payloads
make ``git checkout <sha>`` lossy, working-tree edits/deletions/
untracked-additions diverge installed bytes from HEAD. Without these
checks the lock would silently advertise reproducibility primitives
(``sha``, ``image_id``) that ``git checkout`` or rerunning ``setup.sh``
wouldn't restore — ``strict_reproducibility=true`` would pass on
locks that aren't actually strict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from agent_baselines.skills._internals import _is_installed_skill_file, _run_git

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProvenanceGaps:
    """Edge-case state for a resolved path.

    In the pinned case all fields are no-op defaults: ``effective_included``
    equals the input ``included``, ``path_dirty`` is False, ``image_id``
    is None (no stamp present).
    """

    # ``included`` (the git-tracked file set) folded with any gitignored
    # installer-relevant files. The caller hashes against this so two
    # different ignored payloads produce different ``content_sha256``.
    effective_included: frozenset[Path] | None
    # Whether to stamp ``git["path_dirty"]=True`` in the lock. True when:
    # working-tree porcelain touches an installer-relevant file, or
    # reproducibility is at risk from gitignored payload / stale image
    # stamp (so ``git checkout <sha>`` wouldn't restore the install bytes).
    path_dirty: bool
    # Validated ``.image-id`` stamp (present AND no post-setup edits).
    # None if the stamp is absent or has been invalidated by edits.
    image_id: str | None


def detect_provenance_gaps(
    root: Path,
    dirs: list[Path],
    included: frozenset[Path] | None,
    *,
    repo_root: Path | None,
    entirely_ignored: bool,
) -> ProvenanceGaps:
    """Discover provenance gaps for ``root``.

    ``repo_root`` is None when ``root`` isn't inside a git working tree —
    skips porcelain detection in that case (no SHA to compare against).
    ``entirely_ignored`` is True when ``root`` is inside a working tree
    but every file under it is gitignored; force-dirty applies in that
    case unless an ``.image-id`` stamp provides alternative provenance.
    """
    effective_included = included
    has_ignored = False
    if included is not None:
        ignored = _gitignored_files_under(root, dirs)
        if ignored:
            effective_included = included | ignored
            has_ignored = True

    image_id, stamp_dir = _find_image_stamp(root)
    image_valid = bool(image_id and stamp_dir and not _image_stamp_stale(stamp_dir))
    if image_id and not image_valid:
        logger.warning(
            "skills: %s has files modified after .image-id stamp; "
            "image provenance invalidated. Rerun setup.sh against the "
            "stamped image or commit the changes for reproducibility.",
            root,
        )

    porcelain_dirty = False
    if repo_root is not None:
        # ``--untracked-files=all`` overrides any user config that hides
        # untracked files (e.g. ``status.showUntrackedFiles=no``). Otherwise
        # the porcelain check would call the path clean while the tracked
        # set still includes the untracked files in the hash — strict mode
        # would accept a lock whose SHA can't restore the actual tree.
        porcelain = _run_git(
            root, "status", "--porcelain", "--untracked-files=all", "--", str(root)
        )
        # Union working-tree skill dirs with HEAD-side skill dirs so
        # deletions of subtrees that have vanished from the working
        # tree still mark the lock dirty.
        dirs_for_porcelain = sorted(set(dirs) | _head_skill_dirs(root, repo_root))
        porcelain_dirty = _porcelain_touches_installed(
            porcelain, repo_root, dirs_for_porcelain
        )

    # Force dirty when reproducibility primitives don't cover all the
    # installed bytes: ``git checkout <sha>`` won't restore gitignored
    # payload, and a stale ``.image-id`` doesn't match what setup.sh
    # would produce. Image-validated bytes still need a clean git tree
    # check, hence ``porcelain_dirty`` is OR-ed in regardless.
    force_dirty = (entirely_ignored or has_ignored) and not image_valid

    return ProvenanceGaps(
        effective_included=effective_included,
        path_dirty=porcelain_dirty or force_dirty,
        image_id=image_id if image_valid else None,
    )


def _porcelain_touches_installed(
    porcelain: str | None, repo_root: Path, dirs: list[Path]
) -> bool:
    """Whether ``git status --porcelain`` reports any line affecting an
    installer-relevant file under one of the resolved skill dirs.
    Drops lines about files inspect's installer wouldn't copy
    (top-level scratch, hidden files, ``__pycache__/``, etc.) so an
    untracked ``alpha/notes.md`` doesn't false-positive ``path_dirty``
    when the agent would never receive it.
    """
    if not porcelain:
        return False
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        rest = line[3:]
        # Rename lines are ``XY oldpath -> newpath``; we care about the
        # new path (and check the old path too, since either being dirty
        # is a real edit).
        candidates = [rest] if " -> " not in rest else rest.split(" -> ", 1)
        for raw in candidates:
            raw = raw.strip().strip('"')
            if not raw:
                continue
            abs_path = (repo_root / raw).resolve()
            for d in dirs:
                if _is_installed_skill_file(d, abs_path):
                    return True
    return False


def _head_skill_dirs(path: Path, repo_root: Path) -> set[Path]:
    """Resolved parent dirs of SKILL.md files committed in HEAD under
    ``path``. Used to catch porcelain deletions of skill subtrees that
    have already vanished from the working tree (and so don't appear in
    the working-tree skill-dirs list).
    """
    stdout = _run_git(
        repo_root, "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", str(path)
    )
    if stdout is None:
        return set()
    repo_root_resolved = repo_root.resolve()
    out: set[Path] = set()
    for rel in stdout.split("\0"):
        if not rel:
            continue
        if Path(rel).name == "SKILL.md":
            out.add((repo_root_resolved / rel).parent.resolve())
    return out


def _find_image_stamp(root: Path) -> tuple[str | None, Path | None]:
    """Walk up from ``root`` looking for a ``.image-id`` stamp file.

    ``solvers/inspect-swe/setup.sh`` writes this stamp into
    ``.vendor/asta-plugins/`` after extracting skills from the asta
    image. Its presence means the host-side bytes have an alternative
    provenance — the asta image identified by ``image_id`` — that
    doesn't require git tracking to reproduce: a reviewer reruns
    ``setup.sh`` against the same ``ASTA_IMAGE`` and gets the same
    bytes. Strict mode accepts ``image_id`` as a substitute for the
    clean-git-block guarantee.

    Returns ``(image_id, stamp_dir)`` when found, ``(None, None)``
    otherwise. ``stamp_dir`` is the directory holding ``.image-id`` so
    callers can check whether files under it have been modified since
    the stamp was written. Walks all the way to the filesystem root so
    callers pointing at a sub-tree of the vendor dir
    (``plugins/asta/skills``) still find the stamp at the vendor root.
    """
    for parent in (root, *root.parents):
        stamp = parent / ".image-id"
        if stamp.is_file():
            try:
                content = stamp.read_text().strip()
                return (content or None, parent)
            except OSError:
                return (None, None)
    return (None, None)


def _image_stamp_stale(stamp_dir: Path) -> bool:
    """Whether the stamped vendor tree has been modified after the
    ``.image-id`` stamp was written.

    ``setup.sh`` runs ``docker run ... tar -c | tar -x`` and then writes
    ``.image-id``, so on a fresh extraction the stamp's mtime is the
    latest in the tree. Any tree entry with a later mtime is a post-setup
    change that re-running setup against the stamped image wouldn't
    reproduce — image_id no longer constitutes valid provenance.

    Checks both files *and* directories (and ``stamp_dir`` itself): a
    file deletion bumps only the parent directory's mtime, so a
    files-only walk would miss it.
    """
    stamp = stamp_dir / ".image-id"
    try:
        stamp_mtime = stamp.stat().st_mtime
    except OSError:
        return False
    for p in (stamp_dir, *stamp_dir.rglob("*")):
        if p == stamp:
            continue
        try:
            if p.stat().st_mtime > stamp_mtime:
                return True
        except OSError:
            continue
    return False


def _gitignored_files_under(root: Path, dirs: list[Path]) -> frozenset[Path]:
    """Absolute paths of installer-relevant files under any of ``dirs``
    that git ignores.

    Inspect's skill installer copies SKILL.md + non-hidden files under
    ``scripts/`` / ``references/`` / ``assets/`` — an ignored
    ``scripts/helper.py`` will affect the agent's behavior even though
    the tracked-file set excludes it. The caller folds these into the
    ``included`` set before hashing (so two different ignored payloads
    produce different ``content_sha256``) and marks the git block dirty
    (``git checkout <sha>`` won't restore them).

    Ignored files that the installer *wouldn't* copy (top-level
    ``notes.md``, hidden files like ``.DS_Store``, etc.) are filtered
    out — they don't affect what the agent runs, so they shouldn't
    affect the lock either.
    """
    if not dirs:
        return frozenset()
    stdout = _run_git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        *(str(d) for d in dirs),
    )
    if stdout is None:
        return frozenset()
    root_resolved = root.resolve()
    paths: set[Path] = set()
    for r in stdout.split("\0"):
        if not r:
            continue
        abs_path = (root_resolved / r).resolve()
        for d in dirs:
            if _is_installed_skill_file(d, abs_path):
                paths.add(abs_path)
                break
    return frozenset(paths)
