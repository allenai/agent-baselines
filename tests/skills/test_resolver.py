"""Tests for the skills resolver."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_baselines.skills.resolver import (
    ResolvedSkills,
    _content_hash,
    _list_skill_dirs,
    _sanitize_remote_url,
    resolve_skills,
)


def _git_configure_test_repo(repo: Path) -> None:
    """Set the minimum config needed for ``git commit`` to succeed in a
    fresh test repo, including disabling commit signing so the test doesn't
    depend on the user's global signing setup."""
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@example.com:o/r.git"],
        check=True,
    )


def _git_init_with_skill(parent: Path, name: str = "alpha") -> Path:
    """Create a git repo at ``parent`` with one committed skill."""
    subprocess.run(["git", "init", "-q", str(parent)], check=True)
    _git_configure_test_repo(parent)
    _make_skill(parent, name)
    subprocess.run(["git", "-C", str(parent), "add", "."], check=True)
    subprocess.run(["git", "-C", str(parent), "commit", "-q", "-m", "init"], check=True)
    return parent


def _make_skill(parent: Path, name: str, body: str = "") -> Path:
    d = parent / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\n---\n\n# {name}\n\n{body}"
    )
    return d


class TestListSkillDirs:
    def test_finds_nested(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "a")
        _make_skill(tmp_path, "b")
        (tmp_path / "not-a-skill").mkdir()
        dirs = _list_skill_dirs(tmp_path)
        assert sorted(d.name for d in dirs) == ["a", "b"]


class TestContentHash:
    def test_changes_with_file_change(self, tmp_path: Path) -> None:
        skill = _make_skill(tmp_path, "foo", body="original")
        h1 = _content_hash(tmp_path, [skill])
        (tmp_path / "foo" / "SKILL.md").write_text(
            "---\nname: foo\ndescription: test\n---\n\nedited"
        )
        h2 = _content_hash(tmp_path, [skill])
        assert h1 != h2

    def test_stable_across_calls(self, tmp_path: Path) -> None:
        skill = _make_skill(tmp_path, "foo")
        assert _content_hash(tmp_path, [skill]) == _content_hash(tmp_path, [skill])

    def test_stable_across_root_depth(self, tmp_path: Path) -> None:
        """Identical installed bytes must hash identically regardless of
        which ancestor the caller passed as ref. inspect_swe installs
        the skill dir the same way whether the operator passed
        ``-S skills=/x/skills`` or ``-S skills=/x/skills/alpha``, so
        the content_sha256 mustn't depend on the rel-path prefix from
        the ref root."""
        skill = _make_skill(tmp_path, "alpha", body="hello")
        # Ref at the skill dir itself
        h_at_skill = _content_hash(skill, [skill])
        # Ref at the parent of the skill dir
        h_at_parent = _content_hash(tmp_path, [skill])
        assert h_at_skill == h_at_parent

    def test_vcs_metadata_excluded(self, tmp_path: Path) -> None:
        """``.git/`` internals churn across clones/GC even when skill content
        is identical — they must not affect the hash."""
        skill = _make_skill(tmp_path, "foo")
        h_no_git = _content_hash(tmp_path, [skill])
        # Simulate a git checkout under the skill root.
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (tmp_path / ".git" / "objects").mkdir()
        (tmp_path / ".git" / "objects" / "ab1234").write_bytes(b"\x78\x9c\xff")
        assert _content_hash(tmp_path, [skill]) == h_no_git

    def test_gitignored_files_excluded(self, tmp_path: Path) -> None:
        """Files ignored by .gitignore mustn't affect content_sha256 —
        otherwise the lock is machine-dependent (every Mac's .DS_Store,
        every Python repo's __pycache__) and not reproducible from
        ``git checkout <sha>``."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo)
        # Commit a .gitignore as part of the tracked tree.
        (repo / ".gitignore").write_text("noise.txt\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        h_before = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        # Add a file that .gitignore excludes.
        (repo / "noise.txt").write_text("machine-specific")
        h_after = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        assert h_before == h_after

    def test_explicit_ref_to_gitignored_path_marks_dirty(
        self, tmp_path: Path, caplog
    ) -> None:
        """``git status -- <path>`` reports nothing for paths covered by
        ``.gitignore``, so the porcelain check would call them clean —
        but ``git checkout <sha>`` won't restore the skill files.
        Force ``path_dirty: True`` so reviewers don't trust the SHA for
        reproduction and fall back to ``content_sha256``."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, name="tracked-skill")
        (repo / ".gitignore").write_text("build/\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore-build"], check=True
        )
        build_skills = repo / "build" / "skills"
        build_skills.mkdir(parents=True)
        _make_skill(build_skills, "ignored-skill")
        with caplog.at_level("WARNING", logger="agent_baselines.skills.resolver"):
            result = resolve_skills([str(build_skills)])
        assert result.lock[0]["git"]["path_dirty"] is True

    def test_explicit_ref_to_gitignored_path_includes_skills(
        self, tmp_path: Path
    ) -> None:
        """If a caller explicitly points ``-S skills=`` at a directory that
        lives under a git-ignored subtree (e.g. ``build/skills/``), the
        ``git ls-files`` set is empty for everything under root. The
        resolver must still discover and hash the explicitly-referenced
        skills rather than silently running with an empty skill set."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, name="tracked-skill")
        # Mark build/ as git-ignored.
        (repo / ".gitignore").write_text("build/\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore-build"], check=True
        )
        # Put a skill tree inside the ignored subtree.
        build_skills = repo / "build" / "skills"
        build_skills.mkdir(parents=True)
        _make_skill(build_skills, "ignored-skill")
        # Caller explicitly points at build/skills; resolver should pick it up.
        result = resolve_skills([str(build_skills)])
        assert result.lock[0]["skills"] == ["ignored-skill"]
        assert len(result.skill_dirs) == 1
        assert result.skill_dirs[0].name == "ignored-skill"


class TestResolveLocal:
    def test_returns_skill_dirs_and_lock(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "alpha")
        _make_skill(tmp_path, "beta")

        result = resolve_skills([str(tmp_path)])

        assert sorted(d.name for d in result.skill_dirs) == ["alpha", "beta"]
        assert len(result.lock) == 1
        entry = result.lock[0]
        assert entry["source"] == str(tmp_path)
        assert sorted(entry["skills"]) == ["alpha", "beta"]
        assert "content_sha256" in entry

    def test_relative_path_resolves_against_cwd(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _make_skill(tmp_path, "alpha")
        monkeypatch.chdir(tmp_path.parent)
        result = resolve_skills([f"./{tmp_path.name}"])
        assert result.lock[0]["source"] == str(tmp_path)

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            resolve_skills([str(tmp_path / "nonexistent")])

    def test_existing_path_with_no_skill_md_raises(self, tmp_path: Path) -> None:
        """An explicit ref that resolves to zero SKILL.md is almost
        certainly a typo or wrong path. Silently running with no skills
        would mask the bug — the eval would proceed without the skills
        the operator believed were loaded."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        (empty_dir / "README.md").write_text("not a skill\n")
        with pytest.raises(FileNotFoundError, match="no SKILL.md"):
            resolve_skills([str(empty_dir)])

    def test_empty_refs_empty_result(self) -> None:
        assert resolve_skills([]) == ResolvedSkills()


class TestGitStateInLock:
    def test_not_a_git_tree_omits_git_block(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "alpha")
        result = resolve_skills([str(tmp_path)])
        assert "git" not in result.lock[0]

    def test_clean_git_tree_stamps_origin_sha(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo)
        result = resolve_skills([str(repo)])
        git = result.lock[0]["git"]
        assert git["origin"] == "git@example.com:o/r.git"
        assert len(git["sha"]) == 40
        assert git["path_dirty"] is False

    def test_path_in_repo_for_subdir(self, tmp_path: Path) -> None:
        """When skills live in a subdir of the repo, the lock records the
        path relative to the repo root so reviewers can reproduce with
        `git clone && git checkout <sha> && harness ... <clone>/<path_in_repo>`.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        _git_configure_test_repo(repo)
        skills_dir = repo / "plugins" / "asta" / "skills"
        skills_dir.mkdir(parents=True)
        _make_skill(skills_dir, "alpha")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True
        )
        result = resolve_skills([str(skills_dir)])
        assert result.lock[0]["git"]["path_in_repo"] == "plugins/asta/skills"

    def test_path_in_repo_empty_when_at_root(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo)
        result = resolve_skills([str(repo)])
        # Repo root has no subpath; empty string keeps it semantically clear
        assert result.lock[0]["git"]["path_in_repo"] == ""

    def test_uncommitted_edit_marks_path_dirty_and_warns(
        self, tmp_path: Path, caplog
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo)
        # Tweak the SKILL.md without committing
        (repo / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: edited\n---\n\nchanged"
        )
        with caplog.at_level("WARNING", logger="agent_baselines.skills.resolver"):
            result = resolve_skills([str(repo)])
        assert result.lock[0]["git"]["path_dirty"] is True
        assert any("uncommitted" in r.getMessage() for r in caplog.records)

    def test_untracked_file_marks_path_dirty(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo)
        _make_skill(repo, "beta")  # untracked
        result = resolve_skills([str(repo)])
        assert result.lock[0]["git"]["path_dirty"] is True

    def test_non_installed_tracked_file_no_dirty_no_hash(self, tmp_path: Path) -> None:
        """Inspect's installer copies SKILL.md plus files under
        ``scripts/``/``references/``/``assets/`` (non-hidden,
        non-underscore). Anything else under a skill dir
        (top-level scratch ``notes.md``, hidden files, ``__pycache__/``)
        is *not* installed and therefore mustn't perturb the lock —
        neither ``content_sha256`` nor ``path_dirty`` should flip for
        edits to those files."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, "alpha")
        h_clean = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        # Add and commit a tracked-but-non-installed file under the skill.
        (repo / "alpha" / "notes.md").write_text("scratch v1\n")
        subprocess.run(["git", "-C", str(repo), "add", "alpha/notes.md"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "notes"], check=True
        )
        result_committed = resolve_skills([str(repo)])
        assert (
            result_committed.lock[0]["content_sha256"] == h_clean
        ), "tracked non-installed file mustn't affect content_sha256"
        # Edit the non-installed file uncommitted.
        (repo / "alpha" / "notes.md").write_text("scratch v2\n")
        result_dirty_edit = resolve_skills([str(repo)])
        assert result_dirty_edit.lock[0]["content_sha256"] == h_clean
        assert (
            result_dirty_edit.lock[0]["git"]["path_dirty"] is False
        ), "edits to non-installed files mustn't flip path_dirty"

    def test_untracked_file_detected_under_showuntracked_no(
        self, tmp_path: Path
    ) -> None:
        """``git config status.showUntrackedFiles=no`` would hide
        untracked files from the default porcelain check; the resolver
        must override that, else the lock would call the path clean
        while the hash already includes the untracked content (which
        ``git checkout <sha>`` can't restore)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo)
        subprocess.run(
            ["git", "-C", str(repo), "config", "status.showUntrackedFiles", "no"],
            check=True,
        )
        _make_skill(repo, "beta")  # untracked
        result = resolve_skills([str(repo)])
        assert result.lock[0]["git"]["path_dirty"] is True

    def test_gitignored_files_under_skill_dir_mark_dirty(self, tmp_path: Path) -> None:
        """A tracked skill with gitignored content (scripts/, assets/, etc.)
        still gets its full tree copied into the sandbox by inspect's
        installer — but the hash and porcelain check both drop the
        ignored files. Strict mode would otherwise accept a clean SHA
        that can't reproduce the install payload."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, "alpha")
        # Commit a .gitignore that excludes scripts/ under skill dirs.
        (repo / ".gitignore").write_text("alpha/scripts/\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        # Drop an ignored file under the skill dir. Inspect would copy
        # it; the lock must flag the path dirty.
        (repo / "alpha" / "scripts").mkdir()
        (repo / "alpha" / "scripts" / "helper.py").write_text("# local-only\n")
        result = resolve_skills([str(repo)])
        assert result.lock[0]["git"]["path_dirty"] is True

    def test_gitignored_top_level_file_under_skill_dir_no_effect(
        self, tmp_path: Path
    ) -> None:
        """Inspect's installer copies SKILL.md plus non-hidden files
        under scripts/, references/, assets/. Other files (top-level
        ``notes.md``, hidden ``.DS_Store``, scratch text) aren't
        installed, so they mustn't affect the lock — otherwise
        ``strict_reproducibility`` would fail on a payload the agent
        wouldn't actually receive."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, "alpha")
        (repo / ".gitignore").write_text(
            "alpha/notes.md\nalpha/.DS_Store\nalpha/scratch.txt\n"
        )
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        h_clean = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        # Drop ignored files at the skill root + as a hidden file —
        # inspect would NOT install any of these.
        (repo / "alpha" / "notes.md").write_text("local scratchpad\n")
        (repo / "alpha" / ".DS_Store").write_bytes(b"\x00" * 16)
        (repo / "alpha" / "scratch.txt").write_text("xyz\n")
        result = resolve_skills([str(repo)])
        assert (
            result.lock[0]["content_sha256"] == h_clean
        ), "ignored files inspect doesn't install must not change the hash"
        assert (
            result.lock[0]["git"]["path_dirty"] is False
        ), "ignored files inspect doesn't install must not flip path_dirty"

    def test_gitignored_underscore_subdir_file_no_effect(self, tmp_path: Path) -> None:
        """inspect_ai's skill reader skips path parts starting with ``_``
        (like ``__pycache__/``) just as it skips ``.``-prefixed parts.
        A gitignored ``scripts/__pycache__/foo.pyc`` is a common
        machine-local file that must NOT perturb the lock — otherwise
        every developer's local cache would trip strict mode."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, "alpha")
        (repo / ".gitignore").write_text("alpha/scripts/__pycache__/\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        h_clean = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        (repo / "alpha" / "scripts").mkdir()
        (repo / "alpha" / "scripts" / "__pycache__").mkdir()
        (repo / "alpha" / "scripts" / "__pycache__" / "h.pyc").write_bytes(b"\x00")
        result = resolve_skills([str(repo)])
        assert result.lock[0]["content_sha256"] == h_clean
        assert result.lock[0]["git"]["path_dirty"] is False

    def test_gitignored_hidden_subdir_file_no_effect(self, tmp_path: Path) -> None:
        """A hidden file under an installed subdir (``scripts/.hidden``)
        isn't installed either — inspect's installer skips hidden files."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, "alpha")
        (repo / ".gitignore").write_text("alpha/scripts/.hidden\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        h_clean = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        (repo / "alpha" / "scripts").mkdir()
        (repo / "alpha" / "scripts" / ".hidden").write_text("local\n")
        result = resolve_skills([str(repo)])
        assert result.lock[0]["content_sha256"] == h_clean

    def test_gitignored_files_under_skill_dir_change_hash(self, tmp_path: Path) -> None:
        """Ignored content under a tracked skill dir is install-relevant
        (inspect copies the whole tree). Two different ignored payloads
        must produce different ``content_sha256`` values, else the lock
        falsely claims the same artifact for runs that received different
        bytes. (The ``path_dirty`` flag still fires too, but the *hash*
        is what fingerprints the install payload for archival.)"""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, "alpha")
        (repo / ".gitignore").write_text("alpha/scripts/\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        (repo / "alpha" / "scripts").mkdir()
        (repo / "alpha" / "scripts" / "helper.py").write_text("v1\n")
        h_v1 = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        (repo / "alpha" / "scripts" / "helper.py").write_text("v2\n")
        h_v2 = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        assert h_v1 != h_v2, (
            "ignored skill-payload bytes must affect the hash; otherwise "
            "the lock can't distinguish two runs that installed different code"
        )

    def test_gitignored_outside_skill_dirs_still_excluded(self, tmp_path: Path) -> None:
        """Files NOT under a resolved skill dir stay out of the hash
        (the .DS_Store / __pycache__ portability case)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, "alpha")
        (repo / ".gitignore").write_text("noise.txt\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        h_before = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        (repo / "noise.txt").write_text("machine-specific")
        h_after = resolve_skills([str(repo)]).lock[0]["content_sha256"]
        assert h_before == h_after, (
            "ignored files outside skill dirs must NOT affect the hash; "
            "otherwise every Mac's .DS_Store breaks portability"
        )

    def test_path_dirty_scoped_to_path(self, tmp_path: Path) -> None:
        """Edits outside the resolved path don't mark our skills dirty."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, "alpha")
        # Edit unrelated file at repo root, not under the skills dir
        (repo / "README.md").write_text("unrelated change")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "readme"], check=True
        )
        # Now make an unrelated uncommitted edit at repo root
        (repo / "README.md").write_text("uncommitted unrelated change")

        # Resolve only the skills subdir
        skills_dir = repo / "alpha"
        # alpha contains SKILL.md; treat it as the skills root for this test
        # (in real use it'd be plugins/<plugin>/skills/, also a subdir)
        result = resolve_skills([str(skills_dir)])
        assert result.lock[0]["git"]["path_dirty"] is False

    def test_deleted_skill_marks_dirty(self, tmp_path: Path) -> None:
        """When two SKILL.md trees are committed and the user deletes one
        locally, ``_list_skill_dirs`` drops that dir from the dirs list,
        so a naive porcelain check (filtered by surviving dirs) would
        miss the ``D beta/SKILL.md`` line and stamp a clean SHA. Strict
        mode would then accept a lock whose SHA, on checkout, restores
        ``beta`` and installs a different skill set. Catch it by
        unioning HEAD-side skill dirs into the porcelain check.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        _git_configure_test_repo(repo)
        _make_skill(repo, "alpha")
        _make_skill(repo, "beta")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "two"], check=True
        )
        # Delete beta in working tree.
        (repo / "beta" / "SKILL.md").unlink()
        (repo / "beta").rmdir()

        result = resolve_skills([str(repo)])
        assert result.lock[0]["skills"] == ["alpha"]
        assert result.lock[0]["git"]["path_dirty"] is True


class TestImageStampProvenance:
    """When the source path is under a tree with a ``.image-id`` stamp
    (written by ``solvers/inspect-swe/setup.sh`` after extracting skills
    from the asta image), the resolver records ``image_id`` in the lock
    as an alternative reproducibility primitive — the bytes can be
    reproduced by re-running setup.sh against that image, without
    needing the source dir to be git-tracked."""

    def test_stamp_recorded_in_lock(self, tmp_path: Path) -> None:
        """A skill tree extracted from an asta image carries the
        image_id stamp; the resolver picks it up and includes it in
        the lock entry."""
        vendor = tmp_path / ".vendor" / "asta-plugins"
        skills = vendor / "plugins" / "asta" / "skills"
        skills.mkdir(parents=True)
        _make_skill(skills, "alpha")
        (vendor / ".image-id").write_text(
            "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        result = resolve_skills([str(skills)])
        assert result.lock[0]["image_id"].startswith("sha256:")

    def test_image_stamp_bypasses_dirty_for_ignored_root(self, tmp_path: Path) -> None:
        """When the source is entirely-gitignored AND has an image
        stamp at an ancestor, ``path_dirty`` is *not* force-flipped —
        the image_id provides the alternative provenance. Strict mode
        can then accept the lock entry as reproducible."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, name="tracked-skill")
        # The vendor dir at .vendor/ is git-ignored.
        (repo / ".gitignore").write_text(".vendor/\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        vendor = repo / ".vendor" / "asta-plugins"
        skills = vendor / "plugins" / "asta" / "skills"
        skills.mkdir(parents=True)
        _make_skill(skills, "alpha")
        (vendor / ".image-id").write_text("sha256:abc123")
        result = resolve_skills([str(skills)])
        # image_id recorded; path_dirty NOT force-flipped (it stays
        # whatever git's porcelain check said, which is False for
        # entirely-ignored paths since git doesn't report them).
        assert result.lock[0]["image_id"] == "sha256:abc123"
        assert result.lock[0]["git"]["path_dirty"] is False

    def test_stale_image_stamp_invalidates_provenance(self, tmp_path: Path) -> None:
        """If a file under the stamped vendor tree is edited *after*
        ``.image-id`` was written, the stamp no longer matches what
        setup.sh would produce. Drop ``image_id`` from the lock and
        force ``path_dirty`` so strict mode catches the gap — otherwise
        a reviewer who reruns setup.sh against the stamped image gets
        different bytes than the eval actually ran."""
        import time

        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, name="tracked-skill")
        (repo / ".gitignore").write_text(".vendor/\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        vendor = repo / ".vendor" / "asta-plugins"
        skills = vendor / "plugins" / "asta" / "skills"
        skills.mkdir(parents=True)
        _make_skill(skills, "alpha")
        (vendor / ".image-id").write_text("sha256:abc123")
        # Simulate a post-setup edit: filesystem mtime granularity is
        # typically 1ns on macOS APFS and 1ms on Linux ext4, but sleep
        # for ~10ms to be safe across CI runners.
        time.sleep(0.01)
        (skills / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: edited\n---\n\nedited body"
        )

        result = resolve_skills([str(skills)])
        # Stale stamp: image_id dropped from lock, path_dirty forced True.
        assert "image_id" not in result.lock[0]
        assert result.lock[0]["git"]["path_dirty"] is True

    def test_deletion_under_image_stamp_invalidates_provenance(
        self, tmp_path: Path
    ) -> None:
        """File deletions bump only the *parent directory's* mtime
        (POSIX); a files-only mtime walk would miss them entirely and
        accept a stale stamp. The check walks dirs too so deletions
        flip the stamp to invalid."""
        import time

        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_with_skill(repo, name="tracked-skill")
        (repo / ".gitignore").write_text(".vendor/\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True
        )
        vendor = repo / ".vendor" / "asta-plugins"
        skills = vendor / "plugins" / "asta" / "skills"
        skills.mkdir(parents=True)
        _make_skill(skills, "alpha")
        _make_skill(skills, "beta")
        (vendor / ".image-id").write_text("sha256:abc123")
        # Post-setup deletion: bumps ``skills/`` mtime, not any file.
        time.sleep(0.01)
        (skills / "beta" / "SKILL.md").unlink()
        (skills / "beta").rmdir()

        result = resolve_skills([str(skills)])
        assert "image_id" not in result.lock[0]
        assert result.lock[0]["git"]["path_dirty"] is True


class TestSanitizeRemoteUrl:
    def test_strips_https_token_userinfo(self) -> None:
        """CI remotes embed an auth token in the URL — stamping it into
        the eval log would leak it to anyone with log access."""
        assert (
            _sanitize_remote_url(
                "https://x-access-token:ghp_abc123@github.com/org/repo.git"
            )
            == "https://github.com/org/repo.git"
        )

    def test_passwordless_userinfo_preserved_for_ssh(self) -> None:
        """``ssh://git@github.com/...`` needs the ``git@`` to clone — the
        sanitizer must preserve passwordless ``user@`` on non-HTTP
        schemes where the username is identification, not a credential."""
        assert (
            _sanitize_remote_url("ssh://git@github.com/o/r.git")
            == "ssh://git@github.com/o/r.git"
        )
        assert (
            _sanitize_remote_url("git://user@host/o/r.git") == "git://user@host/o/r.git"
        )

    def test_strips_passwordless_http_userinfo(self) -> None:
        """For HTTP-family schemes, bare ``user@`` can be a Personal
        Access Token (e.g. Azure DevOps ``https://<pat>@dev.azure.com/...``,
        GitHub ``https://<token>@github.com/...``). Strip unconditionally
        for these schemes — distinguishing identity from credential by
        colon presence isn't safe here."""
        assert (
            _sanitize_remote_url("https://ghp_abc123@github.com/o/r.git")
            == "https://github.com/o/r.git"
        )
        assert (
            _sanitize_remote_url("https://alice@gitlab.com/o/r.git")
            == "https://gitlab.com/o/r.git"
        )
        assert (
            _sanitize_remote_url("git+https://token@dev.azure.com/o/r.git")
            == "git+https://dev.azure.com/o/r.git"
        )

    def test_ssh_url_preserved(self) -> None:
        """``git@github.com:o/r.git`` (SCP-like SSH) has no password to
        leak — leave it alone (regex specifically targets URL-form
        ``://user:password@`` patterns)."""
        assert (
            _sanitize_remote_url("git@github.com:o/r.git") == "git@github.com:o/r.git"
        )

    def test_clean_https_preserved(self) -> None:
        assert (
            _sanitize_remote_url("https://github.com/o/r.git")
            == "https://github.com/o/r.git"
        )

    def test_strips_ssh_url_password(self) -> None:
        """``ssh://user:secret@host/path`` (URL form, with password) is
        a credentialed Git remote. Strip the secret."""
        assert (
            _sanitize_remote_url("ssh://alice:secret@git.example.com/o/r.git")
            == "ssh://git.example.com/o/r.git"
        )

    def test_stamped_origin_strips_credentials_end_to_end(self, tmp_path: Path) -> None:
        """End-to-end: a repo with a credentialed HTTPS origin must not
        leak the token into the per-ref ``lock[*]["git"]["origin"]``."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@t"], check=True
        )
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "remote",
                "add",
                "origin",
                "https://x-access-token:SUPERSECRET@github.com/o/r.git",
            ],
            check=True,
        )
        _make_skill(repo, "alpha")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True
        )
        result = resolve_skills([str(repo)])
        origin = result.lock[0]["git"]["origin"]
        assert "SUPERSECRET" not in origin
        assert "x-access-token" not in origin
        assert origin == "https://github.com/o/r.git"


class TestConflictDetection:
    def test_same_skill_in_two_refs_raises(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        _make_skill(a, "shared")
        _make_skill(b, "shared")
        with pytest.raises(ValueError, match="two locations"):
            resolve_skills([str(a), str(b)])

    def test_duplicate_skill_within_one_ref_raises(self, tmp_path: Path) -> None:
        """inspect_swe's ``install_skills`` keys by skill name and silently
        overwrites duplicates. A single ref that happens to contain two
        SKILL.md trees with the same basename (e.g. pointing ``skills=``
        at a parent of ``plugins/asta/skills/semantic-scholar`` AND
        ``plugins/asta-preview/skills/semantic-scholar``) would otherwise
        ship a lock listing both while only one actually installs."""
        parent = tmp_path / "plugins"
        _make_skill(parent / "asta" / "skills", "semantic-scholar")
        _make_skill(parent / "asta-preview" / "skills", "semantic-scholar")
        with pytest.raises(ValueError, match="two locations"):
            resolve_skills([str(parent)])

    def test_distinct_skills_across_refs_ok(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        _make_skill(a, "alpha")
        _make_skill(b, "beta")
        result = resolve_skills([str(a), str(b)])
        assert sorted(d.name for d in result.skill_dirs) == ["alpha", "beta"]
        assert len(result.lock) == 2
