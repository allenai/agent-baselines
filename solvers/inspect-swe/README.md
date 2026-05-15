# inspect_swe coding agents

Wraps the [inspect_swe](https://meridianlabs-ai.github.io/inspect_swe/)
coding agents (claude_code, codex_cli, gemini_cli, mini_swe_agent) as
asta-bench solvers. The agent runs inside the sample sandbox; its
model API calls are proxied back to Inspect via `sandbox_agent_bridge`,
so token usage, transcript, model aliases, and limits all flow through
standard Inspect infrastructure.

## What gets wired

- **Asta access** — `install_asta_skills` picks the agent's asta surface:
  - Default `None`: the task's MCP tools (`snippet_search`, `get_paper`,
    `table_editor`, `python_session`, …) reach the agent as
    `mcp__astabench_*` via the bridge.
  - Set to `"asta"` or `"asta-preview"`: the solver resolves bundled
    skill dirs from `.vendor/asta-plugins/plugins/<plugin>/skills/`
    (extracted by `setup.sh` from the asta image, so the host-side
    skill source always matches the CLI baked into the runtime) and
    passes them to inspect_swe's standard `skills=` plumbing — each
    agent's wrapper handles its own discovery path. The skills give the agent
    a native CLI surface (`asta papers`, `asta documents`,
    `asta analyze-data`, `asta artifacts`, `asta autodiscovery`,
    `asta experiment`, `asta literature find`, `asta generate-theories`,
    `asta pdf-extraction`, `asta auth`) plus skill prose. MCP tools
    with a 1:1 `asta papers` CLI subcommand are filtered from
    `state.tools` so the agent has one canonical paper-search path.
    Non-paper MCP tools and MCP tools without a CLI equivalent
    (`get_paper_batch`, `search_paper_by_title`) always bridge.
- **Model-provider-side web tools** (claude_code's `WebSearch`/`WebFetch`,
  provider equivalents): stripped from every model API request by a
  bridge `GenerateFilter`. The provider can't see them, so they can't
  be invoked. Tasks can still wire client-side web search via
  `state.tools` (e.g. `make_native_search_tools`) — those bridge as
  `mcp__astabench_*` and survive the filter. The agent's own
  subprocess access to external hosts (`curl`, `wget`, etc.) is
  unaffected by this filter — sandbox network policy is a separate
  concern. Disable the filter via `-S deny_external_web=0`.
- **Sandbox image**: `ghcr.io/allenai/asta:v0.16.0` by default. Override via
  the `ASTA_IMAGE` env var (e.g. pin to a different tag).

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

```bash
uv run --project solvers/inspect-swe --frozen -- inspect eval \
    --solver agent_baselines/solvers/inspect_swe/agent.py@inspect_swe_solver \
    --model anthropic/claude-sonnet-4-6 \
    --sandbox docker:solvers/inspect-swe/sandbox_compose.yaml \
    --limit 1 \
    -S agent=claude_code \
    astabench/litqa2_validation
```

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
