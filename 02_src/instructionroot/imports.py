"""Import graph + escape detection for P028 InstructionRoot Resolve (T005).

Parses **only** the import/reference syntax the frozen contract
(``00_contract/profile_contract.json``) explicitly declares, and
only resolves it — never executes an import, never reads a network
URL, never follows a shell command, never treats a Markdown link as
an executable instruction:

* **claude-code** — ``@path`` (contract ``import_syntax`` VERIFIED):
  relative to the file containing the import, absolute paths
  allowed, recursive, maximum **4 hops** (SPEC-01: the fetched
  official doc, not the spec book's depth-5 text). Imports inside
  Markdown code spans / fenced code blocks are skipped; a path
  wrapped in quotes is never imported; spaces in a path must be
  backslash-escaped. Expanded only from startup CLAUDE.md /
  AGENTS.md sources (the same set T003's
  :func:`instructionroot.profiles.claude.iter_import_candidates`
  expands); ``.claude/rules`` files are not import-expanded (no
  source attests imports inside them).
* **copilot-cli** — ``@<relative-path>`` (VERIFIED) in
  ``.github/copilot-instructions.md``, ``AGENTS.md`` and
  ``CLAUDE.md``; **not** expanded in ``GEMINI.md`` or
  ``*.instructions.md``. Absolute paths and paths beginning with
  ``~/`` are not loaded (→ ``IMPORT_ESCAPE``). Nested references
  are supported ("references within referenced files"). There is
  **no** contract max depth for Copilot, so none is imposed here;
  cycles terminate because each file is expanded at most once.
* **codex** — no import syntax is documented (contract:
  ``supported: UNVERIFIED``). ``@...`` text in an ``AGENTS.md``
  is **not** parsed and produces no edges.

Reference parsing reuses
:func:`instructionroot.profiles.claude.parse_imports` (the T003
parser: code-span/fence skipping, quoted-path exclusion,
backslash-escaped spaces) for both Claude and Copilot. The
contract attests those exclusions for Claude only; applying the
same Markdown-text convention to Copilot is a T005 working
assumption, recorded as a contract question in
``review/tasks/P028-T005/TASK_RESULT.md``.

Approved roots (containment is always judged on the **resolved**
path, after symlink resolution — a lexical in-repo path whose
target sits outside has escaped):

* Claude: ``repo_root`` (when known), ``cwd``, ``home`` and any
  additional directories — the same approved roots T004's trust
  classifier uses (repo + home). A target inside the home but
  outside the repo is ``WITHIN_HOME`` and allowed; the contract
  note that imports outside the *working directories* need a
  per-project approval whose state is NOT_OBSERVED is recorded as
  a contract question (see TASK_RESULT.md) — this module does not
  guess approval state, it applies the trust roots.
* Copilot: ``repo_root`` (or ``cwd`` when there is no repo) plus
  the custom-instructions directories. ``home`` is **not** an
  approved root for Copilot (contract: ``home_allowed: false``).

Copilot relative-base assumption (contract question, see
TASK_RESULT.md): the fetched doc does **not** state the base
directory for a relative ``@`` path (``relative_to`` is
UNVERIFIED). T005 resolves Copilot relative references
**file-relative** — the same base Claude documents — as a working
assumption. If the parent resolves the base differently, only
this module's ``_COPILOT_BASE`` decision and the golden fixtures
need to change; no contract file is touched here.

Check order for one reference (fail-closed at every step):

1. Copilot syntactic absolute / ``~/`` → ``IMPORT_ESCAPE``
   (never resolved as a loadable reference).
2. Canonicalisation failure (e.g. ``~user``) → ``UNRESOLVABLE``.
3. Claude depth > 4 → ``DEPTH_EXCEEDED`` (the candidate is still
   listed, never expanded — same as T003).
4. Resolved path outside every approved root → ``IMPORT_ESCAPE``.
   This outranks MISSING: a reference that escapes is an escape
   whether or not the target file happens to exist.
5. Target missing, or not a regular file → ``MISSING``
   (``resolved_target`` is null, as in T003).
6. Otherwise allowed, with reason ``WITHIN_REPO`` /
   ``WITHIN_HOME`` / ``WITHIN_CUSTOM_DIR`` by the root matched.

Edge ``from`` / ``to`` (contract gap, see TASK_RESULT.md): the
receipt schema types ``edge.from`` as "source_id of the
importing source" and ``edge.to`` as a source_id or null. A
depth-1 importer is a discovered source, so ``from`` is its
``src-NNNN`` id; a depth-2+ importer is an import target, not a
receipt source, so there is no source_id to name. For those
edges :meth:`ImportEdge.to_dict` uses the importer's canonical
path as the ``from`` value (the schema puts no pattern on
``from``; the frozen golden format in
``01_s0/fixtures/README.md`` §3 likewise identifies edge ends by
path). ``to`` is the target's source_id when the target is
itself a discovered source, else null — exactly per schema.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from instructionroot.paths import canonicalize, is_within_root
from instructionroot.profiles._common import read_text
from instructionroot.profiles.claude import MAX_IMPORT_DEPTH, parse_imports

__all__ = [
    "EDGE_REASONS",
    "ImportEdge",
    "ImportGraph",
    "assign_source_ids",
    "build_import_graph",
    "expandable_sources",
    "source_id_for",
]

#: Maximum @-import depth in hops for Claude (SPEC-01, official doc).
CLAUDE_MAX_DEPTH = MAX_IMPORT_DEPTH

#: Reason vocabulary used on edges. ``WITHIN_*`` / ``IMPORT_ESCAPE`` /
#: ``MISSING`` / ``NOT_OBSERVED`` are the receipt schema's examples;
#: ``DEPTH_EXCEEDED`` is T003's candidate reason (kept verbatim so
#: T005 edges match the resolver golden fixtures);
#: ``UNRESOLVABLE`` covers references that cannot even be
#: canonicalised (e.g. ``~user`` — no canonical path exists to name).
EDGE_REASONS: tuple[str, ...] = (
    "WITHIN_REPO",
    "WITHIN_HOME",
    "WITHIN_CUSTOM_DIR",
    "IMPORT_ESCAPE",
    "MISSING",
    "DEPTH_EXCEEDED",
    "UNRESOLVABLE",
    "NOT_OBSERVED",
)

#: Claude rules whose startup sources are import-expanded (same set
#: as ``instructionroot.profiles.claude._CLAUDE_RULES``).
_CLAUDE_EXPANDABLE_RULES: frozenset[str] = frozenset({
    "claude-code.managed",
    "claude-code.user",
    "claude-code.project",
    "claude-code.local",
    "claude-code.agents-fallback",
})

#: Copilot rules that may carry an expandable file. The filename
#: check in :func:`_copilot_expandable` does the rest (it excludes
#: GEMINI.md, *.instructions.md and .claude/CLAUDE.md).
_COPILOT_RULES: frozenset[str] = frozenset({
    "copilot-cli.user",
    "copilot-cli.repo-wide",
    "copilot-cli.agents",
    "copilot-cli.claude",
    "copilot-cli.custom-dirs",
})

#: Copilot filenames whose @ references are expanded (contract
#: ``supported_in``; the user-level copilot-instructions.md shares
#: the filename — see module docstring / TASK_RESULT.md).
_COPILOT_EXPANDABLE_NAMES: frozenset[str] = frozenset({
    "copilot-instructions.md",
    "AGENTS.md",
    "CLAUDE.md",
})

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def source_id_for(index: int) -> str:
    """Return the stable receipt id for the *index*-th source (0-based)."""
    return "src-%04d" % (index + 1)


def assign_source_ids(sources) -> dict[str, str]:
    """Map each source's canonical path to its ``src-NNNN`` id.

    Sources are numbered in discovery order; a canonical path seen
    twice (a de-duplication miss) keeps its first id.
    """
    mapping: dict[str, str] = {}
    for index, src in enumerate(sources):
        mapping.setdefault(src.canonical_path, source_id_for(index))
    return mapping


@dataclass(frozen=True)
class ImportEdge:
    """One import/reference edge (receipt ``edge`` + diagnostics).

    ``from_source_id`` is None when the importing file is an import
    target rather than a discovered source (see module docstring);
    ``from_canonical`` always names the importing file.
    ``canonical_target`` is the lexical canonical path (None when
    the reference cannot be resolved); ``resolved_target`` is the
    canonical path after symlink resolution (None when missing /
    unresolvable — the receipt's ``resolved_target``). ``depth`` is
    the hop count from a discovered source (a direct import is 1).
    """

    edge_id: str
    from_source_id: str | None
    from_canonical: str
    syntax: str
    to_source_id: str | None
    canonical_target: str | None
    resolved_target: str | None
    allowed: bool
    reason: str
    depth: int

    def to_dict(self) -> dict:
        """Receipt-shaped edge dict (exactly the schema fields).

        ``from`` is the importer's source_id when it is a discovered
        source, else the importer's canonical path (contract gap —
        see module docstring). ``resolved_target`` is null when the
        target cannot be resolved (missing / unresolvable).
        """
        return {
            "edge_id": self.edge_id,
            "from": self.from_source_id
            if self.from_source_id is not None else self.from_canonical,
            "syntax": self.syntax,
            "to": self.to_source_id,
            "resolved_target": self.resolved_target,
            "allowed": self.allowed,
            "reason": self.reason,
        }

    def to_full_dict(self) -> dict:
        """Diagnostic dict: the receipt fields plus depth/targets."""
        out = self.to_dict()
        out["from_canonical"] = self.from_canonical
        out["canonical_target"] = self.canonical_target
        out["depth"] = self.depth
        return out


@dataclass(frozen=True)
class ImportGraph:
    """The import graph for one harness run: edges in BFS order."""

    edges: tuple[ImportEdge, ...] = ()
    harness: str = ""

    def to_dict_list(self) -> list[dict]:
        """Receipt-shaped edge dicts, in emission order."""
        return [e.to_dict() for e in self.edges]

    @property
    def blocked_edges(self) -> tuple[ImportEdge, ...]:
        """Edges with ``allowed`` False (every escape / missing / depth)."""
        return tuple(e for e in self.edges if not e.allowed)

    @property
    def escape_edges(self) -> tuple[ImportEdge, ...]:
        """Edges whose reason is ``IMPORT_ESCAPE``."""
        return tuple(e for e in self.edges if e.reason == "IMPORT_ESCAPE")


def _claude_expandable(src) -> bool:
    """True when a Claude source's imports are expanded (T003 set)."""
    return src.discovery_rule in _CLAUDE_EXPANDABLE_RULES and src.phase == "startup"


def _copilot_expandable(src) -> bool:
    """True when a Copilot source's @ references are expanded.

    GEMINI.md and ``*.instructions.md`` are never expanded
    (contract ``not_expanded_in``); ``.claude/CLAUDE.md`` is not
    expanded either (contract: whether @ applies there is
    UNVERIFIED — fail-closed, do not expand). ``AGENTS.md``,
    ``CLAUDE.md`` (top-level) and ``copilot-instructions.md`` are.
    """
    if src.discovery_rule not in _COPILOT_RULES:
        return False
    name = os.path.basename(src.canonical_path)
    if name not in _COPILOT_EXPANDABLE_NAMES:
        return False
    if name == "CLAUDE.md" and "/.claude/" in src.canonical_path.replace(os.sep, "/"):
        return False
    return True


def expandable_sources(sources, *, harness: str) -> list:
    """Return the discovered sources whose imports are expanded.

    Codex: none (no import syntax is documented). Claude: startup
    CLAUDE/AGENTS sources. Copilot: the expandable filenames in
    :func:`_copilot_expandable`. Unknown harness → no sources
    (callers validate the harness id separately; this function
    never invents an expansion rule).
    """
    if harness == "claude-code":
        return [s for s in sources if _claude_expandable(s)]
    if harness == "copilot-cli":
        return [s for s in sources if _copilot_expandable(s)]
    return []


def _is_copilot_blocked_reference(syntax: str) -> bool:
    """True for Copilot references that are never loaded.

    Absolute paths (POSIX ``/abs``, Windows drive ``C:\\...`` /
    ``C:/...``) and home references (``~/...`` / ``~``) — contract
    ``absolute_allowed: false``, ``home_allowed: false``.
    """
    return (
        syntax.startswith("/")
        or syntax == "~"
        or syntax.startswith("~/")
        or bool(_DRIVE_RE.match(syntax))
    )


def _reason_for_roots(resolved: str, *, repo_root, cwd, home,
                      custom_dirs, additional_dirs) -> str | None:
    """Return the WITHIN_* reason for *resolved*, or None if outside all roots."""
    if repo_root is not None and is_within_root(resolved, repo_root):
        return "WITHIN_REPO"
    if is_within_root(resolved, cwd):
        return "WITHIN_REPO"
    for directory in custom_dirs:
        if is_within_root(resolved, directory):
            return "WITHIN_CUSTOM_DIR"
    for directory in additional_dirs:
        if is_within_root(resolved, directory):
            return "WITHIN_REPO"
    if home is not None and is_within_root(resolved, home):
        return "WITHIN_HOME"
    return None


def build_import_graph(
    sources,
    *,
    harness: str,
    cwd: str,
    home: str,
    repo_root: str | None = None,
    custom_dirs=(),
    additional_dirs=(),
) -> ImportGraph:
    """Build the import/reference graph for *sources* (one harness).

    *sources* are :class:`SourceCandidate` objects in discovery
    order (T003 output). *cwd* / *home* are canonical absolute
    paths; *repo_root* is the canonical repo top level or None
    (non-git workspace — the CWD then stands in as the workspace
    root). *custom_dirs* are the Copilot custom-instructions
    directories; *additional_dirs* are Claude's ``--add-dir``
    directories. Only standard-library calls; files are read as
    text (UTF-8) and never executed; no network access.

    The walk is breadth-first from every expandable source, each
    file expanded at most once (at its minimal depth), so import
    cycles terminate. A depth-5 Claude candidate is still listed
    (``DEPTH_EXCEEDED``, never expanded). Identical
    ``(from, syntax, target)`` references are listed once.
    """
    if not isinstance(harness, str) or harness == "":
        raise ValueError("harness must be a non-empty string")
    cwd = os.path.normpath(os.fspath(cwd))
    home = os.path.normpath(os.fspath(home))
    repo = os.path.normpath(os.fspath(repo_root)) if repo_root is not None else None
    custom = tuple(os.path.normpath(os.fspath(d)) for d in (custom_dirs or ()))
    additional = tuple(
        os.path.normpath(os.fspath(d)) for d in (additional_dirs or ())
    )

    # Approved roots per harness (see module docstring).
    if harness == "claude-code":
        roots_custom: tuple[str, ...] = ()
        roots_additional = additional
        roots_home: str | None = home
    elif harness == "copilot-cli":
        roots_custom = custom
        roots_additional = ()
        roots_home = None  # home_allowed: false for Copilot
    else:
        # codex (no import syntax) and anything else: no expansion.
        return ImportGraph(edges=(), harness=harness)

    id_by_canonical = assign_source_ids(sources)
    edges: list[ImportEdge] = []
    seen_edges: set[tuple[str, str, str | None]] = set()
    expanded: set[str] = set()
    queue: list[tuple[str, int]] = [
        (src.canonical_path, 0) for src in expandable_sources(sources, harness=harness)
    ]

    def _emit(*, from_canonical, syntax, to_source_id, canonical_target,
              resolved_target, allowed, reason, depth) -> None:
        key = (from_canonical, syntax, canonical_target)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(ImportEdge(
            edge_id="edge-%04d" % (len(edges) + 1),
            from_source_id=id_by_canonical.get(from_canonical),
            from_canonical=from_canonical,
            syntax=syntax,
            to_source_id=to_source_id,
            canonical_target=canonical_target,
            resolved_target=resolved_target,
            allowed=allowed,
            reason=reason,
            depth=depth,
        ))

    while queue:
        file_canonical, file_depth = queue.pop(0)
        if file_canonical in expanded:
            continue
        expanded.add(file_canonical)
        text = read_text(file_canonical)
        if text is None:
            continue  # unreadable / non-UTF-8: no imports asserted, never an error
        base_dir = os.path.dirname(file_canonical)
        for raw_ref in parse_imports(text):
            depth = file_depth + 1
            syntax = "@" + raw_ref

            # -- Copilot syntactic blocks (absolute / ~/) -------------
            if harness == "copilot-cli" and _is_copilot_blocked_reference(raw_ref):
                try:
                    canon = canonicalize(raw_ref, cwd=base_dir, home=home)
                    canonical_target: str | None = canon.canonical_path
                    resolved: str | None = canon.resolved_path
                except (ValueError, TypeError):
                    canonical_target = None
                    resolved = None
                _emit(
                    from_canonical=file_canonical, syntax=syntax,
                    to_source_id=id_by_canonical.get(canonical_target)
                    if canonical_target is not None else None,
                    canonical_target=canonical_target,
                    resolved_target=resolved,
                    allowed=False, reason="IMPORT_ESCAPE", depth=depth,
                )
                continue

            # -- Canonicalise (relative to the importing file) --------
            try:
                canon = canonicalize(raw_ref, cwd=base_dir, home=home)
            except (ValueError, TypeError):
                _emit(
                    from_canonical=file_canonical, syntax=syntax,
                    to_source_id=None, canonical_target=None,
                    resolved_target=None,
                    allowed=False, reason="UNRESOLVABLE", depth=depth,
                )
                continue
            canonical_target = canon.canonical_path
            resolved = canon.resolved_path
            to_source_id = id_by_canonical.get(canonical_target)

            # -- Claude depth cap (SPEC-01: 4 hops) -------------------
            if harness == "claude-code" and depth > CLAUDE_MAX_DEPTH:
                _emit(
                    from_canonical=file_canonical, syntax=syntax,
                    to_source_id=to_source_id,
                    canonical_target=canonical_target,
                    resolved_target=resolved,
                    allowed=False, reason="DEPTH_EXCEEDED", depth=depth,
                )
                continue

            # -- Escape: containment on the resolved path -------------
            if resolved is None:
                # Resolution failed fail-closed (loop / unresolvable):
                # no resolved path can be asserted, so the edge cannot
                # be shown to stay inside the roots.
                _emit(
                    from_canonical=file_canonical, syntax=syntax,
                    to_source_id=to_source_id,
                    canonical_target=canonical_target,
                    resolved_target=None,
                    allowed=False, reason="IMPORT_ESCAPE", depth=depth,
                )
                continue
            within_reason = _reason_for_roots(
                resolved, repo_root=repo, cwd=cwd, home=roots_home,
                custom_dirs=roots_custom, additional_dirs=roots_additional,
            )
            if within_reason is None:
                _emit(
                    from_canonical=file_canonical, syntax=syntax,
                    to_source_id=to_source_id,
                    canonical_target=canonical_target,
                    resolved_target=resolved,
                    allowed=False, reason="IMPORT_ESCAPE", depth=depth,
                )
                continue

            # -- Missing / not a regular file --------------------------
            if not canon.exists or not canon.is_file:
                _emit(
                    from_canonical=file_canonical, syntax=syntax,
                    to_source_id=None, canonical_target=None,
                    resolved_target=None,
                    allowed=False, reason="MISSING", depth=depth,
                )
                continue

            # -- Allowed ------------------------------------------------
            _emit(
                from_canonical=file_canonical, syntax=syntax,
                to_source_id=to_source_id,
                canonical_target=canonical_target,
                resolved_target=resolved,
                allowed=True, reason=within_reason, depth=depth,
            )
            if canonical_target not in expanded:
                queue.append((canonical_target, depth))

    return ImportGraph(edges=tuple(edges), harness=harness)
