# Asta Tables Agent

Agent for the arxivDIGESTables task; see the source code in [`agent_baselines/solvers/arxivdigestables/asta_table_agent.py`](/agent_baselines/solvers/arxivdigestables/asta_table_agent.py).
SQA is the long-form question answering system published in Singh et al., 2025.
It has a retrieval and reranking component and a multi-step LLM to create the final report.

SQA is intended to be run only against the `sqa_dev` or `sqa_test` tasks.

This solver requires [`MODAL_TOKEN`](https://modal.com/) to be set as an environment variable.
