# InspectAI usage + version constraints (per solver)

This document inventories how each solver in this repo uses `inspect_ai`, with a
focus on **version-sensitive touchpoints** (especially private/internal imports)
to inform per-solver version pinning.

## Key constraints
- `astabench` pins `inspect_ai` exactly (currently `inspect_ai==0.3.114`).
- Solvers can diverge via uv `override-dependencies` (see `docs/per_solver_envs.md`),
  but **you can’t mix multiple Inspect versions in the same Python process**.
  Per-solver isolation works because we run each solver in its own env/process.

## High-risk touchpoints (private/internal APIs)
These imports use internal `inspect_ai` modules (paths containing `._...`).
They work on `inspect_ai==0.3.114` and `inspect_ai==0.3.169` (as of 2026-02-02),
but are the most likely to break on future Inspect releases.

| Solver | File | Touchpoint | Risk |
|---|---|---|---|
| react | `agent_baselines/inspect_compat.py` | fallback to `inspect_ai.log._transcript.transcript` | Internal logging API |
| magenticone | `agent_baselines/inspect_compat.py` | fallback to `inspect_ai.model._call_tools.execute_tools` | Internal tool execution API |
| sqa (perplexity) | `agent_baselines/inspect_compat.py` | `inspect_ai.model._providers.perplexity.PerplexityAPI` | Internal provider API |

## Known deprecations / forward-compat risks
- Running with newer `inspect_ai` (e.g. `>=0.3.137`) may emit a deprecation warning
  from `astabench` about `ModelEvent` moving to `inspect_ai.event.ModelEvent`.
- Internal APIs (prefixed with `_`) can change on any release, not just major ones.

## Current Inspect version strategy
- **Default for all solvers:** pin `inspect_ai==0.3.114` (matches `astabench`).
- Solvers that need a newer version use a uv override (see `docs/per_solver_envs.md`).
- Upgrade individual solvers as needed; run their demo/tests to verify.

When a solver relies on internal imports (table above), prefer staying on a
known-good version and only upgrading with a smoke run and/or targeted tests.

## Per-solver inventory

### `react`
- Entry point (demo): `agent_baselines/solvers/react/basic_agent.py@instantiated_basic_agent`
- Inspect APIs used:
  - `inspect_ai.model`: `Model`, `get_model`, `execute_tools`, chat message types
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `chain`, `solver`, `system_message`
  - `inspect_ai.tool`: `Tool`, `ToolCall`, `ToolDef`, `ToolError`, `ToolInfo`, `tool_with`
  - `inspect_ai.util`: `LimitExceededError`
  - Via compat: `agent_baselines.inspect_compat.transcript` (may fall back to internal `inspect_ai.log._transcript.transcript`)
- Version: pinned via `solvers/<name>/pyproject.toml`
- Notes: the internal transcript import is only used on `stop_reason == "model_length"`.

### `paper_finder`
- Code: `agent_baselines/solvers/search/paper_finder.py@ai2i_paper_finder`
- Inspect APIs used:
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
- Version: pinned via `solvers/<name>/pyproject.toml`
- Notes: this solver uses only public Inspect APIs; most coupling is via `astabench`.

### `smolagents`
- Entry point (demo): `agent_baselines/solvers/smolagents/agent.py@smolagents_coder`
- Inspect APIs used:
  - `inspect_ai.model`: `get_model`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `chain`, `solver`
  - `inspect_ai.tool`: `Tool`, `ToolDef`
  - `inspect_ai.util`: `sandbox`
- Version: pinned via `solvers/<name>/pyproject.toml`

### `sqa`
- Entry point (demo): `agent_baselines/solvers/sqa/sqa.py@sqa_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ChatMessageAssistant`, `ModelUsage`, `ResponseSchema`, `get_model`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `chain`, `generate`, `solver`, `prompt_template`, `system_message`
  - `inspect_ai.util`: `json_schema`, `subprocess`
  - Via compat: `agent_baselines.inspect_compat.perplexity_api_class` (internal Perplexity provider import)
- Version: pinned via `solvers/<name>/pyproject.toml`
- Notes: Perplexity integration depends on internal provider APIs; treat upgrades carefully.

### `storm`
- Entry point (demo): `agent_baselines/solvers/sqa/storm_solver.py@storm_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ChatMessageAssistant`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
  - `inspect_ai.util`: `subprocess`
- Version: pinned via `solvers/<name>/pyproject.toml`

### `super` (code agent)
- Entry point (demo): `agent_baselines/solvers/code_agent/agent.py@code_agent`
- Inspect APIs used:
  - `inspect_ai.log`: `transcript`
  - `inspect_ai.solver`: `Solver`, `bridge`, `solver`
  - `inspect_ai.model`: `Model`, `get_model`
- Version: pinned via `solvers/<name>/pyproject.toml`

### `datavoyager`
- Entry point (demo): `agent_baselines/solvers/datavoyager/agent.py@datavoyager_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ModelUsage`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
- Version: pinned via `solvers/<name>/pyproject.toml`

### `magenticone`
- Entry point (demo): `agent_baselines/solvers/magenticone/magentic_autogen_bridge.py@magentic_autogen_bridge`
- Inspect APIs used:
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`, `chain`
  - `inspect_ai.model`: chat message types
  - `inspect_ai.tool`: `Tool`, `ToolDef`, `ToolError`
  - `inspect_ai.util`: `LimitExceededError`, `StoreModel`
  - Internal: `inspect_ai.model._call_tools.execute_tools`
- Version: pinned via `solvers/<name>/pyproject.toml`

### `futurehouse`
- Entry point (demo): `agent_baselines/solvers/futurehouse/futurehouse_solver.py@futurehouse_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ChatMessageAssistant`, `ModelUsage`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
- Version: pinned via `solvers/<name>/pyproject.toml`

### `arxivdigestables`
- Entry point (demo): `agent_baselines/solvers/arxivdigestables/asta_table_agent.py@tables_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ChatMessageAssistant`, `ModelUsage`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
- Version: pinned via `solvers/<name>/pyproject.toml`

### `asta-v0`
- Entry point (demo): `agent_baselines/solvers/asta/v0/asta.py@fewshot_textsim_router`
- Inspect APIs used:
  - `inspect_ai.model`: chat message types, model selection
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
  - `inspect_ai.tool`: `Tool`, `ToolCall`, `ToolDef`, `ToolError`, `tool`
- Version: pinned via `solvers/<name>/pyproject.toml`

### `e2e_discovery`
- Entry point (demo): `agent_baselines/solvers/e2e_discovery/autoasta/autoasta_cached.py@autoasta_cached_solver`
- Inspect APIs used:
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
  - `inspect_ai.model`: chat message types (faker helpers)
  - `inspect_ai.util`: `json_schema`
- Version: pinned via `solvers/<name>/pyproject.toml`
