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
They work on `inspect_ai==0.3.114` and `inspect_ai==0.3.169` today, but are the
most likely to break on `inspect_ai>=0.4`.

| Solver | File | Touchpoint | Risk |
|---|---|---|---|
| react | `agent_baselines/solvers/react/basic_agent.py` | `inspect_ai.log._transcript.transcript` | Internal logging API |
| magenticone | `agent_baselines/solvers/magenticone/magentic_autogen_bridge.py` | `inspect_ai.model._call_tools.execute_tools` | Internal tool execution API |
| sqa (perplexity) | `agent_baselines/solvers/sqa/perplexity_base.py` | `inspect_ai.model._providers.perplexity.PerplexityAPI` | Internal provider API |

## Known deprecations / forward-compat risks
- Running with newer `inspect_ai` (e.g. `>=0.3.137`) may emit a deprecation warning
  from `astabench` about `ModelEvent` moving to `inspect_ai.event.ModelEvent`.
  Treat `inspect_ai>=0.4` as potentially breaking until `astabench` removes any
  deprecated imports.

## Proposed Inspect version ranges
- **Default for all solvers:** `inspect_ai>=0.3.114,<0.4`
  - `0.3.114` is the known-good baseline via `astabench`.
  - `0.4` is expected to remove some deprecated/internal APIs; treat it as a
    breaking upgrade until proven otherwise.

When a solver relies on internal imports (table above), prefer staying on a
known-good `0.3.x` version and only upgrading with a smoke run and/or targeted
tests.

## Per-solver inventory

### `react`
- Entry point (demo): `agent_baselines/solvers/react/basic_agent.py@instantiated_basic_agent`
- Inspect APIs used:
  - `inspect_ai.model`: `Model`, `get_model`, `execute_tools`, chat message types
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `chain`, `solver`, `system_message`
  - `inspect_ai.tool`: `Tool`, `ToolCall`, `ToolDef`, `ToolError`, `ToolInfo`, `tool_with`
  - `inspect_ai.util`: `LimitExceededError`
  - Internal: `inspect_ai.log._transcript.transcript`
- Proposed version range: `>=0.3.114,<0.4`
- Notes: the internal transcript import is only used on `stop_reason == "model_length"`.

### `paper_finder`
- Code: `agent_baselines/solvers/search/paper_finder.py@ai2i_paper_finder`
- Inspect APIs used:
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
- Proposed version range: `>=0.3.114,<0.4`
- Notes: this solver uses only public Inspect APIs; most coupling is via `astabench`.

### `smolagents`
- Entry point (demo): `agent_baselines/solvers/smolagents/agent.py@smolagents_coder`
- Inspect APIs used:
  - `inspect_ai.model`: `get_model`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `chain`, `solver`
  - `inspect_ai.tool`: `Tool`, `ToolDef`
  - `inspect_ai.util`: `sandbox`
- Proposed version range: `>=0.3.114,<0.4`

### `sqa`
- Entry point (demo): `agent_baselines/solvers/sqa/sqa.py@sqa_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ChatMessageAssistant`, `ModelUsage`, `ResponseSchema`, `get_model`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `chain`, `generate`, `solver`, `prompt_template`, `system_message`
  - `inspect_ai.util`: `json_schema`, `subprocess`
  - Internal: `inspect_ai.model._providers.perplexity.PerplexityAPI`
- Proposed version range: `>=0.3.114,<0.4`
- Notes: Perplexity integration depends on internal provider APIs; treat upgrades carefully.

### `storm`
- Entry point (demo): `agent_baselines/solvers/sqa/storm_solver.py@storm_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ChatMessageAssistant`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
  - `inspect_ai.util`: `subprocess`
- Proposed version range: `>=0.3.114,<0.4`

### `super` (code agent)
- Entry point (demo): `agent_baselines/solvers/code_agent/agent.py@code_agent`
- Inspect APIs used:
  - `inspect_ai.log`: `transcript`
  - `inspect_ai.solver`: `Solver`, `bridge`, `solver`
  - `inspect_ai.model`: `Model`, `get_model`
- Proposed version range: `>=0.3.114,<0.4`

### `datavoyager`
- Entry point (demo): `agent_baselines/solvers/datavoyager/agent.py@datavoyager_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ModelUsage`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
- Proposed version range: `>=0.3.114,<0.4`

### `magenticone`
- Entry point (demo): `agent_baselines/solvers/magenticone/magentic_autogen_bridge.py@magentic_autogen_bridge`
- Inspect APIs used:
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`, `chain`
  - `inspect_ai.model`: chat message types
  - `inspect_ai.tool`: `Tool`, `ToolDef`, `ToolError`
  - `inspect_ai.util`: `LimitExceededError`, `StoreModel`
  - Internal: `inspect_ai.model._call_tools.execute_tools`
- Proposed version range: `>=0.3.114,<0.4`

### `futurehouse`
- Entry point (demo): `agent_baselines/solvers/futurehouse/futurehouse_solver.py@futurehouse_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ChatMessageAssistant`, `ModelUsage`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
- Proposed version range: `>=0.3.114,<0.4`

### `arxivdigestables`
- Entry point (demo): `agent_baselines/solvers/arxivdigestables/asta_table_agent.py@tables_solver`
- Inspect APIs used:
  - `inspect_ai.model`: `ChatMessageAssistant`, `ModelUsage`
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
- Proposed version range: `>=0.3.114,<0.4`

### `asta-v0`
- Entry point (demo): `agent_baselines/solvers/asta/v0/asta.py@fewshot_textsim_router`
- Inspect APIs used:
  - `inspect_ai.model`: chat message types, model selection
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
  - `inspect_ai.tool`: `Tool`, `ToolCall`, `ToolDef`, `ToolError`, `tool`
- Proposed version range: `>=0.3.114,<0.4`

### `e2e_discovery`
- Entry point (demo): `agent_baselines/solvers/e2e_discovery/autoasta/autoasta_cached.py@autoasta_cached_solver`
- Inspect APIs used:
  - `inspect_ai.solver`: `Solver`, `TaskState`, `Generate`, `solver`
  - `inspect_ai.model`: chat message types (faker helpers)
  - `inspect_ai.util`: `json_schema`
- Proposed version range: `>=0.3.114,<0.4`
