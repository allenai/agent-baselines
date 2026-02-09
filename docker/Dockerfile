# syntax=docker/dockerfile:1.4
FROM python:3.11.3 AS agent-baselines-base

LABEL name="agent-baselines" \
    org="allenai" \
    description="Benchmark and experimentation framework for scientific agents"

RUN apt-get update && apt-get install -y less git curl cmake clang

RUN curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.3.1.tgz -o docker.tgz \
    && tar xzvf docker.tgz --strip 1 -C /usr/local/bin docker/docker \
    && rm docker.tgz

RUN mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -SL https://github.com/docker/compose/releases/download/v2.29.6/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# install uv
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates build-essential
RUN curl -fsSL https://astral.sh/uv/install.sh -o /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
# Don't let uv link system packages
ENV UV_LINK_MODE=copy

# install cargo:
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:$PATH"

# Install common dependencies
WORKDIR /agent-baselines
COPY pyproject.toml /agent-baselines/
COPY docker/bashrc /root/.bashrc

RUN mkdir -p /agent-baselines/agent_baselines /agent-baselines/solvers /agent-baselines/scripts

RUN uv sync --extra dev --no-install-project

# Copied here (after uv sync) so edits to this script don't bust the dep cache.
COPY scripts/solver_uv.sh /agent-baselines/scripts/solver_uv.sh

FROM agent-baselines-base AS agent-baselines
COPY . /agent-baselines

# Runtime repo contents (without the base stage venv).
#
# We copy these selectively rather than `COPY --from=agent-baselines /agent-baselines /agent-baselines`
# to avoid copying `/agent-baselines/.venv` into solver images.
FROM scratch AS agent-baselines-runtime
COPY --from=agent-baselines /agent-baselines/agent_baselines /agent-baselines/agent_baselines
COPY --from=agent-baselines /agent-baselines/docs /agent-baselines/docs
COPY --from=agent-baselines /agent-baselines/scripts /agent-baselines/scripts
COPY --from=agent-baselines /agent-baselines/solvers /agent-baselines/solvers
COPY --from=agent-baselines /agent-baselines/README.md /agent-baselines/README.md


# Images for running specific solvers
#
# NOTE: Solver stages should install dependencies before copying the full repo
# contents from the agent-baselines stage. This keeps dependency installation
# cached unless solver-specific files change.
# Each solver stage: COPY solver-specific files, run setup, then overlay repo contents.
# solver_uv.sh is already in the base image; only solver-specific files need copying.
FROM agent-baselines-base AS react
COPY solvers/react/pyproject.toml solvers/react/uv.lock solvers/react/setup.sh /agent-baselines/solvers/react/
RUN UV_FROZEN=1 solvers/react/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS paper_finder
COPY solvers/paper_finder/pyproject.toml solvers/paper_finder/uv.lock solvers/paper_finder/setup.sh /agent-baselines/solvers/paper_finder/
RUN UV_FROZEN=1 solvers/paper_finder/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS smolagents
COPY solvers/smolagents/pyproject.toml solvers/smolagents/uv.lock solvers/smolagents/setup.sh /agent-baselines/solvers/smolagents/
RUN UV_FROZEN=1 solvers/smolagents/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS storm
COPY solvers/storm/pyproject.toml solvers/storm/uv.lock solvers/storm/setup.sh /agent-baselines/solvers/storm/
RUN UV_FROZEN=1 solvers/storm/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS sqa
COPY solvers/sqa/pyproject.toml solvers/sqa/uv.lock solvers/sqa/setup.sh /agent-baselines/solvers/sqa/
RUN UV_FROZEN=1 solvers/sqa/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS super
COPY solvers/super/pyproject.toml solvers/super/uv.lock solvers/super/setup.sh /agent-baselines/solvers/super/
RUN UV_FROZEN=1 solvers/super/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS datavoyager
COPY solvers/datavoyager/pyproject.toml solvers/datavoyager/uv.lock solvers/datavoyager/setup.sh /agent-baselines/solvers/datavoyager/
RUN UV_FROZEN=1 solvers/datavoyager/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS futurehouse
COPY solvers/futurehouse/pyproject.toml solvers/futurehouse/uv.lock solvers/futurehouse/setup.sh /agent-baselines/solvers/futurehouse/
RUN UV_FROZEN=1 solvers/futurehouse/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS magenticone
COPY solvers/magenticone/pyproject.toml solvers/magenticone/uv.lock solvers/magenticone/setup.sh /agent-baselines/solvers/magenticone/
RUN UV_FROZEN=1 solvers/magenticone/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS arxivdigestables
COPY solvers/arxivdigestables/pyproject.toml solvers/arxivdigestables/uv.lock solvers/arxivdigestables/setup.sh /agent-baselines/solvers/arxivdigestables/
RUN UV_FROZEN=1 solvers/arxivdigestables/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS asta-v0
COPY solvers/asta-v0/pyproject.toml solvers/asta-v0/uv.lock solvers/asta-v0/setup.sh /agent-baselines/solvers/asta-v0/
RUN UV_FROZEN=1 solvers/asta-v0/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS e2e_discovery
COPY solvers/e2e_discovery/pyproject.toml solvers/e2e_discovery/uv.lock solvers/e2e_discovery/setup.sh /agent-baselines/solvers/e2e_discovery/
RUN UV_FROZEN=1 solvers/e2e_discovery/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/
