"""Read-only Git metadata for P028 InstructionRoot Resolve (T004).

Implements PROJECT_BOOK.md §13.3 ("Git Provenance") against the
frozen contract in ``00_contract/receipt_schema.json`` (``git`` object:
``repo`` / ``tracked`` / ``modified`` / ``head_commit``).

Only these four Git invocations are ever issued, each as an argument
list through :func:`subprocess.run` with ``shell=False``:

* ``git rev-parse --show-toplevel``
* ``git ls-files --error-unmatch -- <path>``
* ``git status --porcelain=v1 -- <path>``
* ``git log -1 --format=%H -- <path>``

No other git subcommand can be issued from this module: the internal
``_run_git`` helper refuses any argument list that is not one of the
four forms above (``ValueError``), so a caller cannot smuggle a
mutation or network operation through it. This module never writes to
a repository, never contacts a remote, and never spawns a shell.

Behaviour for non-git directories (PROJECT_BOOK.md §15 S25):

* :func:`find_repo_root` returns ``None``;
* :func:`get_git_state` returns a :class:`GitState` with
  ``is_git_repo=False``, ``repo=None``, ``tracked=False``,
  ``modified=False`` and ``head_commit=None`` — it does not raise.

Other fail-closed behaviour:

* A missing ``git`` binary, or a Git invocation that times out, is
  reported in ``GitState.error`` (``"GIT_NOT_AVAILABLE"`` /
  ``"GIT_TIMEOUT"``) instead of raising; the state is
  ``is_git_repo=False`` because no repository fact could be observed.
* ``head_commit`` is the SHA returned by ``git log -1`` for the path,
  i.e. the most recent commit touching that path; it is ``None`` for
  untracked files, for files in a repository with no commits yet, and
  for paths outside any repository.
* ``modified`` is True only for a *tracked* file whose
  ``git status --porcelain`` output for the path is non-empty
  (working-tree or staged difference from HEAD). An untracked file
  shows up in ``git status`` as ``??`` but is *not* modified under
  this definition (receipt schema: "False for untracked files"). A
  tracked file deleted from the working tree does show a status entry
  and therefore counts as modified; the trust classifier (T004
  ``trust.py``) still reports it as MISSING, which outranks the git
  state by the §13.4 priority order.
* Paths are passed to Git as a single argument after ``--`` and
  relative to the repository root, so names with spaces, dashes or
  non-ASCII bytes (Q3: Unicode is passed through byte-for-byte, no
  normalisation) cannot be mistaken for options.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

__all__ = [
    "GitState",
    "find_repo_root",
    "get_git_state",
    "is_git_repo",
]

#: Maximum seconds to wait for one Git invocation. Git here only reads
#: local metadata, so a generous bound still fails fast on a wedged
#: repository instead of hanging the preflight.
_GIT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class GitState:
    """Git metadata for one path (receipt ``git`` object + diagnostics).

    * ``repo`` — canonical absolute path of the containing repository
      top level, or ``None`` when the path is not inside a Git
      repository.
    * ``tracked`` — True when the path is present in the index
      (``git ls-files --error-unmatch`` exits 0).
    * ``modified`` — True when a tracked file differs from HEAD
      (working-tree or staged); always False for untracked files.
    * ``head_commit`` — full 40-hex SHA from ``git log -1`` for the
      path, or ``None`` when there is none to report.
    * ``is_git_repo`` — False exactly when no repository could be
      established for the path (non-git directory, or Git itself
      unavailable / unresponsive).
    * ``error`` — ``None`` on the normal paths; ``"GIT_NOT_AVAILABLE"``
      when the ``git`` binary cannot be run, ``"GIT_TIMEOUT"`` when an
      invocation exceeded the timeout. Diagnostic only, never part of
      the receipt hash.
    """

    repo: str | None
    tracked: bool = False
    modified: bool = False
    head_commit: str | None = None
    is_git_repo: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        """Receipt-shaped ``git`` object (exactly the schema fields)."""
        return {
            "repo": self.repo,
            "tracked": self.tracked,
            "modified": self.modified,
            "head_commit": self.head_commit,
        }


def _is_allowed(argv: list[str]) -> bool:
    """Return True only for one of the four permitted Git invocations.

    ``argv`` excludes the leading ``"git"`` itself. The final element
    of the ``ls-files`` / ``status`` / ``log`` forms is the target
    path, which may be any string (it is passed as one argument after
    ``--``).
    """
    if argv == ["rev-parse", "--show-toplevel"]:
        return True
    if len(argv) == 4 and argv[:3] == ["ls-files", "--error-unmatch", "--"]:
        return True
    if len(argv) == 4 and argv[:3] == ["status", "--porcelain=v1", "--"]:
        return True
    if len(argv) == 5 and argv[:4] == ["log", "-1", "--format=%H", "--"]:
        return True
    return False


def _run_git(argv: list[str], *, cwd: str) -> subprocess.CompletedProcess[str] | None:
    """Run one allowlisted Git command; ``None`` when Git cannot run.

    Raises ``ValueError`` for any argument list outside the allowlist
    and ``TimeoutError`` when the invocation exceeds the timeout, so
    callers can record those outcomes instead of guessing.
    """
    if not _is_allowed(argv):
        raise ValueError("refused non-allowlisted git invocation: %r" % (argv,))
    try:
        return subprocess.run(
            ["git", *argv],
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
            cwd=cwd,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("git invocation timed out: %r" % (argv,)) from exc


def _nearest_existing_dir(path: str) -> str:
    """Return *path* itself when it is a directory, else its nearest
    existing ancestor directory (``/`` at the latest). Used as the
    working directory for ``rev-parse`` so a missing file inside a
    repository still resolves its repository root."""
    candidate = os.path.abspath(path)
    while True:
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            return candidate
        candidate = parent


def find_repo_root(path) -> str | None:
    """Return the top level of the Git repository containing *path*.

    ``None`` when *path* is not inside a Git repository, when the
    ``git`` binary cannot be run, or when Git does not answer in time.
    Never raises for a non-git directory (S25).
    """
    target = os.fspath(path)
    if isinstance(target, bytes):
        raise TypeError("path must be str, not bytes")
    try:
        result = _run_git(
            ["rev-parse", "--show-toplevel"],
            cwd=_nearest_existing_dir(target),
        )
    except TimeoutError:
        return None
    if result is None or result.returncode != 0:
        return None
    root = result.stdout.strip()
    if not root:
        return None
    return os.path.normpath(root)


def is_git_repo(path) -> bool:
    """Return True when *path* is inside a Git repository."""
    return find_repo_root(path) is not None


def _relative_to_repo(path: str, repo: str) -> str | None:
    """Return *path* relative to *repo*, or ``None`` when it lies
    outside the repository (``..`` escape)."""
    try:
        rel = os.path.relpath(os.path.abspath(path), repo)
    except ValueError:
        return None
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    return rel


def get_git_state(path, *, repo_root=None) -> GitState:
    """Return the :class:`GitState` for *path*.

    * ``repo_root`` may supply a known repository top level (from a
      snapshot); otherwise it is discovered with
      :func:`find_repo_root`. A path outside the supplied repository
      is reported as not in a repository (``repo=None``).
    * Never raises for a non-git directory, a missing path, an
      untracked file, or a repository with no commits yet — those are
      ordinary states, reported in the returned record.
    """
    target = os.fspath(path)
    if isinstance(target, bytes):
        raise TypeError("path must be str, not bytes")
    repo = None
    if repo_root is not None:
        repo_text = os.fspath(repo_root)
        if isinstance(repo_text, bytes):
            raise TypeError("repo_root must be str, not bytes")
        repo = os.path.normpath(repo_text)
        if _relative_to_repo(target, repo) is None:
            return GitState(repo=None, tracked=False, modified=False,
                            head_commit=None, is_git_repo=False)
    else:
        repo = find_repo_root(target)
        if repo is None:
            return GitState(repo=None, tracked=False, modified=False,
                            head_commit=None, is_git_repo=False)

    rel = _relative_to_repo(target, repo)
    if rel is None:  # defensive: find_repo_root said inside, rel says outside
        return GitState(repo=None, tracked=False, modified=False,
                        head_commit=None, is_git_repo=False)

    try:
        ls_result = _run_git(
            ["ls-files", "--error-unmatch", "--", rel], cwd=repo)
        status_result = _run_git(
            ["status", "--porcelain=v1", "--", rel], cwd=repo)
        log_result = _run_git(
            ["log", "-1", "--format=%H", "--", rel], cwd=repo)
    except TimeoutError:
        return GitState(repo=repo, tracked=False, modified=False,
                        head_commit=None, is_git_repo=False,
                        error="GIT_TIMEOUT")
    if ls_result is None or status_result is None or log_result is None:
        return GitState(repo=repo, tracked=False, modified=False,
                        head_commit=None, is_git_repo=False,
                        error="GIT_NOT_AVAILABLE")

    tracked = ls_result.returncode == 0
    # Status output is authoritative for "differs from HEAD" only for
    # tracked files; untracked files always report "??" and are not
    # modified under the receipt-schema definition.
    modified = bool(tracked and status_result.stdout.strip() != "")
    head_commit: str | None = None
    if log_result.returncode == 0:
        candidate = log_result.stdout.strip().splitlines()
        if candidate:
            sha = candidate[0].strip()
            if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
                head_commit = sha
    return GitState(
        repo=repo,
        tracked=tracked,
        modified=modified,
        head_commit=head_commit,
        is_git_repo=True,
    )
