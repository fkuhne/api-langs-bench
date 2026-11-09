# 0015. Keep Docker, and take the report's timing numbers from native Linux

- Status: Accepted
- Date: 2026-11-09

## Context

Everything runs in Docker Compose ([0008](0008-run-anywhere-with-docker-and-record-the-machine.md)). On a Mac or on Windows, Docker runs its containers in a Linux VM. In step 1.3, the Python backend's paced fake woke about 10 ms late on each token, and a bare container showed that the machine causes it: a 20 ms sleep woke 6.8 ms late at the median ([backends](../../docs/backends.md#timers-in-dockers-vm-on-this-mac)).

The owner asked, on 2026-11-09, whether to fix the delay, and whether the benchmark needs Docker at all.

What was measured on 2026-11-09, on the owner's M3 under Colima (Apple's Virtualization.framework, 4 virtual CPUs), with 200 sleeps of 20 ms ([backends](../../docs/backends.md#where-the-delay-comes-from)):

| Where | `time.sleep`, median / p99 | `asyncio.sleep`, median / p99 |
|---|---|---|
| A container, the VM idle | 4.39 / 6.44 ms | 5.31 / 12.97 ms |
| A container, all 4 virtual CPUs busy | 0.07 / 2.32 ms | 0.08 / 3.21 ms |
| macOS itself, no Docker | 4.24 / 15.47 ms | 1.20 / 7.45 ms |
| macOS itself, one core busy | 5.00 / 5.01 ms | 1.02 / 1.07 ms |

- **The delay comes from the VM's idle virtual CPUs.** When the VM has nothing to run, they sleep on macOS, which wakes them late. Kept busy, they wake on time.
- **The delay shrinks as the load grows.** A backend that burns more CPU keeps the virtual CPUs busier, so its fake runs closer to the contract's pace. In a VM, a heavier backend would look better at stream timing, and no constant can be subtracted to correct it.
- **macOS isn't tighter on its own.** Its own sleeps wake 1 to 5 ms late.
- **On native Linux, a container is a process on the host's kernel,** with the host's CPU and timers. Docker's known cost there is its network: its NAT adds latency at high packet rates, and host networking matches native ([Felter et al., 2014](https://www.read.seas.harvard.edu/~kohler/class/cs260r-s19/containerperf14.pdf), read through summaries, unchecked against its tables).

## Decision

Docker stays, as in [0008](0008-run-anywhere-with-docker-and-record-the-machine.md), and the report's timing numbers come from runs on native Linux. The VM's delay isn't fixed.

- **Timing numbers** are latency, time to first token, stream behaviour and throughput. The report takes them from native Linux only.
- **A machine that runs Docker in a VM,** such as a Mac, is for building, the gates, the conformance suite, and the numbers that don't depend on timers: memory, image size and start-up. Its timing numbers are for development, and say so.
- **Each run measures its machine's timer error before it starts,** and records it with the machine (plan steps 1.6 and 3.5).
- **The conformance suite's pace check** takes its tolerance from that measurement (plan step 1.5).
- **Whether timed runs use host networking on Linux** is plan step 3.1's choice.
- **The Linux machine** is named at plan step 6.2.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Docker for builds and gates, with the backends run directly on the machine for timed runs | On a Mac it removes the VM, but macOS's own sleeps are 1 to 5 ms late, and backends aren't deployed on macOS. macOS can't cap each backend's CPU and memory the same way. Every language would need a second way to run |
| No Docker | Every reader would install every toolchain at its exact version. There would be no equal caps, no Windows, and no rerun with one command |
| Fix the VM's delay by keeping its virtual CPUs busy, with a busy loop or idle polling in its kernel | Timers become tight, but four of the Mac's cores run at 100% all the time, and every CPU number becomes meaningless |

## Consequences

- Nothing changes in the repository's commands. The Mac stays a full development machine.
- The report needs a native Linux machine, not yet named.
- Timing numbers measured on a Mac stay out of the report's tables.

## Assumptions to verify

- [ ] On native Linux, a 20 ms sleep in a container wakes within 1 ms at the median, whether the machine is idle or busy. To check on the report's machine before its first run.
- [ ] Docker's NAT adds latency at high packet rates, and host networking matches native. To check in Felter et al.'s tables, or by a run, at plan step 3.1.

## Sources

- Our runs on 2026-11-06 and 2026-11-09 ([backends](../../docs/backends.md#timers-in-dockers-vm-on-this-mac)).
- W. Felter, A. Ferreira, R. Rajamony and J. Rubio, "An Updated Performance Comparison of Virtual Machines and Linux Containers", IBM Research Report RC25482, 2014 ([PDF](https://www.read.seas.harvard.edu/~kohler/class/cs260r-s19/containerperf14.pdf)), through a [review](https://souptikji.github.io/blog/2018/04/Containerization) and search summaries, 2026-11-09.
- The owner's pick, 2026-11-09.
