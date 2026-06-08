# inspect_swe coding agents

Wraps the [inspect_swe](https://meridianlabs-ai.github.io/inspect_swe/)
coding agents (claude_code, codex_cli, gemini_cli, mini_swe_agent,
opencode) as asta-bench solvers. The agent runs inside the sample sandbox; its
model API calls are proxied back to Inspect via `sandbox_agent_bridge`,
so token usage, transcript, model aliases, and limits all flow through
standard Inspect infrastructure.

## Setup

This solver is configured as a per-solver uv sub-project in `solvers/inspect-swe/pyproject.toml`.

```bash
./solvers/inspect-swe/setup.sh
```

## Auth

- `ASTA_TOOL_KEY` (host env) — used by astabench's asta MCP tools the
  task wires (`x-api-key` to the gateway). Always required when running
  a paper-search task.
- `ASTA_TOKEN` (JWT) — used by the `asta` CLI inside the agent container
  when `install_asta_skills` is set. Get it from the host's asta auth:

  ```bash
  asta auth login                                  # one-time per host
  export ASTA_TOKEN="$(asta auth print-token --raw --refresh)"
  ```

  The solver propagates `ASTA_TOKEN` into the agent's env when set.

## Demo

`AGENT` and `MODEL` are required (no defaults — works for any inspect_swe
agent × any provider model since model calls are proxied through the bridge).

```bash
export ASTA_TOOL_KEY=...

# Claude Code on Sonnet 4.6
ANTHROPIC_API_KEY=... AGENT=claude_code MODEL=anthropic/claude-sonnet-4-6 \
    ./solvers/inspect-swe/demo.sh

# Codex CLI on gpt-5
OPENAI_API_KEY=... AGENT=codex_cli MODEL=openai/gpt-5 \
    ./solvers/inspect-swe/demo.sh

# Claude Code on an OpenAI model — bridge handles provider mismatch
OPENAI_API_KEY=... AGENT=claude_code MODEL=openai/gpt-5-mini \
    ./solvers/inspect-swe/demo.sh

# Knobs
LIMIT=5 AGENT=... MODEL=... ./solvers/inspect-swe/demo.sh                       # more samples
ASTA_IMAGE=ghcr.io/allenai/asta:<tag> AGENT=... MODEL=... ./solvers/inspect-swe/demo.sh    # pin a specific image
```

## Manual invocation

[Demo](#demo) above runs the validation suite via `astabench eval`. For
finer control — running a single task, or setting up a paired
comparison — call `astabench eval` directly:

```bash
# -S version=<x.y.z> pins the agent CLI (default "auto" drifts).
# --task <name> filters to one task; --sample-id <id> filters to one case.
# --epochs N for multiple trials; --working-limit <seconds> bounds compute.
export ASTA_IMAGE=ghcr.io/allenai/asta:latest
uv run --project solvers/inspect-swe --frozen -- astabench eval \
    --split validation \
    --solver agent_baselines/solvers/inspect_swe/agent.py@inspect_swe_solver \
    --sandbox docker:solvers/inspect-swe/sandbox_compose.yaml \
    --model anthropic/claude-sonnet-4-6 \
    -S agent=claude_code \
    -S version=2.1.128 \
    -S install_asta_skills=asta-preview \
    --log-dir logs/main
```

**For benchmark/leaderboard runs**, add `-S strict_reproducibility=true`
and pin `ASTA_IMAGE` to a `@sha256:` digest. Strict mode raises on any
provenance gap (mutable image tag, dirty skill tree, unresolved agent
version) — see [Strict mode](#strict-mode-strict_reproducibilitytrue).

For an ad-hoc single-task run without astabench's split machinery,
swap `astabench eval --split validation` for `inspect eval <task-spec>`.

### Swapping in local skills

For skill iteration (or just running against a non-tagged ref), clone
asta-plugins and point `-S skills=` at its canonical skill tree
(`plugins/asta-preview/skills`) instead of `-S install_asta_skills=`:

```bash
# Skip if already cloned. plugins/asta-preview/skills is the canonical
# source — edit it directly, no build step. (`make build-plugins` only
# regenerates the core `plugins/asta` subset, if you're testing that.)
git clone https://github.com/allenai/asta-plugins.git ../asta-plugins
git -C ../asta-plugins checkout <your-ref>

# Then in the astabench eval command above:
#   -S skills=../asta-plugins/plugins/asta-preview/skills
```

`-S skills=` only swaps skill content (the SKILL.md prose + scripts).
If you're patching the asta CLI itself, rebuild the image and re-run
with that `ASTA_IMAGE` pinned.

### Comparing two configurations

To benchmark an axis — swapped skills (above), agent CLI version,
asta image, model — re-run with one axis changed. Capture what the
first arm actually resolved (handy when not every axis was pinned up
front) and pin those values for the second arm:

```bash
# // error(...) fails loudly if a field is missing rather than silently
# pinning to null.
eval "$(inspect log dump logs/main/*.eval | jq -er '.samples[0].metadata
    | "ASTA_IMAGE=\(.asta_image // error("asta_image missing"))"
    + "\nAGENT_VERSION=\(.agent_version // error("agent_version missing"))"')"
export ASTA_IMAGE

uv run --project solvers/inspect-swe --frozen -- astabench eval \
    --split validation \
    --solver agent_baselines/solvers/inspect_swe/agent.py@inspect_swe_solver \
    --sandbox docker:solvers/inspect-swe/sandbox_compose.yaml \
    --model anthropic/claude-sonnet-4-6 \
    -S agent=claude_code \
    -S version="$AGENT_VERSION" \
    -S skills=../asta-plugins/plugins/asta-preview/skills \
    --log-dir logs/arm-b

inspect view --log-dir logs --recursive
```

## What gets wired

- **Asta access** — two surfaces:
  - Default: the task's MCP tools (`snippet_search`, `get_paper`,
    `table_editor`, `python_session`, …) reach the agent as
    `mcp__astabench_*` via the bridge.
  - `-S skills=<path>` (or `-S install_asta_skills=asta|asta-preview`):
    install SKILL.md trees into the agent's discovery path, giving the
    agent a native `asta papers` / `asta documents` / ... CLI surface
    plus skill prose. When `semantic-scholar` resolves, MCP tools with
    a 1:1 `asta papers` subcommand are filtered out of the bridge so
    the agent has one canonical paper-search path. See
    [Skill provenance lock](#skill-provenance-lock) for what's stamped
    per sample and [Skills support per agent](#skills-support-per-agent)
    for which inspect_swe agents accept the kwarg.
- **Model-provider-side web tools** (claude_code's `WebSearch`/`WebFetch`,
  provider equivalents): stripped from every model API request by a
  bridge `GenerateFilter`. The provider can't see them, so they can't
  be invoked. Tasks can still wire client-side web search via
  `state.tools` (e.g. `make_native_search_tools`) — those bridge as
  `mcp__astabench_*` and survive the filter. The agent's own
  subprocess access to external hosts (`curl`, `wget`, etc.) is
  unaffected by this filter; sandbox network policy is separate.
  Disable the filter via `-S deny_external_web=0`.
- **Sandbox image**: `ghcr.io/allenai/asta:latest` by default. Override
  via `ASTA_IMAGE` (tag or `@sha256:` digest); see
  [Reproducibility](#reproducibility) for what gets stamped and
  [Strict mode](#strict-mode-strict_reproducibilitytrue) for when a
  digest is required. `setup.sh` extracts skills directly from the
  chosen image so any `ASTA_IMAGE` (including `:latest`) is
  self-consistent.

## Reproducibility

Four axes drift independently between runs: the skill source, the sandbox
image, the asta CLI inside the image, and the agent CLI binary the bridge
invokes. The solver stamps each into `state.metadata` so the eval log alone
identifies what ran — no need to also archive the caller's env.

| `state.metadata` field | Source | When stamped |
|---|---|---|
| `skills` | resolved skill path(s), content hash, git block | when `-S skills=` or `-S install_asta_skills=` is set |
| `asta_image` | `docker inspect` on the running sandbox container, resolved to its registry digest (e.g. `ghcr.io/allenai/asta@sha256:...`); falls back to the compose tag if no digest is available | always when docker is reachable |
| `asta_version` | `asta --version` inside the sandbox post-run | when an `asta` binary exists in the sandbox |
| `inspect_swe_version` | `inspect_swe.__version__` | always |
| `agent_version` | concrete value from `-S version=`; else resolved post-run with per-mode policy mirroring inspect_swe's own behavior so the stamp matches the binary that actually ran (see [Agent CLI version](#agent-cli-version) below) | always when a resolver matches the mode; (a) caller left `gemini_cli` unpinned in any mode → solver **raises at construction** (no resolver path; ``ensure_gemini_cli_setup`` downloads each run); (b) mini_swe_agent `latest` → slot left unset (cache isn't authoritative); (c) resolver returns nothing in a gated mode → slot left unset, warning logged |

For a fully reproducible run, pin every axis the run depends on. The
default for each is intentionally mutable — `ASTA_IMAGE=…:latest`,
`-S version=auto`, `install_asta_skills=` against the vendored tree at
whatever ref `setup.sh` was last run with — so the convenience defaults
work for ad-hoc runs, but `asta_image` and `agent_version` are stamped
to their resolved concrete values regardless, so the log itself records
what ran.

Each provenance gap that survives the stamping pass appends a string to
`state.metadata["reproducibility_warnings"]` (a structured signal so
consumers can detect non-reproducible runs without scanning logs). The
field is omitted when the run is fully resolved.

### Strict mode (`strict_reproducibility=True`)

Benchmark/leaderboard runs should pass `-S strict_reproducibility=true`
to promote every warning condition to a raise:

- skills not under a git working tree, or with `path_dirty: True` (uncommitted,
  untracked, or git-ignored content), or with no `origin` remote (local-only
  repo a reviewer can't fetch) → raises at construction;
- `agent_version` unresolved → raises after the run completes (only when
  the agent itself didn't raise — strict mode doesn't mask agent
  failures);
- `asta_image` unresolved (no docker reachable + no `ASTA_IMAGE`), or
  resolved only to a mutable tag (no `@sha256:` digest — the registry
  can re-push the same tag) → raises after the run. Set `ASTA_IMAGE` to
  a `…@sha256:…` digest for benchmark runs.

Strict mode is opt-in so ad-hoc invocations and the regression smoke
tests keep working without ceremony.

### Pre-flight raises

The solver fails fast at construction in two conditions that would
otherwise silently produce misleading numbers:

- **Paper-search skill loaded without `ASTA_TOKEN`.** The asta CLI
  inside the sandbox needs the JWT for auth; without it, `asta papers`
  fails and the agent falls back to direct `api.semanticscholar.org`
  curls — measuring the fallback rather than the skill path. The check
  inspects the *effective* env (`extra_env` overrides + host `ASTA_TOKEN`),
  so callers can supply the token via either. Set `ASTA_TOKEN` (see
  [Auth](#auth)) or remove paper-search skills.
- **`ASTA_IMAGE` semver tag doesn't match skill `PLUGIN_VERSION`.**
  When `ASTA_IMAGE=…:vX.Y.Z` and the loaded skill files declare a
  different `PLUGIN_VERSION`, the skill bash snippets bail to a slow
  self-upgrade inside the sandbox. The check is skipped when the tag
  isn't a parseable semver (`:latest`, `@sha256:…`, unset) since there's
  nothing to compare.

### Skill provenance lock

When `-S skills=<path>` (or `-S install_asta_skills=...`) is set, the solver
writes a per-sample lock to `state.metadata["skills"]`. One entry per
resolved ref:

```json
{
  "source": "/Users/me/dev/asta-plugins/plugins/asta/skills",
  "content_sha256": "b3509822047f2ece…",
  "skills": ["asta-documents", "literature-report", "preview",
             "research-step", "semantic-scholar", "workspace"],
  "git": {
    "origin": "git@github.com:allenai/asta-plugins.git",
    "sha": "6fcf83a663dcfc26c1ce897af3622e4cc472e8ef",
    "path_in_repo": "plugins/asta/skills",
    "path_dirty": false
  }
}
```

The `git` block appears when the source path is inside a git working tree;
omitted otherwise. Together with `path_in_repo`, the block is enough to
reproduce the arm:

```bash
git clone <origin> && cd <repo>
git checkout <sha>
# point your harness at <clone>/<path_in_repo>
```

**`origin` is sanitized.** The `user:password@` form is stripped before
stamping — so CI tokens (`https://x-access-token:<TOKEN>@github.com/...`)
and credentialed SSH URLs (`ssh://alice:secret@host/...`) don't leak
into the eval log. Passwordless `user@` is preserved (no credential to
leak, and SSH-style remotes like `ssh://git@github.com/...` need the
`git@` to remain cloneable). SCP-style remotes (`git@host:path`) are
preserved verbatim.

**`path_dirty` is scoped to the resolved skill path.** Fires when
working-tree state diverges from HEAD in a way that affects installed
bytes — uncommitted edits, untracked files under skill dirs, deletion
of a committed SKILL.md tree, or gitignored install-payload files
(inspect would still copy them but `git checkout <sha>` wouldn't
restore them). Edits elsewhere in the repo don't false-positive. The
resolver overrides `status.showUntrackedFiles=no` so a user repo
config can't hide untracked files from the check.

**`content_sha256` fingerprints what inspect_ai's skill installer
actually copies.** That's SKILL.md plus files under `scripts/`,
`references/`, `assets/` whose path parts don't start with `.` or `_`
— matching inspect_ai's own `read_skills` behavior. Two runs with
different install-payload bytes (including different *gitignored*
payloads) produce different hashes. Machine-local files outside that
scope (`.DS_Store`, `__pycache__/`, top-level scratch files, hidden
files) don't perturb the hash, so the lock stays portable across
clones.

**Duplicate skill names raise at construction.** inspect_swe's
`install_skills()` keys by skill name and would silently overwrite
duplicates while the lock listed both. The resolver rejects up front,
whether the duplicates come from two `-S skills=` refs or from a single
parent ref containing two skill trees with the same basename
(e.g. `plugins/asta/skills/semantic-scholar` *and*
`plugins/asta-preview/skills/semantic-scholar`).

**`image_id`: image-derived alternative to git provenance.** When the
resolved path lives under a tree carrying a `.image-id` stamp (written
by `setup.sh` after extracting skills from the asta image), the
resolver records `image_id` in the lock entry. A reviewer can
reproduce the bytes by re-running `setup.sh` against that image —
*without* needing the source dir to be git-tracked. Strict mode
accepts an entry with `image_id` as reproducible (even when the
source is git-ignored or outside a working tree) **only when the
stamp is verified to match the running `ASTA_IMAGE`** — the solver
resolves `ASTA_IMAGE` to a docker image ID at construction and
raises on mismatch. If verification can't happen (`ASTA_IMAGE` unset,
docker unreachable, or image not locally pulled), strict mode
rejects the entry: an unverified stamp could be from a different
image than the sandbox runs, and the resolver may have relaxed
`path_dirty` on the assumption the stamp is valid, so falling back
to the git block isn't safe either. Pin `ASTA_IMAGE` so verification
can happen. Both `-S install_asta_skills=` and direct `-S skills=`
at a vendored tree go through the same check.

The stamp is invalidated when any file under the stamped tree has an
mtime later than `.image-id` itself — `setup.sh` writes `.image-id`
last, so a later mtime is a post-setup edit. When invalidated,
`image_id` is dropped from the lock and `path_dirty` is forced true;
strict mode treats the entry as unpinned. Rerun `setup.sh` (or commit
the changes) to restore valid provenance.

**Resolution runs per sample.** `inspect_swe`'s constructor re-reads
SKILL.md every sample; the resolver runs alongside it so the lock
stamped into each sample's `state.metadata["skills"]` describes the
bytes actually installed for that sample, not a stale construction-
time snapshot. Edits or rebuilds to a local `-S skills=` tree
between samples are reflected immediately.

### Agent CLI version

`inspect_swe`'s `version=` defaults vary per agent. The solver mirrors
inspect_swe's own per-mode behavior to identify the binary that
*actually* ran, stamping it post-run before the sample exits:

| Agent | Default | Mode | Resolution path |
|---|---|---|---|
| `claude_code` / `codex_cli` | `"auto"` | `auto` (or unset) | sandbox-PATH probe (`which <binary>` → exec `<path> --version`); falls back to inspect_swe's host cache (`cached_agent_binaries`) when nothing's on PATH and inspect_swe downloaded |
| `claude_code` / `codex_cli` | — | `sandbox` | sandbox-PATH probe only; no cache fallback (host cache may be a stale prior run) |
| `claude_code` / `codex_cli` | — | `stable` / `latest` | host cache only — inspect_swe always downloads in these modes, never reuses a preinstalled binary; probing the sandbox would stamp a different CLI than the one inspect_swe invoked |
| `mini_swe_agent` | `"stable"` | `stable` | read inspect_swe's wheel `default_version` directly |
| `gemini_cli` | `"auto"` | any unpinned | **solver raises at construction** — `ensure_gemini_cli_setup` downloads via GitHub releases regardless of what's preinstalled, so no probe can recover the actually-installed version; must pin `-S version=<x.y.z>` |

Sandbox probes inherit the caller's `user=` so PATH resolves the same
binary inspect_swe picked. A non-default user can have a different
PATH (different `claude`/`codex` install) — probing as the default
user would stamp the wrong binary or miss it entirely.

For the three resolvable agents, `agent_version` is normally stamped
(from the caller's pin or post-run resolution). If resolution fails
unexpectedly (empty host cache because the agent install failed, etc.),
the slot is left unset and the solver logs a warning. The missing key
is the signal: downstream extraction (`jq -er ... // error(...)`) fails
loudly when an operator tries to reuse the run as arm A, prompting a
rerun with `-S version=` pinned.

### Skills support per agent

All agents accept `skills=` *except* `mini_swe_agent`, whose inspect_swe
constructor (as of 0.2.54) has no `skills` parameter. Passing
`-S skills=...` or `-S install_asta_skills=...` with `agent=mini_swe_agent`
raises at construction with a clear error — otherwise inspect_swe would
TypeError mid-sample.

## Sandbox compose

`sandbox_compose.yaml` is single-service: the agent runs in the asta image
as `default`. Works for tasks that don't need a separate python sandbox
(`litqa2`, `paper_finder`, `sqa`, `arxivdigestables`). For tasks that need
both a python sandbox and the agent runtime (`python_session`/`SandboxJupyter`
+ inspect_swe agent), point `--sandbox docker:<your-compose.yaml>` at a
two-service compose and pass `-S sandbox_name=agent` to route the
coding agent into the agent service.

## Stale containers

When a run is killed mid-flight (Ctrl-C in the wrong place, OOM, hard signal), inspect_ai's `finally`-block container cleanup may not finish — sandbox containers stick around as `tail -f /dev/null` and accumulate, eventually exhausting Docker Desktop's VM and causing OOM kills on subsequent runs.

Symptom: new runs fail with `Error executing claude code agent 137: Killed` early in the eval, even when the task itself isn't memory-heavy.

The compose files tag this project's containers with `agent_baselines.inspect_swe_baseline=true`, so cleanup can target them without touching anyone else's inspect_ai containers:

```bash
docker ps  --filter "label=agent_baselines.inspect_swe_baseline=true"            # see what's stale
docker rm -f $(docker ps -q --filter "label=agent_baselines.inspect_swe_baseline=true")
```

Run that when you see container counts climb or OOM symptoms. Don't blanket-rm `inspect-*` containers — that would nuke other people's in-flight inspect_ai runs.

## Cost / usage tracking

All agent model calls flow through the sandbox bridge → Inspect's `get_model()`,
so they show up as normal `ModelEvent`s in `inspect view` and roll up into the
CLI summary at end of eval. No manual `record_model_usage_with_inspect` plumbing
is needed (unlike datavoyager / smolagents which intercept after-the-fact).

## Date cutoff

Two env vars pin asta CLI paper queries to a fixed date:

- `ASTA_PUBLICATION_DATE_RANGE=:YYYY-MM-DD` —
  `publicationDateOrYear` upper bound on `asta papers search` /
  `citations` / `get` / `author papers`.
- `ASTA_INSERTED_BEFORE=YYYY-MM-DD` — default for `--inserted-before`
  on `asta papers snippet-search`.

The solver auto-populates both from `state.metadata["insertion_date"]`
(set by asta-bench task setup) per sample. The host can also export
them directly to override.
