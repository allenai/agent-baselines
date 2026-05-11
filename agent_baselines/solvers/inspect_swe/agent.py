"""inspect_swe-backed coding agent solvers."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Literal, NamedTuple

from inspect_ai.agent import BridgedToolsSpec
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import ToolDef

from agent_baselines.skills.resolver import resolve_skills
from agent_baselines.solvers.inspect_swe._filters import deny_external_web_tools

logger = logging.getLogger(__name__)

AgentName = Literal[
    "claude_code", "codex_cli", "gemini_cli", "mini_swe_agent", "opencode"
]
AstaPlugin = Literal["asta", "asta-preview"]


class AgentSpec(NamedTuple):
    """Per-agent facts the wrapper needs in one place.

    Centralizing this is the antidote to scattered conditionals — adding
    another inspect_swe agent should be a single registry entry, not a
    grep for every list/map/preflight branch that mentions ``claude_code``.

    Implemented as ``NamedTuple`` rather than ``@dataclass(frozen=True)``
    because inspect_ai loads the solver via ``importlib.util.exec_module``,
    which doesn't register the module in ``sys.modules`` until after
    decorators have run. ``@dataclass`` introspects via
    ``sys.modules.get(cls.__module__).__dict__`` and ``AttributeError``s
    on ``None``. ``NamedTuple`` avoids that path entirely.
    """

    name: AgentName
    # ``inspect_swe`` module attribute name; resolved lazily via
    # ``_constructor()`` so test patches on ``inspect_swe.claude_code``
    # etc. take effect.
    constructor_attr: str
    # Binary name on PATH when the agent is pre-installed in the sandbox
    # image. ``None`` when the agent isn't a single binary on PATH from
    # inspect_swe's perspective (mini_swe_agent: pip-installed; gemini_cli:
    # no post-run probe path — caller must pin).
    sandbox_binary: str | None
    # Whether ``inspect_swe.cached_agent_binaries(<name>)`` is supported
    # upstream. Only ``claude_code`` / ``codex_cli`` are in the public API.
    host_cache_supported: bool
    # Unpinned ``version=`` placeholders the post-run resolver can
    # authoritatively resolve for this agent. An unpinned mode not in
    # this set (and not ``"sandbox"`` — see below) raises at construction
    # so the operator pins before any sample burns.
    resolvable_unpinned_modes: frozenset[str | None]
    # Whether the upstream constructor accepts a ``skills=`` kwarg.
    # mini_swe_agent's inspect_swe constructor (as of 0.2.48) does not —
    # forwarding ``skills=`` would TypeError before any sample runs. We
    # reject at construction-time when the caller asked for skills on an
    # agent that doesn't accept them.
    accepts_skills: bool
    # Optional fallback resolver (no sandbox probe + no host cache).
    # Used by mini_swe_agent: read ``MINI_SWE_AGENT_SOURCE.default_version``
    # from the inspect_swe wheel.
    default_resolver: Callable[[], str | None] | None = None


def _mini_swe_default_version() -> str | None:
    try:
        from inspect_swe._mini_swe_agent.mini_swe_agent import (
            MINI_SWE_AGENT_SOURCE,
        )

        return MINI_SWE_AGENT_SOURCE.default_version
    except Exception:
        return None


_AGENT_SPECS: dict[AgentName, AgentSpec] = {
    "claude_code": AgentSpec(
        name="claude_code",
        constructor_attr="claude_code",
        sandbox_binary="claude",
        host_cache_supported=True,
        # ``sandbox`` is allowed: inspect_swe's auto/sandbox path reuses
        # a preinstalled ``claude`` on PATH when present, so the binary
        # the eval ran is the binary we can probe post-run.
        resolvable_unpinned_modes=frozenset(
            {None, "auto", "stable", "latest", "sandbox"}
        ),
        accepts_skills=True,
    ),
    "codex_cli": AgentSpec(
        name="codex_cli",
        constructor_attr="codex_cli",
        sandbox_binary="codex",
        host_cache_supported=True,
        resolvable_unpinned_modes=frozenset(
            {None, "auto", "stable", "latest", "sandbox"}
        ),
        accepts_skills=True,
    ),
    "gemini_cli": AgentSpec(
        name="gemini_cli",
        constructor_attr="gemini_cli",
        # gemini_cli's inspect_swe setup downloads via the GitHub releases
        # API regardless of what's already in the sandbox — ``sandbox``
        # mode therefore drifts run-to-run. No resolver path can recover
        # the actually-installed version, so leave this empty: the
        # construction-time gate rejects every unpinned mode.
        sandbox_binary=None,
        host_cache_supported=False,
        resolvable_unpinned_modes=frozenset(),
        accepts_skills=True,
    ),
    "mini_swe_agent": AgentSpec(
        name="mini_swe_agent",
        constructor_attr="mini_swe_agent",
        sandbox_binary=None,  # pip-installed inside sandbox
        host_cache_supported=False,
        resolvable_unpinned_modes=frozenset({None, "stable"}),
        default_resolver=_mini_swe_default_version,
        # mini_swe_agent's constructor (verified through inspect_swe
        # 0.2.54) has no ``skills`` parameter; forwarding one would
        # TypeError at construction. Rejected by the gate below so the
        # caller sees a clean error instead of a stack trace.
        accepts_skills=False,
    ),
    "opencode": AgentSpec(
        # Structurally similar to gemini_cli: every ``version=`` mode
        # (auto/sandbox/stable/latest) resolves to the latest GitHub
        # release and installs via npm to a fixed inspect-swe path,
        # not a system-PATH binary. No public host cache
        # (``cached_agent_binaries("opencode")`` raises). So every
        # unpinned mode is unresolvable post-run → reject at
        # construction, caller pins a concrete version.
        name="opencode",
        constructor_attr="opencode",
        sandbox_binary=None,
        host_cache_supported=False,
        resolvable_unpinned_modes=frozenset(),
        accepts_skills=True,
    ),
}

# Per-mode resolution policy. inspect_swe behaves differently per
# version=... mode and we have to mirror it to stamp the binary that
# *actually* ran:
# - ``auto`` (and unset): reuses a preinstalled sandbox binary if on PATH;
#   else downloads to the host cache. Probe sandbox first, fall back to
#   cache.
# - ``sandbox``: must use the preinstalled sandbox binary; never touches
#   the host cache. Probe sandbox only — falling back to cache would
#   stamp a stale entry from a previous run.
# - ``stable`` / ``latest``: always downloads to the host cache; doesn't
#   reuse a preinstalled binary. Probe the cache only — probing the
#   sandbox would stamp a different binary than the one inspect_swe
#   actually invoked.
_SANDBOX_PROBE_MODES: frozenset[str | None] = frozenset({None, "auto", "sandbox"})
_HOST_CACHE_MODES: frozenset[str | None] = frozenset({None, "auto", "stable", "latest"})
_DEFAULT_RESOLVER_MODES: frozenset[str | None] = frozenset({None, "stable"})


def _constructor(spec: AgentSpec) -> Any:
    """Resolve the inspect_swe constructor for ``spec`` against the
    *current* ``inspect_swe`` module so test patches on
    ``inspect_swe.claude_code`` etc. take effect. Errors here surface
    at solver-construction time rather than module load."""
    try:
        import inspect_swe
    except ImportError as e:
        logger.error(
            "inspect_swe import failed (%s). Invoke via "
            "`uv run --project solvers/inspect-swe`.",
            e,
        )
        raise
    return getattr(inspect_swe, spec.constructor_attr)


# Modes the user might pass that aren't a concrete semver. Anything in
# this set that's not in a particular agent's ``resolvable_unpinned_modes``
# (and isn't ``"sandbox"``) is rejected at construction.
_UNPINNED_VERSION_MODES: frozenset[str | None] = frozenset(
    {None, "auto", "stable", "latest", "sandbox"}
)

_VENDOR_ASTA_PLUGINS = (
    Path(__file__).resolve().parents[3]
    / "solvers"
    / "inspect-swe"
    / ".vendor"
    / "asta-plugins"
)

# MCP paper-search tools with a 1:1 `asta papers` CLI subcommand; filtered
# from the bridge when any of these skill names are installed so the agent
# has one canonical paper-search path.
_PAPER_SEARCH_SKILLS = frozenset({"semantic-scholar"})
_ASTA_MCP_PAPER_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "snippet_search",
        "search_papers_by_relevance",
        "get_paper",
        "get_citations",
        "search_authors_by_name",
        "get_author_papers",
    }
)


_PLUGIN_VERSION_RE = re.compile(r"PLUGIN_VERSION=([\d.]+)")
_ASTA_IMAGE_VERSION_RE = re.compile(r":v([\d.]+)$")


def _check_plugin_image_version_match(skill_dirs: list[Path]) -> None:
    """Raise if ``ASTA_IMAGE`` carries a parseable semver tag that differs
    from the ``PLUGIN_VERSION`` baked into the loaded skill files.

    Skipped (no raise) when:
    - No skills are loaded.
    - ``ASTA_IMAGE`` isn't set or isn't a ``:vX.Y.Z`` tag (e.g. ``:latest``,
      ``@sha256:...``) — there's nothing to compare against.
    - Skill files don't declare ``PLUGIN_VERSION`` (older trees).
    - Multiple skill versions co-exist (caller is mid-iteration; let them
      figure it out rather than block).
    """
    if not skill_dirs:
        return
    image = os.environ.get("ASTA_IMAGE", "")
    m = _ASTA_IMAGE_VERSION_RE.search(image)
    if not m:
        return
    image_version = m.group(1)

    # ``skill_dirs`` is the list of individual skill directories (parents of
    # SKILL.md), not the skill-tree root. Read SKILL.md from each directly.
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


def _asta_plugin_skills_ref(plugin: AstaPlugin) -> str:
    plugin_dir = _VENDOR_ASTA_PLUGINS / "plugins" / plugin / "skills"
    if not plugin_dir.is_dir():
        raise FileNotFoundError(
            f"Bundled skills not found at {plugin_dir}. "
            f"Run solvers/inspect-swe/setup.sh to extract bundled skills "
            f"from the asta image."
        )
    return str(plugin_dir)


def _resolve_env_image_id() -> str | None:
    """Docker-resolved image ID for ``ASTA_IMAGE``, or None when
    ``ASTA_IMAGE`` is unset / docker unreachable / image not locally
    pulled. Used to verify image-stamped skill sources match the asta
    image the sandbox will actually run.
    """
    env_image = os.environ.get("ASTA_IMAGE", "")
    if not env_image:
        return None
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", env_image],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return None
    return result.stdout.strip() or None


def _check_image_stamps_match_env(lock: list[dict], env_image_id: str | None) -> None:
    """Raise if any skill source carries an ``image_id`` stamp that
    doesn't match the docker-resolved ``ASTA_IMAGE``.

    Catches the ``operator changed ASTA_IMAGE without re-running
    setup.sh`` footgun for *any* image-stamped skill source — both
    bundled (``install_asta_skills=...``) and direct
    (``-S skills=<vendor path>``). Compares immutable image IDs so it
    works for tags, ``:latest``, and ``@sha256:`` digests alike.

    No-op when ``env_image_id`` is None (ASTA_IMAGE unset, docker
    unreachable, or image not locally pulled — can't verify; the
    post-run ``asta_image`` stamp will still record what actually ran).
    """
    if env_image_id is None:
        return
    for entry in lock:
        stamped = entry.get("image_id")
        if stamped and stamped != env_image_id:
            raise ValueError(
                f"Skill source {entry['source']!r} was extracted from "
                f"image {stamped[:19]} but ASTA_IMAGE resolves to "
                f"{env_image_id[:19]}. Re-run solvers/inspect-swe/setup.sh "
                f"against the current ASTA_IMAGE, or pin ASTA_IMAGE to "
                f"the stamped image."
            )


@solver
def inspect_swe_solver(
    agent: AgentName = "claude_code",
    skills: str | list[str] | None = None,
    install_asta_skills: AstaPlugin | None = None,
    bridge_astabench_tools: bool = True,
    deny_external_web: bool = True,
    system_prompt: str | None = None,
    max_attempts: int = 1,
    sandbox_name: str | None = None,
    extra_env: dict[str, str] | None = None,
    strict_reproducibility: bool = False,
    **agent_kwargs: Any,
) -> Solver:
    """Solver wrapping any of the inspect_swe coding agents.

    Args:
        agent: Which inspect_swe agent to run.
        skills: Local directory path (or list of paths) holding SKILL.md
            trees to install. Each path is resolved relative to cwd if not
            absolute. Resolution lock (source + content hash + skill names,
            plus git origin/sha/path_in_repo/path_dirty when the path is
            inside a git working tree) is written to
            ``state.metadata["skills"]``.
        install_asta_skills: Sugar for ``skills="<.vendor>/plugins/<plugin>/skills"``.
        bridge_astabench_tools: Forward state.tools to the agent as
            ``mcp__astabench_*``. Set False for agent-only mode.
        deny_external_web: Strip provider-side WebSearch/WebFetch from every
            model API request via the bridge filter.
        system_prompt: Extra system prompt appended to the agent's defaults.
        max_attempts: Number of attempts before giving up (1 = single attempt).
        sandbox_name: For multi-service compose; set to the service name the
            coding agent should run in.
        extra_env: Extra env vars injected into the agent's sandbox process.
        strict_reproducibility: Promote reproducibility-warning conditions
            to raises so a benchmark run can't silently produce a log
            without full provenance. Off by default for ad-hoc runs.
            See ``state.metadata["reproducibility_warnings"]`` for the
            structured warning list emitted in both modes; in strict mode,
            any non-empty list at the end of a sample raises ``RuntimeError``,
            and skills with uncommitted/ignored content (``path_dirty: True``
            in the skills lock) raise at construction.
        **agent_kwargs: Forwarded verbatim to the underlying inspect_swe
            constructor (e.g. ``disallowed_tools=...``, ``version=...``).
    """

    if agent not in _AGENT_SPECS:
        raise ValueError(f"Unknown agent {agent!r}; choose from {sorted(_AGENT_SPECS)}")
    spec = _AGENT_SPECS[agent]
    constructor = _constructor(spec)

    # Reject ambiguous kwargs that would silently bypass the wrapper's
    # invariants:
    # - ``env=``: would override the wrapper-built env after our preflight
    #   checked ``base_env`` (e.g. ASTA_TOKEN, insertion-date vars), so the
    #   constructor could end up with a different env than what the checks
    #   validated. Use ``extra_env=`` instead.
    # - ``sandbox=``: the wrapper has ``sandbox_name=`` and post-run probes
    #   read it; allowing both would let the agent run in one service while
    #   probes target another. Use ``sandbox_name=``.
    if "env" in agent_kwargs:
        raise ValueError(
            "Pass env vars via the wrapper's ``extra_env=`` parameter, not "
            "via agent_kwargs (env=). The wrapper merges extra_env with "
            "host ASTA_TOKEN and runs preflight checks on the merged env; "
            "an env= passed through agent_kwargs would override that "
            "silently."
        )
    if "sandbox" in agent_kwargs and sandbox_name is not None:
        raise ValueError(
            "Pass the sandbox name via the wrapper's ``sandbox_name=`` "
            "parameter only; ``sandbox=`` in agent_kwargs conflicts with "
            "it and ambiguates which service the post-run probes target."
        )

    refs: list[str] = []
    if install_asta_skills is not None:
        refs.append(_asta_plugin_skills_ref(install_asta_skills))
    if isinstance(skills, str):
        refs.append(skills)
    elif skills:
        refs.extend(skills)
    # NOTE: skill resolution is deferred to ``execute`` (per-sample) so
    # the stamped ``content_sha256`` / ``path_dirty`` always describe
    # what the inspect_swe constructor sees for *that* sample. inspect_swe
    # re-reads SKILL.md per sample, so if a caller edits or rebuilds a
    # ``-S skills=`` tree mid-eval, the lock for later samples reflects
    # the actually-installed bytes — not a stale construction-time
    # snapshot. Skill-derived preflights (strict-mode skill checks,
    # ``accepts_skills``, ``ASTA_TOKEN``, ``PLUGIN_VERSION``) run at the
    # start of each sample's ``execute`` so the first sample fails fast
    # if a static condition is violated.

    # Fail at construction (before any sample burns compute) when the
    # caller's version is a drifty placeholder that this agent can't
    # resolve post-run. For example, gemini_cli's inspect_swe setup
    # downloads via GitHub releases for every mode (no sandbox-PATH
    # reuse, no public host cache), so every unpinned mode is rejected
    # — eval logs would otherwise never carry the actual CLI version.
    # mini_swe_agent + ``latest`` is a similar lesser case: ``stable``
    # resolves but ``latest`` doesn't; we let the run proceed (some
    # eval setups deliberately pick latest) but the post-run resolver
    # leaves ``agent_version`` unset.
    req_ver_init = agent_kwargs.get("version")
    if req_ver_init in _UNPINNED_VERSION_MODES and not spec.resolvable_unpinned_modes:
        raise ValueError(
            f"Cannot resolve agent_version for agent={agent!r} with version={req_ver_init!r}: "
            f"no post-run resolver available for this agent. "
            f"Pass `-S version=<x.y.z>` to pin a concrete CLI version."
        )

    base_env: dict[str, str] = dict(extra_env or {})
    if asta_token := os.environ.get("ASTA_TOKEN"):
        base_env.setdefault("ASTA_TOKEN", asta_token)

    # Resolve ASTA_IMAGE → image ID once at construction; per-sample
    # ``_check_image_stamps_match_env`` then does cheap string compares
    # against each entry's ``image_id`` stamp without re-probing docker.
    env_image_id = _resolve_env_image_id()

    async def execute(state: TaskState, generate: Generate) -> TaskState:
        # Re-resolve skills *per sample* so the stamped lock describes
        # the bytes inspect_swe is about to install for this sample —
        # not the bytes that happened to exist when the solver was
        # constructed. inspect_swe's constructor (invoked below) re-
        # reads SKILL.md every time, so edits or rebuilds to a local
        # ``-S skills=`` tree between samples would otherwise install
        # the new bytes while ``state.metadata['skills']`` still
        # described the old ones.
        resolved = resolve_skills(refs)

        # Any ``.image-id``-stamped skill source must match the asta
        # image the sandbox will run, regardless of how it was passed
        # (``install_asta_skills=`` or ``-S skills=`` directly). Without
        # this check a direct ref to a stale vendor tree would let
        # host-side skills come from image A while the in-sandbox asta
        # CLI runs image B.
        _check_image_stamps_match_env(resolved.lock, env_image_id)

        # Skill-derived preflights. Static conditions (agent doesn't
        # accept skills, strict-mode skill gates, ASTA_TOKEN required,
        # PLUGIN_VERSION mismatch) raise on the first sample that hits
        # them — saves compute on subsequent samples but doesn't carry
        # the construction-time fail-fast guarantee.
        if resolved.skill_dirs and not spec.accepts_skills:
            raise ValueError(
                f"agent={agent!r} doesn't support ``skills=``/``install_asta_skills=`` "
                f"(its inspect_swe constructor has no ``skills`` parameter). "
                f"Drop the skills knob, or pick a different agent."
            )
        if strict_reproducibility:
            for entry in resolved.lock:
                image_id = entry.get("image_id")
                if image_id and env_image_id is not None:
                    # Image-derived provenance is reproducible by re-running
                    # ``solvers/inspect-swe/setup.sh`` against the stamped
                    # image. ``_check_image_stamps_match_env`` above raises
                    # on mismatch, so reaching here with ``env_image_id``
                    # set means the stamp was verified; accept the entry
                    # regardless of git block state.
                    continue
                if image_id:
                    # Image-stamped but unverified. The resolver may have
                    # decided ``path_dirty=False`` on the assumption that
                    # ``image_id`` supplies valid provenance (image-stamped
                    # vendor trees are typically gitignored — without that
                    # assumption ``path_dirty`` would be forced True). With
                    # the assumption now disproven, neither image_id (un-
                    # verified) nor the git block (potentially relaxed
                    # because of the unverified image_id) is sufficient.
                    # Reject explicitly rather than falling through.
                    raise ValueError(
                        f"strict_reproducibility: skill source "
                        f"{entry['source']!r} has an unverified .image-id "
                        f"stamp (image_id={image_id[:19]}) — ASTA_IMAGE "
                        f"wasn't resolvable (unset, docker unavailable, "
                        f"or image not locally pulled) so the stamp "
                        f"couldn't be checked against the running image. "
                        f"Set ASTA_IMAGE so the stamp can be verified, or "
                        f"unset strict_reproducibility for ad-hoc."
                    )
                git = entry.get("git")
                if git is None:
                    raise ValueError(
                        f"strict_reproducibility: skill source {entry['source']!r} "
                        f"isn't inside a git working tree — eval log can't carry "
                        f"origin/sha for it. Move it under a git repo or unset "
                        f"strict_reproducibility for ad-hoc runs."
                    )
                if git.get("path_dirty"):
                    raise ValueError(
                        f"strict_reproducibility: skill source {entry['source']!r} "
                        f"is dirty (uncommitted, untracked, or git-ignored "
                        f"content). Commit and clean before strict runs, or "
                        f"unset strict_reproducibility for ad-hoc."
                    )
                if not git.get("origin"):
                    # A local-only repo (no ``origin`` remote) has a sha
                    # but no clone URL for a reviewer to fetch from —
                    # the eval log isn't reproducible by anyone but the
                    # original author. Require an origin in strict mode.
                    raise ValueError(
                        f"strict_reproducibility: skill source {entry['source']!r} "
                        f"has no ``origin`` remote — a reviewer can't fetch the "
                        f"recorded sha. Push the repo and add an origin remote, "
                        f"or unset strict_reproducibility for ad-hoc."
                    )

        paper_search_loaded = any(
            d.name in _PAPER_SEARCH_SKILLS for d in resolved.skill_dirs
        )

        # Pre-flight: ASTA_TOKEN required when the asta CLI inside the
        # sandbox will be exercised by a paper-search skill. Without it
        # the CLI rejects auth and the agent silently falls back to
        # direct API curls, so the eval measures the fallback rather
        # than the skill path. Check only the forwarded value
        # (``base_env``) — the host's ``ASTA_TOKEN`` has already been
        # merged into ``base_env`` via setdefault above, so this catches
        # both "host unset and caller didn't supply" and "caller
        # explicitly cleared the token via extra_env={ASTA_TOKEN: ''}".
        if paper_search_loaded and not base_env.get("ASTA_TOKEN"):
            raise ValueError(
                "ASTA_TOKEN required when paper-search skills are loaded "
                "(the asta CLI inside the sandbox uses it for auth). "
                "Run on host: `asta auth login && export ASTA_TOKEN=$(asta auth "
                "print-token --raw --refresh)`."
            )

        # Pre-flight: PLUGIN_VERSION embedded in the loaded skills must
        # match the asta CLI inside the image, else the skill bash
        # snippets bail to a slow self-upgrade. Skip when the image tag
        # isn't a parseable semver (`:latest`, digest, unset) — only
        # raise on a clear mismatch.
        _check_plugin_image_version_match(resolved.skill_dirs)

        if resolved.lock:
            state.metadata["skills"] = resolved.lock
        # Stamping inspect_swe pins the wrapper protocol (bridge, MCP wiring,
        # binary-install layout). For claude_code / codex_cli the CLI binary
        # also drifts when version="auto" because "stable" / "latest" resolve
        # to upstream's current release — the post-run resolver in the
        # ``finally`` block below stamps the actual version that ran (sandbox
        # probe first, host cache fallback). If the caller pinned a concrete
        # version, take it as-is here and skip the post-run probe.
        try:
            import inspect_swe

            state.metadata["inspect_swe_version"] = inspect_swe.__version__
        except Exception:
            pass
        if (
            req_ver := agent_kwargs.get("version")
        ) and req_ver not in _UNPINNED_VERSION_MODES:
            state.metadata["agent_version"] = str(req_ver)

        env = dict(base_env)
        if insertion_date := state.metadata.get("insertion_date"):
            env.setdefault("ASTA_INSERTED_BEFORE", str(insertion_date))
            env.setdefault("ASTA_PUBLICATION_DATE_RANGE", f":{insertion_date}")

        kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "attempts": max_attempts,
            "env": env or None,
            "skills": resolved.skill_dirs or None,
            **agent_kwargs,
        }
        if deny_external_web:
            kwargs.setdefault("filter", deny_external_web_tools)
        if sandbox_name is not None:
            kwargs["sandbox"] = sandbox_name

        if bridge_astabench_tools and state.tools:
            tools_to_bridge = list(state.tools)
            if paper_search_loaded:
                tools_to_bridge = [
                    t
                    for t in tools_to_bridge
                    if ToolDef(t).name not in _ASTA_MCP_PAPER_TOOL_NAMES
                ]
            if tools_to_bridge:
                kwargs["bridged_tools"] = [
                    BridgedToolsSpec(name="astabench", tools=tools_to_bridge)
                ]

        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        agent_obj = constructor(**kwargs)
        # The constructor-time gate rejects both ``sandbox_name=`` and
        # ``agent_kwargs["sandbox"]`` being set, so exactly one source
        # (or neither) is in play. Read the value back off the final
        # kwargs to match whatever the agent constructor saw — that's
        # the service the post-run probes need to target.
        probe_sandbox_name = kwargs.get("sandbox")
        agent_succeeded = False
        try:
            result = await agent_obj(state)
            agent_succeeded = True
        finally:
            # Best-effort post-run stamping. Three probes target disjoint
            # metadata keys (asta_version / asta_image / agent_version), so
            # run them concurrently — at 100+ parallel samples this saves
            # 200+ serial sandbox execs. Failures inside any probe must not
            # poison an otherwise-good run; each appends to
            # ``reproducibility_warnings`` when it leaves a slot unset, so
            # consumers get a structured signal regardless of strict mode.
            # ``user=`` is forwarded so sandbox probes run as the same user
            # inspect_swe invoked the agent under — a different PATH would
            # stamp the wrong preinstalled version (or miss the binary).
            sandbox_user = agent_kwargs.get("user")
            requested_version = agent_kwargs.get("version")
            await asyncio.gather(
                _stamp_asta_version(state, probe_sandbox_name, sandbox_user),
                _stamp_asta_image_digest(state, probe_sandbox_name),
                _stamp_agent_version(
                    state,
                    agent,
                    spec,
                    requested_version,
                    probe_sandbox_name,
                    sandbox_user,
                ),
            )
        # Strict mode: any reproducibility gap that survived the stamping
        # pass promotes the warning list to a raise. Only fires when the
        # agent itself completed — if the agent already raised, that
        # exception is propagating and a strict raise here would mask it.
        if strict_reproducibility and agent_succeeded:
            warnings = state.metadata.get("reproducibility_warnings", [])
            if warnings:
                raise RuntimeError(
                    "strict_reproducibility: eval log has provenance gaps "
                    f"(state.metadata['reproducibility_warnings']={warnings}). "
                    "Pin the missing axes or unset strict_reproducibility for "
                    "ad-hoc runs."
                )
        return result

    return execute


def _record_repro_warning(state: TaskState, msg: str) -> None:
    """Append a reproducibility-warning string to ``state.metadata`` and
    log at WARNING level for live-run visibility. Consumers can read the
    list to detect provenance gaps without scanning logs; strict mode
    promotes the list to a raise at the end of the sample."""
    state.metadata.setdefault("reproducibility_warnings", []).append(msg)
    logger.warning("%s", msg)


async def _stamp_asta_version(
    state: TaskState, sandbox_name: str | None, sandbox_user: str | None
) -> None:
    """Read ``asta --version`` from the sandbox and stamp it. Best-effort:
    if ``asta`` isn't on PATH (non-asta sandbox) we leave the slot unset
    silently — that's expected for non-paper-search runs. If exec fails
    for any other reason, record a reproducibility warning so reviewers
    know the eval log is missing one axis of provenance.

    Runs as ``sandbox_user`` so the probed PATH matches the user
    inspect_swe ran the agent as — otherwise a custom-user run could
    stamp the default user's ``asta`` (different version, or absent)."""
    from inspect_ai.util import sandbox

    try:
        sbx = sandbox(sandbox_name) if sandbox_name else sandbox()
        res = await sbx.exec(["asta", "--version"], timeout=10, user=sandbox_user)
    except Exception as e:
        _record_repro_warning(
            state, f"asta_version probe raised {e!r}; slot left unset"
        )
        return
    if res.success and (line := res.stdout.strip()):
        state.metadata["asta_version"] = line
    elif res.success:
        _record_repro_warning(
            state, "asta --version returned empty output; slot left unset"
        )


async def _stamp_asta_image_digest(state: TaskState, sandbox_name: str | None) -> None:
    """Resolve the running sandbox container's image to its registry
    digest (e.g. ``ghcr.io/allenai/asta@sha256:...``). Resolution chain:

    1. ``docker inspect`` on the container → ``RepoDigests[0]`` (registry digest).
    2. Compose's ``image:`` value (the tag/@digest the user supplied) when
       no registry digest is available (locally-built images, etc.).
    3. ``ASTA_IMAGE`` env var when the sandbox isn't reachable as a docker
       container (e.g. non-docker sandbox) — coarser provenance but at
       least records what the operator requested.

    Overrides any pre-run env-var stamp so the recorded value is what
    *actually* ran, not what was requested. Logs a warning if every
    resolver in the chain fails and leaves the slot unset."""
    from inspect_ai.util import sandbox

    container: str | None = None
    try:
        sbx = sandbox(sandbox_name) if sandbox_name else sandbox()
        conn = await sbx.connection()
        container = getattr(conn, "container", None)
    except Exception as e:
        logger.debug("asta_image: sandbox connection failed (%s)", e)

    if container:

        async def _docker(*args: str) -> str | None:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            except Exception:
                return None
            if proc.returncode != 0:
                return None
            return stdout.decode().strip() or None

        image_id = await _docker("inspect", "--format", "{{.Image}}", container)
        if image_id:
            digest = await _docker(
                "image",
                "inspect",
                "--format",
                "{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}",
                image_id,
            )
            if digest:
                state.metadata["asta_image"] = digest
                return

        if tag := await _docker("inspect", "--format", "{{.Config.Image}}", container):
            state.metadata["asta_image"] = tag
            _warn_if_mutable_image(state, tag)
            return

    # No reachable docker container — fall back to whatever the operator
    # requested via env. Coarser than a registry digest (the running tag
    # could have been re-pushed since launch) but better than nothing.
    if env_image := os.environ.get("ASTA_IMAGE"):
        state.metadata["asta_image"] = env_image
        _warn_if_mutable_image(state, env_image)
        return

    _record_repro_warning(
        state,
        "asta_image could not be resolved (no docker container reachable "
        "and ASTA_IMAGE unset); slot left unset",
    )


def _warn_if_mutable_image(state: TaskState, image: str) -> None:
    """A registry-digest reference (``...@sha256:...``) is immutable; any
    other form is a tag the registry can re-push. Record a warning so
    reviewers know the asta_image stamp doesn't pin to bytes — and so
    strict mode promotes it to a raise."""
    if "@sha256:" not in image:
        _record_repro_warning(
            state,
            f"asta_image={image!r} resolved to a mutable tag (no @sha256: digest); "
            f"the registry can re-push the same tag, so the eval log won't pin "
            f"to immutable bytes. Set ASTA_IMAGE to a @sha256: digest for "
            f"benchmark runs.",
        )


async def _stamp_agent_version(
    state: TaskState,
    agent: AgentName,
    spec: AgentSpec,
    version: Any | None,
    sandbox_name: str | None,
    sandbox_user: str | None,
) -> None:
    """Resolve the CLI version that just ran and stamp it. No-op when the
    early stamping block already wrote a pinned ``agent_version``;
    otherwise probes per ``spec.resolvable_unpinned_modes`` and records a
    reproducibility warning when nothing resolves.

    Per-mode policy mirrors what inspect_swe actually does for each
    ``version=`` choice so we stamp the binary that ran, not the wrong one:

    - ``auto`` / unset: inspect_swe reuses a sandbox-PATH binary when
      present, else downloads to the host cache. Probe sandbox, fall
      back to cache.
    - ``sandbox``: inspect_swe *must* use a sandbox-PATH binary. Probe
      sandbox only — host cache may carry a stale entry from a previous
      run and reading it would lie about what just ran.
    - ``stable`` / ``latest``: inspect_swe always downloads to the host
      cache; never reuses a preinstalled binary. Probe cache only —
      probing the sandbox would stamp a different binary than the one
      inspect_swe actually invoked (e.g. an older preinstalled CLI).
    - mini_swe_agent ``stable``: hardcoded ``default_version`` in the
      inspect_swe wheel — read it directly.
    """
    if "agent_version" in state.metadata:
        return
    resolved: str | None = None
    if version in spec.resolvable_unpinned_modes:
        if version in _SANDBOX_PROBE_MODES and spec.sandbox_binary is not None:
            resolved = await _agent_version_from_sandbox(
                spec.sandbox_binary, sandbox_name, sandbox_user
            )
        if (
            resolved is None
            and version in _HOST_CACHE_MODES
            and spec.host_cache_supported
        ):
            resolved = _agent_version_from_host_cache(agent)
        if (
            resolved is None
            and version in _DEFAULT_RESOLVER_MODES
            and spec.default_resolver is not None
        ):
            resolved = spec.default_resolver()
    if resolved:
        state.metadata["agent_version"] = resolved
    else:
        _record_repro_warning(
            state,
            f"agent_version could not be resolved for agent={agent!r}; "
            f"eval log will not carry it. Rerun with `-S version=<x.y.z>` "
            f"to record the agent CLI version.",
        )


_SEMVER_TOKEN_RE = re.compile(r"\d+\.\d+\.\d+(?:-[^\s]+)?")


async def _agent_version_from_sandbox(
    binary: str, sandbox_name: str | None, sandbox_user: str | None
) -> str | None:
    """Query ``<binary> --version`` in the sandbox if it's on PATH (i.e.
    pre-installed in the image). Probes run as ``sandbox_user`` to match
    the PATH inspect_swe saw when picking the binary (a non-default user
    can have a different PATH and resolve a different ``claude`` /
    ``codex``). Returns None when the binary isn't on PATH — caller
    should fall back to the host cache (download mode)."""
    from inspect_ai.util import sandbox

    try:
        sbx = sandbox(sandbox_name) if sandbox_name else sandbox()
        which = await sbx.exec(["which", binary], timeout=5, user=sandbox_user)
    except Exception:
        return None
    if not which.success or not which.stdout.strip():
        return None
    path = which.stdout.strip()
    try:
        res = await sbx.exec([path, "--version"], timeout=5, user=sandbox_user)
    except Exception:
        return None
    if not res.success:
        return None
    # claude/codex/gemini all print a line like "x.y.z" or "claude x.y.z".
    # Take the last token that looks like a semver.
    for token in res.stdout.strip().split():
        if _SEMVER_TOKEN_RE.fullmatch(token):
            return token
    return res.stdout.strip() or None


def _agent_version_from_host_cache(agent: AgentName) -> str | None:
    """Newest-mtime entry from inspect_swe's host-side cache. inspect_swe
    ``touch()``es on every hit, so newest-mtime = what just ran (only
    when inspect_swe actually used the cache, i.e. downloaded rather than
    reusing a pre-installed sandbox binary)."""
    try:
        from inspect_swe import cached_agent_binaries

        binaries = cached_agent_binaries(agent, quiet=True)
        if not binaries:
            return None
        newest = max(binaries, key=lambda b: b.path.stat().st_mtime)
        return newest.version
    except Exception:
        return None


@solver
def claude_code_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="claude_code", **kwargs)


@solver
def codex_cli_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="codex_cli", **kwargs)


@solver
def gemini_cli_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="gemini_cli", **kwargs)


@solver
def mini_swe_agent_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="mini_swe_agent", **kwargs)


@solver
def opencode_solver(**kwargs: Any) -> Solver:
    return inspect_swe_solver(agent="opencode", **kwargs)
