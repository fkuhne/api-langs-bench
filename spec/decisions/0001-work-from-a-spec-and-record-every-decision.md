# 0001. Work from a spec and record every decision

- Status: Accepted
- Date: 2026-11-06

## Context

The owner works on a benchmark of the same AI backend written in several programming languages with a coding agent, across many sessions. A session ends, and with it the conversation. That conversation held what was learned, measured and decided, and why. A new session then starts from nothing.

The owner already works from a spec in their other projects, such as `ai-bootstrap`, `ultra-bert`, `granite-switch`, `decision-models-eval` and `idea-lab`:
- a product spec as the source of truth for scope;
- a table from each requirement to how it's met and verified;
- a plan of small steps;
- a record for each decision.

A public benchmark makes the method matter more. A reader who doubts a number should find, in the records, why it was measured that way.

## Decision

The project works from a spec. Everything that drives the work lives in `spec/`:
- `spec/product.md`: the problem, who it's for, the scope and the non-goals. The source of truth.
- `spec/requirements.md`: each requirement, how it's met, and how it's verified.
- `spec/plan.md`: phases of small steps, each ticked in the commit that finishes it.
- `spec/decisions/`: one record per decision, numbered and made from `decision-template.md`, with an index.

`docs/` holds what the project produces for a reader. Its first page is the notes on benchmarking an AI backend, [`docs/benchmarking.md`](../../docs/benchmarking.md), where each claim names its source.

The method's routines run as skills, kept in `.agents/skills/`: `next-step` and `decide`. `AGENTS.md` tells any agent how to work, and `CLAUDE.md` and `GEMINI.md` import it.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| A lab notebook: Jupyter notebooks and nothing else | Good for exploring, poor at recording why. Choices end up in cell comments, and a notebook's output changes each time it runs. Notebooks can still serve a step; the spec and the records stay the source of truth. |
| Notes in one README | It mixes the plan, the decisions and the findings, and it grows without structure. |
| Starting from the ai-bootstrap template | It brings a web UI for chatting, modules and a single backend, where we need one backend per language. Its chat API is reused as the contract instead ([0003](0003-every-backend-implements-ai-bootstraps-chat-api.md)). |

## Consequences

- An agent reads `spec/` and the notes before it acts, as `AGENTS.md` says.
- Records take time to write. They pay off when the owner wants to know why something was set up the way it was, and when a new session needs context.

## Assumptions to verify

- [ ] The method fits this project. Check at the end of the first phase after the spec, and adapt `AGENTS.md` if it doesn't.

## Sources

- The `new-project` skill (`~/.claude/skills/new-project/`), from which this repository was started.
- Record 0001 of the owner's `ultra-bert` project, an earlier record of the same method.
