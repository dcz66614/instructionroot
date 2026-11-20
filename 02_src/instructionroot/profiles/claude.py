"""Claude Code harness profile (T003).

Implements the frozen contract (``00_contract/profile_contract.json``,
profile ``claude-code``, version ``claude-code-2026-11``):

* ``claude-code.managed`` (ORDERED, startup): Linux
  ``/etc/claude-code/CLAUDE.md`` (macOS/Windows paths are not
  observable on this Linux host; see TASK_RESULT.md).
* ``claude-code.user`` (ORDERED, startup): ``~/.claude/CLAUDE.md``.
* ``claude-code.project`` (ORDERED, startup): ``./CLAUDE.md`` or
  ``./.claude/CLAUDE.md`` in the CWD and every ancestor directory,
  concatenated filesystem-root downward. (Contract question Q5 in
  TASK_RESULT.md: both spellings are listed when both exist in one
  directory; the doc does not say they are mutually exclusive.)
* ``claude-code.local`` (ORDERED, startup): ``./CLAUDE.local.md``
  in the CWD and every ancestor; appended after that directory's
  ``CLAUDE.md``.
* ``claude-code.nested`` (UNSPECIFIED, on_demand): ``<subdir>/
  CLAUDE.md`` / ``CLAUDE.local.md`` below the CWD, loaded when
  Claude works with a file in that subdirectory.
* ``claude-code.rules-user`` (ORDERED, startup): ``~/.claude/rules/
  **/*.md`` recursive, before project rules.
* ``claude-code.rules-startup`` (ORDERED, startup): project
  ``.claude/rules/**/*.md`` *without* a ``paths`` frontmatter.
* ``claude-code.rules-path-scoped`` (UNSPECIFIED, on_demand):
  project rules *with* a ``paths`` frontmatter glob list, loaded
  only when a working file matches a glob (patterns relative to
  the directory containing the ``.claude`` folder; user-level
  rules: relative to the main working directory). Unparseable
  YAML frontmatter loads as if it had no paths (contract).
* ``claude-code.agents-fallback`` (ORDERED, startup): ``<dir>/
  AGENTS.md`` and ``<dir>/.claude/AGENTS.md`` in the CWD and every
  ancestor — **only** when no ``CLAUDE.md``, ``.claude/CLAUDE.md``
  or ``CLAUDE.local.md`` exists in the CWD or any ancestor.
* ``claude-code.agents-nested`` (UNSPECIFIED, on_demand): ``<subdir>/
  AGENTS.md`` below the CWD, when that subdirectory contains none
  of the CLAUDE files.
* ``claude-code.additional-dirs`` (UNSPECIFIED, startup): only
  when ``--add-dir`` is used *and*
  ``CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD`` is set (here:
  ``policy["allow_additional_directories"]`` is true and
  additional dirs are supplied). Rules with a ``paths`` field are
  excluded from additional directories.

Import candidates (``@path``): see :func:`iter_import_candidates`.
Maximum depth is **4 hops** per the fetched official doc
(SPEC-01; fixed in FIX-R1 — the spec book now says depth 4,
matching the implementation). A candidate at depth 5 is enumerated with
``allowed=False, reason="DEPTH_EXCEEDED"`` and is not expanded
further. Imports are expanded only from startup CLAUDE/AGENTS
sources (T005 owns the full import graph and edges).

Load limits applied at discovery: CLAUDE.md files over 4 MiB are
skipped (contract ``claude_md_max_bytes``, VERIFIED) and recorded
as not-applicable ``OVERSIZE_CLAUDE_MD``. Symlinked project/user
rules whose resolved path escapes the repo/home roots are
excluded — the contract requires project approval for such
external imports and approval state is NOT_OBSERVED, so it must
not be guessed (recorded ``SYMLINK_EXTERNAL_NOT_OBSERVED``).
``claudeMdExcludes`` and settings exclusions are likewise
NOT_OBSERVED and are not applied.
"""

from __future__ import annotations

import os
import re

from instructionroot.profiles._common import (
    NotApplicable,
    Precedence,
    ResolveContext,
    SourceCandidate,
    ancestor_chain,
    any_glob_matches,
    file_size,
    list_dir_files,
    make_candidate,
    parse_paths_frontmatter,
    read_text,
    relative_posix,
)

__all__ = [
    "PROFILE_ID",
    "PROFILE_VERSION",
    "RULES_HASH",
    "SOURCE_URL",
    "ImportCandidate",
    "discover",
    "iter_import_candidates",
    "parse_imports",
]

PROFILE_ID = "claude-code"
PROFILE_VERSION = "claude-code-2026-11"
SOURCE_URL = "https://docs.anthropic.com/zh-CN/docs/claude-code/memory"
RULES_HASH = (
    "sha256:7f1d074dc0bb8dde1eace4c01498f8899b8ef58aa47f71c32c649768104f6058"
)

#: Maximum @-import depth in hops (SPEC-01: official doc, 4 hops).
MAX_IMPORT_DEPTH = 4

#: CLAUDE.md files over this size are skipped (contract, VERIFIED).
CLAUDE_MD_MAX_BYTES = 4_194_304

_LINUX_MANAGED = "/etc/claude-code/CLAUDE.md"

_P_MANAGED = Precedence(
    kind="ORDERED",
    detail="First: loaded before user and project instructions.",
)
_P_USER = Precedence(
    kind="ORDERED",
    detail="After managed, before project instructions.",
)
_P_PROJECT = Precedence(
    kind="ORDERED",
    detail="Concatenated from the filesystem root downward to the CWD "
    "(ancestors first, CWD last); files are concatenated, not overriding "
    "each other. Override semantics between files: UNSPECIFIED.",
)
_P_LOCAL = Precedence(
    kind="ORDERED",
    detail="In each directory, CLAUDE.local.md is appended after that "
    "directory's CLAUDE.md.",
)
_P_RULES_USER = Precedence(
    kind="ORDERED",
    detail="Loaded before project rules. On conflict, neither user nor "
    "project rules override the other.",
)
_P_RULES_STARTUP = Precedence(
    kind="ORDERED",
    detail="Same precedence as .claude/CLAUDE.md.",
)
_P_AGENTS_FALLBACK = Precedence(
    kind="ORDERED",
    detail="Root-to-CWD concatenation, same as the CLAUDE.md chain, when "
    "the condition holds.",
)
_P_ON_DEMAND = Precedence(
    kind="UNSPECIFIED",
    detail="Trigger is defined; ordering relative to the startup chain is "
    "not defined in the fetched source.",
)
# Path-scoped rules have their own contract detail (FIX-C06): "other
# sources", not "the startup chain" — unlike nested/agents-nested,
# which keep _P_ON_DEMAND above.
_P_PATH_SCOPED = Precedence(
    kind="UNSPECIFIED",
    detail="Trigger is defined; ordering relative to other sources is "
    "not defined in the fetched source.",
)
_P_ADDITIONAL = Precedence(
    kind="UNSPECIFIED",
    detail="Ordering relative to the main chain is not defined in the "
    "fetched source.",
)

_CLAUDE_RULES = {
    "claude-code.managed",
    "claude-code.user",
    "claude-code.project",
    "claude-code.local",
    "claude-code.agents-fallback",
}


# ---------------------------------------------------------------------------
# Import candidates
# ---------------------------------------------------------------------------

class ImportCandidate:
    """One ``@path`` import candidate reachable from a discovered source.

    ``depth`` counts hops from a startup source (a direct import is
    depth 1). ``allowed`` is False when the depth exceeds
    :data:`MAX_IMPORT_DEPTH` (``reason="DEPTH_EXCEEDED"``) or the
    target does not exist (``reason="MISSING"``). Escape detection
    is T005's job; this candidate only records the resolved path.
    """

    __slots__ = (
        "from_canonical",
        "syntax",
        "canonical_target",
        "resolved_target",
        "depth",
        "exists",
        "allowed",
        "reason",
    )

    def __init__(
        self,
        *,
        from_canonical: str,
        syntax: str,
        canonical_target: str | None,
        resolved_target: str | None,
        depth: int,
        exists: bool,
        allowed: bool,
        reason: str,
    ) -> None:
        self.from_canonical = from_canonical
        self.syntax = syntax
        self.canonical_target = canonical_target
        self.resolved_target = resolved_target
        self.depth = depth
        self.exists = exists
        self.allowed = allowed
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "from": self.from_canonical,
            "syntax": self.syntax,
            "canonical_target": self.canonical_target,
            "resolved_target": self.resolved_target,
            "depth": self.depth,
            "exists": self.exists,
            "allowed": self.allowed,
            "reason": self.reason,
        }


_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_IMPORT_RE = re.compile(r"(?<![\w@])@(?![\"'])((?:\\.|[^\s\)\],;'\"`])+)")


def _strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code spans (never imported)."""
    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # Drop inline code spans: keep the segments outside backticks.
        segments = line.split("`")
        out_lines.append("".join(s for i, s in enumerate(segments) if i % 2 == 0))
    return "\n".join(out_lines)


def parse_imports(text: str) -> list[str]:
    """Return the raw ``@path`` reference strings in *text*.

    Imports inside Markdown code spans / fenced code blocks are
    skipped; a path wrapped in quotes is never imported; spaces in
    a path must be backslash-escaped (the escape is removed here).
    """
    found: list[str] = []
    for match in _IMPORT_RE.finditer(_strip_code(text)):
        raw = match.group(1)
        raw = raw.replace("\\ ", " ").replace("\\\\", "\\")
        if raw:
            found.append(raw)
    return found


def iter_import_candidates(
    ctx: ResolveContext, sources: list[SourceCandidate]
) -> list[ImportCandidate]:
    """Enumerate ``@path`` import candidates from startup CLAUDE/AGENTS sources.

    Breadth-first from every startup source whose rule is a CLAUDE
    or AGENTS rule (rules files are not import-expanded — no source
    attests imports inside them). Each target file is expanded at
    most once, at its minimal depth; identical ``(from, syntax,
    target)`` edges are listed once. Expansion stops at depth
    :data:`MAX_IMPORT_DEPTH` + 1: a depth-5 candidate is still
    listed (so the BLOCK is observable) but never expanded.
    """
    from instructionroot.paths import canonicalize

    candidates: list[ImportCandidate] = []
    seen_edges: set[tuple[str, str, str | None]] = set()
    expanded: set[str] = set()
    # Queue entries: (canonical path of file, depth of that file).
    queue: list[tuple[str, int]] = []
    for src in sources:
        if src.discovery_rule in _CLAUDE_RULES and src.phase == "startup":
            queue.append((src.canonical_path, 0))
    while queue:
        file_canonical, file_depth = queue.pop(0)
        if file_canonical in expanded:
            continue
        expanded.add(file_canonical)
        path = file_canonical
        text = read_text(path)
        if text is None:
            continue
        base_dir = os.path.dirname(file_canonical)
        for syntax in parse_imports(text):
            depth = file_depth + 1
            try:
                canon = canonicalize(syntax, cwd=base_dir, home=ctx.home)
                target = canon.canonical_path
                resolved = canon.resolved_path
                exists = canon.exists and canon.is_file
            except (ValueError, TypeError):
                target = None
                resolved = None
                exists = False
            edge_key = (file_canonical, syntax, target)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            if depth > MAX_IMPORT_DEPTH:
                reason = "DEPTH_EXCEEDED"
                allowed = False
            elif not exists:
                # A missing target has no canonical path to report:
                # the receipt edge's resolved_target is null when the
                # target cannot be resolved (missing). The raw
                # reference text in ``syntax`` preserves what was
                # written.
                target = None
                resolved = None
                reason = "MISSING"
                allowed = False
            else:
                reason = "OK"
                allowed = True
            candidates.append(ImportCandidate(
                from_canonical=file_canonical,
                syntax="@" + syntax,
                canonical_target=target,
                resolved_target=resolved,
                depth=depth,
                exists=exists,
                allowed=allowed,
                reason=reason,
            ))
            if allowed and target is not None and depth <= MAX_IMPORT_DEPTH:
                queue.append((target, depth))
    return candidates


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _claude_file(
    ctx: ResolveContext,
    raw_path: str,
    *,
    scope: str,
    rule: str,
    precedence: Precedence,
) -> SourceCandidate | None:
    """A CLAUDE.md / CLAUDE.local.md candidate honouring the 4 MiB cap."""
    try:
        from instructionroot.paths import canonicalize

        canon = canonicalize(raw_path, cwd=ctx.cwd, home=ctx.home)
    except (ValueError, TypeError):
        return None
    if not canon.exists or not canon.is_file:
        return None
    size = file_size(ctx, canon.canonical_path)
    if size is not None and size > CLAUDE_MD_MAX_BYTES:
        ctx.not_applicable.append(NotApplicable(
            raw_path=raw_path,
            canonical_path=canon.canonical_path,
            discovery_rule=rule,
            reason="OVERSIZE_CLAUDE_MD",
            detail="CLAUDE.md over 4 MiB is skipped by Claude Code",
        ))
        return None
    return make_candidate(
        ctx, raw_path, scope=scope, phase="startup",
        discovery_rule=rule, precedence=precedence,
    )


def _rules_symlink_ok(ctx: ResolveContext, cand: SourceCandidate) -> bool:
    """Fail-closed check for symlinked rules files.

    A symlinked ``.claude/rules`` target outside the working
    directories needs project approval for the external import;
    approval state is NOT_OBSERVED, so it must not be guessed.
    A rule whose resolved path escapes both the repo root and the
    home directory is excluded.
    """
    if not cand.is_symlink or cand.resolved_path is None:
        return True
    from instructionroot.paths import is_within_root

    roots = [r for r in (ctx.repo_root, ctx.home) if r]
    if any(is_within_root(cand.resolved_path, r) for r in roots):
        return True
    ctx.not_applicable.append(NotApplicable(
        raw_path=cand.raw_path,
        canonical_path=cand.canonical_path,
        discovery_rule=cand.discovery_rule,
        reason="SYMLINK_EXTERNAL_NOT_OBSERVED",
        detail="symlinked rules target outside working directories; "
        "external-import approval state is NOT_OBSERVED",
    ))
    return False


def _collect_rules(
    ctx: ResolveContext,
    rules_dir: str,
    *,
    scope: str,
    rule_startup: str,
    rule_path_scoped: str,
    base_for_globs: str,
    precedence_startup: Precedence,
) -> list[SourceCandidate]:
    """Collect ``.claude/rules/**/*.md`` under *rules_dir*.

    Rules without a ``paths`` frontmatter load at startup; rules
    with one load on demand only when a working file matches a
    glob (relative to *base_for_globs*). Non-matching path-scoped
    rules are recorded as not-applicable, never as sources.
    """
    out: list[SourceCandidate] = []
    for lex in list_dir_files(rules_dir, recursive=True, suffixes=(".md",)):
        text = read_text(lex)
        paths = parse_paths_frontmatter(text) if text is not None else None
        if paths is None:
            cand = make_candidate(
                ctx, lex, scope=scope, phase="startup",
                discovery_rule=rule_startup, precedence=precedence_startup,
            )
            if cand is not None and _rules_symlink_ok(ctx, cand):
                out.append(cand)
            continue
        # Path-scoped rule: needs a working-file trigger.
        if not ctx.working_files:
            ctx.not_applicable.append(NotApplicable(
                raw_path=lex, canonical_path=None,
                discovery_rule=rule_path_scoped,
                reason="PATH_SCOPED_NO_TRIGGER",
                detail="paths-scoped rule needs a file Claude is working with",
            ))
            continue
        matched = False
        for wf in ctx.working_files:
            rel = relative_posix(wf, base_for_globs)
            if rel is not None and any_glob_matches(paths, rel):
                matched = True
                break
        if not matched:
            ctx.not_applicable.append(NotApplicable(
                raw_path=lex, canonical_path=None,
                discovery_rule=rule_path_scoped,
                reason="PATH_SCOPED_NO_MATCH",
                detail="no working file matches the rule's paths globs",
            ))
            continue
        cand = make_candidate(
            ctx, lex, scope=scope, phase="on_demand",
            discovery_rule=rule_path_scoped, precedence=_P_PATH_SCOPED,
        )
        if cand is not None and _rules_symlink_ok(ctx, cand):
            out.append(cand)
    return out


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover(ctx: ResolveContext) -> list[SourceCandidate]:
    """Discover Claude Code instruction sources for ``ctx``.

    Order: managed, user CLAUDE.md, user rules, then per ancestor
    directory (root to CWD) CLAUDE.md / .claude/CLAUDE.md /
    CLAUDE.local.md / project rules, then the AGENTS.md fallback
    chain (only when the condition holds), then on-demand nested
    sources, then additional-directory sources. On-demand sources
    are appended after the startup chain; their relative order is
    enumeration order, not a precedence claim.
    """
    out: list[SourceCandidate] = []

    # Managed (Linux path; overrideable for tests).
    managed_raw = ctx.managed_path or _LINUX_MANAGED
    managed = _claude_file(
        ctx, managed_raw, scope="managed",
        rule="claude-code.managed", precedence=_P_MANAGED,
    )
    if managed is not None:
        out.append(managed)

    # User CLAUDE.md + user rules.
    user = _claude_file(
        ctx, "~/.claude/CLAUDE.md", scope="user",
        rule="claude-code.user", precedence=_P_USER,
    )
    if user is not None:
        out.append(user)
    out.extend(_collect_rules(
        ctx, ctx.home + "/.claude/rules",
        scope="user",
        rule_startup="claude-code.rules-user",
        rule_path_scoped="claude-code.rules-path-scoped",
        base_for_globs=ctx.cwd,
        precedence_startup=_P_RULES_USER,
    ))

    # Project chain: every ancestor, root to CWD.
    ancestors = ancestor_chain(ctx.cwd, stop=ctx.ancestor_stop)
    claude_present_anywhere = False
    for directory in ancestors:
        for name, rule, precedence in (
            ("CLAUDE.md", "claude-code.project", _P_PROJECT),
            (".claude/CLAUDE.md", "claude-code.project", _P_PROJECT),
            ("CLAUDE.local.md", "claude-code.local", _P_LOCAL),
        ):
            cand = _claude_file(
                ctx, directory + "/" + name, scope="project",
                rule=rule, precedence=precedence,
            )
            if cand is not None:
                claude_present_anywhere = True
                out.append(cand)
        out.extend(_collect_rules(
            ctx, directory + "/.claude/rules",
            scope="project",
            rule_startup="claude-code.rules-startup",
            rule_path_scoped="claude-code.rules-path-scoped",
            base_for_globs=directory,
            precedence_startup=_P_RULES_STARTUP,
        ))

    # AGENTS.md fallback: only when no CLAUDE file exists anywhere
    # in the CWD or above. ~/.claude/CLAUDE.md, the managed file and
    # .claude/rules files do NOT count for this check.
    if not claude_present_anywhere:
        for directory in ancestors:
            for name in ("AGENTS.md", ".claude/AGENTS.md"):
                cand = make_candidate(
                    ctx, directory + "/" + name, scope="project",
                    phase="startup",
                    discovery_rule="claude-code.agents-fallback",
                    precedence=_P_AGENTS_FALLBACK,
                )
                if cand is not None:
                    out.append(cand)

    # Nested on-demand: subdirectories below the CWD holding a
    # working file. Shallowest subdir first, sorted within a depth.
    if ctx.policy.get("allow_nested_on_demand", True) and ctx.working_files:
        nested = _nested_sources(ctx)
        out.extend(nested)
    elif ctx.working_files and not ctx.policy.get("allow_nested_on_demand", True):
        for wf in ctx.working_files:
            rel = relative_posix(wf, ctx.cwd)
            if rel and "/" in rel:
                ctx.not_applicable.append(NotApplicable(
                    raw_path=wf, canonical_path=None,
                    discovery_rule="claude-code.nested",
                    reason="ON_DEMAND_DISABLED_BY_POLICY",
                    detail="allow_nested_on_demand is false",
                ))

    # Additional directories: only when the policy allows them and
    # dirs were supplied (CLI --add-dir + env var in real use).
    if ctx.policy.get("allow_additional_directories", False) and ctx.additional_dirs:
        for directory in ctx.additional_dirs:
            for name, rule in (
                ("CLAUDE.md", "claude-code.additional-dirs"),
                (".claude/CLAUDE.md", "claude-code.additional-dirs"),
                ("CLAUDE.local.md", "claude-code.additional-dirs"),
            ):
                cand = _claude_file(
                    ctx, directory + "/" + name, scope="project",
                    rule=rule, precedence=_P_ADDITIONAL,
                )
                if cand is not None:
                    out.append(cand)
            # Rules in additional dirs: *.md only (not recursive),
            # and rules with a paths field are excluded.
            for lex in list_dir_files(
                directory + "/.claude/rules", recursive=False, suffixes=(".md",)
            ):
                text = read_text(lex)
                if text is not None and parse_paths_frontmatter(text) is not None:
                    continue
                cand = make_candidate(
                    ctx, lex, scope="project", phase="startup",
                    discovery_rule="claude-code.additional-dirs",
                    precedence=_P_ADDITIONAL,
                )
                if cand is not None:
                    out.append(cand)
    elif ctx.additional_dirs and not ctx.policy.get(
        "allow_additional_directories", False
    ):
        for directory in ctx.additional_dirs:
            ctx.not_applicable.append(NotApplicable(
                raw_path=directory, canonical_path=None,
                discovery_rule="claude-code.additional-dirs",
                reason="ADDITIONAL_DIRS_DISABLED_BY_POLICY",
                detail="allow_additional_directories is false (default)",
            ))

    return out


def _nested_sources(ctx: ResolveContext) -> list[SourceCandidate]:
    """On-demand nested sources for subdirectories holding a working file."""
    # Map each subdir (below CWD, containing a working file) to its depth.
    subdirs: dict[str, int] = {}
    for wf in ctx.working_files:
        rel = relative_posix(wf, ctx.cwd)
        if rel is None or "/" not in rel:
            continue  # working file is in the CWD itself, not a subdir
        parts = rel.split("/")[:-1]  # directory components below CWD
        cur = ctx.cwd
        for i, part in enumerate(parts, start=1):
            cur = cur + "/" + part
            subdirs.setdefault(cur, i)
    out: list[SourceCandidate] = []
    for directory in sorted(subdirs, key=lambda d: (subdirs[d], d)):
        claude_here = False
        for name, rule in (
            ("CLAUDE.md", "claude-code.nested"),
            ("CLAUDE.local.md", "claude-code.nested"),
        ):
            cand = make_candidate(
                ctx, directory + "/" + name, scope="nested",
                phase="on_demand", discovery_rule=rule,
                precedence=_P_ON_DEMAND,
            )
            if cand is not None:
                claude_here = True
                out.append(cand)
        if not claude_here:
            cand = make_candidate(
                ctx, directory + "/AGENTS.md", scope="nested",
                phase="on_demand",
                discovery_rule="claude-code.agents-nested",
                precedence=_P_ON_DEMAND,
            )
            if cand is not None:
                out.append(cand)
    return out
