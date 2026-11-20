"""Provenance assembly for P028 InstructionRoot Resolve (T004).

Joins the two T002/T004 primitives for one source path into the
receipt-shaped record defined by ``00_contract/receipt_schema.json``:

* Git metadata from :mod:`instructionroot.git` (``repo`` /
  ``tracked`` / ``modified`` / ``head_commit``);
* content hash from :func:`instructionroot.snapshot.hash_file`
  (SHA-256 of the file bytes, ``None`` when the file cannot be read);
* the lexical/resolved dual record from
  :mod:`instructionroot.paths` (``canonical_path`` /
  ``resolved_path``), so a reviewer can see *which* path the Git
  state and the hash were taken for.

Rules:

* The hash and the Git state are always taken for the **resolved**
  path (after symlink resolution). Hashing the lexical path would
  hash the link itself rather than the content the harness would
  actually load; when resolution fails (loop / unresolvable,
  ``resolved_path`` is ``None``) no hash is asserted and the Git
  state is probed for the canonical path instead, fail-closed.
* ``sha256`` is ``None`` for missing paths, directories, broken
  symlinks and unreadable files — a missing file is never given a
  fabricated hash (receipt schema: null only when the file is
  missing; unreadable files additionally carry ``error``).
* This module performs no Git mutation and no network access: all
  Git work is delegated to :mod:`instructionroot.git`, and all
  hashing is a local file read. Standard library only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from instructionroot.git import GitState, get_git_state
from instructionroot.paths import canonicalize
from instructionroot.snapshot import hash_file

__all__ = [
    "Provenance",
    "build_provenance",
    "provenance_for_entry",
]


@dataclass(frozen=True)
class Provenance:
    """Provenance record for one source path.

    * ``repo`` / ``tracked`` / ``modified`` / ``head_commit`` — the
      Git metadata (see :class:`instructionroot.git.GitState`).
    * ``sha256`` — lowercase hex SHA-256 of the resolved file bytes,
      or ``None`` when the file is missing, a directory, a broken
      symlink, or unreadable.
    * ``canonical_path`` / ``resolved_path`` — the lexical/resolved
      dual record the Git state and hash belong to.
    * ``error`` — ``None`` on the normal paths; the
      :func:`instructionroot.paths.canonicalize` error
      (``"SYMLINK_LOOP"`` / ``"UNRESOLVABLE"``) when resolution
      failed, or ``"UNREADABLE: <ExceptionName>"`` when the file
      exists but its bytes could not be read.
    """

    repo: str | None
    tracked: bool = False
    modified: bool = False
    head_commit: str | None = None
    sha256: str | None = None
    canonical_path: str | None = None
    resolved_path: str | None = None
    error: str | None = None

    def git_dict(self) -> dict:
        """Receipt-shaped ``git`` object (exactly the schema fields)."""
        return {
            "repo": self.repo,
            "tracked": self.tracked,
            "modified": self.modified,
            "head_commit": self.head_commit,
        }

    def to_dict(self) -> dict:
        """Receipt-shaped fields: ``{"git": {...}, "sha256": ...}``."""
        return {"git": self.git_dict(), "sha256": self.sha256}

    def to_flat_dict(self) -> dict:
        """Flat dict (git fields + sha256 + paths + error)."""
        return {
            "repo": self.repo,
            "tracked": self.tracked,
            "modified": self.modified,
            "head_commit": self.head_commit,
            "sha256": self.sha256,
            "canonical_path": self.canonical_path,
            "resolved_path": self.resolved_path,
            "error": self.error,
        }


def build_provenance(
    path,
    *,
    cwd=None,
    home=None,
    repo_root=None,
    compute_hash: bool = True,
    git_state: GitState | dict | None = None,
) -> Provenance:
    """Assemble the :class:`Provenance` for *path*.

    * ``path`` may be absolute or relative to ``cwd`` (required for
      relative input); ``~`` expands only against the explicitly
      supplied ``home`` — the same input rules as
      :func:`instructionroot.paths.canonicalize`, which raises
      ``ValueError`` / ``TypeError`` only for malformed *input*.
    * ``repo_root`` may supply a known repository top level;
      otherwise it is discovered from the path itself.
    * ``git_state`` may supply a pre-computed
      :class:`instructionroot.git.GitState` (or a dict with its
      fields); otherwise :func:`instructionroot.git.get_git_state`
      is called for the resolved path.
    * With ``compute_hash=False`` the hash is skipped (``sha256``
      is ``None``) while the Git state is still reported.
    """
    # T002 canonicalize() accepts str only; accept path-like objects
    # here and convert before delegating.
    path = os.fspath(path)
    if isinstance(path, bytes):
        raise TypeError("path must be str, not bytes")
    canon = canonicalize(path, cwd=cwd, home=home)
    probe = canon.resolved_path if canon.resolved_path is not None \
        else canon.canonical_path

    if git_state is None:
        state = get_git_state(probe, repo_root=repo_root)
    elif isinstance(git_state, GitState):
        state = git_state
    elif isinstance(git_state, dict):
        state = GitState(
            repo=git_state.get("repo"),
            tracked=bool(git_state.get("tracked", False)),
            modified=bool(git_state.get("modified", False)),
            head_commit=git_state.get("head_commit"),
            is_git_repo=bool(git_state.get("is_git_repo", False)),
            error=git_state.get("error"),
        )
    else:
        raise TypeError(
            "git_state must be GitState, dict or None, not %s"
            % type(git_state).__name__
        )

    sha: str | None = None
    error: str | None = canon.error
    if (
        compute_hash
        and canon.exists
        and canon.is_file
        and canon.resolved_path is not None
    ):
        try:
            sha = hash_file(canon.resolved_path)
        except OSError as exc:
            error = "UNREADABLE: %s" % exc.__class__.__name__
            sha = None
    return Provenance(
        repo=state.repo,
        tracked=state.tracked,
        modified=state.modified,
        head_commit=state.head_commit,
        sha256=sha,
        canonical_path=canon.canonical_path,
        resolved_path=canon.resolved_path,
        error=error,
    )


def provenance_for_entry(entry, *, git_state: GitState | dict | None = None) -> Provenance:
    """Assemble a :class:`Provenance` from a T002 snapshot entry.

    Convenience wrapper for callers that already hold a
    :class:`instructionroot.snapshot.PathEntry`: the Git state is
    probed for the entry's resolved path (canonical path when
    resolution failed) and the entry's recorded ``sha256`` is reused
    instead of re-reading the file. ``git_state`` may still override
    the probed Git state, as in :func:`build_provenance`.
    """
    if git_state is None:
        probe = entry.resolved_path if entry.resolved_path is not None \
            else entry.canonical_path
        state = get_git_state(probe)
    elif isinstance(git_state, GitState):
        state = git_state
    elif isinstance(git_state, dict):
        state = GitState(
            repo=git_state.get("repo"),
            tracked=bool(git_state.get("tracked", False)),
            modified=bool(git_state.get("modified", False)),
            head_commit=git_state.get("head_commit"),
            is_git_repo=bool(git_state.get("is_git_repo", False)),
            error=git_state.get("error"),
        )
    else:
        raise TypeError(
            "git_state must be GitState, dict or None, not %s"
            % type(git_state).__name__
        )
    return Provenance(
        repo=state.repo,
        tracked=state.tracked,
        modified=state.modified,
        head_commit=state.head_commit,
        sha256=entry.sha256,
        canonical_path=entry.canonical_path,
        resolved_path=entry.resolved_path,
        error=entry.error,
    )
