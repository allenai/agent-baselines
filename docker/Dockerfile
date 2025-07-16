# syntax=docker/dockerfile:1.4
FROM python:3.11.3 AS astabench-base

LABEL name="astabench" \
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
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
# Don't let uv link system packages
ENV UV_LINK_MODE=copy

# install cargo:
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:$PATH"

# Only copy pyproject.toml; dependencies can be installed this way, but the docker
# cache won't depend on any other files
WORKDIR /astabench
COPY pyproject.toml /astabench/

# Create a basic directory structure for the package
RUN mkdir -p /astabench/astabench

COPY docker/bashrc /root/.bashrc

# Images for running specific solvers
# Each must copy the code and call "uv sync --inexact"
#   to make the registry without uninstalling previous dependencies

FROM astabench-base AS smolagents
COPY . /astabench
RUN uv sync --extra smolagents --inexact

FROM astabench-base AS azure
COPY . /astabench
RUN uv sync --extra azure --inexact


FROM astabench-base AS sqa
COPY . /astabench
RUN uv sync --extra sqa --inexact


FROM astabench-base AS super
COPY . /astabench
RUN uv sync --extra super --inexact


FROM astabench-base AS datavoyager
COPY . /astabench
RUN uv sync --extra datavoyager --inexact

