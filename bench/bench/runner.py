"""The first runner: one workload at a ladder of rates, sent to each backend in turn, in passes,
each run saved once (spec/decisions/0018, spec/decisions/0020).

    docker compose run --rm runner [--backend NAME]... [--rate N]... [--passes N]
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench import oha, repository
from bench.backends import BACKENDS, url
from bench.compose import PROJECT_DIR, Compose
from bench.pace import PROBE_GAP_MS, PROBE_SLEEPS, Tolerance, probe
from bench.workload import RATES, STREAM_20, Workload

# Where the runner's service mounts the repository's `runs/`.
RUNS_DIR = Path("/runs")
# The version of a run's file. It changes when a field's meaning does.
SCHEMA = 2
# How many times every backend is run at every rate, unless `--passes` says.
PASSES = 3
# The owner's description of the host, which Docker can't see from inside a VM.
MACHINE_SETTING = "BENCH_MACHINE"
# How long oha may take beyond the time it sends for, in seconds, before the run is given up.
GRACE_S = 2 * oha.REQUEST_TIMEOUT_S


def _load(command: Sequence[str], timeout_s: int) -> str:
    # The command is always one of oha's own, built by `bench.oha`.
    result = subprocess.run(  # noqa: S603
        command, capture_output=True, text=True, check=False, timeout=timeout_s
    )
    if result.returncode != 0:
        raise RuntimeError(f"`{' '.join(command)}` failed: {result.stderr}")
    return result.stdout


@dataclass(frozen=True)
class Runner:
    """Runs a workload against one backend at a time, and saves what it measured."""

    compose: Compose
    runs_dir: Path = RUNS_DIR
    # The host, in the owner's words.
    machine: str | None = None
    load: Callable[[Sequence[str], int], str] = _load
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    probe: Callable[[], list[float]] = probe
    repository: Callable[[], dict[str, Any]] = lambda: repository.describe(PROJECT_DIR)

    def run(self, service: str, workload: Workload, run_pass: int = 1) -> Path:
        """One run: `workload` against `service`, alone, in a new container, its fake set as the
        workload asks."""
        self.compose.stop(*(other for other in BACKENDS if other != service))
        self.compose.start(service, workload.settings.environment(), fresh=True)
        timers = Tolerance.of(self.probe())
        started = self.now()
        target = url(service, workload.path)
        warmup = oha.parse(self._send(oha.command(workload, target, workload.warmup_s)))
        command = oha.command(workload, target, workload.duration_s)
        measured = oha.parse(self._send(command))
        docker = self.compose.docker_info()
        record = {
            "schema": SCHEMA,
            "id": f"{started:%Y%m%dT%H%M%SZ}-{service}-{workload.rate}rps",
            "started_at": f"{started:%Y-%m-%dT%H:%M:%SZ}",
            "pass": run_pass,
            "backend": {
                "service": service,
                "image": self.compose.image(service),
                # As Docker holds the container to them; 0 is no limit (R5).
                "limits": self.compose.limits(service),
            },
            "upstream": workload.settings.environment()["LLM_PROVIDER"],
            "workload": workload.described(),
            "load_generator": {
                "name": "oha",
                "version": self.load([oha.OHA, "--version"], GRACE_S).strip().removeprefix("oha "),
                "command": command,
            },
            "repository": self.repository(),
            "machine": {
                "description": self.machine,
                "docker": {
                    "version": docker["ServerVersion"],
                    "os": docker["OperatingSystem"],
                    "kernel": docker["KernelVersion"],
                    "architecture": docker["Architecture"],
                    "cpus": docker["NCPU"],
                    "memory_bytes": docker["MemTotal"],
                },
                "compose": self.compose.version(),
                # How late this machine's sleeps woke, just before the run (spec/decisions/0015).
                "timers": {
                    "sleeps": PROBE_SLEEPS,
                    "gap_ms": PROBE_GAP_MS,
                    "median_late_ms": round(timers.median_ms, 3),
                    "p99_late_ms": round(timers.p99_ms, 3),
                },
            },
            "warmup": {"requests": warmup.requests},
            "results": measured.described(workload),
            "oha": measured.raw,
        }
        return save(record, self.runs_dir)

    def restore(self) -> None:
        """Every backend running again, with the settings `.env` gives."""
        for service in BACKENDS:
            self.compose.start(service, {})

    def _send(self, command: Sequence[str]) -> str:
        duration_s = int(command[command.index("-z") + 1].removesuffix("s"))
        return self.load(command, duration_s + GRACE_S)


def save(record: dict[str, Any], runs_dir: Path) -> Path:
    """Writes a run's file, once: it fails if the file is already there."""
    path = runs_dir / f"{record['id']}.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)
        file.write("\n")
    return path


def summary(path: Path) -> str:
    """One line on a saved run."""
    record = json.loads(path.read_text(encoding="utf-8"))
    results = record["results"]
    latency = results["latency_ms"]
    kept = "" if results["rate_kept"] else ", THE RATE WASN'T KEPT"
    return (
        f"{record['backend']['service']} at {record['workload']['rate_per_s']}/s: "
        f"{results['requests']} requests at "
        f"{results['rate_per_s']:.1f}/s{kept}; statuses {results['statuses']}, "
        f"errors {results['errors']}; latency p50 {latency['p50']} ms, p95 {latency['p95']}, "
        f"p99 {latency['p99']}; saved as runs/{path.name}"
    )


def _spread(values: Sequence[float | None]) -> str:
    """The median of a number over the passes, and its range."""
    known = [value for value in values if value is not None]
    if not known:
        return "none"
    if len(known) == 1:
        return f"{known[0]:.1f}"
    return f"{statistics.median(known):.1f} ({min(known):.1f} to {max(known):.1f})"


def table(paths: Sequence[Path]) -> str:
    """These runs as a Markdown table: for each backend and rate, the latency's p50 and p99 over
    the passes, as a median and a range, with the errors and the runs that kept their rate."""
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        key = (record["backend"]["service"], record["workload"]["rate_per_s"])
        groups.setdefault(key, []).append(record["results"])
    lines = [
        "| Backend | Rate | Runs | p50, ms | p99, ms | Requests | Not 200 | Kept the rate |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (service, rate), results in sorted(
        groups.items(), key=lambda group: (BACKENDS.index(group[0][0]), group[0][1])
    ):
        requests = sum(result["requests"] for result in results)
        good = sum(result["statuses"].get("200", 0) for result in results)
        kept = sum(result["rate_kept"] for result in results)
        lines.append(
            f"| `{service}` | {rate}/s | {len(results)} "
            f"| {_spread([result['latency_ms']['p50'] for result in results])} "
            f"| {_spread([result['latency_ms']['p99'] for result in results])} "
            f"| {requests} | {requests - good} | {kept} of {len(results)} |"
        )
    return "\n".join(lines)


def main(
    arguments: Sequence[str] | None = None,
    runner: Runner | None = None,
    out: Callable[[str], object] = print,
) -> int:
    parser = argparse.ArgumentParser(prog="runner", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--backend",
        action="append",
        choices=BACKENDS,
        help="a backend to run against; may be given more than once (default: every backend)",
    )
    parser.add_argument(
        "--rate",
        action="append",
        type=int,
        help=f"a rate, in requests a second; may be given more than once (default: {RATES})",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=PASSES,
        help=f"how many times to run every backend at every rate (default: {PASSES})",
    )
    options = parser.parse_args(arguments)
    runner = runner or Runner(Compose(), machine=os.environ.get(MACHINE_SETTING) or None)
    backends = list(options.backend or BACKENDS)
    paths = []
    try:
        for run_pass in range(1, options.passes + 1):
            # The order rotates, so no backend always runs first.
            turn = (run_pass - 1) % len(backends)
            for service in backends[turn:] + backends[:turn]:
                for rate in sorted(options.rate or RATES):
                    paths.append(runner.run(service, STREAM_20.at(rate), run_pass))
                    out(f"pass {run_pass}, {summary(paths[-1])}")
    finally:
        runner.restore()
        if paths:
            out("")
            out(table(paths))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
