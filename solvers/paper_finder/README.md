# Asta Paper Finder

Paper Finder is our paper-seeking agent, described in detail in the [AstaBench paper](https://allenai.org/papers/astabench). It is intended to be run against the `paper_finder` and `paper_finder_litqa2` test/validation tasks.

The implementation is in [https://github.com/allenai/asta-paper-finder](https://github.com/allenai/asta-paper-finder)

This solver uses the agent as an API. The `base_url` solver argument should point to an instance of the API set up by following the instructions in the above repo.

## Dependencies

This solver is configured as a per‑solver uv sub‑project in `solvers/paper_finder/pyproject.toml`.
Install deps with:
```
./solvers/paper_finder/setup.sh
```
