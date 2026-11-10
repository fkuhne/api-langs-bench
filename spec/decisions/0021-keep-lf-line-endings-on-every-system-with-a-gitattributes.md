# 0021. Keep LF line endings on every system, with a `.gitattributes`

- Status: Accepted
- Date: 2026-11-10

## Context

The repository runs anywhere with Docker, Windows included ([0008](0008-run-anywhere-with-docker-and-record-the-machine.md)). Every run records its commit, and `dirty`: whether a tracked file differed from it ([0018](0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md)).

The first numbers were made on Windows on 2026-11-10, and all 36 runs say `"dirty": true`, from a tree that `git status` calls clean ([runner](../../docs/runner.md#why-every-file-says-dirty)). What was checked that day:
- **Git for Windows sets `core.autocrlf` to `true`** in its system-wide config, `C:/Program Files/Git/etc/gitconfig` (the owner, on that machine). So a checkout there has CRLF line endings.
- **The runner reads the repository from inside a container,** with dulwich, where that config can't be seen. Each file's CRLF content looks like a change.
- **Reproduced on the Mac,** with git 2.46.0: a clone made with `core.autocrlf` set outside the repository had 180 files with CRLF endings, and the runner's reader called it dirty, with 180 files changed.
- **Every tracked file is text, with LF endings in git:** 180 files, and 3 empty ones (`git ls-files --eol`).
- **Docker's builds on that machine copied CRLF sources into the images.** They built, and the 36 runs were made. Whether those images behave like the ones built from LF sources wasn't checked: no run of the conformance suite there is recorded.

## Decision

A `.gitattributes` at the root says `* text=auto eol=lf`: every text file is checked out with LF endings on every system, and is stored with LF endings whatever an editor wrote.

- **It overrides `core.autocrlf`,** wherever that is set, so nobody configures anything before cloning.
- **A clone made before this record keeps its CRLF files** until it's checked out again. In that clone:

  ```text
  git pull
  git rm --cached -r -q .
  git reset --hard
  docker compose build
  ```

  `.env` and the runs not yet committed stay as they are. A new clone needs none of this.
- **The 36 runs of the first numbers stay as they are,** with `"dirty": true`: a run is never edited ([0018](0018-the-first-runner-oha-as-the-load-generator-one-streamed-workload-and-runs-committed-as-json.md)). The notes say why.

## Alternatives considered

| Option | Why we didn't choose it |
|---|---|
| Make the runner's reader ignore line endings | `dirty` would read right, but Docker would still build Windows' images from different bytes than everywhere else. More code, for half the problem |
| Ask Windows users to set `core.autocrlf` to `false` before cloning | A manual step, and forgetting it fails silently, as it did here |
| `* -text`: no conversion at all | Checkouts would have LF endings too, but an editor's CRLF would be committed as it is |
| Leave it | `dirty` means nothing on Windows, so a run there can't show it was made from a clean tree |

## Consequences

- A run on Windows can say `"dirty": false`, and its images are built from the same bytes as on any other machine.
- A file that needs CRLF endings, or a binary file git mistakes for text, would need its own line in `.gitattributes`. There's none today.
- Runs with `"dirty": false` from the owner's Windows machine need the clone checked out again, and the ladder run again.

## Assumptions to verify

- [x] With the file, a clone made under a `core.autocrlf` set outside the repository has LF endings, and the runner's reader calls it clean. *2026-11-10, on the Mac: no file with CRLF endings, and `dirty` false, against 180 files and `dirty` true without it (our run).*
- [x] The four commands turn an older clone's files to LF endings, and keep `.env` and uncommitted runs. *2026-11-10, on the Mac, in a clone made as above: 180 files with CRLF endings before, none after, and both kept (our run).*
- [ ] On the owner's Windows machine, a run made after the new checkout says `"dirty": false`. To check with the next runs there.
- [ ] Nothing on Windows needs CRLF endings. Unchecked: every tool runs in a Linux container, and editors on Windows read LF.

## Sources

- The first numbers' 36 runs, and the owner's checks on that machine, 2026-11-10 ([runner](../../docs/runner.md#why-every-file-says-dirty)).
- Our runs on the Mac on 2026-11-10, with git 2.46.0 and dulwich 1.2.21: clones made with `GIT_CONFIG_GLOBAL` naming a file that sets `core.autocrlf` to `true`, read by [`repository.py`](../../bench/bench/repository.py) in the runner's image.
- [Git's documentation of `gitattributes`](https://git-scm.com/docs/gitattributes), for `text=auto` and `eol`. Unchecked today: cited from memory, and tested above.
- The owner's pick, 2026-11-10.
