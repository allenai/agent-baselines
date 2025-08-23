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

RUN mkdir -p /agent-baselines/agent-baselines

RUN uv sync --extra dev

COPY docker/bashrc /root/.bashrc
COPY . /agent-baselines


# Images for running specific solvers
FROM agent-baselines-base AS react
RUN solvers/react/setup.sh

FROM agent-baselines-base AS smolagents
RUN solvers/smolagents/setup.sh

FROM agent-baselines-base AS storm
RUN solvers/storm/setup.sh

FROM agent-baselines-base AS sqa
RUN solvers/sqa/setup.sh

FROM agent-baselines-base AS super
RUN solvers/super/setup.sh

FROM agent-baselines-base AS datavoyager
RUN solvers/datavoyager/setup.sh

FROM agent-baselines-base AS futurehouse
RUN solvers/futurehouse/setup.sh
