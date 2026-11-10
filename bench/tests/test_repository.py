"""Reading the commit a run was made from (spec/decisions/0018)."""

from pathlib import Path

import pytest
from dulwich import porcelain

from bench.repository import describe


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    porcelain.init(str(tmp_path))
    (tmp_path / "kept.txt").write_text("one\n")
    porcelain.add(str(tmp_path), paths=[str(tmp_path / "kept.txt")])
    return tmp_path


def commit(repo: Path) -> str:
    made = porcelain.commit(
        str(repo), message=b"a commit", author=b"A <a@example.com>", committer=b"A <a@example.com>"
    )
    return made.decode("ascii")


def test_a_clean_checkout_gives_its_commit(repo: Path) -> None:
    made = commit(repo)

    assert describe(repo) == {"commit": made, "dirty": False}


def test_a_changed_tracked_file_is_dirty(repo: Path) -> None:
    made = commit(repo)
    (repo / "kept.txt").write_text("two\n")

    assert describe(repo) == {"commit": made, "dirty": True}


def test_a_staged_change_is_dirty(repo: Path) -> None:
    made = commit(repo)
    (repo / "new.txt").write_text("new\n")
    porcelain.add(str(repo), paths=[str(repo / "new.txt")])

    assert describe(repo) == {"commit": made, "dirty": True}


def test_an_untracked_file_such_as_a_new_run_isnt(repo: Path) -> None:
    made = commit(repo)
    (repo / "run.json").write_text("{}\n")

    assert describe(repo) == {"commit": made, "dirty": False}
