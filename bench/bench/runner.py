"""The runner: a workload sent to each backend in turn, from each upstream, in passes, each run
saved once (spec/decisions/0018, spec/decisions/0020, spec/decisions/0026).

    docker compose run --rm runner [--upstream NAME]... [--backend NAME]... [--rate N]...
                                   [--passes N]
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench import oha, repository
from bench.backends import (
    BACKENDS,
    FAKE_SERVER,
    IN_PROCESS,
    LLAMA_CPP,
    upstream_settings,
    upstream_url,
    url,
)
from bench.compose import PROJECT_DIR, Compose
from bench.pace import PROBE_GAP_MS, PROBE_SLEEPS, Tolerance, probe
from bench.workload import LLAMA_20, RATES, STREAM_20, Load, Workload

# Where the runner's service mounts the repository's `runs/`.
RUNS_DIR = Path("/runs")
# The version of a run's file. It changes when a field's meaning does. 3 names the upstream; 4 adds
# the cores (spec/decisions/0027).
SCHEMA = 4
# How many times every backend is run at every rate, unless `--passes` says.
PASSES = 3
# The owner's description of the host, which Docker can't see from inside a VM.
MACHINE_SETTING = "BENCH_MACHINE"
# How long oha may take beyond the time it sends for, in seconds, before the run is given up.
GRACE_S = 2 * oha.REQUEST_TIMEOUT_S

# Every upstream a run can have, and those run unless `--upstream` says: llama.cpp needs its
# model, so it's run only when asked (spec/decisions/0026).
UPSTREAMS = (IN_PROCESS, FAKE_SERVER, LLAMA_CPP)
DEFAULT_UPSTREAMS = (IN_PROCESS, FAKE_SERVER)
# What each upstream's table is headed with.
TITLES = {
    IN_PROCESS: "From each backend's in-process fake",
    FAKE_SERVER: "Through the fake server",
    LLAMA_CPP: "Through llama.cpp",
}


@dataclass(frozen=True)
class Target:
    """What a run's load is sent to: a backend answering from an upstream, or, with no backend,
    the upstream alone."""

    backend: str | None
    upstream: str

    @property
    def name(self) -> str:
        """The target, for a run's name and a table's row."""
        return f"{self.backend}-{self.upstream}" if self.backend else f"{self.upstream}-alone"

    def url(self, path: str) -> str:
        return url(self.backend, path) if self.backend else upstream_url(self.upstream, path)


def _load(command: Sequence[str], timeout_s: int) -> str:
    # The command is always one of oha's own, built by `bench.oha`.
    result = subprocess.run(  # noqa: S603
        command, capture_output=True, text=True, check=False, timeout=timeout_s
    )
    if result.returncode != 0:
        raise RuntimeError(f"`{' '.join(command)}` failed: {result.stderr}")
    return result.stdout


def _size(to: str, load: Load) -> int:
    """The size of one answer's body, asked for once."""
    request = urllib.request.Request(  # noqa: S310
        to,
        data=json.dumps(load.body).encode(),
        headers={"Content-Type": "application/json"},
        method=load.method,
    )
    # The address is always one of the runner's own targets, on Compose's network.
    with urllib.request.urlopen(request, timeout=oha.REQUEST_TIMEOUT_S) as response:  # noqa: S310
        return len(response.read())


@dataclass(frozen=True)
class Runner:
    """Runs a workload against one target at a time, and saves what it measured."""

    compose: Compose
    runs_dir: Path = RUNS_DIR
    # The host, in the owner's words.
    machine: str | None = None
    load: Callable[[Sequence[str], int], str] = _load
    size: Callable[[str, Load], int] = _size
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    probe: Callable[[], list[float]] = probe
    repository: Callable[[], dict[str, Any]] = lambda: repository.describe(PROJECT_DIR)
    # The cores this process, and so the load generator it starts, may run on.
    cores: Callable[[], list[int]] = lambda: sorted(os.sched_getaffinity(0))

    def run(self, target: Target, workload: Load, run_pass: int = 1) -> Path:
        """One run: `workload` against `target`, no other backend running. The backend and the
        fake server each start in a new container, with the settings the workload asks."""
        self.compose.stop(*(other for other in BACKENDS if other != target.backend))
        if target.upstream == FAKE_SERVER:
            self.compose.start(FAKE_SERVER, workload.environment, fresh=True)
        elif target.upstream == LLAMA_CPP:
            # Kept running from one run to the next: its model takes seconds to load.
            self.compose.start(LLAMA_CPP, {})
        if target.backend:
            settings = workload.environment | upstream_settings(target.upstream)
            self.compose.start(target.backend, settings, fresh=True)
            sent = workload
        else:
            sent = workload.alone()
        timers = Tolerance.of(self.probe())
        started = self.now()
        to = target.url(sent.path)
        # Both fakes answer the same request with the same bytes every time, so one answer's
        # size says whether every other one was whole. A real model's answers vary.
        answer_bytes = self.size(to, sent) if isinstance(sent, Workload) else None
        warmup = oha.parse(self._send(sent, to, warmup=True))
        command = oha.command(sent, to)
        measured = oha.parse(self._send(sent, to))
        docker = self.compose.docker_info()
        record = {
            "schema": SCHEMA,
            "id": f"{started:%Y%m%dT%H%M%SZ}-{target.name}-{sent.label}",
            "started_at": f"{started:%Y-%m-%dT%H:%M:%SZ}",
            "pass": run_pass,
            "target": target.name,
            # None when the load goes straight to the upstream.
            "backend": target.backend
            and {
                "service": target.backend,
                "image": self.compose.image(target.backend),
                # As Docker holds the container to them: 0 is no limit, and a None cpuset any core
                # (R5).
                "limits": self.compose.limits(target.backend),
            },
            "upstream": {
                "name": target.upstream,
                # The in-process fake is part of the backend's own image, and its limits.
                "image": None
                if target.upstream == IN_PROCESS
                else self.compose.image(target.upstream),
                "limits": None
                if target.upstream == IN_PROCESS
                else self.compose.limits(target.upstream),
            },
            "workload": sent.described(),
            "load_generator": {
                "name": "oha",
                "version": self.load([oha.OHA, "--version"], GRACE_S).strip().removeprefix("oha "),
                "command": command,
                "cores": self.cores(),
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
            "results": measured.described(sent, answer_bytes),
            "oha": measured.raw,
        }
        return save(record, self.runs_dir)

    def restore(self) -> None:
        """Every backend and the fake server running again, with the settings `.env` gives."""
        for service in (*BACKENDS, FAKE_SERVER):
            self.compose.start(service, {})

    def _send(self, load: Load, to: str, *, warmup: bool = False) -> str:
        limit = oha.time_limit_s(load, warmup=warmup) + GRACE_S
        return self.load(oha.command(load, to, warmup=warmup), limit)


def save(record: dict[str, Any], runs_dir: Path) -> Path:
    """Writes a run's file, once: it fails if the file is already there."""
    path = runs_dir / f"{record['id']}.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)
        file.write("\n")
    return path


def _load_of(workload: dict[str, Any]) -> str:
    """A recorded workload's load, for a line or a row: its rate, or its requests in turn."""
    if "rate_per_s" in workload:
        return f"{workload['rate_per_s']}/s"
    return f"{workload['requests']}, one at a time"


def summary(path: Path) -> str:
    """One line on a saved run."""
    record = json.loads(path.read_text(encoding="utf-8"))
    results = record["results"]
    latency = results["latency_ms"]
    kept = "" if results["rate_kept"] else ", THE LOAD WASN'T KEPT"
    kept += "" if results["complete"] else ", NOT EVERY ANSWER WAS WHOLE"
    return (
        f"{record['target']} at {_load_of(record['workload'])}: "
        f"{results['requests']} requests of {results['requests_due']} due{kept}; "
        f"statuses {results['statuses']}, errors {results['errors']}; "
        f"latency p50 {latency['p50']} ms, p95 {latency['p95']}, p99 {latency['p99']}; "
        f"first byte p50 {results['first_byte_ms']['p50']}; saved as runs/{path.name}"
    )


def _spread(values: Sequence[float | None], *, signed: bool = False) -> str:
    """The median of a number over the passes, and its range."""
    known = [value for value in values if value is not None]
    show = "{:+.1f}" if signed else "{:.1f}"
    if not known:
        return "none"
    if len(known) == 1:
        return show.format(known[0])
    middle, low, high = (show.format(v) for v in (statistics.median(known), min(known), max(known)))
    return f"{middle} ({low} to {high})"


def _added(run: dict[str, Any], alone: dict[str, Any] | None, time: str) -> float | None:
    """What the backend added to a run's p50 over its upstream's own, in the same pass: None
    unless both runs kept their load, got every answer whole, and gave the time
    (spec/decisions/0026)."""
    if alone is None or not (_sound(run["results"]) and _sound(alone["results"])):
        return None
    ours, theirs = run["results"][time]["p50"], alone["results"][time]["p50"]
    return None if ours is None or theirs is None else ours - theirs


def _sound(results: dict[str, Any]) -> bool:
    """A run whose numbers describe whole answers at the load asked for."""
    return bool(results["rate_kept"] and results["complete"])


def _order(key: tuple[str | None, str, int]) -> tuple[int, int]:
    """The upstream alone first, then the backends in their order; each by its load."""
    backend, _, load = key
    return (BACKENDS.index(backend) + 1 if backend else 0, load)


def _table(upstream: str, records: Sequence[dict[str, Any]]) -> str:
    """One upstream's runs as a Markdown table, under its title."""
    groups: dict[tuple[str | None, str, int], list[dict[str, Any]]] = {}
    alone: dict[tuple[int, int], dict[str, Any]] = {}
    for record in records:
        workload = record["workload"]
        load = workload.get("rate_per_s", workload.get("requests", 0))
        backend = record["backend"]["service"] if record["backend"] else None
        groups.setdefault((backend, _load_of(workload), load), []).append(record)
        if backend is None:
            alone[(record["pass"], load)] = record
    lines = [
        f"**{TITLES[upstream]}**",
        "",
        "| Target | Load | Runs | p50, ms | p99, ms | First token p50, ms "
        "| Added p50, ms | Added first token, ms | Requests | Not 200 | Kept the load "
        "| All answers whole |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for (backend, shown, load), runs in sorted(groups.items(), key=lambda group: _order(group[0])):
        results = [run["results"] for run in runs]
        requests = sum(result["requests"] for result in results)
        good = sum(result["statuses"].get("200", 0) for result in results)
        kept = sum(result["rate_kept"] for result in results)
        whole = sum(result["complete"] for result in results)
        added = {
            time: _spread(
                [_added(run, alone.get((run["pass"], load)), time) for run in runs], signed=True
            )
            if backend and alone
            else "n/a"
            for time in ("latency_ms", "first_byte_ms")
        }
        lines.append(
            f"| `{backend or upstream + ' alone'}` | {shown} | {len(runs)} "
            f"| {_spread([result['latency_ms']['p50'] for result in results])} "
            f"| {_spread([result['latency_ms']['p99'] for result in results])} "
            f"| {_spread([result['first_byte_ms']['p50'] for result in results])} "
            f"| {added['latency_ms']} | {added['first_byte_ms']} "
            f"| {requests} | {requests - good} | {kept} of {len(runs)} | {whole} of {len(runs)} |"
        )
    return "\n".join(lines)


def table(paths: Sequence[Path]) -> str:
    """These runs as Markdown tables, one for each upstream. Each row is a target at a load: its
    latency's p50 and p99 and its first token's p50 over the passes, as a median and a range;
    what the backend added over its upstream alone; the errors; the runs that kept their load;
    and those whose every answer was whole."""
    by_upstream: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        by_upstream.setdefault(record["upstream"]["name"], []).append(record)
    return "\n\n".join(
        _table(upstream, by_upstream[upstream]) for upstream in UPSTREAMS if upstream in by_upstream
    )


def main(
    arguments: Sequence[str] | None = None,
    runner: Runner | None = None,
    out: Callable[[str], object] = print,
) -> int:
    parser = argparse.ArgumentParser(prog="runner", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--upstream",
        action="append",
        choices=UPSTREAMS,
        help=f"an upstream to run from; may be given more than once (default: {DEFAULT_UPSTREAMS})",
    )
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
    rates = sorted(options.rate or RATES)
    paths = []
    try:
        for run_pass in range(1, options.passes + 1):
            for upstream in options.upstream or DEFAULT_UPSTREAMS:
                targets = [Target(backend, upstream) for backend in backends]
                if upstream != IN_PROCESS:
                    # The upstream alone, which the backends' added time is worked out against.
                    targets.append(Target(None, upstream))
                loads: list[Load] = (
                    [LLAMA_20] if upstream == LLAMA_CPP else [STREAM_20.at(rate) for rate in rates]
                )
                # The order rotates, so no target always runs first.
                turn = (run_pass - 1) % len(targets)
                for target in targets[turn:] + targets[:turn]:
                    for load in loads:
                        paths.append(runner.run(target, load, run_pass))
                        out(f"pass {run_pass}, {summary(paths[-1])}")
    finally:
        runner.restore()
        if paths:
            out("")
            out(table(paths))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
