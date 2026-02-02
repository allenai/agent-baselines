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
FROM agent-baselines-base AS react
COPY scripts/solver_uv.sh /agent-baselines/scripts/solver_uv.sh
COPY solvers/react/pyproject.toml solvers/react/uv.lock solvers/react/setup.sh /agent-baselines/solvers/react/
RUN UV_FROZEN=1 solvers/react/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS paper_finder
COPY scripts/solver_uv.sh /agent-baselines/scripts/solver_uv.sh
COPY solvers/paper_finder/pyproject.toml solvers/paper_finder/uv.lock solvers/paper_finder/setup.sh /agent-baselines/solvers/paper_finder/
RUN UV_FROZEN=1 solvers/paper_finder/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS smolagents
COPY solvers/smolagents/setup.sh /agent-baselines/solvers/smolagents/setup.sh
RUN solvers/smolagents/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS storm
COPY solvers/storm/setup.sh /agent-baselines/solvers/storm/setup.sh
RUN solvers/storm/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS sqa
COPY solvers/sqa/setup.sh /agent-baselines/solvers/sqa/setup.sh
RUN solvers/sqa/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS super
COPY solvers/super/setup.sh /agent-baselines/solvers/super/setup.sh
RUN solvers/super/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS datavoyager
COPY solvers/datavoyager/setup.sh /agent-baselines/solvers/datavoyager/setup.sh
RUN solvers/datavoyager/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS futurehouse
COPY solvers/futurehouse/setup.sh /agent-baselines/solvers/futurehouse/setup.sh
RUN solvers/futurehouse/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/

FROM agent-baselines-base AS magenticone
COPY solvers/magenticone/setup.sh /agent-baselines/solvers/magenticone/setup.sh
RUN solvers/magenticone/setup.sh
COPY --from=agent-baselines-runtime /agent-baselines/ /agent-baselines/
