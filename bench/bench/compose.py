"""Starts a backend with the settings a check needs, through Docker Compose (spec/decisions/0017).

The conformance service holds Docker's socket and the repository, read-only, at `/repo`, so the
Compose inside it drives the same project as the one outside: the same `compose.yaml`, `.env`
and containers.
"""

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# Where the conformance image puts Docker's binary, and its service mounts the repository.
DOCKER = "/usr/local/bin/docker"
PROJECT_DIR = Path("/repo")
# How long Compose waits for a backend to become healthy, in seconds.
WAIT_TIMEOUT_S = 60

type Run = Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]]


def _run(
    command: Sequence[str], environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    # The command is always one of this module's own, never anything a request holds.
    return subprocess.run(  # noqa: S603
        command,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
        timeout=2 * WAIT_TIMEOUT_S,
    )


class ComposeError(RuntimeError):
    """Compose failed to do what was asked."""


@dataclass(frozen=True)
class State:
    """A service's container, as `docker compose ps` shows it."""

    state: str
    exit_code: int


class Compose:
    """One Compose project's services, started and inspected through the Docker CLI."""

    def __init__(
        self,
        project_dir: Path = PROJECT_DIR,
        run: Run = _run,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._command = [DOCKER, "compose", "--project-directory", str(project_dir)]
        self._run = run
        self._environment = dict(os.environ if environment is None else environment)

    def up(self, service: str, settings: Mapping[str, str]) -> bool:
        """Starts `service` with `settings` over this process's environment, recreating it if they
        changed, and waits until it's healthy. False if it didn't get there."""
        result = self._run(
            [
                *self._command,
                "up",
                "--detach",
                "--wait",
                "--wait-timeout",
                str(WAIT_TIMEOUT_S),
                "--no-build",
                "--no-deps",
                service,
            ],
            self._environment | dict(settings),
        )
        return result.returncode == 0

    def start(self, service: str, settings: Mapping[str, str]) -> None:
        """Starts `service` with `settings`, or fails with its last logs."""
        if not self.up(service, settings):
            raise ComposeError(f"{service} didn't start:\n{self.logs(service)}")

    def state(self, service: str) -> State:
        """The state of `service`'s one container, running or not."""
        output = self._output("ps", "--all", "--format", "json", service)
        lines = [line for line in output.splitlines() if line.strip()]
        if len(lines) != 1:
            raise ComposeError(f"{service} has {len(lines)} containers, not one: {output!r}")
        container = json.loads(lines[0])
        return State(state=container["State"], exit_code=container["ExitCode"])

    def logs(self, service: str, lines: int = 20) -> str:
        """The last lines `service`'s container wrote."""
        return self._output("logs", "--no-color", "--tail", str(lines), service)

    def _output(self, *arguments: str) -> str:
        result = self._run([*self._command, *arguments], self._environment)
        if result.returncode != 0:
            raise ComposeError(f"`docker compose {' '.join(arguments)}` failed: {result.stderr}")
        return result.stdout
