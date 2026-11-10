"""The runner, with stand-ins for Docker and oha (spec/decisions/0018)."""

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bench import oha
from bench.compose import Compose
from bench.runner import Runner, _load, main, save, summary, table
from bench.workload import STREAM_20
from tests.test_oha import OUTPUT

INFO = {
    "ServerVersion": "29.5.2",
    "OperatingSystem": "Ubuntu 24.04.4 LTS",
    "KernelVersion": "6.8.0",
    "Architecture": "aarch64",
    "NCPU": 4,
    "MemTotal": 5_000_000_000,
    "Name": "left out",
}


class Docker:
    """Answers each Docker command the runner makes, and records them with their settings."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(
        self, command: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(environment)))
        out = ""
        if "inspect" in command:
            out = "1000000000 536870912\n"
        elif "--quiet" in command:
            out = "f198ed0e450c\n"
        elif "images" in command:
            out = json.dumps([{"ID": "sha256:0b89"}])
        elif "info" in command:
            out = json.dumps(INFO)
        elif "version" in command:
            out = "5.1.4\n"
        return subprocess.CompletedProcess(command, 0, out, "")

    def did(self, verb: str) -> list[list[str]]:
        """The arguments after `verb`, for each command with it."""
        return [call[call.index(verb) + 1 :] for call, _ in self.calls if verb in call]


class Oha:
    """Answers each oha command with the same output, and records them."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, command: Sequence[str], timeout_s: int) -> str:
        self.calls.append((list(command), timeout_s))
        return "oha 1.16.0\n" if "--version" in command else json.dumps(OUTPUT)


@pytest.fixture
def docker() -> Docker:
    return Docker()


@pytest.fixture
def load() -> Oha:
    return Oha()


@pytest.fixture
def runner(docker: Docker, load: Oha, tmp_path: Path) -> Runner:
    return Runner(
        compose=Compose(Path("/repo"), run=docker, environment={}),
        runs_dir=tmp_path,
        machine="A test machine",
        load=load,
        now=lambda: datetime(2026, 11, 9, 21, 30, 5, tzinfo=UTC),
        probe=lambda: [1.0, 2.0, 3.0],
        repository=lambda: {"commit": "0ed94a9", "dirty": False},
    )


def test_a_run_measures_one_backend_alone_with_the_workloads_settings(
    runner: Runner, docker: Docker
) -> None:
    runner.run("go-gin", STREAM_20)

    assert docker.did("stop") == [["python-fastapi", "go-nethttp"]]
    (up,) = [(call, env) for call, env in docker.calls if "up" in call]
    assert up[0][-2:] == ["--force-recreate", "go-gin"]
    assert up[1] == STREAM_20.settings.environment()


def test_a_run_warms_up_then_measures(runner: Runner, load: Oha) -> None:
    runner.run("go-gin", STREAM_20)

    url = "http://go-gin:8000/api/chat/stream"
    assert load.calls[:2] == [
        (oha.command(STREAM_20, url, 5), 65),
        (oha.command(STREAM_20, url, 30), 90),
    ]


def test_a_runs_file_says_what_ran_where_and_what_was_measured(runner: Runner) -> None:
    path = runner.run("go-gin", STREAM_20, 2)

    record: dict[str, Any] = json.loads(path.read_text())
    assert path.name == "20261109T213005Z-go-gin-100rps.json"
    assert record.pop("oha") == OUTPUT
    assert record == {
        "schema": 2,
        "id": "20261109T213005Z-go-gin-100rps",
        "started_at": "2026-11-09T21:30:05Z",
        "pass": 2,
        "backend": {
            "service": "go-gin",
            "image": "sha256:0b89",
            "limits": {"cpus": 1.0, "memory_bytes": 536870912},
        },
        "upstream": "fake",
        "workload": STREAM_20.described(),
        "load_generator": {
            "name": "oha",
            "version": "1.16.0",
            "command": oha.command(STREAM_20, "http://go-gin:8000/api/chat/stream", 30),
        },
        "repository": {"commit": "0ed94a9", "dirty": False},
        "machine": {
            "description": "A test machine",
            "docker": {
                "version": "29.5.2",
                "os": "Ubuntu 24.04.4 LTS",
                "kernel": "6.8.0",
                "architecture": "aarch64",
                "cpus": 4,
                "memory_bytes": 5_000_000_000,
            },
            "compose": "5.1.4",
            "timers": {"sleeps": 200, "gap_ms": 10, "median_late_ms": 2.0, "p99_late_ms": 3.0},
        },
        "warmup": {"requests": 3000},
        "results": oha.parse(json.dumps(OUTPUT)).described(STREAM_20),
    }


def test_a_run_is_written_once(tmp_path: Path) -> None:
    save({"id": "a-run", "results": 1}, tmp_path)

    with pytest.raises(FileExistsError):
        save({"id": "a-run", "results": 2}, tmp_path)

    assert json.loads((tmp_path / "a-run.json").read_text()) == {"id": "a-run", "results": 1}


def test_the_summary_is_one_line_on_the_run(runner: Runner) -> None:
    line = summary(runner.run("go-gin", STREAM_20))

    assert line == (
        "go-gin at 100/s: 3000 requests at 100.0/s; statuses {'200': 2990, '503': 4}, "
        "errors {'connection closed before message completed': 6}; "
        "latency p50 241.343 ms, p95 243.347, p99 253.711; "
        "saved as runs/20261109T213005Z-go-gin-100rps.json"
    )


def test_the_summary_says_when_the_rate_wasnt_kept(tmp_path: Path) -> None:
    results = {
        "requests": 1230,
        "rate_per_s": 41.0,
        "rate_kept": False,
        "statuses": {"200": 1230},
        "errors": {},
        "latency_ms": {"p50": 3207.7, "p95": 5772.1, "p99": 6042.8},
    }
    record = {
        "id": "slow",
        "backend": {"service": "go-gin"},
        "workload": {"rate_per_s": 100},
        "results": results,
    }
    path = save(record, tmp_path)

    assert "at 41.0/s, THE RATE WASN'T KEPT;" in summary(path)


def ticking(runner: Runner) -> Runner:
    """The runner on a clock that moves on a second at each reading, so no two runs share a name."""
    times = (datetime(2026, 11, 9, 21, 30 + n // 60, n % 60, tzinfo=UTC) for n in range(3600))
    return Runner(**{**vars(runner), "now": lambda: next(times)})


def test_main_runs_every_backend_at_every_rate_in_three_passes(
    runner: Runner, docker: Docker, tmp_path: Path
) -> None:
    lines: list[str] = []

    code = main([], ticking(runner), lines.append)

    assert code == 0
    assert len(list(tmp_path.iterdir())) == 3 * 3 * 4
    ran = [line.split(":")[0] for line in lines if line.startswith("pass ")]
    assert ran[:5] == [
        "pass 1, python-fastapi at 100/s",
        "pass 1, python-fastapi at 500/s",
        "pass 1, python-fastapi at 1000/s",
        "pass 1, python-fastapi at 2000/s",
        "pass 1, go-nethttp at 100/s",
    ]
    restored = [(call[-1], env) for call, env in docker.calls if "up" in call][-3:]
    assert restored == [("python-fastapi", {}), ("go-nethttp", {}), ("go-gin", {})]


def test_the_backends_order_rotates_from_one_pass_to_the_next(runner: Runner) -> None:
    lines: list[str] = []

    main(["--rate", "100"], ticking(runner), lines.append)

    ran = [line.split(" at ")[0] for line in lines if line.startswith("pass ")]
    assert ran == [
        *("pass 1, python-fastapi", "pass 1, go-nethttp", "pass 1, go-gin"),
        *("pass 2, go-nethttp", "pass 2, go-gin", "pass 2, python-fastapi"),
        *("pass 3, go-gin", "pass 3, python-fastapi", "pass 3, go-nethttp"),
    ]


def test_main_runs_only_what_is_named(runner: Runner, tmp_path: Path) -> None:
    arguments = ["--backend", "go-nethttp", "--rate", "500", "--rate", "50", "--passes", "1"]

    main(arguments, ticking(runner), lambda line: None)

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "20261109T213000Z-go-nethttp-50rps.json",
        "20261109T213001Z-go-nethttp-500rps.json",
    ]


def test_main_ends_with_a_table_of_its_runs(runner: Runner) -> None:
    lines: list[str] = []

    main(["--backend", "go-gin", "--rate", "100", "--passes", "2"], ticking(runner), lines.append)

    assert lines[-2] == ""
    assert lines[-1].splitlines() == [
        "| Backend | Rate | Runs | p50, ms | p99, ms | Requests | Not 200 | Kept the rate |",
        "|---|---|---|---|---|---|---|---|",
        "| `go-gin` | 100/s | 2 | 241.3 (241.3 to 241.3) | 253.7 (253.7 to 253.7) "
        "| 6000 | 20 | 2 of 2 |",
    ]


def test_no_passes_run_nothing_and_print_no_table(runner: Runner, tmp_path: Path) -> None:
    lines: list[str] = []

    assert main(["--passes", "0"], runner, lines.append) == 0
    assert (lines, list(tmp_path.iterdir())) == ([], [])


def results(p50: float | None, p99: float | None, good: int = 3000) -> dict[str, Any]:
    return {
        "requests": 3000,
        "statuses": {"200": good} if good else {},
        "rate_kept": good == 3000,
        "latency_ms": {"p50": p50, "p99": p99},
    }


def test_the_table_gives_each_numbers_median_and_range_over_the_passes(tmp_path: Path) -> None:
    runs = [
        ("go-gin", 500, results(242.0, 250.0)),
        ("python-fastapi", 500, results(250.0, 300.0)),
        ("python-fastapi", 100, results(245.0, 260.0)),
        ("python-fastapi", 500, results(270.0, 900.0, good=2900)),
        ("python-fastapi", 500, results(260.0, 400.0)),
        ("go-nethttp", 100, results(None, None, good=0)),
    ]
    paths = [
        save(
            {
                "id": str(number),
                "backend": {"service": service},
                "workload": {"rate_per_s": rate},
                "results": measured,
            },
            tmp_path,
        )
        for number, (service, rate, measured) in enumerate(runs)
    ]

    assert table(paths).splitlines()[2:] == [
        "| `python-fastapi` | 100/s | 1 | 245.0 | 260.0 | 3000 | 0 | 1 of 1 |",
        "| `python-fastapi` | 500/s | 3 | 260.0 (250.0 to 270.0) | 400.0 (300.0 to 900.0) "
        "| 9000 | 100 | 2 of 3 |",
        "| `go-nethttp` | 100/s | 1 | none | none | 3000 | 3000 | 0 of 1 |",
        "| `go-gin` | 500/s | 1 | 242.0 | 250.0 | 3000 | 0 | 1 of 1 |",
    ]


def test_main_restores_the_backends_when_a_run_fails(
    runner: Runner, docker: Docker, tmp_path: Path
) -> None:
    def fails(command: Sequence[str], timeout_s: int) -> str:
        raise RuntimeError("oha failed")

    with pytest.raises(RuntimeError, match="oha failed"):
        main([], Runner(**{**vars(runner), "load": fails}), lambda line: None)

    assert list(tmp_path.iterdir()) == []
    assert [call[-1] for call, _ in docker.calls if "up" in call][-3:] == [
        "python-fastapi",
        "go-nethttp",
        "go-gin",
    ]


def test_the_default_loader_returns_what_the_command_printed() -> None:
    assert _load([sys.executable, "-c", "print(42)"], 10) == "42\n"


def test_the_default_loader_fails_with_the_commands_errors() -> None:
    script = "import sys; sys.exit('no route to host')"

    with pytest.raises(RuntimeError, match="no route to host"):
        _load([sys.executable, "-c", script], 10)
