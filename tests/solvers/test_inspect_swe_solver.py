"""Tests for the inspect_swe_solver wiring contract.

Cover the kwargs the solver passes to the underlying ``inspect_swe`` agent
constructor: bridge filter wiring, host ``ASTA_TOKEN`` propagation, per-sample
``state.metadata["insertion_date"]`` → asta CLI env, skill resolution +
provenance lock stamped to ``state.metadata["skills"]``, MCP paper-search
tool filtering when paper-search skills are loaded.
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from inspect_ai.agent import BridgedToolsSpec  # noqa: F401
    from inspect_ai.model import GenerateInput  # noqa: F401
    from inspect_ai.tool import ToolDef
except ImportError:  # pragma: no cover
    pytest.skip(
        "inspect_swe solver tests require the newer inspect_ai; run via "
        "solvers/inspect-swe subproject venv",
        allow_module_level=True,
    )

from agent_baselines.skills.resolver import ResolvedSkills


def _run_solver(
    state_metadata=None,
    state_tools=None,
    resolved=None,
    sandbox_responses=None,
    sandbox_container=None,
    **solver_kwargs,
):
    """Invoke ``inspect_swe_solver(...)`` with ``inspect_swe.claude_code`` and
    ``resolve_skills`` mocked. Returns ``(constructor_kwargs, state, resolve_mock)``.

    ``sandbox_responses`` (dict) seeds canned ``sandbox().exec(...)`` results
    for the post-run ``asta --version`` query. Key: ``asta_version`` (str or
    None — None means the exec failed, modelling a non-asta sandbox).
    """
    from agent_baselines.solvers.inspect_swe.agent import inspect_swe_solver

    mock_agent = AsyncMock(return_value=MagicMock())
    resolved = resolved if resolved is not None else ResolvedSkills()

    sandbox_responses = sandbox_responses or {}
    asta_version_out = sandbox_responses.get("asta_version")
    sandbox_binary_path = sandbox_responses.get("sandbox_binary_path")
    sandbox_binary_version = sandbox_responses.get("sandbox_binary_version")

    async def fake_exec(cmd, **kwargs):
        res = MagicMock()
        if cmd == ["asta", "--version"]:
            res.success = asta_version_out is not None
            res.stdout = asta_version_out or ""
        elif len(cmd) == 2 and cmd[0] == "which":
            res.success = sandbox_binary_path is not None
            res.stdout = sandbox_binary_path or ""
        elif (
            sandbox_binary_path is not None
            and len(cmd) == 2
            and cmd[0] == sandbox_binary_path
            and cmd[1] == "--version"
        ):
            res.success = sandbox_binary_version is not None
            res.stdout = sandbox_binary_version or ""
        else:
            res.success = False
            res.stdout = ""
        return res

    mock_sandbox = MagicMock()
    mock_sandbox.exec = fake_exec

    async def fake_connection(**kwargs):
        # If a container was provided, hand it to the docker-inspect helper;
        # otherwise raise to model "no docker / non-docker sandbox".
        if sandbox_container is None:
            raise RuntimeError("no container")
        conn = MagicMock()
        conn.container = sandbox_container
        return conn

    mock_sandbox.connection = fake_connection

    constructor_mocks: dict[str, MagicMock] = {}
    with (
        patch("inspect_swe.claude_code") as mock_cc,
        patch("inspect_swe.codex_cli") as mock_codex,
        patch("inspect_swe.gemini_cli") as mock_gemini,
        patch("inspect_swe.mini_swe_agent") as mock_mini,
        patch("inspect_swe.opencode") as mock_oc,
        patch(
            "agent_baselines.solvers.inspect_swe.agent.resolve_skills",
            return_value=resolved,
        ) as mock_resolve,
        patch(
            "agent_baselines.solvers.inspect_swe.agent._asta_plugin_skills_ref",
            side_effect=lambda plugin: (
                f"/fake/.vendor/asta-plugins/plugins/{plugin}/skills"
            ),
        ),
        patch("inspect_ai.util.sandbox", return_value=mock_sandbox),
    ):
        for ctor in (mock_cc, mock_codex, mock_gemini, mock_mini, mock_oc):
            ctor.return_value = mock_agent
        constructor_mocks = {
            "claude_code": mock_cc,
            "codex_cli": mock_codex,
            "gemini_cli": mock_gemini,
            "mini_swe_agent": mock_mini,
            "opencode": mock_oc,
        }
        solver = inspect_swe_solver(**(solver_kwargs or {}))
        state = MagicMock()
        state.metadata = dict(state_metadata or {})
        state.tools = list(state_tools or [])
        import asyncio

        asyncio.run(solver(state, AsyncMock()))
        ctor = constructor_mocks[(solver_kwargs or {}).get("agent", "claude_code")]
        return ctor.call_args.kwargs, state, mock_resolve


def _named_tool(name: str):
    from inspect_ai.tool import ToolDef
    from inspect_ai.tool._tool_info import ToolParams

    async def _impl() -> str:
        return ""

    return ToolDef(
        tool=_impl, name=name, description="stub", parameters=ToolParams()
    ).as_tool()


class TestFilterWiring:
    def test_filter_wired_by_default(self):
        from agent_baselines.solvers.inspect_swe._filters import (
            deny_external_web_tools,
        )

        kwargs, _, _ = _run_solver()
        assert kwargs.get("filter") is deny_external_web_tools

    def test_disable_knob(self):
        kwargs, _, _ = _run_solver(deny_external_web=False)
        assert "filter" not in kwargs

    def test_explicit_filter_wins(self):
        async def custom(*a, **k):
            return None

        kwargs, _, _ = _run_solver(filter=custom)
        assert kwargs.get("filter") is custom


class TestTokenPropagation:
    def test_host_asta_token_reaches_agent_env(self):
        with patch.dict(os.environ, {"ASTA_TOKEN": "host-token"}):
            kwargs, _, _ = _run_solver()
        env_arg = kwargs.get("env") or {}
        assert env_arg.get("ASTA_TOKEN") == "host-token"

    def test_no_token_when_host_unset(self):
        env_before = dict(os.environ)
        os.environ.pop("ASTA_TOKEN", None)
        try:
            kwargs, _, _ = _run_solver()
        finally:
            os.environ.clear()
            os.environ.update(env_before)
        env_arg = kwargs.get("env") or {}
        assert "ASTA_TOKEN" not in env_arg


class TestInsertionDatePropagation:
    def test_metadata_drives_env(self):
        kwargs, _, _ = _run_solver(state_metadata={"insertion_date": "2024-10-17"})
        env = kwargs.get("env") or {}
        assert env.get("ASTA_INSERTED_BEFORE") == "2024-10-17"
        assert env.get("ASTA_PUBLICATION_DATE_RANGE") == ":2024-10-17"

    def test_no_metadata_no_env(self):
        kwargs, _, _ = _run_solver(state_metadata={})
        env = kwargs.get("env") or {}
        assert "ASTA_INSERTED_BEFORE" not in env
        assert "ASTA_PUBLICATION_DATE_RANGE" not in env

    def test_caller_env_wins(self):
        kwargs, _, _ = _run_solver(
            state_metadata={"insertion_date": "2024-10-17"},
            extra_env={
                "ASTA_INSERTED_BEFORE": "2023-01-01",
                "ASTA_PUBLICATION_DATE_RANGE": "2020-",
            },
        )
        env = kwargs.get("env") or {}
        assert env["ASTA_INSERTED_BEFORE"] == "2023-01-01"
        assert env["ASTA_PUBLICATION_DATE_RANGE"] == "2020-"


class TestAmbiguousKwargsRejected:
    """The wrapper has dedicated parameters for env vars (``extra_env=``)
    and the sandbox name (``sandbox_name=``); forwarding those through
    ``agent_kwargs`` instead would silently bypass the wrapper's
    preflight invariants. Reject at construction."""

    def test_env_in_agent_kwargs_raises(self):
        """``env=`` via agent_kwargs would override the wrapper-built
        env *after* preflight (ASTA_TOKEN, insertion-date) checked
        ``base_env`` — the constructor would receive a different env
        than what the checks validated."""
        with pytest.raises(ValueError, match="extra_env"):
            _run_solver(env={"FOO": "bar"})

    def test_conflicting_sandbox_raises(self):
        """Both ``sandbox_name=`` and ``sandbox=`` (via agent_kwargs)
        being set is ambiguous: the constructor wins one way, the
        post-run probes another. Reject the combo."""
        with pytest.raises(ValueError, match="sandbox_name"):
            _run_solver(sandbox_name="svc-a", sandbox="svc-b")

    def test_agent_kwargs_sandbox_only_ok(self):
        """A single sandbox source is fine — let the caller use either
        ``sandbox_name=`` or ``sandbox=`` (e.g. when threading from a
        downstream config that only knows the inspect_swe kwarg name)."""
        kwargs, _, _ = _run_solver(sandbox="svc-only")
        assert kwargs.get("sandbox") == "svc-only"


class TestPerSampleResolution:
    """inspect_swe re-reads SKILL.md every sample, so if a caller
    rebuilds or edits a local ``-S skills=`` tree mid-eval, later
    samples install the new bytes. The stamped lock must describe what
    *each sample* actually got, not a stale construction-time snapshot.
    The resolver runs at execute time (once per sample), so each
    sample's ``state.metadata['skills']`` reflects the bytes
    inspect_swe is installing for that sample."""

    def test_resolve_skills_called_per_sample(self):
        """Verify resolve_skills is invoked on each ``solver(state, ...)``
        call, not just at construction. With construction-time-only
        resolution, two samples in the same eval would share one lock
        even if the source bytes changed between them."""
        from agent_baselines.solvers.inspect_swe.agent import inspect_swe_solver

        mock_agent = AsyncMock(return_value=MagicMock())
        mock_sandbox = MagicMock()
        mock_sandbox.exec = AsyncMock(return_value=MagicMock(success=False, stdout=""))

        async def fake_connection(**kwargs):
            raise RuntimeError("no container")

        mock_sandbox.connection = fake_connection
        resolve_calls = 0
        # Construction-time resolution would invoke resolve_skills once
        # for an N-sample eval; per-sample resolution invokes it N+1
        # times (construction + per sample). Verify >1 call across 2
        # ``solver(...)`` invocations.

        def fake_resolve(refs):
            nonlocal resolve_calls
            resolve_calls += 1
            return ResolvedSkills()

        with (
            patch("inspect_swe.claude_code") as mock_cc,
            patch("inspect_swe.codex_cli"),
            patch("inspect_swe.gemini_cli"),
            patch("inspect_swe.mini_swe_agent"),
            patch("inspect_swe.opencode"),
            patch(
                "agent_baselines.solvers.inspect_swe.agent.resolve_skills",
                side_effect=fake_resolve,
            ),
            patch("inspect_ai.util.sandbox", return_value=mock_sandbox),
        ):
            mock_cc.return_value = mock_agent
            solver = inspect_swe_solver(agent="claude_code", version="2.1.128")
            state = MagicMock()
            state.metadata = {}
            state.tools = []
            import asyncio

            asyncio.run(solver(state, AsyncMock()))
            calls_after_first = resolve_calls
            asyncio.run(solver(state, AsyncMock()))
        assert resolve_calls > calls_after_first, (
            f"resolve_skills must be re-called per sample so the stamped lock "
            f"reflects the bytes inspect_swe will install on this sample; "
            f"saw {resolve_calls} total calls across 2 invocations"
        )


class TestStrictReproducibility:
    """Strict mode promotes reproducibility-warning conditions to raises
    so a benchmark log can't slip out without full provenance. Default
    is best-effort + warn (suitable for ad-hoc runs); strict is opt-in
    for benchmark/leaderboard runs that must be defensible."""

    def test_strict_dirty_skills_raise_at_construction(self):
        """Skills with uncommitted/ignored content can't be recreated
        via ``git checkout <sha>``; strict mode rejects them upfront."""
        resolved = ResolvedSkills(
            skill_dirs=[Path("/foo/x")],
            lock=[
                {
                    "source": "/foo",
                    "skills": ["x"],
                    "content_sha256": "abc",
                    "git": {
                        "origin": "git@example.com:o/r.git",
                        "sha": "a" * 40,
                        "path_in_repo": "",
                        "path_dirty": True,
                    },
                }
            ],
        )
        with pytest.raises(ValueError, match="path_dirty|dirty"):
            _run_solver(skills="/foo", resolved=resolved, strict_reproducibility=True)

    def test_strict_skills_outside_git_raise_at_construction(self):
        """No git block → no origin/sha → can't reproduce the run. Reject."""
        resolved = ResolvedSkills(
            skill_dirs=[Path("/foo/x")],
            lock=[{"source": "/foo", "skills": ["x"], "content_sha256": "abc"}],
        )
        with pytest.raises(ValueError, match="git working tree"):
            _run_solver(skills="/foo", resolved=resolved, strict_reproducibility=True)

    def test_strict_clean_skills_ok(self, monkeypatch):
        """Clean git block (committed, untouched, origin present) +
        pinned versions + immutable image digest is the strict happy path."""
        monkeypatch.setenv(
            "ASTA_IMAGE",
            "ghcr.io/allenai/asta@sha256:" + "a" * 64,
        )
        resolved = ResolvedSkills(
            skill_dirs=[Path("/foo/x")],
            lock=[
                {
                    "source": "/foo",
                    "skills": ["x"],
                    "content_sha256": "abc",
                    "git": {
                        "origin": "git@example.com:o/r.git",
                        "sha": "a" * 40,
                        "path_in_repo": "plugins/asta/skills",
                        "path_dirty": False,
                    },
                }
            ],
        )
        _, state, _ = _run_solver(
            skills="/foo",
            resolved=resolved,
            strict_reproducibility=True,
            version="2.1.128",  # pinned → no agent_version probe
        )
        # No raise; lock stamped as-is.
        assert state.metadata["skills"] == resolved.lock
        assert state.metadata.get("reproducibility_warnings", []) == [] or (
            "reproducibility_warnings" not in state.metadata
        )

    def test_strict_unresolved_agent_version_raises_after_run(self, monkeypatch):
        """When the post-run resolver returns nothing AND strict is on,
        promote the warning to a raise — the eval log would otherwise
        carry no agent_version, breaking downstream extraction."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta@sha256:" + "a" * 64)
        with patch("inspect_swe.cached_agent_binaries", return_value=[]):
            with pytest.raises(RuntimeError, match="reproducibility_warnings"):
                _run_solver(
                    agent="claude_code",
                    version="auto",
                    strict_reproducibility=True,
                )

    def test_strict_unresolved_asta_image_raises_after_run(self, monkeypatch):
        """No docker container reachable AND no ASTA_IMAGE → strict mode
        raises so the operator pins before treating the run as benchmark-grade."""
        monkeypatch.delenv("ASTA_IMAGE", raising=False)
        with pytest.raises(RuntimeError, match="reproducibility_warnings"):
            _run_solver(
                agent="claude_code",
                version="2.1.128",  # pinned so agent_version resolves
                strict_reproducibility=True,
            )

    def test_non_strict_records_warnings_in_metadata(self, monkeypatch):
        """In default (non-strict) mode, provenance gaps populate
        ``reproducibility_warnings`` as a structured signal — consumers
        can detect non-reproducible runs without scanning logs."""
        monkeypatch.delenv("ASTA_IMAGE", raising=False)
        _, state, _ = _run_solver(agent="claude_code", version="2.1.128")
        warnings = state.metadata.get("reproducibility_warnings", [])
        assert any(
            "asta_image" in w for w in warnings
        ), f"expected an asta_image warning; got {warnings}"

    def test_clean_run_has_no_warnings_field(self, monkeypatch):
        """When every axis resolves to an immutable form, don't pollute
        metadata with an empty warnings list."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta@sha256:" + "a" * 64)
        _, state, _ = _run_solver(agent="claude_code", version="2.1.128")
        assert state.metadata.get("reproducibility_warnings", []) == [] or (
            "reproducibility_warnings" not in state.metadata
        )

    def test_strict_skills_no_origin_raise_at_construction(self):
        """A local-only git repo (no ``origin`` remote) has sha + clean
        tree but no clone URL for a reviewer — strict mode rejects
        because the recorded sha isn't fetchable from elsewhere."""
        resolved = ResolvedSkills(
            skill_dirs=[Path("/foo/x")],
            lock=[
                {
                    "source": "/foo",
                    "skills": ["x"],
                    "content_sha256": "abc",
                    "git": {
                        "origin": None,
                        "sha": "a" * 40,
                        "path_in_repo": "",
                        "path_dirty": False,
                    },
                }
            ],
        )
        with pytest.raises(ValueError, match="origin"):
            _run_solver(skills="/foo", resolved=resolved, strict_reproducibility=True)

    def test_strict_accepts_verified_image_id_provenance(self, monkeypatch):
        """When the lock entry carries ``image_id`` AND that stamp
        verifies against the running ASTA_IMAGE, strict mode treats the
        entry as reproducible even though the source is gitignored —
        the verified asta-image stamp IS the provenance. Unblocks
        ``-S install_asta_skills=`` under strict mode."""
        stamped_id = "sha256:" + "b" * 64
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta@sha256:" + "a" * 64)
        # docker resolves ASTA_IMAGE to the same image_id stamped on
        # the source → stamp is verified.
        monkeypatch.setattr(
            "agent_baselines.solvers.inspect_swe.agent.subprocess.run",
            lambda *a, **kw: MagicMock(stdout=stamped_id + "\n", returncode=0),
        )
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[
                {
                    "source": "/fake/.vendor/asta-plugins/plugins/asta/skills",
                    "content_sha256": "abc",
                    "skills": ["semantic-scholar"],
                    "image_id": stamped_id,
                    # Vendor dir is gitignored → path_dirty=True. Strict
                    # would normally raise; verified image_id accepts.
                    "git": {
                        "origin": "git@github.com:allenai/agent-baselines.git",
                        "sha": "a" * 40,
                        "path_in_repo": "solvers/inspect-swe/.vendor/...",
                        "path_dirty": True,
                    },
                }
            ],
        )
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        _, state, _ = _run_solver(
            install_asta_skills="asta",
            resolved=resolved,
            strict_reproducibility=True,
            version="2.1.128",
        )
        assert state.metadata["skills"] == resolved.lock

    def test_strict_rejects_unverified_image_id(self, monkeypatch):
        """When ``image_id`` is in the lock but ASTA_IMAGE wasn't
        verifiable (unset / docker unavailable / image not local), the
        stamp could be from a different image than the sandbox runs.
        Strict mode must reject explicitly rather than fall through to
        git checks — the resolver may have set ``path_dirty=False`` on
        the assumption that image_id provides valid provenance (the
        gitignored-vendor case: fresh stamp relaxes path_dirty, strict
        mode's fallthrough would otherwise accept)."""
        monkeypatch.delenv("ASTA_IMAGE", raising=False)
        # _resolve_env_image_id() returns None on ASTA_IMAGE unset
        # without consulting docker.
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[
                {
                    "source": "/fake/.vendor/asta-plugins/plugins/asta/skills",
                    "content_sha256": "abc",
                    "skills": ["semantic-scholar"],
                    "image_id": "sha256:" + "b" * 64,
                    # Gitignored vendor: resolver trusted image_id, so
                    # path_dirty=False. Without the explicit unverified-
                    # image rejection, strict mode would fall through
                    # and accept this.
                    "git": {
                        "origin": "git@github.com:allenai/agent-baselines.git",
                        "sha": "a" * 40,
                        "path_in_repo": "solvers/inspect-swe/.vendor/...",
                        "path_dirty": False,
                    },
                }
            ],
        )
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        with pytest.raises(ValueError, match="unverified .image-id"):
            _run_solver(
                install_asta_skills="asta",
                resolved=resolved,
                strict_reproducibility=True,
                version="2.1.128",
            )

    def test_mutable_image_tag_records_warning(self, monkeypatch):
        """``ASTA_IMAGE=…:vX.Y.Z`` is a tag — the registry can re-push
        it — so it's not immutable provenance. Record a warning so
        consumers (and strict mode) know."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")
        _, state, _ = _run_solver(agent="claude_code", version="2.1.128")
        warnings = state.metadata.get("reproducibility_warnings", [])
        assert any(
            "mutable tag" in w for w in warnings
        ), f"expected mutable-tag warning; got {warnings}"

    def test_immutable_image_digest_no_warning(self, monkeypatch):
        """``ASTA_IMAGE=...@sha256:...`` pins to immutable bytes — no warning."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta@sha256:" + "a" * 64)
        _, state, _ = _run_solver(agent="claude_code", version="2.1.128")
        warnings = state.metadata.get("reproducibility_warnings", [])
        assert not any(
            "mutable tag" in w for w in warnings
        ), f"unexpected mutable-tag warning for digest; got {warnings}"

    def test_strict_mutable_image_raises_after_run(self, monkeypatch):
        """Strict mode promotes the mutable-tag warning to a raise so a
        benchmark run can't slip out with a re-pushable image stamp."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")
        with pytest.raises(RuntimeError, match="reproducibility_warnings"):
            _run_solver(
                agent="claude_code",
                version="2.1.128",
                strict_reproducibility=True,
            )


class TestSkillsResolution:
    """``skills=`` accepts vercel-skills-style refs; ``install_asta_skills=``
    is a sugar wrapper that resolves to the bundled plugin path. Both routes
    go through ``resolve_skills`` and produce a consistent provenance lock."""

    def test_no_skills_default(self):
        kwargs, _, _ = _run_solver()
        assert kwargs.get("skills") is None

    def test_explicit_skills_string(self):
        resolved = ResolvedSkills(
            skill_dirs=[Path("/tmp/fake-dir")],
            lock=[{"source": "/tmp/fake-dir", "skills": ["x"]}],
        )
        kwargs, _, _ = _run_solver(skills="./fake-dir", resolved=resolved)
        assert kwargs["skills"] == [Path("/tmp/fake-dir")]

    def test_install_asta_skills_sugar(self, monkeypatch):
        """``install_asta_skills="asta"`` resolves to the bundled plugin path
        and goes through the same resolver as explicit ``skills=`` refs."""
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")], lock=[{"source": "x"}]
        )
        _, _, m_resolve = _run_solver(install_asta_skills="asta", resolved=resolved)
        assert m_resolve.call_args.args[0] == [
            "/fake/.vendor/asta-plugins/plugins/asta/skills",
        ]

    def test_provenance_lock_stamped_to_state_metadata(self):
        """The lock is the load-bearing piece — it lets you trace from an
        eval log to exactly which sources/shas were used."""
        lock = [{"source": "/foo", "skills": ["x"], "content_sha256": "abc"}]
        resolved = ResolvedSkills(skill_dirs=[Path("/foo/x")], lock=lock)
        _, state, _ = _run_solver(skills="/foo", resolved=resolved)
        assert state.metadata["skills"] == lock

    def test_empty_lock_no_metadata_write(self):
        """When nothing is resolved, don't pollute state.metadata."""
        _, state, _ = _run_solver()
        assert "skills" not in state.metadata

    def test_asta_image_resolved_from_container(self):
        """Post-run, the solver queries docker for the running container's
        registry digest so the log records the immutable identifier of
        what actually ran (regardless of whether the caller pinned via
        ASTA_IMAGE env or let compose default to :latest)."""
        digest = "ghcr.io/allenai/asta@sha256:abcd1234"
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=_fake_docker_inspect(image_id="sha256:abcd", digest=digest),
        ):
            _, state, _ = _run_solver(sandbox_container="container-xyz")
        assert state.metadata["asta_image"] == digest

    def test_asta_image_falls_back_to_tag_without_digest(self):
        """Locally-built images have no RepoDigests; fall back to the
        compose-supplied tag."""
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=_fake_docker_inspect(
                image_id="sha256:local", digest="", config_image="local/test:dev"
            ),
        ):
            _, state, _ = _run_solver(sandbox_container="container-xyz")
        assert state.metadata["asta_image"] == "local/test:dev"

    def test_asta_image_unset_when_docker_unavailable(self, monkeypatch, caplog):
        """If sbx.connection() / docker calls fail AND ASTA_IMAGE is unset,
        leave the slot unset and warn so the operator sees the gap."""
        monkeypatch.delenv("ASTA_IMAGE", raising=False)
        with caplog.at_level("WARNING"):
            _, state, _ = _run_solver()
        assert "asta_image" not in state.metadata
        assert any(
            "asta_image could not be resolved" in r.message for r in caplog.records
        )

    def test_asta_image_falls_back_to_env_var(self, monkeypatch):
        """When the sandbox isn't reachable as a docker container (e.g.
        a non-docker sandbox), stamp the operator-requested ``ASTA_IMAGE``.
        Coarser than a registry digest but at least carries forward what
        the operator asked for."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")
        _, state, _ = _run_solver()  # no sandbox_container → connection() fails
        assert state.metadata["asta_image"] == "ghcr.io/allenai/asta:v0.17.0"

    def test_probes_use_agent_kwargs_sandbox(self):
        """Callers can override the solver's top-level sandbox by passing
        ``sandbox=`` through ``agent_kwargs`` (forwarded into the
        inspect_swe constructor). When they do, post-run probes
        (asta/agent version, image digest) must hit the *same* service
        — probing the default container instead would stamp the wrong
        image and version for multi-service runs."""
        captured_sandbox_names: list[str | None] = []

        async def fake_exec(cmd, **kwargs):
            res = MagicMock()
            res.success = False
            res.stdout = ""
            return res

        mock_sandbox = MagicMock()
        mock_sandbox.exec = fake_exec

        async def fake_connection(**kwargs):
            raise RuntimeError("no container")

        mock_sandbox.connection = fake_connection

        def sandbox_factory(name=None, *args, **kwargs):
            captured_sandbox_names.append(name)
            return mock_sandbox

        with (
            patch("inspect_swe.claude_code") as mock_cc,
            patch("inspect_swe.codex_cli"),
            patch("inspect_swe.gemini_cli"),
            patch("inspect_swe.mini_swe_agent"),
            patch("inspect_swe.opencode"),
            patch(
                "agent_baselines.solvers.inspect_swe.agent.resolve_skills",
                return_value=ResolvedSkills(),
            ),
            patch("inspect_ai.util.sandbox", side_effect=sandbox_factory),
        ):
            from agent_baselines.solvers.inspect_swe.agent import inspect_swe_solver

            mock_cc.return_value = AsyncMock(return_value=MagicMock())
            # Caller forwards sandbox="agent-service" via agent_kwargs;
            # solver's own sandbox is not set.
            solver = inspect_swe_solver(
                agent="claude_code",
                version="2.1.128",
                sandbox="agent-service",
            )
            state = MagicMock()
            state.metadata = {}
            state.tools = []
            import asyncio

            asyncio.run(solver(state, AsyncMock()))
        # Probes should target "agent-service", not None (the default).
        assert "agent-service" in captured_sandbox_names, (
            f"post-run probes didn't target the agent_kwargs sandbox; "
            f"saw {captured_sandbox_names}"
        )
        assert (
            None not in captured_sandbox_names
        ), f"post-run probes used the default sandbox; saw {captured_sandbox_names}"


class TestVersionStamping:
    """Reproducibility metadata captured per sample: wrapper version (always),
    asta CLI version (from ``asta --version`` in sandbox), and the agent CLI
    version (concrete caller value, else resolved via inspect_swe's public
    host-side cache for the two agents that support it)."""

    def test_inspect_swe_version_stamped(self):
        """Always stamp the wrapper version — it's a robust public attr
        and pins most of the reproducibility-relevant behavior."""
        import inspect_swe

        _, state, _ = _run_solver()
        assert state.metadata["inspect_swe_version"] == inspect_swe.__version__

    def test_concrete_agent_version_stamped(self):
        _, state, _ = _run_solver(version="2.1.126")
        assert state.metadata["agent_version"] == "2.1.126"

    def test_auto_version_resolved_via_cache(self):
        """``auto`` drifts at the API layer, but inspect_swe ``touch()``es
        the cache entry it just used. Newest-mtime entry = what just ran."""
        fake_binaries = _fake_cached_binaries(
            [("2.1.124", 1000.0), ("2.1.128", 5000.0), ("2.1.126", 3000.0)]
        )
        with patch("inspect_swe.cached_agent_binaries", return_value=fake_binaries):
            _, state, _ = _run_solver(version="auto")
        assert state.metadata["agent_version"] == "2.1.128"

    def test_concrete_version_wins_over_cache(self):
        """If the caller pinned, trust them — don't override with cache
        lookup (cache could contain a stale entry from a prior run)."""
        fake_binaries = _fake_cached_binaries([("2.1.999", 9999.0)])
        with patch("inspect_swe.cached_agent_binaries", return_value=fake_binaries):
            _, state, _ = _run_solver(version="2.1.126")
        assert state.metadata["agent_version"] == "2.1.126"

    def test_cache_empty_no_stamp(self):
        """First run on a fresh host, or cache lookup failed — leave the
        slot empty rather than guess."""
        with patch("inspect_swe.cached_agent_binaries", return_value=[]):
            _, state, _ = _run_solver(version="auto")
        assert "agent_version" not in state.metadata

    def test_gemini_unpinned_raises_at_construction(self):
        """gemini_cli has no public resolver. For an eval run, the
        contract is: pin or rerun. Fail fast at construction before any
        sample burns compute."""
        with pytest.raises(ValueError, match="Cannot resolve agent_version"):
            _run_solver(agent="gemini_cli", version="auto")

    def test_gemini_pinned_no_raise(self):
        """Concrete version means no resolution needed — gemini_cli is fine."""
        _, state, _ = _run_solver(agent="gemini_cli", version="0.5.0")
        assert state.metadata["agent_version"] == "0.5.0"

    def test_gemini_sandbox_raises_at_construction(self):
        """gemini_cli's inspect_swe setup downloads via the GitHub releases
        API regardless of what's preinstalled in the sandbox, so
        ``version="sandbox"`` does *not* actually pin to image state — the
        installed CLI drifts release-to-release. Reject at construction
        rather than silently produce drifting unstamped runs."""
        with pytest.raises(ValueError, match="Cannot resolve agent_version"):
            _run_solver(agent="gemini_cli", version="sandbox")

    def test_opencode_unpinned_raises_at_construction(self):
        """opencode (inspect_swe 0.2.52+) behaves like gemini_cli for
        version resolution: every mode (auto/sandbox/stable/latest)
        downloads via the GitHub releases API and installs to a fixed
        inspect-swe-internal path (not a system-PATH binary). No public
        host cache. So every unpinned mode is unresolvable post-run —
        reject at construction so the operator pins."""
        with pytest.raises(ValueError, match="Cannot resolve agent_version"):
            _run_solver(agent="opencode", version="auto")

    def test_opencode_pinned_no_raise(self):
        _, state, _ = _run_solver(agent="opencode", version="0.4.2")
        assert state.metadata["agent_version"] == "0.4.2"

    def test_mini_swe_agent_rejects_skills_at_construction(self):
        """inspect_swe 0.2.48's ``mini_swe_agent`` constructor has no
        ``skills`` parameter. Forwarding ``-S skills=...`` (or its
        sugar ``install_asta_skills=``) would TypeError at sample-start
        with an opaque inspect_swe stack trace. Reject at construction
        with a clear message so the operator picks a different agent
        (or drops the skills knob)."""
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[{"source": "/fake", "skills": ["semantic-scholar"]}],
        )
        with pytest.raises(ValueError, match="doesn't support ``skills="):
            _run_solver(
                agent="mini_swe_agent",
                skills="/fake",
                resolved=resolved,
                version="stable",
            )

    def test_mini_swe_agent_no_skills_ok(self):
        """No skills passed → mini_swe_agent runs fine."""
        _, state, _ = _run_solver(agent="mini_swe_agent", version="stable")
        # Just verify it reaches the post-run stamping path.
        assert "inspect_swe_version" in state.metadata

    def test_mini_swe_agent_resolves_default_version(self):
        """``stable`` for mini_swe_agent is pinned by inspect_swe to a
        hardcoded ``default_version``. Reading it lets the log carry the
        concrete CLI version directly, without forcing the operator to
        cross-reference inspect_swe's source."""
        from inspect_swe._mini_swe_agent.mini_swe_agent import (
            MINI_SWE_AGENT_SOURCE,
        )

        _, state, _ = _run_solver(agent="mini_swe_agent", version="stable")
        assert state.metadata["agent_version"] == MINI_SWE_AGENT_SOURCE.default_version

    def test_mini_swe_agent_latest_not_resolved_from_default(self):
        """``mini_swe_agent`` with version=``latest`` downloads from PyPI;
        that's not the hardcoded ``default_version``. Don't stamp the
        wrong version — leave the slot unset rather than fabricate."""
        _, state, _ = _run_solver(agent="mini_swe_agent", version="latest")
        assert "agent_version" not in state.metadata

    def test_sandbox_version_not_resolved_from_cache(self):
        """``version="sandbox"`` uses the binary already installed in the
        sandbox image, not the host cache. The host cache may have a stale
        entry from a previous run — don't stamp from it."""
        fake_binaries = _fake_cached_binaries([("2.1.999", 9999.0)])
        with patch("inspect_swe.cached_agent_binaries", return_value=fake_binaries):
            _, state, _ = _run_solver(agent="claude_code", version="sandbox")
        assert "agent_version" not in state.metadata

    def test_sandbox_version_resolved_from_sandbox_probe(self):
        """``version="sandbox"`` should stamp the actually-installed
        binary's version when probing the sandbox succeeds — that's the
        whole point of the mode."""
        _, state, _ = _run_solver(
            agent="claude_code",
            version="sandbox",
            sandbox_responses={
                "sandbox_binary_path": "/usr/local/bin/claude",
                "sandbox_binary_version": "2.1.500\n",
            },
        )
        assert state.metadata["agent_version"] == "2.1.500"

    def test_stable_does_not_probe_sandbox(self):
        """inspect_swe with ``version="stable"`` always downloads to the
        host cache — it does *not* reuse a preinstalled sandbox binary.
        Probing the sandbox would stamp the wrong binary on images that
        ship an older CLI preinstalled. Cache is authoritative here."""
        fake_binaries = _fake_cached_binaries([("2.1.128", 9999.0)])
        with patch("inspect_swe.cached_agent_binaries", return_value=fake_binaries):
            _, state, _ = _run_solver(
                agent="claude_code",
                version="stable",
                sandbox_responses={
                    "sandbox_binary_path": "/usr/local/bin/claude",
                    "sandbox_binary_version": "2.0.000\n",  # older preinstalled
                },
            )
        assert state.metadata["agent_version"] == "2.1.128"

    def test_latest_does_not_probe_sandbox(self):
        """Same as stable: inspect_swe with ``version="latest"`` always
        downloads; cache is authoritative."""
        fake_binaries = _fake_cached_binaries([("2.1.500", 9999.0)])
        with patch("inspect_swe.cached_agent_binaries", return_value=fake_binaries):
            _, state, _ = _run_solver(
                agent="claude_code",
                version="latest",
                sandbox_responses={
                    "sandbox_binary_path": "/usr/local/bin/claude",
                    "sandbox_binary_version": "2.0.000\n",
                },
            )
        assert state.metadata["agent_version"] == "2.1.500"

    def test_sandbox_probe_runs_as_configured_user(self):
        """When the caller passes ``user=`` so inspect_swe runs the agent
        binary as a non-default sandbox user, the post-run probe must use
        the same user — otherwise PATH may resolve a different ``claude``
        / ``codex`` (or fail to find one) and we'd stamp the wrong binary."""
        captured_users: list[str | None] = []

        async def fake_exec(cmd, **kwargs):
            captured_users.append(kwargs.get("user"))
            res = MagicMock()
            res.success = cmd[0] == "which"
            res.stdout = "/usr/local/bin/claude\n" if cmd[0] == "which" else ""
            return res

        mock_sandbox = MagicMock()
        mock_sandbox.exec = fake_exec

        with (
            patch("inspect_swe.claude_code") as mock_cc,
            patch("inspect_swe.codex_cli"),
            patch("inspect_swe.gemini_cli"),
            patch("inspect_swe.mini_swe_agent"),
            patch("inspect_swe.opencode"),
            patch(
                "agent_baselines.solvers.inspect_swe.agent.resolve_skills",
                return_value=ResolvedSkills(),
            ),
            patch("inspect_ai.util.sandbox", return_value=mock_sandbox),
        ):
            from agent_baselines.solvers.inspect_swe.agent import inspect_swe_solver

            mock_cc.return_value = AsyncMock(return_value=MagicMock())
            solver = inspect_swe_solver(agent="claude_code", user="appuser")
            state = MagicMock()
            state.metadata = {}
            state.tools = []
            import asyncio

            asyncio.run(solver(state, AsyncMock()))
        assert (
            "appuser" in captured_users
        ), f"sandbox probes did not forward user=appuser; saw users={captured_users}"

    def test_auto_prefers_sandbox_binary_over_host_cache(self):
        """In ``auto`` mode inspect_swe first probes the sandbox via
        ``which <binary>`` and reuses any pre-installed binary; it only
        touches the host cache when nothing is on PATH. Our resolver
        mirrors that: when ``which`` finds the binary, exec ``--version``
        for the ground-truth value (the host cache may be stale)."""
        fake_binaries = _fake_cached_binaries([("2.1.999", 9999.0)])
        with patch("inspect_swe.cached_agent_binaries", return_value=fake_binaries):
            _, state, _ = _run_solver(
                agent="claude_code",
                version="auto",
                sandbox_responses={
                    "sandbox_binary_path": "/usr/local/bin/claude",
                    "sandbox_binary_version": "2.1.500\n",
                },
            )
        assert state.metadata["agent_version"] == "2.1.500"

    def test_auto_falls_back_to_cache_when_binary_not_on_path(self):
        """When ``which <binary>`` fails (inspect_swe downloaded to its
        install dir, not on PATH), use the host cache as authoritative."""
        fake_binaries = _fake_cached_binaries([("2.1.128", 9999.0)])
        with patch("inspect_swe.cached_agent_binaries", return_value=fake_binaries):
            _, state, _ = _run_solver(agent="claude_code", version="auto")
        assert state.metadata["agent_version"] == "2.1.128"

    def test_resolver_returns_none_leaves_slot_unset(self, caplog):
        """When a resolver exists but returned nothing (empty host cache,
        broken upstream import), leave the slot unset — the missing key
        IS the signal: the suite README's jq extraction fails loudly when
        the operator tries to extract for arm B. Warn for live visibility."""
        import logging

        with caplog.at_level(logging.WARNING):
            with patch("inspect_swe.cached_agent_binaries", return_value=[]):
                _, state, _ = _run_solver(agent="claude_code", version="auto")
        assert "agent_version" not in state.metadata
        assert any(
            "agent_version could not be resolved" in r.message for r in caplog.records
        )

    def test_asta_version_stamped(self):
        _, state, _ = _run_solver(sandbox_responses={"asta_version": "asta 0.17.0\n"})
        assert state.metadata["asta_version"] == "asta 0.17.0"

    def test_no_asta_no_stamp(self):
        """``asta`` missing (non-asta sandbox) — leave the slot empty."""
        _, state, _ = _run_solver(sandbox_responses={"asta_version": None})
        assert "asta_version" not in state.metadata

    def test_asta_probe_runs_as_configured_user(self):
        """When the caller threads ``user=`` through agent_kwargs,
        inspect_swe runs the agent and its skill bash commands as that
        user. The asta probe must use the same user so the stamped
        version reflects the CLI on *that user's* PATH — otherwise a
        custom-user run could stamp the default user's asta (different
        version, or absent) and strict mode would accept incomplete
        provenance."""
        captured_users: list[str | None] = []

        async def fake_exec(cmd, **kwargs):
            captured_users.append(kwargs.get("user"))
            res = MagicMock()
            res.success = cmd == ["asta", "--version"]
            res.stdout = "asta 0.17.0\n" if cmd == ["asta", "--version"] else ""
            return res

        mock_sandbox = MagicMock()
        mock_sandbox.exec = fake_exec

        async def fake_connection(**kwargs):
            raise RuntimeError("no container")

        mock_sandbox.connection = fake_connection
        with (
            patch("inspect_swe.claude_code") as mock_cc,
            patch("inspect_swe.codex_cli"),
            patch("inspect_swe.gemini_cli"),
            patch("inspect_swe.mini_swe_agent"),
            patch("inspect_swe.opencode"),
            patch(
                "agent_baselines.solvers.inspect_swe.agent.resolve_skills",
                return_value=ResolvedSkills(),
            ),
            patch("inspect_ai.util.sandbox", return_value=mock_sandbox),
        ):
            from agent_baselines.solvers.inspect_swe.agent import inspect_swe_solver

            mock_cc.return_value = AsyncMock(return_value=MagicMock())
            solver = inspect_swe_solver(
                agent="claude_code", user="appuser", version="2.1.128"
            )
            state = MagicMock()
            state.metadata = {}
            state.tools = []
            import asyncio

            asyncio.run(solver(state, AsyncMock()))
        # The asta probe (``["asta", "--version"]``) must have been
        # invoked with user="appuser".
        assert "appuser" in captured_users, (
            f"asta_version probe didn't forward user=appuser; "
            f"saw users={captured_users}"
        )


def _fake_docker_inspect(image_id="sha256:fake", digest="", config_image=""):
    """Return a side_effect for ``asyncio.create_subprocess_exec`` that
    fakes ``docker inspect`` calls the solver makes when resolving the
    sandbox image. Three calls in order:
    1. ``docker inspect --format '{{.Image}}' <container>`` → image_id
    2. ``docker image inspect ... '{{...RepoDigests...}}' <image_id>`` → digest
    3. ``docker inspect --format '{{.Config.Image}}' <container>`` → config_image (only if digest empty)
    """
    responses = iter([image_id, digest, config_image])

    async def fake_exec(*args, **kwargs):
        proc = MagicMock()
        proc.returncode = 0
        out = next(responses, "")
        proc.communicate = AsyncMock(return_value=(out.encode(), b""))
        return proc

    return fake_exec


def _fake_cached_binaries(specs):
    """Build a list of objects with ``.version`` + ``.path.stat().st_mtime``
    matching the ``AgentBinary`` shape we read in
    ``_resolve_agent_version_via_cache``."""
    out = []
    for version, mtime in specs:
        stat = MagicMock()
        stat.st_mtime = mtime
        path = MagicMock()
        path.stat.return_value = stat
        b = MagicMock()
        b.version = version
        b.path = path
        out.append(b)
    return out


class TestMCPPaperSearchFiltering:
    """When the ``semantic-scholar`` skill is loaded, the asta CLI provides
    the canonical paper-search path. We filter the MCP equivalents from the
    bridge so the agent doesn't have two surfaces for the same thing."""

    def test_no_skills_bridges_all_state_tools(self):
        kwargs, _, _ = _run_solver(state_tools=[_named_tool("snippet_search")])
        assert "bridged_tools" in kwargs
        assert [ToolDef(t).name for t in kwargs["bridged_tools"][0].tools] == [
            "snippet_search"
        ]

    def test_paper_search_skill_filters_mcp_paper_tools(self, monkeypatch):
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[{"source": "/fake"}],
        )
        kwargs, _, _ = _run_solver(
            skills="/fake",
            resolved=resolved,
            state_tools=[
                _named_tool("snippet_search"),
                _named_tool("get_paper"),
                _named_tool("table_editor"),
            ],
        )
        # Paper-search MCP tools filtered; non-paper passes through.
        assert [ToolDef(t).name for t in kwargs["bridged_tools"][0].tools] == [
            "table_editor"
        ]

    def test_uncovered_mcp_tools_pass_through(self, monkeypatch):
        """get_paper_batch / search_paper_by_title have no asta CLI
        equivalent — they keep the MCP path even when paper-search skills
        are loaded."""
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[{"source": "/fake"}],
        )
        kwargs, _, _ = _run_solver(
            skills="/fake",
            resolved=resolved,
            state_tools=[
                _named_tool("get_paper_batch"),
                _named_tool("search_paper_by_title"),
            ],
        )
        names = [ToolDef(t).name for t in kwargs["bridged_tools"][0].tools]
        assert set(names) == {"get_paper_batch", "search_paper_by_title"}

    def test_non_paper_skill_doesnt_filter(self):
        """Skills that aren't paper-search (e.g. preview, workspace) shouldn't
        trigger MCP paper-tool filtering."""
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/preview")], lock=[{"source": "/fake"}]
        )
        kwargs, _, _ = _run_solver(
            skills="/fake",
            resolved=resolved,
            state_tools=[_named_tool("snippet_search")],
        )
        assert [ToolDef(t).name for t in kwargs["bridged_tools"][0].tools] == [
            "snippet_search"
        ]

    def test_bridge_off_disables_everything(self):
        kwargs, _, _ = _run_solver(
            bridge_astabench_tools=False,
            state_tools=[_named_tool("snippet_search")],
        )
        assert "bridged_tools" not in kwargs


class TestAstaPluginShortcutMissingVendor:
    def test_missing_vendor_dir_raises(self):
        """If setup.sh wasn't run, ``install_asta_skills="asta"`` fails loudly
        before the eval starts."""
        from agent_baselines.solvers.inspect_swe.agent import inspect_swe_solver

        with (
            patch("inspect_swe.claude_code"),
            patch(
                "agent_baselines.solvers.inspect_swe.agent._asta_plugin_skills_ref",
                side_effect=FileNotFoundError("setup.sh not run"),
            ),
        ):
            with pytest.raises(FileNotFoundError):
                inspect_swe_solver(install_asta_skills="asta")


class TestPreflightAuthCheck:
    """When paper-search skills are loaded, the asta CLI inside the sandbox
    needs ASTA_TOKEN for auth. Without it, asta papers silently fails and
    the agent falls back to direct API curls — measuring the fallback
    rather than the skill path. Raise at construction so the operator sees
    it before any sample burns."""

    def test_paper_search_skill_without_asta_token_raises(self, monkeypatch):
        monkeypatch.delenv("ASTA_TOKEN", raising=False)
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[{"source": "/fake"}],
        )
        with pytest.raises(ValueError, match="ASTA_TOKEN required"):
            _run_solver(skills="/fake", resolved=resolved)

    def test_paper_search_skill_with_asta_token_ok(self, monkeypatch):
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[{"source": "/fake"}],
        )
        # should not raise
        _run_solver(skills="/fake", resolved=resolved)

    def test_no_paper_search_skill_no_check(self, monkeypatch):
        """Non-paper-search skills don't need ASTA_TOKEN."""
        monkeypatch.delenv("ASTA_TOKEN", raising=False)
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/preview")], lock=[{"source": "/fake"}]
        )
        _run_solver(skills="/fake", resolved=resolved)

    def test_asta_token_via_extra_env_satisfies_check(self, monkeypatch):
        """Caller can supply ASTA_TOKEN through ``extra_env`` instead of the
        host env. The preflight must inspect the effective env (what gets
        forwarded), not just os.environ."""
        monkeypatch.delenv("ASTA_TOKEN", raising=False)
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[{"source": "/fake"}],
        )
        _run_solver(
            skills="/fake",
            resolved=resolved,
            extra_env={"ASTA_TOKEN": "from-caller"},
        )

    def test_extra_env_empty_token_overrides_host(self, monkeypatch):
        """Caller can explicitly clear ASTA_TOKEN via
        ``extra_env={"ASTA_TOKEN": ""}``. The forwarded env will have an
        empty value; we must catch that and not fall back to the host
        token (which would let the eval run without auth and degrade to
        the fallback path the preflight is meant to prevent)."""
        monkeypatch.setenv("ASTA_TOKEN", "host-token")
        resolved = ResolvedSkills(
            skill_dirs=[Path("/fake/semantic-scholar")],
            lock=[{"source": "/fake"}],
        )
        with pytest.raises(ValueError, match="ASTA_TOKEN required"):
            _run_solver(
                skills="/fake",
                resolved=resolved,
                extra_env={"ASTA_TOKEN": ""},
            )


class TestPreflightVersionMatch:
    """Skill prose embeds ``PLUGIN_VERSION=X.Y.Z``; the asta CLI inside the
    image must match it, else the skill bash snippets bail to a slow
    self-upgrade. When ASTA_IMAGE carries a parseable semver tag, raise on
    mismatch at construction."""

    def _write_skill(self, tmp_path, name, plugin_version=None):
        skill_dir = tmp_path / name
        skill_dir.mkdir()
        body = "---\nname: x\ndescription: y\n---\n"
        if plugin_version:
            body += f"\n```bash\nPLUGIN_VERSION={plugin_version}\n```\n"
        (skill_dir / "SKILL.md").write_text(body)
        return skill_dir

    def test_mismatch_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        skill_dir = self._write_skill(tmp_path, "semantic-scholar", "0.18.0")
        resolved = ResolvedSkills(skill_dirs=[skill_dir], lock=[{"source": "x"}])
        with pytest.raises(ValueError, match="doesn't match skill"):
            _run_solver(skills=str(tmp_path), resolved=resolved)

    def test_match_ok(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        skill_dir = self._write_skill(tmp_path, "semantic-scholar", "0.17.0")
        resolved = ResolvedSkills(skill_dirs=[skill_dir], lock=[{"source": "x"}])
        _run_solver(skills=str(tmp_path), resolved=resolved)

    def test_image_unset_no_check(self, monkeypatch, tmp_path):
        """No image pinned → nothing to compare against; let it through."""
        monkeypatch.delenv("ASTA_IMAGE", raising=False)
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        skill_dir = self._write_skill(tmp_path, "semantic-scholar", "0.18.0")
        resolved = ResolvedSkills(skill_dirs=[skill_dir], lock=[{"source": "x"}])
        _run_solver(skills=str(tmp_path), resolved=resolved)

    def test_image_latest_tag_no_check(self, monkeypatch, tmp_path):
        """``:latest`` isn't a parseable semver; skip the check."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:latest")
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        skill_dir = self._write_skill(tmp_path, "semantic-scholar", "0.18.0")
        resolved = ResolvedSkills(skill_dirs=[skill_dir], lock=[{"source": "x"}])
        _run_solver(skills=str(tmp_path), resolved=resolved)

    def test_skill_without_plugin_version_no_check(self, monkeypatch, tmp_path):
        """Older skill trees without PLUGIN_VERSION → nothing to compare."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")
        monkeypatch.setenv("ASTA_TOKEN", "abc")
        skill_dir = self._write_skill(tmp_path, "semantic-scholar")  # no PLUGIN_VERSION
        resolved = ResolvedSkills(skill_dirs=[skill_dir], lock=[{"source": "x"}])
        _run_solver(skills=str(tmp_path), resolved=resolved)


class TestImageStampVsEnv:
    """``setup.sh`` extracts skills from the asta image and stamps the
    image ID into ``.image-id``. If the operator later overrides
    ``ASTA_IMAGE`` without re-running setup, the host-side skill source
    silently disagrees with the asta CLI in the sandbox.
    ``_check_image_stamps_match_env`` raises in that case for *any*
    image-stamped skill source — both ``install_asta_skills=`` bundled
    paths and direct ``-S skills=<vendor>`` refs."""

    def test_matching_ids_no_raise(self, monkeypatch):
        """Stamp matches what docker resolves → happy path."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")
        monkeypatch.setattr(
            "agent_baselines.solvers.inspect_swe.agent.subprocess.run",
            lambda *a, **kw: MagicMock(stdout="sha256:abc123\n", returncode=0),
        )
        from agent_baselines.solvers.inspect_swe.agent import (
            _check_image_stamps_match_env,
            _resolve_env_image_id,
        )

        env_id = _resolve_env_image_id()
        _check_image_stamps_match_env(
            [{"source": "/x", "image_id": "sha256:abc123"}], env_id
        )

    def test_mismatch_raises(self, monkeypatch):
        """Stamp ≠ current ASTA_IMAGE's docker ID → raise. Catches the
        ``changed ASTA_IMAGE without re-running setup.sh`` footgun
        regardless of how the skill source was specified."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:latest")
        monkeypatch.setattr(
            "agent_baselines.solvers.inspect_swe.agent.subprocess.run",
            lambda *a, **kw: MagicMock(stdout="sha256:def456\n", returncode=0),
        )
        from agent_baselines.solvers.inspect_swe.agent import (
            _check_image_stamps_match_env,
            _resolve_env_image_id,
        )

        env_id = _resolve_env_image_id()
        with pytest.raises(ValueError, match="Re-run solvers/inspect-swe/setup.sh"):
            _check_image_stamps_match_env(
                [{"source": "/x", "image_id": "sha256:abc123"}], env_id
            )

    def test_direct_skills_ref_also_checked(self, monkeypatch):
        """Direct ``-S skills=`` refs that happen to be stamped must
        be verified the same way as bundled ``install_asta_skills=``
        paths. Without this the strict-mode loop would accept a stale
        direct ref via the ``image_id`` short-circuit."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:latest")
        monkeypatch.setattr(
            "agent_baselines.solvers.inspect_swe.agent.subprocess.run",
            lambda *a, **kw: MagicMock(stdout="sha256:def456\n", returncode=0),
        )
        from agent_baselines.solvers.inspect_swe.agent import (
            _check_image_stamps_match_env,
            _resolve_env_image_id,
        )

        env_id = _resolve_env_image_id()
        # Lock entry simulating a direct -S skills= ref under a vendor
        # tree carrying .image-id: same lock shape as the bundled path,
        # so the same check fires.
        direct_ref_lock = [
            {"source": "/some/external/vendor/skills", "image_id": "sha256:abc123"}
        ]
        with pytest.raises(ValueError, match="Re-run"):
            _check_image_stamps_match_env(direct_ref_lock, env_id)

    def test_no_asta_image_env_skips(self, monkeypatch):
        """ASTA_IMAGE unset → can't verify; trust operator (post-run
        ``asta_image`` stamp will still record what actually ran)."""
        monkeypatch.delenv("ASTA_IMAGE", raising=False)
        from agent_baselines.solvers.inspect_swe.agent import (
            _check_image_stamps_match_env,
            _resolve_env_image_id,
        )

        env_id = _resolve_env_image_id()
        assert env_id is None
        _check_image_stamps_match_env(
            [{"source": "/x", "image_id": "sha256:abc123"}], env_id
        )

    def test_docker_unavailable_skips(self, monkeypatch):
        """docker not on PATH → no way to resolve ASTA_IMAGE to an ID."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")

        def fake_run(*args, **kwargs):
            raise FileNotFoundError("docker not installed")

        monkeypatch.setattr(
            "agent_baselines.solvers.inspect_swe.agent.subprocess.run", fake_run
        )
        from agent_baselines.solvers.inspect_swe.agent import (
            _check_image_stamps_match_env,
            _resolve_env_image_id,
        )

        env_id = _resolve_env_image_id()
        assert env_id is None
        _check_image_stamps_match_env(
            [{"source": "/x", "image_id": "sha256:abc123"}], env_id
        )

    def test_entry_without_image_id_ignored(self, monkeypatch):
        """Lock entries lacking an ``image_id`` (non-stamped sources)
        aren't subject to the check."""
        monkeypatch.setenv("ASTA_IMAGE", "ghcr.io/allenai/asta:v0.17.0")
        monkeypatch.setattr(
            "agent_baselines.solvers.inspect_swe.agent.subprocess.run",
            lambda *a, **kw: MagicMock(stdout="sha256:def456\n", returncode=0),
        )
        from agent_baselines.solvers.inspect_swe.agent import (
            _check_image_stamps_match_env,
            _resolve_env_image_id,
        )

        env_id = _resolve_env_image_id()
        # No image_id on the entry → no check.
        _check_image_stamps_match_env([{"source": "/x"}], env_id)
