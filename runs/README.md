# Runs

Each file here is one run of the runner: one workload sent to one backend, with what it ran on and what it measured ([`docs/runner.md`](../docs/runner.md), [0018](../spec/decisions/0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md)).

- A file is written once, and never edited.
- Its name is the time the run started, in UTC, the backend, and the rate.
- A number in a doc names the run it comes from.
- Numbers from different machines are never compared ([0008](../spec/decisions/0008-run-anywhere-with-docker-and-record-the-machine.md)).
