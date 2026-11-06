# 0011. Lay the repository out by role

- Status: Accepted
- Date: 2026-11-06

## Context

Plan step 1.2 places each part of the benchmark:
- the contract, in `contract/` since step 1.1 ([0010](0010-the-contract-ai-bootstraps-chat-in-text-paced-fakes-and-openapi-3-2.md));
- the backends, Python and Go first, with more languages after version 1, and perhaps more than one framework per language ([product](../product.md#scope));
- the fake server (step 2.1), and the evaluation tool: the conformance suite (1.5), the runner (1.6) and later the web UI;
- one Compose file, with every setting in `.env.example` ([0008](0008-run-anywhere-with-docker-and-record-the-machine.md)).

The sibling projects use one folder per component, a multi-stage Dockerfile in each, and a `-checks` service in Compose for its gates, as in [ai-bootstrap](https://github.com/fkuhne/ai-bootstrap/blob/main/compose.yaml).

Each backend's in-process fake reads `contract/fake-tokens.json`, which sits outside the backend's own folder.

## Decision

The repository is laid out by role:

| Path | What it holds | From step |
|---|---|---|
| `contract/` | The API and the fakes | 1.1 |
| `backends/<language>-<framework>/` | One backend each, such as `backends/python-fastapi/` | 1.2, then 1.3 and 1.4 |
| `fake-server/` | The fake upstream server | 2.1 |
| `bench/` | The evaluation tool: the conformance suite, the runner, the analysis | 1.2, then 1.5 and 1.6 |
| `compose.yaml` | Every service, the gates included | 1.2 |
| `.env.example` | Every setting, with its default | 1.2 |

- **Go's folder** is `backends/go/` until its framework is picked in step 1.4, when it's renamed `go-<framework>`.
- **Each backend listens on port 8000 in its own container,** and Compose publishes each on its own port on `127.0.0.1`, as the contract's `servers` entry says.
- **Where runs are saved** is step 1.6's choice.
- **The contract reaches each image** through a named build context: Compose's `additional_contexts`, as `contract`. The gates mount it read-only at `/contract`, so a backend finds its token file at the same path in every container.
- **Step 1.2 creates small starting projects,** enough for the gates to run. The real code is steps 1.3 to 1.6.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| By language: `python/` and `go/`, each with its backend and tools | The tooling would sit inside one contestant's folder, and a new language would bring mostly empty folders |
| One repository per backend | Rerunning the benchmark would mean fetching several repositories, and the conformance suite and the one Compose file would get harder |
| Names by language alone, such as `backends/python/` | A second framework for a language, in Next, would need a rename, or a name that doesn't match its siblings |
| The repository's root as every image's build context | Each image would see the whole repository, and every change would invalidate every build's cache |

## Consequences

- Adding a language is adding a folder under `backends/`, a service in `compose.yaml`, and its gates.
- Step 1.4 renames `backends/go/`.
- Readers find each backend in one folder, with its Dockerfile, its settings and its tests.

## Assumptions to verify

- [ ] Compose's `additional_contexts` works the same on Docker Desktop, Colima and Linux. Checked on Colima in step 1.2; the others at the report's two machines (step 6.2). *Colima, 2026-11-06: works with Compose 5.5.1 and Docker 29.5.2. The Python checks image holds `/contract` without a mount ([gates](../../docs/gates.md#measured-on-2026-11-06)).*

## Sources

- ai-bootstrap's [`compose.yaml`](https://github.com/fkuhne/ai-bootstrap/blob/main/compose.yaml) and [backend Dockerfile](https://github.com/fkuhne/ai-bootstrap/blob/main/backend/Dockerfile), read on 2026-11-06.
- The owner's pick, 2026-11-06.
