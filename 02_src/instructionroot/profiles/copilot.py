"""GitHub Copilot CLI harness profile (T003).

Implements the frozen contract (``00_contract/profile_contract.json``,
profile ``copilot-cli``, version ``copilot-cli-2026-11``).

All eight rules are ``COMBINE_UNORDERED``: Copilot CLI "combines
their instructions" and "does not define a general precedence order
between these files". The precedence list on the GitHub *concepts*
page (personal > path-specific > repo-wide > agent > organization)
applies to Copilot Chat on GitHub.com, NOT to Copilot CLI, and is
explicitly NOT modelled here. The order in which this module emits
sources is deterministic *enumeration* order (user, user-modular,
repo-wide, repo-modular, agents, claude, gemini, custom-dirs;
sorted by canonical path within each group) — it is not a
precedence claim, and the golden runner asserts set equality for
this profile, not order.

* ``copilot-cli.user`` (startup): ``$HOME/.copilot/
  copilot-instructions.md`` (or ``$COPILOT_HOME`` when set).
* ``copilot-cli.user-modular`` (on_demand): ``$HOME/.copilot/
  instructions/**/*.instructions.md``, included only when its
  ``applyTo`` matches a file Copilot CLI is working with.
  Behaviour when ``applyTo`` is absent is UNVERIFIED for Copilot
  CLI — the file is excluded and recorded as not-applicable
  (``APPLYTO_ABSENT_UNVERIFIED``), never guessed in.
* ``copilot-cli.repo-wide`` (startup): ``.github/
  copilot-instructions.md`` in the standard locations: repo root,
  CWD, intermediate directories between them, and directories
  nested in the path of a file Copilot CLI is working on.
* ``copilot-cli.repo-modular`` (on_demand): ``.github/instructions/
  **/*.instructions.md`` in the standard locations **except**
  intermediate directories; ``applyTo``-gated like user-modular.
* ``copilot-cli.agents`` (startup): ``AGENTS.md`` in the standard
  locations.
* ``copilot-cli.claude`` (startup): ``CLAUDE.md`` and
  ``.claude/CLAUDE.md`` in the standard locations.
* ``copilot-cli.gemini`` (startup): ``GEMINI.md`` in the standard
  locations. (``@`` references are NOT expanded in ``GEMINI.md``.)
* ``copilot-cli.custom-dirs`` (startup): ``AGENTS.md`` and
  ``*.instructions.md`` in each directory listed in
  ``COPILOT_CUSTOM_INSTRUCTIONS_DIRS``. Whether ``*.instructions.md``
  files found here are still ``applyTo``-gated is UNVERIFIED — the
  same gating is applied as for repo-modular (fail-closed) and the
  question is recorded in TASK_RESULT.md.

``@`` references: supported in ``.github/copilot-instructions.md``,
``AGENTS.md`` and ``CLAUDE.md`` (not in ``GEMINI.md`` or
``*.instructions.md``), but the fetched doc does NOT state the base
directory for a relative ``@`` path — so T003 lists no resolved
import candidates for Copilot at all (T005 must resolve the base
from a primary source first). Organization instructions are not
supported in local sessions (out of scope); a file disabled via
``/instructions`` is session state and NOT_OBSERVED.
"""

from __future__ import annotations

import os

from instructionroot.profiles._common import (
    NotApplicable,
    Precedence,
    ResolveContext,
    SourceCandidate,
    any_glob_matches,
    chain_dirs,
    list_dir_files,
    make_candidate,
    parse_applyto,
    read_text,
    relative_posix,
)

__all__ = [
    "PROFILE_ID",
    "PROFILE_VERSION",
    "RULES_HASH",
    "SOURCE_URL",
    "discover",
]

PROFILE_ID = "copilot-cli"
PROFILE_VERSION = "copilot-cli-2026-11"
SOURCE_URL = (
    "https://docs.github.com/en/copilot/how-tos/copilot-cli/"
    "customize-copilot/add-custom-instructions"
)
RULES_HASH = (
    "sha256:76a5f6c8fbd7fc4ff910bf5f471ecb9291ab2a575d871f93338fb1b298c73d0e"
)

_COMBINE = Precedence(
    kind="COMBINE_UNORDERED",
    detail="Combined with applicable instructions; no general precedence "
    "order between files.",
)

# Per-rule contract details (FIX-C06): copilot-cli.user and
# copilot-cli.repo-wide each have their own detail text in
# profile_contract.json; every other copilot rule uses _COMBINE.
_P_COPILOT_USER = Precedence(
    kind="COMBINE_UNORDERED",
    detail="Combined with applicable repository instructions; no general "
    "precedence order between files.",
)
_P_COPILOT_REPO_WIDE = Precedence(
    kind="COMBINE_UNORDERED",
    detail="Combined with applicable user and repository instructions; no "
    "general precedence order between files.",
)


def _standard_dirs(ctx: ResolveContext, *, include_intermediate: bool) -> list[str]:
    """Standard locations for repo-level Copilot instructions.

    Repo root, CWD, intermediate directories between them (unless
    ``include_intermediate`` is False — repo-modular excludes them),
    plus directories nested in the path of each working file below
    the CWD. Deterministic order: root to CWD, then working-file
    directories shallowest first. Without a repo root (non-git),
    the CWD stands in for the repo root.
    """
    chain = chain_dirs(ctx.repo_root, ctx.cwd)
    if not include_intermediate:
        keep = {chain[0], chain[-1]} if chain else set()
        base = [d for d in chain if d in keep]
    else:
        base = list(chain)
    seen = set(base)
    extra: list[tuple[int, str]] = []
    for wf in ctx.working_files:
        rel = relative_posix(wf, ctx.cwd)
        if rel is None or "/" not in rel:
            continue
        cur = ctx.cwd
        for i, part in enumerate(rel.split("/")[:-1], start=1):
            cur = cur + "/" + part
            if cur not in seen:
                seen.add(cur)
                extra.append((i, cur))
    extra.sort()
    return base + [d for _, d in extra]


def _applyto_gate(
    ctx: ResolveContext,
    lex_path: str,
    *,
    rule: str,
    base_for_globs: str,
) -> bool:
    """Check the ``applyTo`` gate for a modular instructions file.

    Returns True only when an ``applyTo`` frontmatter exists and
    matches at least one working file (glob relative to
    *base_for_globs*). Every other outcome excludes the file and
    records why: no working file at all, no ``applyTo`` (UNVERIFIED
    behaviour — never guessed), or no match (SPEC-04: the file is
    simply absent from sources).
    """
    if not ctx.working_files:
        ctx.not_applicable.append(NotApplicable(
            raw_path=lex_path, canonical_path=None,
            discovery_rule=rule, reason="APPLYTO_NO_WORKING_FILE",
            detail="applyTo can only match a file Copilot is working with",
        ))
        return False
    text = read_text(lex_path)
    patterns = parse_applyto(text) if text is not None else None
    if patterns is None:
        ctx.not_applicable.append(NotApplicable(
            raw_path=lex_path, canonical_path=None,
            discovery_rule=rule, reason="APPLYTO_ABSENT_UNVERIFIED",
            detail="applyTo absent; behaviour for Copilot CLI is UNVERIFIED",
        ))
        return False
    for wf in ctx.working_files:
        rel = relative_posix(wf, base_for_globs)
        if rel is not None and any_glob_matches(patterns, rel):
            return True
    ctx.not_applicable.append(NotApplicable(
        raw_path=lex_path, canonical_path=None,
        discovery_rule=rule, reason="APPLYTO_NO_MATCH",
        detail="applyTo does not match any file Copilot is working with",
    ))
    return False


def _modular_files(
    ctx: ResolveContext,
    instructions_dir: str,
    *,
    rule: str,
    base_for_globs: str,
) -> list[SourceCandidate]:
    """``**/*.instructions.md`` under *instructions_dir*, applyTo-gated."""
    out: list[SourceCandidate] = []
    for lex in list_dir_files(
        instructions_dir, recursive=True, filename_glob="*.instructions.md"
    ):
        if not _applyto_gate(ctx, lex, rule=rule, base_for_globs=base_for_globs):
            continue
        cand = make_candidate(
            ctx, lex, scope="user" if rule == "copilot-cli.user-modular" else "project",
            phase="on_demand", discovery_rule=rule, precedence=_COMBINE,
        )
        if cand is not None:
            out.append(cand)
    return out


def discover(ctx: ResolveContext) -> list[SourceCandidate]:
    """Discover Copilot CLI instruction sources for ``ctx``.

    All sources carry ``COMBINE_UNORDERED`` precedence. Emission
    order is fixed enumeration order (see module docstring), not a
    precedence claim.
    """
    out: list[SourceCandidate] = []
    copilot_home = ctx.copilot_home or os.path.join(ctx.home, ".copilot")
    repo_root = ctx.repo_root or ctx.cwd  # standard-location base

    # User-level.
    user = make_candidate(
        ctx, copilot_home + "/copilot-instructions.md",
        scope="user", phase="startup",
        discovery_rule="copilot-cli.user", precedence=_P_COPILOT_USER,
    )
    if user is not None:
        out.append(user)
    out.extend(_modular_files(
        ctx, copilot_home + "/instructions",
        rule="copilot-cli.user-modular", base_for_globs=ctx.cwd,
    ))

    # Repo-wide: .github/copilot-instructions.md (all standard dirs).
    for directory in _standard_dirs(ctx, include_intermediate=True):
        cand = make_candidate(
            ctx, directory + "/.github/copilot-instructions.md",
            scope="project", phase="startup",
            discovery_rule="copilot-cli.repo-wide", precedence=_P_COPILOT_REPO_WIDE,
        )
        if cand is not None:
            out.append(cand)

    # Repo-modular: .github/instructions/**/*.instructions.md,
    # standard dirs EXCEPT intermediate directories.
    for directory in _standard_dirs(ctx, include_intermediate=False):
        out.extend(_modular_files(
            ctx, directory + "/.github/instructions",
            rule="copilot-cli.repo-modular", base_for_globs=repo_root,
        ))

    # Agents / Claude / Gemini in all standard locations.
    for directory in _standard_dirs(ctx, include_intermediate=True):
        for name, rule in (
            ("AGENTS.md", "copilot-cli.agents"),
            ("CLAUDE.md", "copilot-cli.claude"),
            (".claude/CLAUDE.md", "copilot-cli.claude"),
            ("GEMINI.md", "copilot-cli.gemini"),
        ):
            cand = make_candidate(
                ctx, directory + "/" + name,
                scope="project", phase="startup",
                discovery_rule=rule, precedence=_COMBINE,
            )
            if cand is not None:
                out.append(cand)

    # Custom instruction directories (env var or explicit override).
    custom_dirs = ctx.custom_dirs
    if custom_dirs is None:
        env = os.environ.get("COPILOT_CUSTOM_INSTRUCTIONS_DIRS", "")
        custom_dirs = tuple(
            d for d in (p.strip() for p in env.split(",")) if d
        )
    for directory in custom_dirs:
        from instructionroot.paths import lexical_canonical

        try:
            dir_canon = lexical_canonical(directory, cwd=ctx.cwd, home=ctx.home)
        except (ValueError, TypeError):
            continue
        cand = make_candidate(
            ctx, dir_canon + "/AGENTS.md",
            scope="project", phase="startup",
            discovery_rule="copilot-cli.custom-dirs", precedence=_COMBINE,
        )
        if cand is not None:
            out.append(cand)
        for lex in list_dir_files(
            dir_canon, recursive=False, filename_glob="*.instructions.md"
        ):
            if not _applyto_gate(
                ctx, lex, rule="copilot-cli.custom-dirs",
                base_for_globs=repo_root,
            ):
                continue
            cand = make_candidate(
                ctx, lex, scope="project", phase="startup",
                discovery_rule="copilot-cli.custom-dirs", precedence=_COMBINE,
            )
            if cand is not None:
                out.append(cand)

    return out
