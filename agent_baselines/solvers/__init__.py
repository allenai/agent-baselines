# Re-exports that pull in astabench are guarded so submodules without
# astabench dependencies (e.g. agent_baselines.solvers.inspect_swe) can
# be imported in environments where astabench isn't installed.
try:
    from astabench.util.model import (  # noqa: F401
        normalize_model_name,
        record_model_usage_with_inspect,
    )
    from .futurehouse import futurehouse_solver  # noqa: F401
except ImportError:
    pass

from .llm import llm_with_prompt  # noqa: F401
