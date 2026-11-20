"""Shared helpers for the P028 harness profiles (T003).

This module holds the pieces every profile needs, so the three
profile modules stay small and the resolver can share the same
candidate type:

* :class:`SourceCandidate` — one discovered instruction source.
  It carries the receipt-schema source fields that discovery can
  fill in (T004 owns ``git``/``trust``; T005 owns import ``edges``),
  plus ``also_discovered_by`` for de-duplication traceability.
* :class:`NotApplicable` — a path the profile *considered* but did
  not put in the effective chain, with a machine-readable reason.
  This is the T003 answer to SPEC-04 (profile_contract.json):
  no new enum value is invented; a non-matching file is simply
  absent from ``sources`` and listed here instead, so T007 can
  assert on it (e.g. S16 Copilot ``applyTo`` no-match).
* :class:`ResolveContext` — the resolved inputs a profile needs:
  snapshot (cwd/home/repo_root + entry index), policy, the files
  the harness is working with (on-demand triggers), and optional
  overrides (managed path, Copilot home, custom/additional dirs).
* Frontmatter parsing (a strict YAML *subset*: ``key: scalar``,
  inline ``[a, b]`` lists and block ``- item`` lists). Anything
  else is unparseable and the frontmatter is treated as absent —
  which is exactly the contract rule for ``.claude/rules`` paths
  frontmatter ("unparseable YAML frontmatter is ignored and the
  rule loads as if it had no paths").
* Glob matching for ``applyTo`` / ``paths`` (``fnmatch``; ``*``
  crosses ``/``, so ``**/*.py`` works; a pattern without a slash
  matches the basename).

Determinism: every directory walk is sorted by name, every
candidate list is emitted in a fixed order, and no wall-clock,
network or shell use occurs anywhere in this module.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field

from instructionroot.paths import _normalize_for_comparison, canonicalize
from instructionroot.snapshot import FilesystemSnapshot, PathEntry, hash_file

__all__ = [
    "NotApplicable",
    "Precedence",
    "ResolveContext",
    "SourceCandidate",
    "ancestor_chain",
    "chain_dirs",
    "glob_matches",
    "list_dir_files",
    "make_candidate",
    "parse_applyto",
    "parse_frontmatter",
    "parse_paths_frontmatter",
    "relative_posix",
]


# ---------------------------------------------------------------------------
# Candidate / precedence / not-applicable records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Precedence:
    """Ordering claim for one source (receipt ``precedence`` object)."""

    kind: str  # ORDERED | COMBINE_UNORDERED | UNSPECIFIED (+ BEFORE/AFTER unused here)
    detail: str = ""

    def to_dict(self) -> dict:
        out: dict[str, str] = {"kind": self.kind}
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class SourceCandidate:
    """One discovered instruction source (receipt source minus T004/T005 fields).

    ``git`` and ``trust`` are deliberately absent: T004 fills them in.
    ``sha256`` comes from the snapshot entry when present, else is
    computed live from the resolved path (``None`` only when the file
    cannot be read). ``depth`` is ``None`` for directly discovered
    sources; import candidates (Claude ``@``) carry their hop depth.
    ``also_discovered_by`` lists the discovery rules that found the
    same canonical file after the first one (S10 de-duplication).
    """

    raw_path: str
    canonical_path: str
    resolved_path: str | None
    scope: str  # managed | user | project | nested
    phase: str  # startup | on_demand
    discovery_rule: str
    precedence: Precedence
    sha256: str | None = None
    exists: bool = True
    is_symlink: bool = False
    symlink_target: str | None = None
    also_discovered_by: tuple[str, ...] = ()
    depth: int | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "raw_path": self.raw_path,
            "canonical_path": self.canonical_path,
            "resolved_path": self.resolved_path,
            "scope": self.scope,
            "phase": self.phase,
            "discovery_rule": self.discovery_rule,
            "precedence": self.precedence.to_dict(),
            "sha256": self.sha256,
            "exists": self.exists,
            "is_symlink": self.is_symlink,
            "symlink_target": self.symlink_target,
            "also_discovered_by": list(self.also_discovered_by),
            "depth": self.depth,
            "error": self.error,
        }


@dataclass(frozen=True)
class NotApplicable:
    """A path the profile considered but excluded from the chain.

    ``reason`` values used by T003 (all fail-closed, no invented
    enum): ``APPLYTO_NO_MATCH``, ``APPLYTO_ABSENT_UNVERIFIED``,
    ``APPLYTO_NO_WORKING_FILE``, ``PATH_SCOPED_NO_MATCH``,
    ``PATH_SCOPED_NO_TRIGGER``, ``ON_DEMAND_DISABLED_BY_POLICY``,
    ``ADDITIONAL_DIRS_DISABLED_BY_POLICY``,
    ``OVERSIZE_CLAUDE_MD``, ``SYMLINK_EXTERNAL_NOT_OBSERVED``,
    ``NOT_A_FILE``.
    """

    raw_path: str
    canonical_path: str | None
    discovery_rule: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "raw_path": self.raw_path,
            "canonical_path": self.canonical_path,
            "discovery_rule": self.discovery_rule,
            "reason": self.reason,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Resolve context
# ---------------------------------------------------------------------------

@dataclass
class ResolveContext:
    """Inputs a profile discovery function needs.

    ``snapshot`` supplies cwd/home/repo_root (canonical) and the
    entry index (canonical path -> :class:`PathEntry`). ``cwd`` may
    differ from ``snapshot.cwd`` when the caller overrides it.
    ``working_files`` are the files the harness is working with:
    they trigger on-demand discovery (Claude nested / path-scoped
    rules, Copilot ``applyTo`` and nested-in-path locations) and
    are canonical absolute paths. ``additional_dirs`` (Claude
    ``--add-dir``) and ``custom_dirs`` (Copilot
    ``COPILOT_CUSTOM_INSTRUCTIONS_DIRS``) are canonical absolute
    directory paths, or ``None`` to fall back to the environment
    variable of the same name. ``managed_path`` overrides the
    Linux managed CLAUDE.md location (tests only). ``ancestor_stop``
    bounds Claude's upward walk (see :func:`ancestor_chain`).
    """

    snapshot: FilesystemSnapshot
    cwd: str
    home: str
    repo_root: str | None
    policy: dict
    working_files: tuple[str, ...] = ()
    additional_dirs: tuple[str, ...] | None = None
    custom_dirs: tuple[str, ...] | None = None
    copilot_home: str | None = None
    managed_path: str | None = None
    ancestor_stop: str | None = None
    not_applicable: list[NotApplicable] = field(default_factory=list)

    @property
    def entries_by_canonical(self) -> dict[str, PathEntry]:
        return {e.canonical_path: e for e in self.snapshot.entries}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def ancestor_chain(cwd: str, stop: str | None = None,
                   *, os_name: str | None = None) -> list[str]:
    """Directories from a top ancestor down to *cwd* (inclusive).

    ``/a/b/c`` -> ``["/", "/a", "/a/b", "/a/b/c"]``. Used for Claude
    upward discovery, which walks every ancestor, not just the repo.
    ``stop`` bounds the walk: the topmost ancestor to include
    (inclusive). It models the root of the *observed* filesystem:
    in production it is ``None`` (the real filesystem root); in
    synthetic fixtures/tests it is the fixture root, so the walk
    cannot escape the fixture and pick up real files above it
    (e.g. a real ``~/AGENTS.md`` sitting above the case dir).

    FIX-R3 B: inputs are normalised to ``C:/`` form first, so a
    Windows spelling (``C:\\repo\\shared``) yields the same chain
    the Oracle builds (``["/", "/C:", "/C:/repo",
    "/C:/repo/shared"]``) instead of collapsing to ``["/"]`` plus
    one backslash component. POSIX inputs are unchanged.

    FIX-R5: on a Windows host (``os_name == "nt"``, defaulting to
    ``os.name``) a drive-letter cwd yields a *drive-form* chain
    (``["C:/", "C:/repo", "C:/repo/shared"]``), NOT the
    ``"/-prefixed"`` shape. The old shape is unconsumable on
    Windows: ``canonicalize`` feeds ``"/C:/..."`` to Windows
    ``ntpath.normpath``, which mangles it into a UNC spelling
    (``"\\\\C:\\..."``) that never exists — so every claude-code
    ancestor probe missed and the CLI returned 0 sources (V4 E08-5
    fail-open), while the runner's stop-collapsed ``[cwd]`` walk
    still found the file. The drive-form chain is consumable (the
    drive branch) and the stop filter now matches, so the walk is
    ``[stop..cwd]`` instead of the degenerate ``[cwd]`` FIX-R3
    recorded ("parity, not a bug to fix alone" — the Oracle mirrors
    this shape under ``cfg!(windows)``, so both sides change
    together). On any other host the old shape is kept byte-identical
    (the FIX-R3 Linux simulation behaviour for Windows spellings).
    """
    cwd = _normalize_for_comparison(cwd)
    host = os.name if os_name is None else os_name
    # Windows drive-letter cwd on a Windows host: drive-form chain.
    if host == "nt" and len(cwd) >= 3 and cwd[1] == ":" and cwd[2] == "/" \
            and cwd[0].isalpha():
        drive = cwd[:2]  # e.g. "C:"
        rest = [p for p in cwd[3:].split("/") if p not in ("", ".")]
        chain = [drive + "/"]
        cur = drive
        for part in rest:
            cur += "/" + part
            chain.append(cur)
        if stop is not None:
            stop = _normalize_for_comparison(stop)
            if stop == drive + "/":
                return chain
            chain = [d for d in chain if d == stop or d.startswith(stop + "/")]
            if not chain or chain[0] != stop:
                # stop is not an ancestor of cwd: the walk is just the CWD.
                return [cwd]
        return chain
    parts = [p for p in cwd.split("/") if p not in ("", ".")]
    chain = ["/"]
    cur = ""
    for part in parts:
        cur += "/" + part
        chain.append(cur)
    if stop is not None:
        stop = _normalize_for_comparison(stop)
        if stop == "/":
            return chain
        chain = [d for d in chain if d == stop or d.startswith(stop + "/")]
        if not chain or chain[0] != stop:
            # stop is not an ancestor of cwd: the walk is just the CWD.
            return [cwd]
    return chain


def chain_dirs(repo_root: str | None, cwd: str) -> list[str]:
    """Directories from *repo_root* down to *cwd* (inclusive).

    When there is no repo root (non-git workspace, S25) the chain is
    just ``[cwd]`` — the contract defines no repo root for that case
    (codex repo-root determination is UNVERIFIED), so no directory
    above the CWD is claimed. When *cwd* is not under *repo_root*
    (should not happen for a well-formed snapshot) the chain is
    also just ``[cwd]``.

    FIX-R3 B: inputs are normalised to ``C:/`` form first, so a
    Windows spelling (``C:\\repo`` / ``C:\\repo\\shared``) yields
    ``["C:/repo", "C:/repo/shared"]`` instead of ``["C:\\repo\\shared"]``
    (the ``"/"``-separator prefix test never matched a backslash
    ``normpath`` result). POSIX inputs are unchanged.
    """
    cwd = _normalize_for_comparison(cwd)
    if repo_root is None:
        return [cwd]
    root = _normalize_for_comparison(repo_root)
    if cwd == root:
        return [root]
    if not cwd.startswith(root + "/"):
        return [cwd]
    rel = cwd[len(root) + 1:]
    out = [root]
    cur = root
    for part in rel.split("/"):
        cur += "/" + part
        out.append(cur)
    return out


def relative_posix(path: str, base: str) -> str | None:
    """``path`` relative to ``base`` with ``/`` separators, or None.

    FIX-R3 B: inputs are normalised to ``C:/`` form first, so a
    Windows spelling (``C:\\repo\\AGENTS.md`` vs ``C:\\repo``)
    yields ``"AGENTS.md"`` instead of ``None``. A drive root
    (``C:/``) as *base* behaves like ``/``. POSIX inputs are
    unchanged.
    """
    path = _normalize_for_comparison(path)
    base = _normalize_for_comparison(base)
    if path == base:
        return ""
    base_prefix = base.rstrip("/") or "/"
    if base_prefix == "/":
        return path.lstrip("/")
    if path.startswith(base_prefix + "/"):
        return path[len(base_prefix) + 1:]
    return None


def list_dir_files(
    dir_canonical: str,
    *,
    recursive: bool,
    suffixes: tuple[str, ...] | None = None,
    filename_glob: str | None = None,
) -> list[str]:
    """Deterministically list files under *dir_canonical* (lexical paths).

    Returns canonical (lexical, symlink-unresolved) absolute paths,
    sorted. Directory symlinks are *not* descended into (a symlinked
    rules directory is a separate trust question, not a traversal).
    Files reached through a symlinked *file* are listed (their
    canonical path keeps the symlink spelling; resolution happens
    in :func:`make_candidate`). A missing or unreadable directory
    yields an empty list — discovery of an absent directory is not
    an error. ``suffixes`` filters by filename suffix (e.g.
    ``(".md",)``); ``filename_glob`` filters by ``fnmatch`` on the
    filename (e.g. ``"*.instructions.md"``).
    """
    out: list[str] = []
    resolved = dir_canonical
    try:
        resolved_real = os.path.realpath(dir_canonical)
    except OSError:
        return out
    # Walk the resolved directory but report lexical paths.
    stack: list[tuple[str, str]] = [(resolved_real, os.path.normpath(dir_canonical))]
    while stack:
        real_dir, lex_dir = stack.pop()
        try:
            children = sorted(os.scandir(real_dir), key=lambda e: e.name)
        except OSError:
            continue
        subdirs: list[tuple[str, str]] = []
        for child in children:
            lex_child = lex_dir + "/" + child.name
            try:
                is_dir = child.is_dir(follow_symlinks=False)
                is_link = child.is_symlink()
            except OSError:
                continue
            if is_dir and not is_link:
                if recursive:
                    subdirs.append((os.path.join(real_dir, child.name), lex_child))
            elif is_dir and is_link:
                continue  # never descend into a symlinked directory
            else:
                name = child.name
                if suffixes is not None and not name.endswith(suffixes):
                    continue
                if filename_glob is not None and not fnmatch.fnmatchcase(
                    name, filename_glob
                ):
                    continue
                out.append(os.path.normpath(lex_child))
        # Depth-first in sorted order: push reversed so pop yields sorted.
        stack.extend(reversed(subdirs))
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Candidate construction
# ---------------------------------------------------------------------------

def make_candidate(
    ctx: ResolveContext,
    raw_path: str,
    *,
    scope: str,
    phase: str,
    discovery_rule: str,
    precedence: Precedence,
    depth: int | None = None,
) -> SourceCandidate | None:
    """Build a candidate for *raw_path*, or None when it is not a file.

    A path that does not exist, or exists but is not a regular file,
    produces no source (discovery only lists files present on disk;
    a *missing* reference is a T005 edge concern, not a discovered
    source — see TASK_RESULT.md). The sha comes from the snapshot
    entry when present, else is computed live from the resolved
    path. A file that cannot be read yields ``sha256=None`` with
    ``error="UNREADABLE: ..."`` rather than a fabricated hash.
    """
    try:
        canon = canonicalize(raw_path, cwd=ctx.cwd, home=ctx.home)
    except (ValueError, TypeError):
        ctx.not_applicable.append(NotApplicable(
            raw_path=raw_path, canonical_path=None,
            discovery_rule=discovery_rule, reason="NOT_A_FILE",
            detail="path could not be canonicalised",
        ))
        return None
    if not canon.exists or not canon.is_file:
        return None
    entry = ctx.entries_by_canonical.get(canon.canonical_path)
    sha: str | None = None
    error: str | None = None
    if entry is not None and entry.sha256 is not None:
        sha = entry.sha256
    elif canon.resolved_path is not None:
        try:
            sha = hash_file(canon.resolved_path)
        except OSError as exc:
            error = "UNREADABLE: %s" % exc.__class__.__name__
    if canon.error is not None:
        error = canon.error
    return SourceCandidate(
        raw_path=raw_path,
        canonical_path=canon.canonical_path,
        resolved_path=canon.resolved_path,
        scope=scope,
        phase=phase,
        discovery_rule=discovery_rule,
        precedence=precedence,
        sha256=sha,
        exists=True,
        is_symlink=canon.is_symlink,
        symlink_target=canon.symlink_target,
        depth=depth,
        error=error,
    )


def file_size(ctx: ResolveContext, canonical_path: str) -> int | None:
    """Byte size of the file at *canonical_path* (snapshot or live)."""
    entry = ctx.entries_by_canonical.get(canonical_path)
    if entry is not None and entry.size is not None:
        return entry.size
    try:
        canon = canonicalize(canonical_path, cwd=ctx.cwd, home=ctx.home)
        if canon.resolved_path is None:
            return None
        return os.path.getsize(canon.resolved_path)
    except (ValueError, TypeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Frontmatter (strict YAML subset)
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict | None:
    """Parse a leading ``---`` YAML frontmatter block (subset).

    Returns the parsed mapping, or ``None`` when there is no
    frontmatter block *or* the block is unparseable. Callers treat
    ``None`` as "no frontmatter", which is exactly the contract
    rule for unparseable ``paths`` frontmatter. Supported: ``key:
    scalar`` lines (scalars optionally single/double quoted),
    ``key:`` followed by ``- item`` lines, and inline ``[a, b]``
    lists. Comments (``#``) and blank lines are skipped. Any other
    construct (nested maps, multi-line scalars, ``:`` inside an
    unquoted scalar, duplicate keys) makes the whole block
    unparseable.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None  # unterminated block: unparseable
    data: dict[str, object] = {}
    current_key: str | None = None
    for raw in lines[1:end]:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- ") or line == "-":
            if current_key is None:
                return None
            item = line[1:].strip()
            item = _unquote(item)
            if item is None:
                return None
            existing = data.get(current_key)
            if not isinstance(existing, list):
                return None
            existing.append(item)
            continue
        if ":" not in line:
            return None
        key, _, value = line.partition(":")
        key = key.strip()
        if not key or key in data or " " in key:
            return None
        current_key = None
        value = value.strip()
        if value == "":
            data[key] = []
            current_key = key
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items: list[str] = []
            if inner:
                for part in inner.split(","):
                    item = _unquote(part.strip())
                    if item is None:
                        return None
                    items.append(item)
            data[key] = items
            continue
        scalar = _unquote(value)
        if scalar is None:
            return None
        data[key] = scalar
    return data


def _unquote(value: str) -> str | None:
    """Strip one layer of matching quotes, or None if unbalanced."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    if value.startswith(("'", '"')) or value.endswith(("'", '"')):
        return None
    if ":" in value:
        # An unquoted scalar containing ':' is ambiguous YAML; reject.
        return None
    return value


def _patterns_from(value: object) -> list[str] | None:
    """Normalise a frontmatter value to a glob-pattern list, or None."""
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return None
            out.extend(p.strip() for p in item.split(",") if p.strip())
        return out
    return None


def parse_paths_frontmatter(text: str) -> list[str] | None:
    """Return the ``paths`` frontmatter glob list, or None if absent.

    ``None`` covers both "no frontmatter" and "unparseable" — per
    the contract both load the rule as if it had no paths.
    """
    data = parse_frontmatter(text)
    if data is None or "paths" not in data:
        return None
    return _patterns_from(data["paths"])


def parse_applyto(text: str) -> list[str] | None:
    """Return the ``applyTo`` frontmatter glob list, or None if absent.

    ``None`` means the behaviour is UNVERIFIED for Copilot CLI
    (contract): callers must not guess — they exclude the file and
    record ``APPLYTO_ABSENT_UNVERIFIED``.
    """
    data = parse_frontmatter(text)
    if data is None or "applyTo" not in data:
        return None
    return _patterns_from(data["applyTo"])


def read_text(path: str, *, limit_chars: int = 1_000_000) -> str | None:
    """Read a file as UTF-8 text (for frontmatter/import scanning).

    Returns ``None`` when the file cannot be read or is not valid
    UTF-8 (callers treat that as "no frontmatter / no imports",
    never as an error that invents content). Only the first
    ``limit_chars`` characters are read: frontmatter and ``@``
    references live at the top of instruction files.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as fh:
            return fh.read(limit_chars + 1)[:limit_chars]
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Glob matching (applyTo / paths)
# ---------------------------------------------------------------------------

def glob_matches(pattern: str, rel_posix_path: str) -> bool:
    """Match one glob *pattern* against a ``/``-separated rel path.

    ``fnmatch`` ``*`` already crosses ``/``, so ``**/*.py`` and
    ``src/**`` behave as expected. A pattern with no ``/`` matches
    the basename (``*.py`` matches ``src/app.py``). ``**/`` also
    matches zero directories (``src/**/*.py`` matches
    ``src/app.py`` as well as ``src/a/b.py``) — plain ``fnmatch``
    would miss the zero-directory case, so the ``**/``-stripped
    variant is tried too. Matching is case-sensitive (Linux
    semantics; Windows case behaviour is a T011 case, not guessed
    here).
    """
    pattern = pattern.strip()
    if not pattern:
        return False
    if "/" not in pattern:
        return fnmatch.fnmatchcase(rel_posix_path.rsplit("/", 1)[-1], pattern)
    variants = {pattern}
    if "**/" in pattern:
        variants.add(pattern.replace("**/", ""))
    return any(
        fnmatch.fnmatchcase(rel_posix_path, variant) for variant in variants
    )


def any_glob_matches(patterns: list[str], rel_posix_path: str) -> bool:
    return any(glob_matches(p, rel_posix_path) for p in patterns)
