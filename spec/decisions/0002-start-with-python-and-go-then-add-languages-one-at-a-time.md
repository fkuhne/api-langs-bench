# 0002. Start with Python and Go, then add languages one at a time

- Status: Proposed
- Date: 2026-11-06

## Context

The owner wants to compare programming languages for an AI backend: Python and Go first, and Rust, C++, Java and JavaScript after ("let's start with two and after that we expand", 2026-11-05).

Everything shared between the backends is new at the start: the contract, the conformance suite, the fakes, the load generator and the fairness rules. A mistake in any of them would have to be fixed once per backend.

## Decision

Version 1 has two backends, Python and Go. The other languages come after version 1, one at a time, in an order picked then. Each new one implements the same contract and passes the same conformance suite. An `add-language` skill, written from what the first two taught, makes adding one routine.

Why these two, beyond the owner's choice:
- **Python** is where most AI code lives, and it's ai-bootstrap's backend.
- **Go** is a common choice for LLM gateways, such as Bifrost ([notes](../../docs/benchmarking.md#prior-art)). Python against Go is the comparison readers ask about first.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| All six languages at once | Every early mistake would be fixed six times, and the first numbers would come much later. |
| Python alone first | It would have nothing to compare against, so the harness couldn't be proven fair. |

## Consequences

- The contract, the harness and the fairness rules are proven on two backends before a third arrives.
- The first report compares only two languages. It says so.

## Assumptions to verify

- [ ] Two languages are enough to find the harness's mistakes before a third is added. Check when the third language arrives: count what had to change in the shared code.

## Sources

- The owner's brief and interview, 2026-11-05 and 2026-11-06.
