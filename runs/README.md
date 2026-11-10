# Runs

Each file here is one run of the runner: one workload sent to one backend, with what it ran on and what it measured ([`docs/runner.md`](../docs/runner.md), [0018](../spec/decisions/0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md)).

- A file is written once, and never edited.
- Its name is the time the run started, in UTC, the backend, and the rate: `20261110T115536Z-python-fastapi-100rps.json` started on 2026-11-10 at 11:55:36 UTC, against the Python backend, at 100 requests a second.
- What each field holds is in [the runner's notes](../docs/runner.md#a-runs-file), and how to read the numbers in [its next section](../docs/runner.md#reading-a-table-of-runs).
- A number in a doc names the run it comes from.
- Numbers from different machines are never compared ([0008](../spec/decisions/0008-run-anywhere-with-docker-and-record-the-machine.md)).
