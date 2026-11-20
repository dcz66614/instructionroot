"""Filesystem snapshot for P028 InstructionRoot Resolve (T002).

Implements PROJECT_BOOK.md §8.2 ("Filesystem Discovery") and the
workspace part of ``00_contract/receipt_schema.json``:

* the snapshot records ``cwd``, ``home`` and ``repo_root`` (canonical
  absolute paths; ``repo_root`` is ``None`` for a non-git directory,
  S25), plus one deterministic entry per observed path;
* every entry carries the lexical/resolved dual record from
  :mod:`instructionroot.paths`, existence, file/dir/symlink state,
  symlink chain, byte size and SHA-256 (files only), and containment
  against the snapshot roots;
* the serialised snapshot is **deterministic**: entries are sorted by
  canonical path, JSON keys are sorted, separators are fixed, and no
  wall-clock timestamp, duration, username or other volatile value is
  ever included. The same input therefore produces byte-identical
  output on every run, and :meth:`FilesystemSnapshot.snapshot_hash`
  is stable across runs.

Scope / non-goals (later tasks own them):

* discovering *which* files are instruction sources is T003's job —
  this module only snapshots paths it is given (or a directory tree
  it is asked to walk);
* Git state (tracked / modified / HEAD commit) is T004's job;
* trust classification is T004's job — containment flags here are
  raw inputs to it, not a verdict;
* the real user home is never read: ``home`` is an explicit,
  caller-supplied path (in tests and fixtures, a synthetic directory).
  Nothing in this module calls ``Path.home()`` or ``expanduser``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, replace

from instructionroot.paths import (
    CanonicalPath,
    canonicalize,
    detect_escape,
    is_within_root,
)

__all__ = [
    "FilesystemSnapshot",
    "PathEntry",
    "SnapshotError",
    "build_snapshot",
    "hash_file",
    "snapshot_entry",
    "snapshot_tree",
]

#: Chunk size for streaming file hashes.
_HASH_CHUNK_SIZE = 65536

#: Default maximum directory depth for :func:`snapshot_tree`.
DEFAULT_MAX_DEPTH = 64


class SnapshotError(ValueError):
    """Fail-closed snapshot input error (bad cwd/home/repo_root, ...).

    A ``SnapshotError`` means the snapshot cannot be trusted, so the
    caller must not proceed to a PASS verdict on its basis. It is a
    ``ValueError`` so callers that only distinguish input errors from
    internal errors can catch it as either.
    """


def hash_file(path: str) -> str:
    """Return the lowercase hex SHA-256 of the file at *path*.

    Reads in fixed-size chunks; raises ``OSError`` when the file
    cannot be read (callers record that as an entry error, fail-closed,
    rather than inventing a hash).
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PathEntry:
    """One observed path in a snapshot (deterministic, JSON-able).

    ``canonical_path`` / ``resolved_path`` are the lexical/resolved
    dual record from :func:`instructionroot.paths.canonicalize`.
    ``sha256`` is set only for existing regular files that could be
    read; it is ``None`` for directories, missing paths, broken
    symlinks and unreadable files (with ``error`` set in the last
    case). ``contained_in`` maps each snapshot root name (``"repo"``,
    ``"home"``) to whether the *resolved* path lies within it;
    ``escapes_all_roots`` is True when the resolved path is within
    none of the snapshot roots (or resolution failed).
    """

    raw_path: str
    canonical_path: str
    resolved_path: str | None
    exists: bool = False
    is_file: bool = False
    is_dir: bool = False
    is_symlink: bool = False
    symlink_target: str | None = None
    symlink_chain: tuple[str, ...] = ()
    is_broken_symlink: bool = False
    is_loop: bool = False
    size: int | None = None
    sha256: str | None = None
    contained_in: dict[str, bool] = field(default_factory=dict)
    escapes_all_roots: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        """Deterministic dict (fixed keys; JSON-serialisable)."""
        return {
            "raw_path": self.raw_path,
            "canonical_path": self.canonical_path,
            "resolved_path": self.resolved_path,
            "exists": self.exists,
            "is_file": self.is_file,
            "is_dir": self.is_dir,
            "is_symlink": self.is_symlink,
            "symlink_target": self.symlink_target,
            "symlink_chain": list(self.symlink_chain),
            "is_broken_symlink": self.is_broken_symlink,
            "is_loop": self.is_loop,
            "size": self.size,
            "sha256": self.sha256,
            "contained_in": dict(self.contained_in),
            "escapes_all_roots": self.escapes_all_roots,
            "error": self.error,
        }

    @classmethod
    def from_canonical(
        cls,
        canon: CanonicalPath,
        *,
        roots: dict[str, str] | None = None,
        compute_hash: bool = True,
    ) -> "PathEntry":
        """Build an entry from a :class:`CanonicalPath` record."""
        roots = roots or {}
        contained: dict[str, bool] = {}
        for name, root in roots.items():
            if canon.resolved_path is None:
                contained[name] = False
            else:
                contained[name] = is_within_root(canon.resolved_path, root)
        escape = detect_escape(
            canon.resolved_path, tuple(roots.values())
        ) if roots else detect_escape(canon.resolved_path, ())
        size: int | None = None
        sha: str | None = None
        error: str | None = canon.error
        if canon.exists and canon.is_file and canon.resolved_path is not None:
            try:
                size = os.path.getsize(canon.resolved_path)
            except OSError as exc:
                error = "UNREADABLE: %s" % exc.__class__.__name__
            if compute_hash and error is None:
                try:
                    sha = hash_file(canon.resolved_path)
                except OSError as exc:
                    error = "UNREADABLE: %s" % exc.__class__.__name__
                    sha = None
        elif canon.exists and canon.is_dir and canon.resolved_path is not None:
            size = None
        return cls(
            raw_path=canon.raw_path,
            canonical_path=canon.canonical_path,
            resolved_path=canon.resolved_path,
            exists=canon.exists,
            is_file=canon.is_file,
            is_dir=canon.is_dir,
            is_symlink=canon.is_symlink,
            symlink_target=canon.symlink_target,
            symlink_chain=canon.symlink_chain,
            is_broken_symlink=canon.is_broken_symlink,
            is_loop=canon.is_loop,
            size=size,
            sha256=sha,
            contained_in=contained,
            escapes_all_roots=escape.escaped,
            error=error,
        )


def snapshot_entry(raw, *, cwd, home, repo_root=None, compute_hash=True) -> PathEntry:
    """Snapshot a single path (absolute or relative to *cwd*).

    Missing paths and broken symlinks are valid entries
    (``exists=False``); only malformed *input* (empty path, ``~``
    without ``home``, relative path without ``cwd``) raises. The
    workspace directories must be absolute (fail-closed otherwise).
    """
    cwd_canon = canonicalize(cwd)
    home_canon = canonicalize(home)
    repo_canon = canonicalize(repo_root) if repo_root is not None else None
    canon = canonicalize(raw, cwd=cwd_canon.resolved_path, home=home_canon.resolved_path)
    roots: dict[str, str] = {"home": home_canon.resolved_path or home_canon.canonical_path}
    if repo_canon is not None:
        roots["repo"] = repo_canon.resolved_path or repo_canon.canonical_path
    return PathEntry.from_canonical(canon, roots=roots, compute_hash=compute_hash)


def snapshot_tree(
    root,
    *,
    cwd,
    home,
    repo_root=None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    follow_dir_symlinks: bool = False,
    compute_hash: bool = True,
) -> list[PathEntry]:
    """Deterministically snapshot a directory tree rooted at *root*.

    Entries are returned sorted by canonical path. Traversal order is
    fixed (``os.scandir`` results sorted by name), directory symlinks
    are recorded but *not* descended into by default, and visited
    directory inodes are remembered so a symlinked directory cycle
    cannot loop forever even with ``follow_dir_symlinks=True``. A
    directory deeper than ``max_depth`` is recorded with
    ``error="MAX_DEPTH"`` and not descended into.

    The tree root itself is the first entry (a directory entry).
    Missing ``root`` yields a single missing-path entry, not an error.
    """
    if max_depth < 0:
        raise SnapshotError("max_depth must be >= 0")
    roots: dict[str, str] = {"home": os.path.normpath(str(home))}
    if repo_root is not None:
        roots["repo"] = os.path.normpath(str(repo_root))
    entries: list[PathEntry] = []
    visited_inodes: set[tuple[int, int]] = set()

    def _walk(dir_path: str, depth: int) -> None:
        canon = canonicalize(dir_path, cwd=cwd, home=home)
        entry = PathEntry.from_canonical(canon, roots=roots, compute_hash=False)
        if depth > max_depth:
            entries.append(replace(entry, error="MAX_DEPTH"))
            return
        entries.append(entry)
        if not canon.exists or not canon.is_dir:
            return
        if canon.is_symlink and not follow_dir_symlinks:
            return
        resolved = canon.resolved_path
        if resolved is None:
            return
        try:
            st = os.stat(resolved)
        except OSError:
            return
        inode = (st.st_dev, st.st_ino)
        if inode in visited_inodes:
            return  # directory cycle via symlinked dirs: stop, no loop
        visited_inodes.add(inode)
        try:
            children = sorted(os.scandir(resolved), key=lambda e: e.name)
        except OSError:
            return
        for child in children:
            child_path = os.path.join(resolved, child.name)
            try:
                is_dir = child.is_dir(follow_symlinks=False)
                is_link = child.is_symlink()
            except OSError:
                is_dir = is_link = False
            if is_dir:
                _walk(child_path, depth + 1)
            elif is_link and follow_dir_symlinks:
                # Symlink to a directory: _walk records the entry
                # itself, so do not append a second entry here.
                try:
                    if os.path.isdir(child_path):
                        _walk(child_path, depth + 1)
                        continue
                except OSError:
                    pass
                child_canon = canonicalize(child_path, cwd=cwd, home=home)
                entries.append(PathEntry.from_canonical(
                    child_canon, roots=roots, compute_hash=compute_hash
                ))
            else:
                child_canon = canonicalize(child_path, cwd=cwd, home=home)
                entries.append(PathEntry.from_canonical(
                    child_canon, roots=roots, compute_hash=compute_hash
                ))

    _walk(str(root), 0)
    entries.sort(key=lambda e: e.canonical_path)
    return entries


@dataclass(frozen=True)
class FilesystemSnapshot:
    """A deterministic snapshot of a workspace (cwd/home/repo + entries).

    ``cwd`` / ``home`` / ``repo_root`` are the *canonical* absolute
    paths (receipt ``workspace`` fields); ``repo_root`` is ``None``
    when the CWD is not inside a git repository (S25). ``entries``
    are sorted by canonical path. The snapshot carries no timestamps.
    """

    cwd: str
    home: str
    repo_root: str | None
    entries: tuple[PathEntry, ...] = ()

    def to_dict(self) -> dict:
        """Deterministic dict (fixed keys; JSON-serialisable)."""
        return {
            "cwd": self.cwd,
            "home": self.home,
            "repo_root": self.repo_root,
            "entries": [e.to_dict() for e in self.entries],
        }

    def to_canonical_json(self) -> str:
        """Canonical JSON: sorted keys, fixed separators, UTF-8 text.

        No wall-clock or volatile field is ever present, so this
        string is byte-identical across runs for the same input.
        """
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        )

    def snapshot_hash(self) -> str:
        """SHA-256 (lowercase hex) of :meth:`to_canonical_json`."""
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()


def _validate_workspace_dir(label: str, value, *, allow_none: bool = False) -> str | None:
    """Validate that *value* names an existing directory; return its canonical path."""
    if value is None:
        if allow_none:
            return None
        raise SnapshotError("%s is required" % label)
    if isinstance(value, bytes):
        raise SnapshotError("%s must be str, not bytes" % label)
    text = os.fspath(value)
    if not isinstance(text, str) or text == "" or "\x00" in text:
        raise SnapshotError("%s must be a non-empty path string" % label)
    canon = canonicalize(text)
    if canon.resolved_path is None or not canon.exists or not canon.is_dir:
        raise SnapshotError(
            "%s does not exist or is not a directory: %s" % (label, text)
        )
    return canon.resolved_path


def build_snapshot(
    *,
    cwd,
    home,
    repo_root=None,
    paths=(),
    include_tree: bool = False,
    tree_root=None,
    compute_hash: bool = True,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> FilesystemSnapshot:
    """Build a deterministic :class:`FilesystemSnapshot`.

    * ``cwd`` / ``home`` must be existing directories (fail-closed
      ``SnapshotError`` otherwise); ``repo_root`` may be ``None``
      (non-git workspace, S25) or an existing directory.
    * ``paths`` are extra paths to snapshot (absolute, or relative to
      ``cwd``; missing paths are recorded, not rejected). Duplicate
      canonical paths are de-duplicated (first occurrence wins).
    * With ``include_tree=True``, ``tree_root`` (default: ``cwd``)
      is walked with :func:`snapshot_tree` and merged in, still
      sorted and de-duplicated by canonical path.

    The result contains no timestamps and is byte-stable across runs.
    """
    cwd_canon = _validate_workspace_dir("cwd", cwd)
    home_canon = _validate_workspace_dir("home", home)
    repo_canon = _validate_workspace_dir("repo_root", repo_root, allow_none=True)
    assert cwd_canon is not None and home_canon is not None  # validated above

    roots: dict[str, str] = {"home": home_canon}
    if repo_canon is not None:
        roots["repo"] = repo_canon

    by_canonical: dict[str, PathEntry] = {}

    def _add(entry: PathEntry) -> None:
        by_canonical.setdefault(entry.canonical_path, entry)

    for raw in paths:
        canon = canonicalize(raw, cwd=cwd_canon, home=home_canon)
        _add(PathEntry.from_canonical(canon, roots=roots, compute_hash=compute_hash))

    if include_tree:
        walk_root = tree_root if tree_root is not None else cwd_canon
        for entry in snapshot_tree(
            walk_root, cwd=cwd_canon, home=home_canon, repo_root=repo_canon,
            max_depth=max_depth, compute_hash=compute_hash,
        ):
            _add(entry)

    entries = tuple(sorted(by_canonical.values(), key=lambda e: e.canonical_path))
    return FilesystemSnapshot(
        cwd=cwd_canon, home=home_canon, repo_root=repo_canon, entries=entries,
    )
