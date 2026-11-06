# 0009. Publish as a public GitHub repository

- Status: Accepted
- Date: 2026-11-06

## Context

The owner wants to publish the comparison for engineers building similar backends and tech leads looking for benchmarks, with a post on LinkedIn and X later, at no set date (2026-11-05).

## Decision

The repository is public on GitHub, from its first commit, as `fkuhne/api-langs-bench`.
- **Nothing private in git:** keys and secrets stay in `.env`, which git ignores.
- **The licence:** MIT No Attribution (MIT-0), from the first commit, as in ai-bootstrap. Readers can copy any backend without keeping a notice.
- **The name:** `api-langs-bench`, picked by the owner on 2026-11-06. "langs" means programming languages; with no AI word beside it, it doesn't read as LangChain. "bench" is the word readers search for.
- **Links** to the owner's other projects point to their public repositories, such as [ai-bootstrap](https://github.com/fkuhne/ai-bootstrap), never to a local folder.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Private until the first results | The owner chose public. Being public from the start also keeps every record readable as written. |
| A blog post alone | Readers couldn't see the code or repeat the runs. |
| The names `api-lang-eval`, `one-api-many-langs` or `api-lang-bench` | `api-lang-eval`, the working name: "eval" leans towards AI, where it means scoring a model's answers. `one-api-many-langs`: distinct, but harder to find in search. `api-lang-bench`: taken, by the InCIT 2023 paper's code. |
| MIT or Apache-2.0 | Both ask readers to keep a notice. MIT-0 doesn't, and matches ai-bootstrap. |

## Consequences

- Every record and note is written for strangers to read.
- The README must say how to run the benchmark, once there's something to run.

## Assumptions to verify

- [ ] No key or secret reaches git. Check before each push, and in CI.

## Sources

- The interview, 2026-11-05 and 2026-11-06.
- GitHub searches for each candidate name, 2026-11-05.
