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
from bench.runner import Runner, _load, main, save, summary
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
        if "images" in command:
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
    assert up[0][-1] == "go-gin"
    assert up[1] == STREAM_20.settings.environment()


def test_a_run_warms_up_then_measures(runner: Runner, load: Oha) -> None:
    runner.run("go-gin", STREAM_20)

    url = "http://go-gin:8000/api/chat/stream"
    assert load.calls[:2] == [
        (oha.command(STREAM_20, url, 5), 65),
        (oha.command(STREAM_20, url, 30), 90),
    ]


def test_a_runs_file_says_what_ran_where_and_what_was_measured(runner: Runner) -> None:
    path = runner.run("go-gin", STREAM_20)

    record: dict[str, Any] = json.loads(path.read_text())
    assert path.name == "20261109T213005Z-go-gin.json"
    assert record.pop("oha") == OUTPUT
    assert record == {
        "schema": 1,
        "id": "20261109T213005Z-go-gin",
        "started_at": "2026-11-09T21:30:05Z",
        "backend": {"service": "go-gin", "image": "sha256:0b89"},
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
        "go-gin: 3000 requests at 100.0/s; statuses {'200': 2990, '503': 4}, "
        "errors {'connection closed before message completed': 6}; "
        "latency p50 241.343 ms, p95 243.347, p99 253.711; "
        "saved as runs/20261109T213005Z-go-gin.json"
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
    path = save({"id": "slow", "backend": {"service": "go-gin"}, "results": results}, tmp_path)

    assert "at 41.0/s, THE RATE WASN'T KEPT;" in summary(path)


def test_main_runs_every_backend_then_restores_them(
    runner: Runner, docker: Docker, tmp_path: Path
) -> None:
    times = iter(datetime(2026, 11, 9, 21, 30, second, tzinfo=UTC) for second in range(3))
    lines: list[str] = []

    code = main([], Runner(**{**vars(runner), "now": lambda: next(times)}), lines.append)

    assert code == 0
    assert [line.split(":")[0] for line in lines] == ["python-fastapi", "go-nethttp", "go-gin"]
    assert len(list(tmp_path.iterdir())) == 3
    restored = [(call[-1], env) for call, env in docker.calls if "up" in call][-3:]
    assert restored == [("python-fastapi", {}), ("go-nethttp", {}), ("go-gin", {})]


def test_main_runs_only_the_backends_named(runner: Runner, tmp_path: Path) -> None:
    main(["--backend", "go-nethttp"], runner, lambda line: None)

    assert [path.name for path in tmp_path.iterdir()] == ["20261109T213005Z-go-nethttp.json"]


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
