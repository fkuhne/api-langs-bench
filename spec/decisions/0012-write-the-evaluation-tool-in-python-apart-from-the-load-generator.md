# 0012. Write the evaluation tool in Python, apart from the load generator

- Status: Accepted
- Date: 2026-11-06

## Context

The evaluation tool does several jobs:
- the conformance suite (step 1.5): every backend answers the same requests the same way, and its fake keeps the contract's pace;
- the runner (step 1.6): it starts the services, sends the load, and saves each run once, with the machine it ran on;
- the analysis, and later the web UI's server ([0007](0007-a-web-ui-that-runs-the-benchmark-and-shows-its-results.md)).

Only the load generator is on the timed path. It must reach well beyond every backend's ceiling (R4), and it's step 1.6's choice: an existing tool such as k6, vegeta, oha or wrk2, or a client of our own. The rest isn't timed. The conformance suite's timing checks run without load.

Python is the owner's language and ai-bootstrap's. Python's jsonschema 4.26 already validated the contract's OpenAPI 3.2 schemas, in step 1.1's check ([0010](0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md)).

## Decision

The evaluation tool is written in Python, in `bench/` ([0011](0011-lay-the-repository-out-by-role.md)). It has the same gates as the Python backend ([0013](0013-gates-equally-strict-for-every-language.md)). The load generator is a separate program, chosen in step 1.6 and measured on its own first. It may be in another language.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Go, one fast binary that also generates the load | A contestant would measure itself, and it's further from the owner's Python tools |
| Rust | Slower to write, and the project has no Rust until after version 1 |
| Python, generating the load too | Too slow to stay out of the way at the rates we need (R4) |

## Consequences

- The conformance suite, the runner and the analysis share one Python project, with one lockfile.
- Step 1.6 has to connect the runner to a load generator in another process, and read that generator's output.

## Assumptions to verify

- [x] Python times each streamed event closely enough to check the fakes' pace without load, at the gaps the workloads use. To check in step 1.5. *2026-11-09: at a 20 ms gap, the suite's Python client saw each backend's median lateness within 7.5 ms on a Mac, in 10 runs, and failed a fake that drifts ([conformance](../../docs/conformance.md#measured-on-2026-11-09)). The workloads' gaps are plan step 3.2's; a smaller one is checked then.*

## Sources

- Requirements [R3, R4 and R7](../requirements.md), and plan steps 1.5 and 1.6.
- The owner's pick, 2026-11-06.
