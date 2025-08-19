# agent-baselines

The repo contains baseline implementations of a variety of agents to as reported in [AstaBench]().  

These agents are implemented as InspectAI solvers and can be run on the AstaBench suit with the `astabench eval` command.

## Usage

```bash
git clone https://github.com/allenai/agent-baselines.git
```

The `solvers` directory has descriptions of each of the baseline agents, along with sample scripts to set up the environment required by that solver and
run against a limit number of eval samples.

If you have trouble setting up an environment on your local system, a Docker image is provided

```commandline
make shell SOLVER=<solver_name>
root:/astabench# ./solvers/<solver_name>/demo.sh
```

See documentation in [asta-bench](https://github.com/allenai/asta-bench) for details on how to run the suite.
