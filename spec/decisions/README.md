# Decision records

This folder records every decision that shapes the project, one file per decision. Each record states:
- the context;
- what we chose;
- the alternatives, and why we rejected them;
- the consequences;
- the assumptions we still have to verify.

**Statuses**
- **Proposed**: planned, but not yet confirmed by the owner or proven by an implementation. The commit that implements it flips it to Accepted, amending it if the implementation taught us something.
- **Accepted**: in force.
- **Superseded**: replaced by a later record, which it links to. It's kept for history.

**Adding a record**
1. Copy [`decision-template.md`](decision-template.md) to the next free number, e.g. `0002-short-title.md`.
2. Fill it in and add a row to the table below.
3. Commit it on its own, before or together with the change it justifies.

Don't rewrite a record to change its decision. Write a new record and mark the old one superseded. Ticking assumptions and adding evidence is fine. Never renumber: commits and other records cite records by number.

| # | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-work-from-a-spec-and-record-every-decision.md) | Work from a spec and record every decision | Accepted | 2026-11-06 |
| [0002](0002-start-with-python-and-go-then-add-languages-one-at-a-time.md) | Start with Python and Go, then add languages one at a time | Proposed | 2026-11-06 |
| [0003](0003-every-backend-implements-ai-bootstraps-chat-api.md) | Every backend implements ai-bootstrap's chat API | Proposed | 2026-11-06 |
| [0004](0004-three-local-upstreams-llama-cpp-a-fake-server-and-an-in-process-fake.md) | Three local upstreams: llama.cpp, a fake server and an in-process fake | Proposed | 2026-11-06 |
| [0005](0005-conversations-on-postgresql-as-version-1s-last-backend-phase.md) | Conversations on PostgreSQL, as version 1's last backend phase | Proposed | 2026-11-06 |
| [0006](0006-a-remote-upstream-ollama-cloud-beside-a-local-imitation.md) | A remote upstream: Ollama Cloud, beside a local imitation | Proposed | 2026-11-06 |
| [0007](0007-a-web-ui-that-runs-the-benchmark-and-shows-its-results.md) | A web UI that runs the benchmark and shows its results | Proposed | 2026-11-06 |
| [0008](0008-run-anywhere-with-docker-and-record-the-machine.md) | Run anywhere with Docker, and record the machine | Proposed | 2026-11-06 |
| [0009](0009-publish-as-a-public-github-repository.md) | Publish as a public GitHub repository | Accepted | 2026-11-06 |
