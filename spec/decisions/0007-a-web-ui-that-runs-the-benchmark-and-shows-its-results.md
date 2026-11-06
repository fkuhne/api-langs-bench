# 0007. A web UI that runs the benchmark and shows its results

- Status: Proposed
- Date: 2026-11-06

## Context

The owner asked for a simple web UI, to start runs and see their results (2026-11-06). A run must also stay repeatable from one command, and anything running beside a benchmark on the same machine can change what it measures.

## Decision

Version 1's last step adds a simple web UI with three pages: the list of runs, one run's results, and the backends compared with charts. It can start a run.
- **The command stays the source.** The UI starts the same runner a person would type, and reads the same saved runs. A run never needs the UI.
- **The UI keeps quiet during a run.** It only shows progress, and stays off the CPUs the backend under test uses.

Its stack, and how it starts a run, are plan step 6.1.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| A static report page only | It can't start a run, which the owner asked for. |
| Grafana dashboards | Another stack to run. They show live metrics well, but not our comparison between backends. |
| The UI first | It needs runs to show, and the runner's shape to call. |

## Consequences

- The report's comparison page is the UI's comparison page.
- It isn't a chat UI: chatting stays out of scope.

## Assumptions to verify

- [ ] The UI's progress display doesn't measurably change a run. Check with the same run made with the UI open and closed.

## Sources

- The interview, 2026-11-06.
