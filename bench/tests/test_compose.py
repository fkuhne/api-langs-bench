"""The Compose driver, against a stand-in for the Docker CLI (spec/decisions/0017)."""

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from bench.compose import DOCKER, Compose, ComposeError, State, _run

BASE = [DOCKER, "compose", "--project-directory", "/repo"]


class Docker:
    """Records each command and its environment, and answers from a list of results."""

    def __init__(self, *answers: tuple[int, str, str]) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(
        self, command: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(environment)))
        code, out, err = self.answers.pop(0)
        return subprocess.CompletedProcess(command, code, out, err)


def compose(docker: Docker) -> Compose:
    return Compose(
        Path("/repo"), run=docker, environment={"PATH": "/bin", "FAKE_TOKEN_GAP_MS": "7"}
    )


def test_up_waits_for_the_service_with_its_settings_over_the_environment() -> None:
    docker = Docker((0, "", ""))

    assert compose(docker).up("go-gin", {"FAKE_TOKEN_GAP_MS": "20"}) is True

    command, environment = docker.calls[0]
    assert command == [
        *BASE,
        *["up", "--detach", "--wait", "--wait-timeout", "60", "--no-build", "--no-deps", "go-gin"],
    ]
    assert environment == {"PATH": "/bin", "FAKE_TOKEN_GAP_MS": "20"}


def test_up_is_false_when_the_service_doesnt_get_healthy() -> None:
    assert compose(Docker((1, "", "container exited (1)"))).up("go-gin", {}) is False


def test_start_fails_with_the_services_last_logs() -> None:
    docker = Docker((1, "", "exited"), (0, "invalid setting: FAKE_ANSWER_TOKENS\n", ""))

    with pytest.raises(ComposeError, match="go-gin didn't start:\ninvalid setting"):
        compose(docker).start("go-gin", {"FAKE_ANSWER_TOKENS": "0"})

    assert docker.calls[1][0] == [*BASE, "logs", "--no-color", "--tail", "20", "go-gin"]


def test_start_returns_once_the_service_is_healthy() -> None:
    docker = Docker((0, "", ""))

    compose(docker).start("go-gin", {})

    assert len(docker.calls) == 1


def test_state_reads_the_one_container() -> None:
    line = '{"Service":"go-gin","State":"exited","ExitCode":1,"Health":""}\n'
    docker = Docker((0, line, ""))

    assert compose(docker).state("go-gin") == State(state="exited", exit_code=1)
    assert docker.calls[0] == (
        [*BASE, "ps", "--all", "--format", "json", "go-gin"],
        {"PATH": "/bin", "FAKE_TOKEN_GAP_MS": "7"},
    )


def test_state_fails_without_exactly_one_container() -> None:
    with pytest.raises(ComposeError, match="has 0 containers"):
        compose(Docker((0, "\n", ""))).state("go-gin")


def test_a_failed_command_fails_with_its_errors() -> None:
    with pytest.raises(ComposeError, match="no such service: go-fiber"):
        compose(Docker((1, "", "no such service: go-fiber"))).state("go-fiber")


def test_the_default_runner_runs_the_command_with_the_environment() -> None:
    script = "import os; print(os.environ['ANSWER'])"

    result = _run([sys.executable, "-c", script], {"ANSWER": "42"})

    assert (result.returncode, result.stdout) == (0, "42\n")
