# Magentic-One

This directory contains Magentic-One style agents that use an outer loop (orchestrator) to monitor progress and re-plan when the agent stalls.

## Implementations

1. **magentic_outer_loop**: A native Inspect implementation that uses an orchestrator (outer loop) to monitor progress and re-plan when the agent stalls.

2. **magentic_autogen_bridge**: A bridge to autogen's MagenticOneGroupChat using Inspect's bridge() mechanism to capture all LLM calls.  Note that `bridge()` passes `inspect` as the model name, so some model-specific autogen processing may not perfectly match a standalone implementation.

## Setup

This solver is configured as a per‑solver uv sub‑project in `solvers/magenticone/pyproject.toml`.
Install deps with:

```bash
./solvers/magenticone/setup.sh
```

## Usage

Run the demo script:

```bash
./solvers/magenticone/demo.sh
```

Or use directly in your code:

```python
from agent_baselines.solvers.magenticone.magentic_outer_loop import magentic_outer_loop
from agent_baselines.solvers.magenticone.magentic_autogen_bridge import magentic_autogen_bridge

# Use the native implementation
solver = magentic_outer_loop(max_turns=20, max_stalls=3)

# Or use the autogen bridge
solver = magentic_autogen_bridge(max_turns=20, max_stalls=3)
```
