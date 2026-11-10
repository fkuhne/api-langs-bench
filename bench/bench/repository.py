"""The repository a run was made from (spec/decisions/0018)."""

from pathlib import Path
from typing import Any

from dulwich import porcelain
from dulwich.repo import Repo


def describe(path: Path) -> dict[str, Any]:
    """The commit checked out at `path`, and whether any tracked file differs from it. Files git
    doesn't track, such as a new run's, don't count."""
    with Repo(str(path)) as repo:
        commit = repo.head().decode("ascii")
        status = porcelain.status(repo, untracked_files="no")
    dirty = any(status.staged.values()) or bool(status.unstaged)
    return {"commit": commit, "dirty": dirty}
