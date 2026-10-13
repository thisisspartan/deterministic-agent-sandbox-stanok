# Runtime contract

The contract as it works today, four points.

## 1. k8s is the only runtime

The host orchestrator `launcher/k8s.py` runs two Jobs: a worker Job (the ticket
turn) and a fresh-check Job (the independent re-run of the declared tests).
The Docker path was removed (CC-258). An explicit `STANOK_RUNTIME=docker` is
refused with ENV-FAIL `rc=16` — it is an environment error, not a red test.

## 2. Tree transport

The tree reaches the Pod as a ConfigMap transport copy: the Pod works on that
copy, never on the host tree. The machine's patch lands on the live tree only
on a clean verdict — a failing or unchecked turn leaves the tree unchanged.

## 3. Network boundary

The rendered NetworkPolicy defines the Pod's egress: only the model server and
the Opik tracing backend are reachable. Everything else — package indexes,
general internet — is closed; the code uses only what the image already has.

## 4. Entrypoint and stack

`scripts/run.sh` is the only interface for running tests (`list`,
`test <path>`, `test --all`, `smoke <path>`). The stack registry
`scripts/stacks/*.toml` is the single source of truth: the registry, not the
ticket, picks the framework — the `py` manifest runs pytest over
`tests/**/*_test.py`.
