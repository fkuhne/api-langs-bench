# 0008. Run anywhere with Docker, and record the machine

- Status: Proposed
- Date: 2026-11-06

## Context

The owner wants the benchmark to run "locally, in this machine, or in any other" (2026-11-06). Readers will run it on their own machines. No machine is fixed, so none can bound the design.

Numbers from different machines can't be compared, and a backend's numbers depend on the CPU and memory it's given.

## Decision

- **Everything runs in Docker Compose:** the backends, the upstreams, the database and the evaluation tool.
- **Commands are Docker commands,** the same in PowerShell, cmd and POSIX shells, as in the sibling projects.
- **Pinned:** images, dependencies and the model, to exact versions.
- **The same limits for every backend:** each in its own container, with the same CPU and memory. The load generator runs on other cores. How is plan step 3.1.
- **Every run records its machine:** the CPU's model and cores, the memory, the OS, Docker's version, whether Docker runs inside a VM, and the limits each container ran under.
- **Settings come from environment variables,** each with a working default, and a line in `.env.example`. `.env` is optional.
- **Ports are published on `127.0.0.1` only.**

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Native runs, with each language's toolchain installed | Closer to the metal, but every reader's toolchain differs, and the same limits are hard to set. |
| A fixed cloud VM type, such as AWS's t3.medium | Repeatable hardware, but it costs money, and the owner wants any machine. A VM can still be a run's machine. |

## Consequences

- Docker Desktop on macOS and Windows runs containers inside a Linux VM (unchecked, from memory). Numbers from it may not match native Linux, so the run's record says which.
- The report compares numbers from one machine at a time, never across machines.

## Assumptions to verify

- [ ] Docker's CPU limits hold each backend to the same share on Docker Desktop as on Linux.
- [ ] Docker's networking adds the same cost to every backend.
- [ ] A machine's timers are tight enough for paced fakes. *Not on Colima on the owner's M3, 2026-11-06: a 20 ms sleep wakes 6.8 ms late at the median and 11.2 ms late at p99, in a bare container ([backends](../../docs/backends.md#timers-in-dockers-vm-on-this-mac)). Each run should measure its machine's timer error and record it with the machine.* *2026-11-09: the delay comes from the VM's idle virtual CPUs, and shrinks under load, so it can favour a backend that burns more CPU. macOS's own sleeps are 1 to 5 ms late. The report's timing numbers come from native Linux ([0015](0015-keep-docker-and-take-the-reports-timing-numbers-from-native-linux.md)).*

## Sources

- The interview, 2026-11-06.
- The conventions of the owner's sibling projects, such as decision-models-eval and ai-bootstrap.
