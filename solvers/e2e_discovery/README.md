# Asta E2E Discovery (Asta Panda, CodeScientist, and Faker)

Note: these solvers are currently not yet fully integrated, and their implementation consists of fetching cached results from the real solvers.  The stub code is in [`agent_baselines/solvers/e2e_discovery`](/agent_baselines/solvers/e2e_discovery/).

The `demo.sh` script runs the Asta Panda agent, which is intended to be run only against the `e2e_discovery_validation` or `e2e_discovery_test` tasks.  The other two solvers are analogous (just replace `autoasta` with `codescientist` or `faker`).
