"""The runner, with stand-ins for Docker and oha (spec/decisions/0018, spec/decisions/0026)."""

import http.server
import json
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bench import oha
from bench.compose import Compose
from bench.runner import Runner, Target, _load, _size, main, save, summary, table
from bench.workload import LLAMA_20, STREAM_20
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
            # The backends on their cores, with their limits; the helpers on theirs, without.
            helper = command[-1].startswith(("fake-server", "llama-cpp"))
            out = "0 0 0,1\n" if helper else "1000000000 536870912 2,3\n"
        elif "--quiet" in command:
            out = f"{command[-1]}-f198ed0e450c\n"
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
        size=lambda to, load: 865,
        now=lambda: datetime(2026, 11, 9, 21, 30, 5, tzinfo=UTC),
        probe=lambda: [1.0, 2.0, 3.0],
        repository=lambda: {"commit": "0ed94a9", "dirty": False},
        cores=lambda: [0, 1],
    )


GIN = Target("go-gin", "fake")
GIN_VIA_SERVER = Target("go-gin", "fake-server")
SERVER_ALONE = Target(None, "fake-server")
GIN_VIA_LLAMA = Target("go-gin", "llama-cpp")
LLAMA_ALONE = Target(None, "llama-cpp")


def ups(docker: Docker) -> list[tuple[str, bool, dict[str, str]]]:
    """Each service started: its name, whether in a new container, and its settings."""
    return [
        (call[-1], "--force-recreate" in call, env) for call, env in docker.calls if "up" in call
    ]


def test_a_run_measures_one_backend_alone_with_the_workloads_settings(
    runner: Runner, docker: Docker
) -> None:
    runner.run(GIN, STREAM_20)

    assert docker.did("stop") == [["python-fastapi", "go-nethttp"]]
    assert ups(docker) == [("go-gin", True, STREAM_20.settings.environment())]


def test_through_the_fake_server_both_start_anew_with_the_same_settings(
    runner: Runner, docker: Docker
) -> None:
    runner.run(GIN_VIA_SERVER, STREAM_20)

    fake = STREAM_20.settings.environment()
    assert ups(docker) == [
        ("fake-server", True, fake),
        (
            "go-gin",
            True,
            fake
            | {"LLM_PROVIDER": "openai-compatible", "LLM_BASE_URL": "http://fake-server:8080/v1"},
        ),
    ]


def test_the_upstream_alone_gets_the_load_a_backend_would_send_it(
    runner: Runner, docker: Docker, load: Oha
) -> None:
    path = runner.run(SERVER_ALONE, STREAM_20.at(500), 2)

    assert docker.did("stop") == [["python-fastapi", "go-nethttp", "go-gin"]]
    assert ups(docker) == [("fake-server", True, STREAM_20.settings.environment())]
    alone = STREAM_20.at(500).alone()
    assert load.calls[1] == (
        oha.command(alone, "http://fake-server:8080/v1/chat/completions"),
        90,
    )
    record = json.loads(path.read_text())
    assert path.name == "20261109T213005Z-fake-server-alone-500rps.json"
    assert (record["target"], record["backend"]) == ("fake-server-alone", None)
    assert record["upstream"] == {
        "name": "fake-server",
        "image": "sha256:0b89",
        "limits": {"cpus": 0, "memory_bytes": 0, "cpuset": "0,1"},
    }
    assert record["workload"] == alone.described()


def test_llama_cpp_keeps_running_and_takes_one_request_at_a_time(
    runner: Runner, docker: Docker, load: Oha
) -> None:
    path = runner.run(GIN_VIA_LLAMA, LLAMA_20)

    assert ups(docker) == [
        ("llama-cpp", False, {}),
        (
            "go-gin",
            True,
            {"LLM_PROVIDER": "openai-compatible", "LLM_BASE_URL": "http://llama-cpp:8080/v1"},
        ),
    ]
    url = "http://go-gin:8000/api/chat/stream"
    assert load.calls[:2] == [
        (oha.command(LLAMA_20, url, warmup=True), 3 * 30 + 60),
        (oha.command(LLAMA_20, url), 30 * 30 + 60),
    ]
    record = json.loads(path.read_text())
    assert path.name == "20261109T213005Z-go-gin-llama-cpp-30x1.json"
    assert record["upstream"]["name"] == "llama-cpp"
    assert record["results"]["requests_due"] == 30
    # A real model's answers vary in size, so none is taken as the measure.
    assert record["results"]["answer_bytes"] is None


def test_llama_cpp_alone_gets_the_same_request_straight(runner: Runner, load: Oha) -> None:
    runner.run(LLAMA_ALONE, LLAMA_20)

    assert load.calls[1][0] == oha.command(
        LLAMA_20.alone(), "http://llama-cpp:8080/v1/chat/completions"
    )


def test_a_run_warms_up_then_measures(runner: Runner, load: Oha) -> None:
    runner.run(GIN, STREAM_20)

    url = "http://go-gin:8000/api/chat/stream"
    assert load.calls[:2] == [
        (oha.command(STREAM_20, url, warmup=True), 65),
        (oha.command(STREAM_20, url), 90),
    ]


def test_a_runs_file_says_what_ran_where_and_what_was_measured(runner: Runner) -> None:
    path = runner.run(GIN, STREAM_20, 2)

    record: dict[str, Any] = json.loads(path.read_text())
    assert path.name == "20261109T213005Z-go-gin-fake-100rps.json"
    assert record.pop("oha") == OUTPUT
    assert record == {
        "schema": 4,
        "id": "20261109T213005Z-go-gin-fake-100rps",
        "started_at": "2026-11-09T21:30:05Z",
        "pass": 2,
        "target": "go-gin-fake",
        "backend": {
            "service": "go-gin",
            "image": "sha256:0b89",
            "limits": {"cpus": 1.0, "memory_bytes": 536870912, "cpuset": "2,3"},
        },
        "upstream": {"name": "fake", "image": None, "limits": None},
        "workload": STREAM_20.described(),
        "load_generator": {
            "name": "oha",
            "version": "1.16.0",
            "command": oha.command(STREAM_20, "http://go-gin:8000/api/chat/stream"),
            "cores": [0, 1],
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
        "results": oha.parse(json.dumps(OUTPUT)).described(STREAM_20, 865),
    }


def test_a_run_is_written_once(tmp_path: Path) -> None:
    save({"id": "a-run", "results": 1}, tmp_path)

    with pytest.raises(FileExistsError):
        save({"id": "a-run", "results": 2}, tmp_path)

    assert json.loads((tmp_path / "a-run.json").read_text()) == {"id": "a-run", "results": 1}


def test_the_summary_is_one_line_on_the_run(runner: Runner) -> None:
    line = summary(runner.run(GIN, STREAM_20))

    assert line == (
        "go-gin-fake at 100/s: 3000 requests of 3000 due, NOT EVERY ANSWER WAS WHOLE; "
        "statuses {'200': 2990, '503': 4}, "
        "errors {'connection closed before message completed': 6}; "
        "latency p50 241.343 ms, p95 243.347, p99 253.711; first byte p50 0.726; "
        "saved as runs/20261109T213005Z-go-gin-fake-100rps.json"
    )


def test_the_summary_says_when_the_load_wasnt_kept(runner: Runner, tmp_path: Path) -> None:
    record = json.loads(runner.run(LLAMA_ALONE, LLAMA_20).read_text())
    record["id"] = "slow"
    record["results"] |= {"requests": 12, "rate_kept": False, "complete": True}

    line = summary(save(record, tmp_path))

    assert line.startswith(
        "llama-cpp-alone at 30, one at a time: 12 requests of 30 due, THE LOAD WASN'T KEPT;"
    )


def ticking(runner: Runner) -> Runner:
    """The runner on a clock that moves on a second at each reading, so no two runs share a name."""
    times = (datetime(2026, 11, 9, 21, 30 + n // 60, n % 60, tzinfo=UTC) for n in range(3600))
    return Runner(**{**vars(runner), "now": lambda: next(times)})


def ran(lines: list[str]) -> list[str]:
    """Each run a line reports: its pass, its target and its load."""
    return [line.split(":")[0] for line in lines if line.startswith("pass ")]


def test_main_runs_every_backend_from_both_fakes_at_every_rate_in_three_passes(
    runner: Runner, docker: Docker, tmp_path: Path
) -> None:
    lines: list[str] = []

    code = main([], ticking(runner), lines.append)

    assert code == 0
    # Three backends from the in-process fake; three and the fake server alone through it.
    assert len(list(tmp_path.iterdir())) == 3 * (3 + 4) * 5
    assert ran(lines)[:6] == [
        "pass 1, python-fastapi-fake at 100/s",
        "pass 1, python-fastapi-fake at 200/s",
        "pass 1, python-fastapi-fake at 500/s",
        "pass 1, python-fastapi-fake at 1000/s",
        "pass 1, python-fastapi-fake at 2000/s",
        "pass 1, go-nethttp-fake at 100/s",
    ]
    assert ran(lines)[15] == "pass 1, python-fastapi-fake-server at 100/s"
    assert ran(lines)[30] == "pass 1, fake-server-alone at 100/s"
    assert ups(docker)[-4:] == [
        ("python-fastapi", False, {}),
        ("go-nethttp", False, {}),
        ("go-gin", False, {}),
        ("fake-server", False, {}),
    ]


def test_the_targets_order_rotates_from_one_pass_to_the_next(runner: Runner) -> None:
    lines: list[str] = []

    main(["--rate", "100", "--upstream", "fake-server"], ticking(runner), lines.append)

    assert [line.removesuffix(" at 100/s") for line in ran(lines)] == [
        *("pass 1, python-fastapi-fake-server", "pass 1, go-nethttp-fake-server"),
        *("pass 1, go-gin-fake-server", "pass 1, fake-server-alone"),
        *("pass 2, go-nethttp-fake-server", "pass 2, go-gin-fake-server"),
        *("pass 2, fake-server-alone", "pass 2, python-fastapi-fake-server"),
        *("pass 3, go-gin-fake-server", "pass 3, fake-server-alone"),
        *("pass 3, python-fastapi-fake-server", "pass 3, go-nethttp-fake-server"),
    ]


def test_main_runs_only_what_is_named(runner: Runner, tmp_path: Path) -> None:
    arguments = ["--upstream", "fake", "--backend", "go-nethttp"]
    arguments += ["--rate", "500", "--rate", "50", "--passes", "1"]

    main(arguments, ticking(runner), lambda line: None)

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "20261109T213000Z-go-nethttp-fake-50rps.json",
        "20261109T213001Z-go-nethttp-fake-500rps.json",
    ]


def test_llama_cpp_is_run_only_when_asked_and_one_at_a_time(runner: Runner) -> None:
    lines: list[str] = []

    main(
        ["--upstream", "llama-cpp", "--backend", "go-gin", "--passes", "1"],
        ticking(runner),
        lines.append,
    )

    assert ran(lines) == [
        "pass 1, go-gin-llama-cpp at 30, one at a time",
        "pass 1, llama-cpp-alone at 30, one at a time",
    ]


def test_main_ends_with_a_table_for_each_upstream(runner: Runner) -> None:
    lines: list[str] = []

    main(["--backend", "go-gin", "--rate", "100", "--passes", "2"], ticking(runner), lines.append)

    header = (
        "| Target | Load | Runs | p50, ms | p99, ms | First token p50, ms "
        "| Added p50, ms | Added first token, ms | Requests | Not 200 | Kept the load "
        "| All answers whole |"
    )
    numbers = "| 100/s | 2 | 241.3 (241.3 to 241.3) | 253.7 (253.7 to 253.7) | 0.7 (0.7 to 0.7) "
    assert lines[-2] == ""
    assert lines[-1].splitlines() == [
        "**From each backend's in-process fake**",
        "",
        header,
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        f"| `go-gin` {numbers}| n/a | n/a | 6000 | 20 | 2 of 2 | 0 of 2 |",
        "",
        "**Through the fake server**",
        "",
        header,
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        f"| `fake-server alone` {numbers}| n/a | n/a | 6000 | 20 | 2 of 2 | 0 of 2 |",
        # The stand-in for oha reports failed requests, so no added time is worked out.
        f"| `go-gin` {numbers}| none | none | 6000 | 20 | 2 of 2 | 0 of 2 |",
    ]


def test_no_passes_run_nothing_and_print_no_table(runner: Runner, tmp_path: Path) -> None:
    lines: list[str] = []

    assert main(["--passes", "0"], runner, lines.append) == 0
    assert (lines, list(tmp_path.iterdir())) == ([], [])


def a_run(
    backend: str | None,
    rate: int,
    p50: float | None,
    p99: float | None,
    *,
    upstream: str = "fake",
    run_pass: int = 1,
    first: float | None = 51.0,
    good: int = 3000,
    whole: bool = True,
) -> dict[str, Any]:
    """A run's record, cut to what the table reads."""
    return {
        "pass": run_pass,
        "backend": {"service": backend} if backend else None,
        "upstream": {"name": upstream},
        "workload": {"rate_per_s": rate},
        "results": {
            "requests": 3000,
            "statuses": {"200": good} if good else {},
            "rate_kept": good == 3000,
            "complete": good == 3000 and whole,
            "latency_ms": {"p50": p50, "p99": p99},
            "first_byte_ms": {"p50": first},
        },
    }


def saved(runs: Sequence[dict[str, Any]], tmp_path: Path) -> list[Path]:
    return [save({"id": str(number), **run}, tmp_path) for number, run in enumerate(runs)]


def test_the_table_gives_each_numbers_median_and_range_over_the_passes(tmp_path: Path) -> None:
    paths = saved(
        [
            a_run("go-gin", 500, 242.0, 250.0),
            a_run("python-fastapi", 500, 250.0, 300.0),
            a_run("python-fastapi", 100, 245.0, 260.0),
            a_run("python-fastapi", 500, 270.0, 900.0, good=2900),
            a_run("python-fastapi", 500, 260.0, 400.0),
            a_run("go-nethttp", 100, None, None, first=None, good=0),
        ],
        tmp_path,
    )

    assert table(paths).splitlines()[4:] == [
        "| `python-fastapi` | 100/s | 1 | 245.0 | 260.0 | 51.0 | n/a | n/a | 3000 | 0 | 1 of 1 "
        "| 1 of 1 |",
        "| `python-fastapi` | 500/s | 3 | 260.0 (250.0 to 270.0) | 400.0 (300.0 to 900.0) "
        "| 51.0 (51.0 to 51.0) | n/a | n/a | 9000 | 100 | 2 of 3 | 2 of 3 |",
        "| `go-nethttp` | 100/s | 1 | none | none | none | n/a | n/a | 3000 | 3000 | 0 of 1 "
        "| 0 of 1 |",
        "| `go-gin` | 500/s | 1 | 242.0 | 250.0 | 51.0 | n/a | n/a | 3000 | 0 | 1 of 1 | 1 of 1 |",
    ]


def test_the_added_time_is_the_backends_p50_less_the_upstreams_own_in_the_same_pass(
    tmp_path: Path,
) -> None:
    def via(
        backend: str | None, rate: int, p50: float, first: float, **more: Any
    ) -> dict[str, Any]:
        return a_run(backend, rate, p50, p50 + 10, upstream="fake-server", first=first, **more)

    paths = saved(
        [
            # Pass 1: the fake server alone ended at 241.0 ms, and the backend at 243.5.
            via(None, 100, 241.0, 51.0),
            via("go-gin", 100, 243.5, 52.0),
            # Pass 2: a slower machine moved both, and the difference less.
            via(None, 100, 251.0, 55.0, run_pass=2),
            via("go-gin", 100, 254.5, 56.5, run_pass=2),
            # A rate the backend didn't keep, one the upstream didn't, and one never run alone.
            via(None, 500, 241.0, 51.0),
            via("go-gin", 500, 900.0, 60.0, good=2000),
            via(None, 1000, 400.0, 90.0, good=2000),
            via("go-gin", 1000, 401.0, 91.0),
            via("go-gin", 2000, 300.0, 70.0),
            # Every request a 200, but some answers cut short: the numbers aren't whole streams'.
            via(None, 200, 241.0, 51.0),
            via("go-gin", 200, 1.9, 1.7, whole=False),
        ],
        tmp_path,
    )

    rows = [row.split(" | ")[6:8] for row in table(paths).splitlines()[4:]]

    assert rows == [
        ["n/a", "n/a"],  # The fake server alone, at 100
        ["n/a", "n/a"],  # at 200
        ["n/a", "n/a"],  # at 500
        ["n/a", "n/a"],  # at 1,000
        ["+3.0 (+2.5 to +3.5)", "+1.2 (+1.0 to +1.5)"],
        ["none", "none"],
        ["none", "none"],
        ["none", "none"],
        ["none", "none"],
    ]


def test_a_time_no_run_gave_adds_nothing(tmp_path: Path) -> None:
    paths = saved(
        [
            a_run(None, 100, 241.0, 250.0, upstream="fake-server", first=None),
            a_run("go-gin", 100, 243.0, 250.0, upstream="fake-server"),
        ],
        tmp_path,
    )

    assert table(paths).splitlines()[-1].split(" | ")[6:8] == ["+2.0", "none"]


def test_llama_cpps_table_names_its_load(runner: Runner, tmp_path: Path) -> None:
    paths = [
        ticked.run(target, LLAMA_20)
        for ticked in [ticking(runner)]
        for target in (LLAMA_ALONE, GIN_VIA_LLAMA)
    ]

    lines = table(paths).splitlines()

    assert lines[0] == "**Through llama.cpp**"
    assert lines[4].startswith(
        "| `llama-cpp alone` | 30, one at a time | 1 | 241.3 | 253.7 | 0.7 | n/a"
    )
    assert lines[5].startswith(
        "| `go-gin` | 30, one at a time | 1 | 241.3 | 253.7 | 0.7 | none | none | 3000"
    )


def test_main_restores_the_backends_when_a_run_fails(
    runner: Runner, docker: Docker, tmp_path: Path
) -> None:
    def fails(command: Sequence[str], timeout_s: int) -> str:
        raise RuntimeError("oha failed")

    with pytest.raises(RuntimeError, match="oha failed"):
        main([], Runner(**{**vars(runner), "load": fails}), lambda line: None)

    assert list(tmp_path.iterdir()) == []
    assert [name for name, _, _ in ups(docker)][-4:] == [
        "python-fastapi",
        "go-nethttp",
        "go-gin",
        "fake-server",
    ]


def test_the_default_loader_returns_what_the_command_printed() -> None:
    assert _load([sys.executable, "-c", "print(42)"], 10) == "42\n"


def test_the_default_loader_fails_with_the_commands_errors() -> None:
    script = "import sys; sys.exit('no route to host')"

    with pytest.raises(RuntimeError, match="no route to host"):
        _load([sys.executable, "-c", script], 10)


def test_the_default_size_is_one_answers_body_in_bytes() -> None:
    received: list[tuple[str, bytes, str | None]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            received.append((self.path, self.rfile.read(length), self.headers["Content-Type"]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"event: token\n\n" * 3)

        def log_message(self, *arguments: object) -> None:
            """Nothing: the test's output stays clean."""

    with http.server.HTTPServer(("127.0.0.1", 0), Handler) as server:
        threading.Thread(target=server.handle_request).start()
        to = f"http://127.0.0.1:{server.server_port}/api/chat/stream"

        assert _size(to, STREAM_20) == 3 * len(b"event: token\n\n")

    assert received == [
        ("/api/chat/stream", json.dumps(STREAM_20.body).encode(), "application/json")
    ]
