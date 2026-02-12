.PHONY: shell format mypy flake test build-image test-expensive smoke-solvers smoke-solvers-ci solve-score-ci

# allow passing extra pytest args, e.g. make test-expensive PYTEST_ARGS="-k EVAL_NAME"
PYTEST_ARGS ?=

AGENT_BASELINES_TAG	:= agent-baselines
CONTAINER_NAME		:= agent-baselines-container
DOCKER_SOCKET_PATH ?= $(if $(XDG_RUNTIME_DIR),$(XDG_RUNTIME_DIR)/docker.sock,/var/run/docker.sock)

ENV_ARGS :=

# Name of solver to build Docker container for
SOLVER :=
# Docker image tag for the solver
TARGET := --target agent-baselines
BUILD_ARGS :=
SMOKE_SOLVERS ?=

ifdef SOLVER
  TARGET := --target solver
  BUILD_ARGS += --build-arg SOLVER_NAME=$(SOLVER)
  AGENT_BASELINES_TAG := $(AGENT_BASELINES_TAG)-$(SOLVER)
  ENV_ARGS += --env-file solvers/$(SOLVER)/env
endif

# Add each env var only if it's defined
ifdef OPENAI_API_KEY
  ENV_ARGS += -e OPENAI_API_KEY
endif

ifdef AZUREAI_OPENAI_API_KEY
  ENV_ARGS += -e AZUREAI_OPENAI_API_KEY
endif

ifdef HF_TOKEN
  ENV_ARGS += -e HF_TOKEN
endif

# Also support .env file if it exists
ifneq ("$(wildcard .env)","")
  ENV_ARGS += --env-file .env
endif

# -----------------------------------------------------------------------------
# Local vs CI environment vars
# -----------------------------------------------------------------------------
ifeq ($(IS_CI),true)
  LOCAL_MOUNTS :=
  ENV_ARGS += -e IS_CI
  TEST_RUN := docker run --rm $(ENV_ARGS) -v /var/run/docker.sock:/var/run/docker.sock $(AGENT_BASELINES_TAG)
  BUILD_QUIET := --quiet
else
  LOCAL_MOUNTS := \
    -v $(DOCKER_SOCKET_PATH):/var/run/docker.sock \
    -v $$(pwd)/pyproject.toml:/agent-baselines/pyproject.toml:ro \
    -v $$(pwd)/agent_baselines:/agent-baselines/agent_baselines \
    -v $$(pwd)/scripts:/agent-baselines/scripts:ro \
    -v $$(pwd)/tests:/agent-baselines/tests \
    -v $$(pwd)/logs:/agent-baselines/logs \
    -v $$(pwd)/solvers:/agent-baselines/solvers \
    -v agent-baselines-cache:/root/.cache
  TEST_RUN := docker run --rm $(ENV_ARGS) $(LOCAL_MOUNTS) $(AGENT_BASELINES_TAG)
  BUILD_QUIET ?=
endif

# -----------------------------------------------------------------------------
# Build the Docker image (primary target)
# -----------------------------------------------------------------------------

build-image:
	docker build $(BUILD_QUIET) $(TARGET) $(BUILD_ARGS) . --tag $(AGENT_BASELINES_TAG) -f ./docker/Dockerfile

# -----------------------------------------------------------------------------
# Interactive shell in container
# -----------------------------------------------------------------------------
shell: build-image
	@docker run --rm -it --name $(CONTAINER_NAME) \
		$(LOCAL_MOUNTS) \
		-v agent-baselines-home:/root/.agent-baselines \
		$(ENV_ARGS) -p 7575:7575 \
		$(AGENT_BASELINES_TAG) \
		/bin/bash

# -----------------------------------------------------------------------------
#  Formatting and linting
# -----------------------------------------------------------------------------
# NOTE: These commands aim to install only the dev dependencies, without the
# main package depedencies which require more complex setup, e.g., ~ssh.
# Ideally they would install the exact lib versions of the dev dependencies,
# but limiting to only dev dependencies in pyproject.toml in a DRY manner is not
# easy to do since pip has no mechanism and uv requires defining a seeparate section
# in pyproject.toml which pip cannot read.

ifneq ($(IS_CI),true)
format: build-image
endif

format:
	docker run --rm \
		-v $$(pwd):/agent-baselines \
		$(AGENT_BASELINES_TAG) \
		uv run --extra dev -m black .

ifneq ($(IS_CI),true)
mypy: build-image
endif

mypy:
	docker run --rm \
		-v $$(pwd):/agent-baselines \
		$(AGENT_BASELINES_TAG) \
		uv run --extra dev -m mypy agent_baselines/ tests/

ifneq ($(IS_CI),true)
flake: build-image
endif

flake:
	docker run --rm \
		-v $$(pwd):/agent-baselines \
		$(AGENT_BASELINES_TAG) \
		uv run --extra dev -m flake8 agent_baselines/ tests/

ifneq ($(IS_CI),true)
test: build-image
endif

test:
	@$(TEST_RUN) uv run --no-sync --extra dev --extra smolagents \
		-m pytest $(PYTEST_ARGS) -vv /agent-baselines/tests

ifneq ($(IS_CI),true)
test-expensive: build-image
endif

test-expensive:
	@$(TEST_RUN) uv run --no-sync --extra dev --extra inspect_evals --extra smolagents \
		-m pytest $(PYTEST_ARGS) -vv -o addopts= -m expensive /agent-baselines/tests

# -----------------------------------------------------------------------------
# Solver uv sub-project smoke checks
# -----------------------------------------------------------------------------
ifneq ($(IS_CI),true)
smoke-solvers: build-image
smoke-solvers-ci: build-image
solve-score-ci: build-image
endif

smoke-solvers:
	@$(TEST_RUN) ./scripts/smoke_solvers.sh $(SMOKE_SOLVERS)

smoke-solvers-ci:
	@$(TEST_RUN) ./scripts/smoke_solvers.sh react paper_finder

solve-score-ci:
	@$(TEST_RUN) ./scripts/smoke_solve_score.sh paper_finder
