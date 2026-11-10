"""The first runner: one workload, sent to each backend in turn, each run saved once
(spec/decisions/0018).

    docker compose run --rm runner [--backend NAME]...
"""

import argparse
import json
import os
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
from bench.workload import STREAM_20, Workload

# Where the runner's service mounts the repository's `runs/`.
RUNS_DIR = Path("/runs")
# The version of a run's file. It changes when a field's meaning does.
SCHEMA = 1
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

    def run(self, service: str, workload: Workload) -> Path:
        """One run: `workload` against `service`, alone, its fake set as the workload asks."""
        self.compose.stop(*(other for other in BACKENDS if other != service))
        self.compose.start(service, workload.settings.environment())
        timers = Tolerance.of(self.probe())
        started = self.now()
        target = url(service, workload.path)
        warmup = oha.parse(self._send(oha.command(workload, target, workload.warmup_s)))
        command = oha.command(workload, target, workload.duration_s)
        measured = oha.parse(self._send(command))
        docker = self.compose.docker_info()
        record = {
            "schema": SCHEMA,
            "id": f"{started:%Y%m%dT%H%M%SZ}-{service}",
            "started_at": f"{started:%Y-%m-%dT%H:%M:%SZ}",
            "backend": {"service": service, "image": self.compose.image(service)},
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
        f"{record['backend']['service']}: {results['requests']} requests at "
        f"{results['rate_per_s']:.1f}/s{kept}; statuses {results['statuses']}, "
        f"errors {results['errors']}; latency p50 {latency['p50']} ms, p95 {latency['p95']}, "
        f"p99 {latency['p99']}; saved as runs/{path.name}"
    )


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
    options = parser.parse_args(arguments)
    runner = runner or Runner(Compose(), machine=os.environ.get(MACHINE_SETTING) or None)
    try:
        for service in options.backend or BACKENDS:
            out(summary(runner.run(service, STREAM_20)))
    finally:
        runner.restore()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
