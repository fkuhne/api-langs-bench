"""Starts a backend with the settings a check or a run needs, through Docker Compose
(spec/decisions/0017).

The conformance and runner services hold Docker's socket and the repository, read-only, at
`/repo`, so the Compose inside them drives the same project as the one outside: the same
`compose.yaml`, `.env` and containers.
"""

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    def up(self, service: str, settings: Mapping[str, str], *, fresh: bool = False) -> bool:
        """Starts `service` with `settings` over this process's environment, and waits until it's
        healthy. Its container is made again if they changed, or always if `fresh`. False if it
        didn't get there."""
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
                *(["--force-recreate"] if fresh else []),
                service,
            ],
            self._environment | dict(settings),
        )
        return result.returncode == 0

    def start(self, service: str, settings: Mapping[str, str], *, fresh: bool = False) -> None:
        """Starts `service` with `settings`, or fails with its last logs."""
        if not self.up(service, settings, fresh=fresh):
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

    def stop(self, *services: str) -> None:
        """Stops these services' containers, and keeps them."""
        self._output("stop", *services)

    def image(self, service: str) -> str:
        """The ID of the image `service`'s one container was made from."""
        images = json.loads(self._output("images", "--format", "json", service))
        if len(images) != 1:
            raise ComposeError(f"{service} has {len(images)} containers, not one")
        return str(images[0]["ID"])

    def limits(self, service: str) -> dict[str, float | int]:
        """The CPU and memory limits Docker holds `service`'s one container to; 0 for none."""
        containers = self._output("ps", "--quiet", service).split()
        if len(containers) != 1:
            raise ComposeError(f"{service} has {len(containers)} containers running, not one")
        template = "{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}"
        inspected = self._capture([DOCKER, "inspect", "--format", template, *containers])
        nano_cpus, memory = inspected.split()
        return {"cpus": int(nano_cpus) / 1e9, "memory_bytes": int(memory)}

    def version(self) -> str:
        """This Compose's version."""
        return self._output("version", "--short").strip()

    def docker_info(self) -> dict[str, Any]:
        """What Docker's daemon says of itself and its machine, as `docker info` gives it."""
        info: dict[str, Any] = json.loads(self._capture([DOCKER, "info", "--format", "{{json .}}"]))
        return info

    def _output(self, *arguments: str) -> str:
        return self._capture([*self._command, *arguments])

    def _capture(self, command: Sequence[str]) -> str:
        result = self._run(command, self._environment)
        if result.returncode != 0:
            raise ComposeError(f"`{' '.join(command[1:])}` failed: {result.stderr}")
        return result.stdout
