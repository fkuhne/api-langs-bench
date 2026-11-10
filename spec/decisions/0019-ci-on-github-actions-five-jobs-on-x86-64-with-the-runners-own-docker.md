# 0019. CI on GitHub Actions: five jobs on x86-64, with the runner's own Docker

- Status: Proposed
- Date: 2026-11-09

## Context

Plan step 1.7 runs each language's gates, and the conformance suite against the in-process fakes, on every push (R18), with no key (R17). The repository is public on GitHub, with Actions enabled ([0009](0009-publish-as-a-public-github-repository.md)). GitHub Actions is free for a public repository's standard runners.

What was checked on 2026-11-09:
- **GitHub's `ubuntu-24.04` runner,** image 20261101.360.1, has Docker 28.0.4, Compose 2.38.2 and Buildx 0.38.1, on an x86-64 VM with kernel 7.0.0 ([its README](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)). The development Mac has Docker 29.5.2 and Compose 5.5.1, on arm64.
- **Every image the repository pins has an x86-64 build:** Go, golangci-lint, Python, uv, Docker's CLI, oha, Redocly CLI, and the distroless image's digest (`docker buildx imagetools inspect`).
- **Nothing in the repository has been built on x86-64 yet.**
- **The latest `actions/checkout`** is v7.0.1, commit `3d3c42e5aac5ba805825da76410c181273ba90b1` (GitHub's API).
- **Cold, on the Mac,** the Go gates took 81.4 s ([gates](../../docs/gates.md#measured-on-2026-11-09)), and the conformance suite 52 to 61 s once its images were built ([conformance](../../docs/conformance.md#measured-on-2026-11-09)).

## Decision

CI is one GitHub Actions workflow, `.github/workflows/ci.yml`, with five jobs side by side, on every push and pull request. Each job runs on `ubuntu-24.04`, with the runner's own Docker and Compose, and runs one of the repository's own commands:

| Job | Command |
|---|---|
| `contract` | `docker compose run --rm contract-checks` |
| `python-fastapi` | `docker compose run --rm python-fastapi-checks` |
| `go` | `docker compose run --rm go-checks` |
| `bench` | `docker compose run --rm bench-checks` |
| `conformance` | `docker compose run --rm conformance` |

- **The same commands as on any machine,** so CI checks what a reader runs, and needs no `.env`: every setting has a working default ([0008](0008-run-anywhere-with-docker-and-record-the-machine.md)).
- **The conformance suite runs whole,** its pace checks included, with the tolerance from its own probe of the runner's timers ([0017](0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md)). What the first runs measure is written down. If the pace checks prove flaky there, what to do is a decision for then, with that data.
- **No cache** of the images' layers at first. The jobs' times are measured, and a cache is added only if they call for it.
- **Safe by default:**
  - every action is pinned by its commit, with its version in a comment;
  - the workflow's token can only read the repository's contents;
  - no job uses a secret.
- **A push that supersedes another on the same branch** cancels the older run.
- **Each job stops after 20 minutes.**

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| One job, the five commands in a row | Slower, and the first failure hides the rest |
| arm64, `ubuntu-24.04-arm` | The development Mac's architecture already; it would test nothing new |
| Both architectures, as a matrix | Twice the jobs, for little more than x86-64 gives |
| Docker and Compose installed at the Mac's versions | A slower start to every job, and it would hide whether older versions work, which many readers have |
| The conformance suite without its pace checks | Never flaky, but a fake that drifts would pass CI |
| Docker's layer cache in GitHub's cache, from the start | More to configure before we know it's needed |

## Consequences

- Every push checks the repository on a second architecture and an older Compose, which tests R16 in part.
- The conformance job is the first run of the suite on native Linux, though in a shared VM. Its timer probe gives a first number for [0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)'s open question.
- A change to a command in `compose.yaml` changes CI with it.
- The runner (plan step 1.6) isn't in CI: its numbers from a shared VM would mean nothing.

## Assumptions to verify

- [ ] Every image builds and every gate passes on x86-64. To check in this step.
- [ ] The conformance suite drives the runner's Docker 28.0.4 through its socket, with the Compose 5.1.4 inside its image. To check in this step. This also answers part of [0017](0017-the-conformance-suite-pytest-that-drives-compose-and-a-pace-rule-from-the-machines-timers.md)'s question about the socket on other hosts.
- [ ] The pace checks pass on GitHub's runner. To check in this step, over several runs.
- [ ] The slowest job takes under 10 minutes without a cache. To check in this step.
- [ ] `docker compose run` needs no terminal in CI. To check in this step.

## Sources

- [GitHub's Ubuntu 24.04 runner image README](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md), read on 2026-11-09.
- GitHub's API for `actions/checkout`'s latest release and its commit, and for the repository's Actions settings, 2026-11-09.
- `docker buildx imagetools inspect` of every pinned image, 2026-11-09.
- The owner's picks, 2026-11-09.
