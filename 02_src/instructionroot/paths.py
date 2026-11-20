"""Canonical path handling for P028 InstructionRoot Resolve (T002).

Implements PROJECT_BOOK.md §13.1 algorithm A ("Canonical Path") against
the frozen contract in ``00_contract/receipt_schema.json``:

* ``canonical_path`` — the *lexical* canonical path: absolute, ``..`` / ``.``
  normalised, duplicate separators collapsed, trailing separator removed
  (except the filesystem root). Symlinks are **not** resolved here, so a
  path that goes through a symlink keeps the path as written (lexically
  normalised). This is the ``canonical_path`` field of a receipt source.
* ``resolved_path`` — the canonical path *after* symlink/junction
  resolution. It equals ``canonical_path`` when no path component is a
  symlink. This is the ``resolved_path`` field of a receipt source.
* Both are always recorded together ("lexical vs resolved dual record");
  a source is never identified by one alone.

Design decisions (all fail-closed, stdlib only):

* No wall-clock, no network, no shell. Only ``pathlib`` / ``os`` /
  ``ntpath`` (pure-string Windows normalisation) are used.
* The real user home is never read implicitly. ``~`` expands only
  against an *explicitly supplied* ``home`` argument; without one it is
  an error. ``~user`` expansion is unsupported and is an error.
* Symlink resolution is done component-by-component with a hard hop
  bound (``MAX_SYMLINK_HOPS = 40``, matching the usual kernel
  ``ELOOP`` limit). A loop therefore returns
  ``CanonicalPath(is_loop=True, valid=False, error="SYMLINK_LOOP")``
  instead of hanging or raising. A broken symlink is *not* an error:
  it resolves lexically to its (missing) target and is reported with
  ``is_broken_symlink=True, exists=False`` — a missing file must never
  be fabricated as existing.
* Unicode: the canonical representation is the exact UTF-8 string of
  the normalised absolute path. No NFC/NFD normalisation is applied:
  two spellings that differ only in Unicode normalisation form are
  different byte strings on disk and are *not* conflated. (macOS
  HFS+/APFS NFD behaviour is therefore preserved, not hidden.)
* Windows: a drive-letter path (``C:/...``) is resolved against the
  real filesystem **only when the host is Windows** (``os.name ==
  "nt"``): the drive root (``C:/``) is the root, components are
  resolved one by one, ``..`` stops at the drive root, and a component
  is a link exactly when its reparse tag (``os.lstat(p).st_reparse_tag``)
  is a junction (``0xA0000003``) or a symlink (``0xA000000C``) — plain
  ``os.path.islink`` returns False for junctions on Windows and must
  not be used there. A relative reference joined onto a Windows cwd
  is re-normalised the same way first (FIX-R3 A): the join result on
  Windows is backslash-spelled and would otherwise miss the
  drive-letter branch and fall back to ``/C:\\...``. Readlink targets are normalised (backslashes ->
  ``/``, a ``\\?\\`` prefix stripped) before being split; an absolute
  drive-letter target resets the root to that drive. On any other host
  (this Linux host included) a drive-letter spelling keeps its pinned
  Linux behaviour — lexical ``C:/...`` resolves to ``/C:/...`` — so
  the S0 ``fs/windows`` probes and the ``copilot-absolute`` fixture
  are unchanged. The Windows branch is testable on Linux through the
  injectable ``fs`` / ``os_name`` arguments of :func:`canonicalize`
  (see below); UNC paths (``//server/share/...``) stay pure-string
  normalisation in this round and are not resolved against a
  filesystem.
* Testability (FIX-R2): :func:`canonicalize` and the internal resolver
  accept ``fs`` (an object with ``islink`` / ``lexists`` / ``exists`` /
  ``isfile`` / ``isdir`` / ``readlink`` / ``reparse_tag`` methods,
  defaulting to the real ``os`` functions) and ``os_name`` (defaulting
  to ``os.name``). Passing ``os_name="nt"`` with a fake ``fs`` runs
  the Windows drive branch on Linux, so junction following, drive
  switching and loop fail-closed are covered by unit tests without a
  Windows machine. Real Windows verification still belongs to the
  Windows runner (V2 pack on Sam's PC); the fake-FS tests are a
  simulation, never a claim of real-Windows proof.
* POSIX backslash is a valid filename character, not a separator:
  ``a\\b`` on Linux stays one component. Only strings that look
  Windows-style (drive letter or UNC prefix) get backslash treatment.
"""

from __future__ import annotations

import ntpath
import os
import re
from dataclasses import dataclass

__all__ = [
    "MAX_SYMLINK_HOPS",
    "CanonicalPath",
    "EscapeInfo",
    "canonicalize",
    "detect_escape",
    "is_windows_style_path",
    "is_within_root",
    "lexical_canonical",
    "normalize_windows_path",
    "redact_home",
]

#: Maximum symlink hops followed while resolving one path. Matches the
#: usual kernel ELOOP limit; exceeding it is reported as a loop, never
#: followed further.
MAX_SYMLINK_HOPS = 40

#: Hard bound on total path components processed during one resolution,
#: guarding against pathological (e.g. adversarially long) inputs.
_MAX_COMPONENTS = 10_000

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_RE = re.compile(r"^\\\\[^\\]+\\[^\\]+")

#: Lexical drive-letter absolute path in canonical (``C:/...``) form.
_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:/")

#: Reparse tags that make a Windows path component a link (FIX-R2 D2).
#: 0xA0000003 = IO_REPARSE_TAG_MOUNT_POINT (junction),
#: 0xA000000C = IO_REPARSE_TAG_SYMLINK. Any other tag (including 0x0,
#: i.e. "not a reparse point") is not a link. This is the unified
#: link rule shared with the Oracle: ``os.path.islink`` returns False
#: for junctions on Windows, so it must never be the Windows test.
REPARSE_TAG_JUNCTION = 0xA0000003
REPARSE_TAG_SYMLINK = 0xA000000C
WINDOWS_LINK_TAGS = frozenset({REPARSE_TAG_JUNCTION, REPARSE_TAG_SYMLINK})


class _RealFS:
    """Filesystem probe backed by the real ``os`` functions (default).

    The probe protocol is the set of methods used by the resolver:
    ``islink`` / ``lexists`` / ``exists`` / ``isfile`` / ``isdir`` /
    ``readlink`` / ``reparse_tag``. ``reparse_tag`` returns the
    ``st_reparse_tag`` from ``os.lstat`` (``None`` when the platform
    does not report one) and raises ``OSError`` when the path cannot
    be lstatted, exactly like a failed ``islink`` probe would.
    """

    @staticmethod
    def islink(path: str) -> bool:
        return os.path.islink(path)

    @staticmethod
    def lexists(path: str) -> bool:
        return os.path.lexists(path)

    @staticmethod
    def exists(path: str) -> bool:
        return os.path.exists(path)

    @staticmethod
    def isfile(path: str) -> bool:
        return os.path.isfile(path)

    @staticmethod
    def isdir(path: str) -> bool:
        return os.path.isdir(path)

    @staticmethod
    def readlink(path: str) -> str:
        return os.readlink(path)

    @staticmethod
    def reparse_tag(path: str):
        try:
            return getattr(os.lstat(path), "st_reparse_tag", None)
        except OSError:
            raise


#: Default probe (real filesystem). Tests pass a fake object instead.
_REAL_FS = _RealFS()


def _normalize_windows_readlink_target(target: str) -> str:
    """Normalise a Windows readlink target for resolution (FIX-R2 D2).

    Backslashes become ``/`` and a ``\\\\?\\`` prefix is stripped
    (CPython's ``os.readlink`` returns junction targets as
    ``\\\\?\\C:\\...`` while the Oracle's ``fs::read_link`` returns the
    same target as ``C:\\...`` — the prefix is an OS artefact, not
    part of the target). A ``\\\\?\\UNC\\server\\share`` target maps
    back to ``//server/share``. The result is *not* lexically
    normalised further: ``..`` components are left in place so the
    resolver can pop them against the already-resolved prefix (an
    absolute target resets the prefix first).
    """
    s = target.replace("\\", "/")
    if s.startswith("//?/"):
        s = s[4:]
    if s.startswith("UNC/"):
        s = "//" + s[4:]
    return s


def _split_windows_components(rest: str) -> list[str]:
    """Split a ``/``-separated Windows path remainder into components."""
    return [c for c in rest.split("/") if c not in ("", ".")]


def _is_link(path: str, *, windows: bool, fs) -> bool:
    """Unified link test (FIX-R2 D2).

    POSIX: ``fs.islink`` (unchanged). Windows: the component is a link
    exactly when ``fs.reparse_tag`` is a junction or symlink tag.
    Raises ``OSError`` when the path cannot be lstatted on Windows.
    """
    if windows:
        return fs.reparse_tag(path) in WINDOWS_LINK_TAGS
    return fs.islink(path)


# ---------------------------------------------------------------------------
# Windows-style spelling (pure string; no filesystem access)
# ---------------------------------------------------------------------------

def is_windows_style_path(raw: str) -> bool:
    """Return True when *raw* is spelled like a Windows path.

    True for a drive-letter path (``C:\\...`` or ``C:/...``) or a UNC
    path (``\\\\server\\share\\...``). A bare ``C:foo`` (drive-relative,
    no separator) is *not* accepted as a Windows absolute path and is
    reported by :func:`normalize_windows_path` as an error instead.
    """
    if not isinstance(raw, str):
        raise TypeError("path must be str, not %s" % type(raw).__name__)
    return bool(_DRIVE_RE.match(raw) or _UNC_RE.match(raw))


def normalize_windows_path(raw: str) -> str:
    """Normalise a Windows-style path spelling to ``C:/...`` form.

    Pure-string operation (usable on Linux): backslashes become ``/``,
    ``.`` / ``..`` are resolved lexically, duplicate separators
    collapse. The result is a *spelling*, not a filesystem resolution —
    it does not follow junctions, does not touch a disk, and says
    nothing about whether the path exists.

    Raises ``ValueError`` for a drive-relative spelling (``C:foo``) and
    for an empty path.
    """
    if not isinstance(raw, str):
        raise TypeError("path must be str, not %s" % type(raw).__name__)
    if raw == "":
        raise ValueError("empty path")
    if re.match(r"^[A-Za-z]:[^\\/]", raw):
        raise ValueError("drive-relative Windows path is ambiguous: %r" % raw)
    # ntpath.normpath resolves . / .. lexically and collapses separators.
    normal = ntpath.normpath(raw)
    return normal.replace("\\", "/")


# ---------------------------------------------------------------------------
# Lexical canonicalisation (no symlink resolution, no FS access beyond
# the caller-supplied cwd/home strings)
# ---------------------------------------------------------------------------

def _is_absolute_path(path: str) -> bool:
    """``os.path.isabs`` plus Windows-style spellings, on any host.

    A drive-letter / UNC spelling is absolute even when the host
    ``os.path`` is POSIX (a Linux test host passes Windows cwds to
    the fake-FS ``os_name="nt"`` simulation); on a real Windows host
    ``os.path.isabs`` already covers these, so this is a no-op
    there. Consistent with :func:`lexical_canonical`, which already
    treats any Windows-style *raw* as absolute on any host.
    """
    return os.path.isabs(path) or is_windows_style_path(path)


def _normalize_for_comparison(path: str) -> str:
    """Normalise *path* for separator-insensitive comparison (FIX-R3 B).

    Windows-style spellings become ``C:/...`` form (via
    :func:`normalize_windows_path`); anything else goes through
    ``os.path.normpath`` unchanged. On a POSIX host this is a no-op
    for POSIX paths (``normpath`` there is already ``/``), so Linux
    behaviour is byte-identical — only Windows spellings change.
    """
    if is_windows_style_path(path):
        return normalize_windows_path(path)
    return os.path.normpath(path)


def _check_no_nul(raw: str) -> None:
    if "\x00" in raw:
        raise ValueError("path contains NUL byte")


def lexical_canonical(raw, cwd=None, home=None) -> str:
    """Return the lexical canonical form of *raw* (absolute, normalised).

    Steps (PROJECT_BOOK.md §13.1, steps 1/3/4, lexical part):

    1. ``~`` / ``~/...`` expands against the explicitly supplied
       ``home`` only. ``~user`` is rejected. Without ``home`` a leading
       ``~`` is an error — the real user home is never consulted.
    2. A relative path is joined onto ``cwd`` (required for relative
       input; an absolute path ignores ``cwd``). The joined result
       is re-normalised exactly like an absolute raw (FIX-R3 A):
       on Windows ``os.path.join`` produces backslashes, so without
       this step a joined ``C:\\...`` spelling misses the
       drive-letter branch below and falls back to ``/C:\\...``.
    3. ``.`` / ``..`` are resolved lexically, duplicate separators
       collapse, a trailing separator is removed (except for ``/``).
       A leading ``//`` is collapsed to ``/`` so the canonical form is
       stable.
    4. Windows-style spellings (drive letter / UNC) are normalised by
       :func:`normalize_windows_path` instead of POSIX rules.

    The result is a ``str`` (UTF-8). It performs no symlink resolution
    and no existence check, so it is defined for missing paths too.

    Raises ``ValueError`` for an empty path, a NUL byte, ``~`` without
    ``home``, ``~user``, a relative path without ``cwd``, or a
    drive-relative Windows spelling.
    """
    if isinstance(raw, bytes):
        raise TypeError("path must be str, not bytes")
    if not isinstance(raw, str):
        raise TypeError("path must be str, not %s" % type(raw).__name__)
    if raw == "":
        raise ValueError("empty path")
    _check_no_nul(raw)

    if is_windows_style_path(raw):
        return normalize_windows_path(raw)

    path = raw
    if path == "~" or path.startswith("~/"):
        if home is None:
            raise ValueError("~ expansion requires an explicit home argument")
        home_str = os.fspath(home)
        _check_no_nul(home_str)
        if not _is_absolute_path(home_str):
            raise ValueError("home must be absolute: %r" % home_str)
        path = home_str + path[1:]  # "~" -> home, "~/x" -> home + "/x"
    elif path.startswith("~"):
        raise ValueError("~user expansion is unsupported: %r" % raw)

    if not _is_absolute_path(path):
        if cwd is None:
            raise ValueError("relative path requires an explicit cwd: %r" % raw)
        cwd_str = os.fspath(cwd)
        _check_no_nul(cwd_str)
        if not _is_absolute_path(cwd_str):
            raise ValueError("cwd must be absolute: %r" % cwd_str)
        path = os.path.join(cwd_str, path)

    # FIX-R3 A: the joined / ~-expanded result may itself be a
    # Windows spelling (on Windows the join produces backslashes,
    # and "~" expansion concatenates a backslash home with "/x").
    # It must go through the same Windows normalisation as an
    # absolute raw above, or the drive-letter branch of
    # _resolve_components never matches and the path falls back to
    # the POSIX "/C:\..." form (V2 root cause A).
    if is_windows_style_path(path):
        return normalize_windows_path(path)

    # os.path.normpath resolves . / .. lexically and strips trailing "/".
    normal = os.path.normpath(path)
    if normal.startswith("//"):
        normal = "/" + normal.lstrip("/")
    return normal


# ---------------------------------------------------------------------------
# Symlink-aware resolution (bounded, fail-closed)
# ---------------------------------------------------------------------------

def _split_components(abs_path: str) -> list[str]:
    """Split an absolute POSIX path into components (no ``/``, ``.``)."""
    return [c for c in abs_path.split("/") if c not in ("", ".")]


def _resolve_components(lexical: str, *, fs=None, os_name=None) -> tuple[str, list[str], bool, str | None]:
    """Resolve symlinks in *lexical* (absolute path) component-wise.

    Returns ``(resolved, chain, is_loop, error)`` where ``chain`` is
    the list of symlink targets encountered (in resolution order) and
    ``error`` is ``"SYMLINK_LOOP"`` / ``"UNRESOLVABLE"`` / ``None``.

    Dispatch (FIX-R2 D1): when *lexical* is a drive-letter absolute
    path (``^[A-Za-z]:/``) and the host is Windows (``os_name ==
    "nt"``), the Windows branch runs (see
    :func:`_resolve_windows_drive`); otherwise the original POSIX
    algorithm runs unchanged — on Linux a drive-letter spelling
    therefore still resolves to ``/C:/...``, exactly as before.

    POSIX algorithm: walk the component queue left to right,
    maintaining the already-resolved prefix. When the next component
    is a symlink, splice its target components to the front of the
    queue (an absolute target resets the prefix). ``..`` pops the
    last resolved component. A component that does not exist (or whose
    parent is not a directory) ends resolution: the rest is appended
    lexically, so a missing leaf is reported as missing, not
    fabricated. A hop bound plus a visited-set makes loops terminate.
    """
    fs = _REAL_FS if fs is None else fs
    platform = os.name if os_name is None else os_name
    if platform == "nt" and _DRIVE_ABS_RE.match(lexical):
        return _resolve_windows_drive(lexical, fs=fs)
    queue = _split_components(lexical)
    out: list[str] = []
    chain: list[str] = []
    seen: set[tuple[tuple[str, ...], str]] = set()
    hops = 0
    steps = 0
    while queue:
        steps += 1
        if steps > _MAX_COMPONENTS:
            return "/" + "/".join(out), chain, False, "UNRESOLVABLE"
        comp = queue.pop(0)
        if comp == "..":
            if out:
                out.pop()
            continue
        current = "/" + "/".join(out + [comp]) if out else "/" + comp
        try:
            is_link = fs.islink(current)
        except OSError:
            # Unreadable component: stop resolving here, keep lexical rest.
            out.append(comp)
            out.extend(queue)
            return "/" + "/".join(out), chain, False, None
        if not is_link:
            if not fs.lexists(current):
                # Missing from here on: nothing further can be a symlink
                # we could observe, so append the rest lexically.
                out.append(comp)
                out.extend(queue)
                return "/" + "/".join(out), chain, False, None
            out.append(comp)
            continue
        # Symlink component.
        key = (tuple(out), comp)
        if key in seen:
            out.append(comp)
            out.extend(queue)
            return "/" + "/".join(out), chain, True, "SYMLINK_LOOP"
        seen.add(key)
        hops += 1
        if hops > MAX_SYMLINK_HOPS:
            out.append(comp)
            out.extend(queue)
            return "/" + "/".join(out), chain, True, "SYMLINK_LOOP"
        try:
            target = fs.readlink(current)
        except OSError:
            out.append(comp)
            out.extend(queue)
            return "/" + "/".join(out), chain, False, None
        chain.append(target)
        if os.path.isabs(target):
            out = []
            queue = _split_components(target) + queue
        else:
            queue = _split_components(target) + queue
    return "/" + "/".join(out) if out else "/", chain, False, None


def _resolve_windows_drive(lexical: str, *, fs) -> tuple[str, list[str], bool, str | None]:
    """Windows drive-letter branch of :func:`_resolve_components`.

    The drive root (``C:/``) is the root: components are resolved
    against the real filesystem one by one, ``..`` pops the last
    resolved component and stops at the drive root (it can never
    cross to another drive), and a component is a link exactly when
    its reparse tag is a junction (``0xA0000003``) or a symlink
    (``0xA000000C``) — see :func:`_is_link`. A readlink target is
    normalised by :func:`_normalize_windows_readlink_target` before
    being split; an absolute drive-letter target resets the root to
    that drive, a ``/``-absolute target resets to the current drive
    root, a UNC target resets to that share. Chain entries are the
    *normalised* targets (the ``\\\\?\\`` prefix CPython adds is an
    OS artefact the Oracle never reports, so the raw form could
    never match it). A missing component ends resolution with the
    rest appended lexically, exactly like the POSIX branch. Loops
    fail closed with ``SYMLINK_LOOP`` and no resolved path.
    """
    root = lexical[:3]  # e.g. "C:/" (lexical is already "C:/..." form)
    queue = _split_windows_components(lexical[3:])
    out: list[str] = []
    chain: list[str] = []
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    hops = 0
    steps = 0

    def _join(prefix: str, parts: list[str]) -> str:
        return prefix + "/".join(parts) if parts else prefix

    while queue:
        steps += 1
        if steps > _MAX_COMPONENTS:
            return _join(root, out), chain, False, "UNRESOLVABLE"
        comp = queue.pop(0)
        if comp == "..":
            if out:
                out.pop()
            # At the drive root ".." stops: it never crosses a drive.
            continue
        current = _join(root, out + [comp])
        try:
            is_link = _is_link(current, windows=True, fs=fs)
        except OSError:
            # Unreadable component (lstat failed): stop here, keep
            # the lexical rest, like the POSIX branch.
            out.append(comp)
            out.extend(queue)
            return _join(root, out), chain, False, None
        if not is_link:
            if not fs.lexists(current):
                out.append(comp)
                out.extend(queue)
                return _join(root, out), chain, False, None
            out.append(comp)
            continue
        # Link component (junction or symlink, by reparse tag).
        key = (root, tuple(out), comp)
        if key in seen:
            out.append(comp)
            out.extend(queue)
            return _join(root, out), chain, True, "SYMLINK_LOOP"
        seen.add(key)
        hops += 1
        if hops > MAX_SYMLINK_HOPS:
            out.append(comp)
            out.extend(queue)
            return _join(root, out), chain, True, "SYMLINK_LOOP"
        try:
            raw_target = fs.readlink(current)
        except OSError:
            out.append(comp)
            out.extend(queue)
            return _join(root, out), chain, False, None
        target = _normalize_windows_readlink_target(raw_target)
        chain.append(target)
        if _DRIVE_ABS_RE.match(target):
            root = target[:3]
            out = []
            queue = _split_windows_components(target[3:]) + queue
        elif target.startswith("//"):
            # UNC target: root is the share, the rest are components.
            # (A target with fewer than server+share components is
            # malformed; treat the whole thing as the new root.)
            parts = _split_windows_components(target[2:])
            if len(parts) >= 2:
                root = "//" + parts[0] + "/" + parts[1] + "/"
                queue = parts[2:] + queue
            else:
                root = "//" + "/".join(parts) + "/" if parts else "//"
            out = []
        elif target.startswith("/"):
            out = []
            queue = _split_windows_components(target) + queue
        else:
            queue = _split_windows_components(target) + queue
    return _join(root, out), chain, False, None


@dataclass(frozen=True)
class CanonicalPath:
    """The canonical record for one input path (lexical + resolved).

    Field meanings follow ``00_contract/receipt_schema.json`` source
    fields ``canonical_path`` / ``resolved_path`` / ``is_symlink`` /
    ``symlink_target``:

    * ``raw_path`` — the path exactly as supplied by the caller.
    * ``canonical_path`` — lexical canonical path (absolute, ``..``
      normalised, separators normalised; symlinks *not* resolved).
      Identical to ``lexical_path``; both names are kept so receipt
      code can use the contract spelling.
    * ``resolved_path`` — canonical path after symlink resolution, or
      ``None`` when resolution failed fail-closed (loop / unresolvable).
      Equals ``canonical_path`` when no component is a symlink.
    * ``exists`` — the resolved target exists (``False`` for missing
      paths and for broken symlinks).
    * ``is_symlink`` — True when *any* path component is a symlink.
    * ``symlink_target`` — the target of the final path component
      when that component itself is a symlink, else ``None``. On the
      Windows drive branch the target is normalised (backslashes ->
      ``/``, ``\\?\\`` prefix stripped) so it matches the form the
      Oracle reports; elsewhere it is the raw ``readlink`` result.
    * ``symlink_chain`` — raw targets of every symlink component
      encountered, in resolution order (empty when ``is_symlink`` is
      False). The chain is what lets a reviewer see *how* a path
      escapes, not just that it does.
    * ``is_broken_symlink`` — a symlink whose (resolved) target does
      not exist.
    * ``is_loop`` / ``error`` — ``is_loop=True`` and
      ``error="SYMLINK_LOOP"`` when resolution hit the hop bound or a
      repeated link; ``error="UNRESOLVABLE"`` for pathological inputs.
      ``valid`` is False in both cases: callers must treat the path
      as unusable (fail-closed), never as a normal path.
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
    error: str | None = None

    @property
    def lexical_path(self) -> str:
        """Alias for ``canonical_path`` (the lexical record)."""
        return self.canonical_path

    @property
    def valid(self) -> bool:
        """False when resolution failed fail-closed (loop/unresolvable)."""
        return self.error is None

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
            "error": self.error,
        }


def canonicalize(raw, cwd=None, home=None, *, fs=None, os_name=None) -> CanonicalPath:
    """Canonicalise *raw* into a :class:`CanonicalPath` (lexical+resolved).

    Never raises for a loop, a broken symlink, or a missing path —
    those are reported in the returned record. Raises ``ValueError`` /
    ``TypeError`` only for malformed *input* (empty path, NUL byte,
    ``~`` without an explicit ``home``, ``~user``, relative path
    without ``cwd``), i.e. caller errors, not filesystem states.

    ``fs`` / ``os_name`` are the FIX-R2 testability hooks (D3): ``fs``
    is a filesystem probe (``islink`` / ``lexists`` / ``exists`` /
    ``isfile`` / ``isdir`` / ``readlink`` / ``reparse_tag``; defaults
    to the real ``os`` functions) and ``os_name`` overrides ``os.name``
    (defaults to it). Callers never pass them; tests pass
    ``os_name="nt"`` with a fake ``fs`` to exercise the Windows
    drive-letter branch on Linux. On a real Windows host the branch
    activates automatically for drive-letter paths.
    """
    lexical = lexical_canonical(raw, cwd=cwd, home=home)
    raw_str = raw if isinstance(raw, str) else os.fspath(raw)
    fs_obj = _REAL_FS if fs is None else fs
    platform = os.name if os_name is None else os_name
    windows_drive = platform == "nt" and bool(_DRIVE_ABS_RE.match(lexical))

    # Final-component symlink target. On the Windows drive branch the
    # link test is the unified reparse-tag rule (D2: ``os.path.islink``
    # returns False for junctions, so it must not be used here) and
    # the target is normalised; elsewhere it is the raw readlink
    # result, exactly as before.
    symlink_target: str | None = None
    try:
        if windows_drive:
            if _is_link(lexical, windows=True, fs=fs_obj):
                symlink_target = _normalize_windows_readlink_target(
                    fs_obj.readlink(lexical))
        elif fs_obj.islink(lexical):
            symlink_target = fs_obj.readlink(lexical)
    except OSError:
        symlink_target = None

    resolved, chain, is_loop, error = _resolve_components(
        lexical, fs=fs_obj, os_name=platform)
    if is_loop or error is not None:
        # Fail-closed: no resolved path is asserted for a loop.
        return CanonicalPath(
            raw_path=raw_str,
            canonical_path=lexical,
            resolved_path=None,
            exists=False,
            is_symlink=bool(chain),
            symlink_target=symlink_target,
            symlink_chain=tuple(chain),
            is_broken_symlink=False,
            is_loop=is_loop,
            error=error or "UNRESOLVABLE",
        )

    exists = fs_obj.exists(resolved)
    is_broken = bool(chain) and not exists and fs_obj.lexists(lexical)
    try:
        is_file = fs_obj.isfile(resolved) if exists else False
        is_dir = fs_obj.isdir(resolved) if exists else False
    except OSError:
        is_file = is_dir = False
    return CanonicalPath(
        raw_path=raw_str,
        canonical_path=lexical,
        resolved_path=resolved,
        exists=exists,
        is_file=is_file,
        is_dir=is_dir,
        is_symlink=bool(chain),
        symlink_target=symlink_target,
        symlink_chain=tuple(chain),
        is_broken_symlink=is_broken,
        is_loop=False,
        error=None,
    )


# ---------------------------------------------------------------------------
# Containment / escape (lexical strings; no trust classification here —
# trust is T004's job and uses these primitives)
# ---------------------------------------------------------------------------

def is_within_root(path: str, root: str) -> bool:
    """Return True when canonical absolute *path* is *root* or under it.

    Both arguments are normalised lexically (``..`` resolved) before
    comparison; the check itself needs no filesystem access. The root
    itself counts as within. ``/`` contains everything. A path that
    merely shares a string prefix (``/repo2`` vs root ``/repo``) is
    correctly *not* within — comparison is component-wise, not textual.

    FIX-R3 B: both sides go through
    :func:`_normalize_for_comparison` first, so a Windows spelling
    (``C:\\repo\\x``) compares in ``C:/`` form instead of failing
    the ``"/"``-separator prefix test after ``os.path.normpath``
    produced backslashes. A drive root (``C:/``) contains
    everything under that drive, like ``/`` does for POSIX.
    """
    if not isinstance(path, str) or not isinstance(root, str):
        raise TypeError("path and root must be str")
    _check_no_nul(path)
    _check_no_nul(root)
    norm_path = _normalize_for_comparison(path)
    norm_root = _normalize_for_comparison(root)
    # Strip one trailing separator so a root spelled "C:/" (or "/")
    # does not demand a doubled "//" in the prefix test.
    root_base = norm_root.rstrip("/") or "/"
    if root_base == "/":
        return norm_path.startswith("/")
    return norm_path == root_base or norm_path.startswith(root_base + "/")


def redact_home(canonical: str, home: str) -> str:
    """Redact *home* as ``<HOME>`` for display (receipt schema note).

    Only a display transform: the receipt hash always uses the
    unredacted canonical path. Returns *canonical* unchanged when it
    is not under ``home``.
    """
    if not isinstance(canonical, str) or not isinstance(home, str):
        raise TypeError("canonical and home must be str")
    norm_home = os.path.normpath(home)
    norm_path = os.path.normpath(canonical)
    if norm_path == norm_home:
        return "<HOME>"
    if norm_path.startswith(norm_home + "/"):
        return "<HOME>/" + norm_path[len(norm_home) + 1:]
    return canonical


@dataclass(frozen=True)
class EscapeInfo:
    """Result of :func:`detect_escape` for one resolved path."""

    resolved_path: str | None
    allowed_roots: tuple[str, ...]
    within_roots: tuple[str, ...] = ()
    escaped: bool = True

    def to_dict(self) -> dict:
        return {
            "resolved_path": self.resolved_path,
            "allowed_roots": list(self.allowed_roots),
            "within_roots": list(self.within_roots),
            "escaped": self.escaped,
        }


def detect_escape(resolved_path, allowed_roots) -> EscapeInfo:
    """Check whether *resolved_path* escapes all of *allowed_roots*.

    Containment is always judged on the **resolved** path (a symlink
    whose lexical path sits inside the repo but whose target sits
    outside it *has* escaped — that is the S07 case). ``allowed_roots``
    are the approved roots for the source (e.g. repo root and the
    synthetic home for user-scope sources); callers decide which roots
    apply. With no allowed roots, or a ``None`` resolved path (loop /
    unresolvable), the result is fail-closed ``escaped=True``.
    """
    roots = tuple(os.path.normpath(str(r)) for r in (allowed_roots or ()))
    if resolved_path is None:
        return EscapeInfo(
            resolved_path=None, allowed_roots=roots,
            within_roots=(), escaped=True,
        )
    resolved = os.path.normpath(str(resolved_path))
    within = tuple(r for r in roots if is_within_root(resolved, r))
    return EscapeInfo(
        resolved_path=resolved,
        allowed_roots=roots,
        within_roots=within,
        escaped=len(within) == 0,
    )
