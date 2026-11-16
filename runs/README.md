# Runs

Each file here is one run of the runner: one workload sent to one backend, with what it ran on and what it measured ([`docs/runner.md`](../docs/runner.md), [0018](../spec/decisions/0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md)).

- A file is written once, and never edited.
- Its name is the time the run started, in UTC, the backend, and the rate: `20261110T115536Z-python-fastapi-100rps.json` started on 2026-11-10 at 11:55:36 UTC, against the Python backend, at 100 requests a second.
- What each field holds is in [the runner's notes](../docs/runner.md#a-runs-file), and how to read the numbers in [its next section](../docs/runner.md#reading-a-table-of-runs).
- A number in a doc names the run it comes from.
- Numbers from different machines are never compared ([0008](../spec/decisions/0008-run-anywhere-with-docker-and-record-the-machine.md)).

## Commits renamed on 2026-11-16

On 2026-11-16 the history was rewritten to take an email address out of two commits. Every commit kept its files, so each one's tree is the same as before. But the 27 commits from 2026-11-10 on have new hashes. A run's file is never edited, so 153 runs still name the old ones:

| Runs | The files name | The commit now |
|---|---|---|
| `20261110T145513Z-python-fastapi-500rps.json` | `484c97c` | `23f06af` |
| The 47 of 2026-11-13, `20261113T194341Z-…` to `20261113T201002Z-…` | `9b7cde6` | `c1b4bb9` |
| The 105 of 2026-11-16, `20261116T125818Z-…` to `20261116T141339Z-…` | `fbf0a01` | `671f67d` |

The notes cite the new hashes. GitHub's pages for earlier CI runs still show the old ones: `72fdaf1` is now `8a1114f`, `658e24e` is `613f140`, and `7bf50e3` is `b4dc9fa`.
