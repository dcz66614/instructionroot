"""Trust classifier for P028 InstructionRoot Resolve (T004).

Implements PROJECT_BOOK.md §13.4 ("Trust Classification") and §8.5
against the frozen contract (``00_contract/receipt_schema.json``
``trust_enum`` / ``trust_priority``; ``00_contract/policy_schema.json``
defaults; ``00_contract/profile_contract.json`` known conflicts
SPEC-02 / SPEC-03).

Priority order (§13.4, highest first):

.. code-block:: text

    IMPORT_ESCAPE
    SYMLINK_ESCAPE
    MISSING
    OUTSIDE_REPO
    GIT_UNTRACKED
    GIT_MODIFIED
    GIT_TRACKED
    USER_SCOPE

The first condition that applies wins; the classifier never blends
two trust values and never invents a precedence the harness did not
define. Containment is always judged on the **resolved** path (after
symlink resolution); a lexical path inside the repository whose
resolved target sits outside it has escaped.

Inputs (see :func:`classify_trust`):

* ``resolved_path`` — canonical path after symlink resolution
  (``None`` when resolution failed, e.g. a symlink loop);
* ``repo_root`` / ``home`` — the approved roots (repository top
  level, user home); either may be ``None``;
* ``git_state`` — a :class:`instructionroot.git.GitState` (or a
  dict with its fields), or ``None`` when no Git state was observed;
* ``policy`` — accepted for interface completeness (verdict
  derivation is a later task's job). Policy **never changes the
  trust value**: per ``policy_schema.json`` it only changes the
  verdict for a discovered file (e.g. SPEC-02
  ``block_repo_untracked=false`` keeps an untracked in-repo source
  at WARN rather than BLOCK, while its trust stays GIT_UNTRACKED).
  Unknown policy keys are ignored; a non-dict policy is a
  ``TypeError``.

Reason codes (IMPLEMENTATION_PLAN.md §9.4) and the trust value each
one yields:

.. code-block:: text

    R001 WITHIN_REPO_TRACKED        -> GIT_TRACKED
    R002 WITHIN_REPO_MODIFIED       -> GIT_MODIFIED
    R003 WITHIN_REPO_UNTRACKED      -> GIT_UNTRACKED
    R004 USER_SCOPE                 -> USER_SCOPE
    R005 OUTSIDE_REPO               -> OUTSIDE_REPO
    R006 SYMLINK_ESCAPE             -> SYMLINK_ESCAPE
    R007 IMPORT_ESCAPE              -> IMPORT_ESCAPE
    R008 MISSING                    -> MISSING
    R009 NOT_OBSERVED               -> NOT_OBSERVED
    R010 UNSPECIFIED_PRECEDENCE     -> (no trust of its own; see below)

R009 / R010 need care, because the contract defines them as reason
codes without a matching trust priority position (SPEC-03: the §13.4
order omits NOT_OBSERVED because it marks unobserved state, not a
source classification):

* **R009 NOT_OBSERVED** is returned when the classifier cannot
  observe the fact it would need: the resolved path is unavailable
  (symlink loop / unresolvable), or the path is inside a repository
  but no Git state was supplied, so tracked/modified cannot be
  known. The trust value is NOT_OBSERVED. Downstream verdict code
  must treat NOT_OBSERVED as fail-closed (never a silent PASS);
  that verdict rule belongs to a later task, not to this classifier.
* **R010 UNSPECIFIED_PRECEDENCE** is returned when the harness
  defines no precedence for the source (``precedence_kind`` is
  ``"UNSPECIFIED"``) and no more specific reason (R002/R003/R005–
  R008) applies: the trust value stays the provenance-derived one
  (GIT_TRACKED or USER_SCOPE) and only the reason code becomes R010,
  so the receipt keeps a valid trust enum value while still
  recording that the order was undefined. The classifier never
  invents an order for such a source.

Two further mappings are forced by the frozen enum, which has no
value for them; both are recorded as contract issues in
``review/tasks/P028-T004/TASK_RESULT.md`` and no new enum value is
invented here:

* **Managed scope** (Claude Code ``/etc/claude-code/CLAUDE.md`` and
  equivalents, ``scope="managed"``): outside every repository and
  outside the home, so a purely mechanical containment check would
  call it OUTSIDE_REPO — yet the default policy explicitly permits
  managed scope (``allow_managed_scope=true``). It is therefore
  classified USER_SCOPE / R004, the only approved-non-repo trust
  value, keyed off the ``scope`` argument. The verdict layer must
  still apply ``allow_managed_scope`` separately.
* **Import escape** (``is_import_escape=True``) is an edge-level
  fact supplied by the import-graph task (T005); this classifier
  only honours the flag and applies the §13.4 priority, it does not
  parse imports itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from instructionroot.git import GitState
from instructionroot.paths import is_within_root

__all__ = [
    "REASON_CODES",
    "REASON_TO_TRUST",
    "TRUST_ENUM",
    "TRUST_PRIORITY",
    "TrustResult",
    "classify_trust",
    "trust_priority_index",
]

#: Trust priority order, PROJECT_BOOK.md §13.4 / receipt_schema.json
#: ``trust_priority``. NOT_OBSERVED has no position here (SPEC-03).
TRUST_PRIORITY: tuple[str, ...] = (
    "IMPORT_ESCAPE",
    "SYMLINK_ESCAPE",
    "MISSING",
    "OUTSIDE_REPO",
    "GIT_UNTRACKED",
    "GIT_MODIFIED",
    "GIT_TRACKED",
    "USER_SCOPE",
)

#: Full trust enum from the frozen receipt schema (priority list plus
#: NOT_OBSERVED, which has no priority position).
TRUST_ENUM: tuple[str, ...] = TRUST_PRIORITY + ("NOT_OBSERVED",)

#: Reason codes, IMPLEMENTATION_PLAN.md §9.4.
REASON_CODES: dict[str, str] = {
    "R001": "WITHIN_REPO_TRACKED",
    "R002": "WITHIN_REPO_MODIFIED",
    "R003": "WITHIN_REPO_UNTRACKED",
    "R004": "USER_SCOPE",
    "R005": "OUTSIDE_REPO",
    "R006": "SYMLINK_ESCAPE",
    "R007": "IMPORT_ESCAPE",
    "R008": "MISSING",
    "R009": "NOT_OBSERVED",
    "R010": "UNSPECIFIED_PRECEDENCE",
}

#: Trust value each reason code yields. R010 has no trust of its own:
#: it annotates the provenance-derived trust (see module docstring).
REASON_TO_TRUST: dict[str, str | None] = {
    "R001": "GIT_TRACKED",
    "R002": "GIT_MODIFIED",
    "R003": "GIT_UNTRACKED",
    "R004": "USER_SCOPE",
    "R005": "OUTSIDE_REPO",
    "R006": "SYMLINK_ESCAPE",
    "R007": "IMPORT_ESCAPE",
    "R008": "MISSING",
    "R009": "NOT_OBSERVED",
    "R010": None,
}


def trust_priority_index(trust: str) -> int | None:
    """Return the §13.4 priority index of *trust* (0 = highest).

    ``None`` for NOT_OBSERVED (no priority position, SPEC-03) and
    for any value outside the trust enum.
    """
    try:
        return TRUST_PRIORITY.index(trust)
    except ValueError:
        return None


@dataclass(frozen=True)
class TrustResult:
    """The outcome of :func:`classify_trust`.

    * ``trust`` — one of the frozen trust enum values.
    * ``reason_code`` — one of R001–R010 (see :data:`REASON_CODES`).
    * ``detail`` — a short human-readable statement of which fact
      decided the classification (diagnostic only).
    """

    trust: str
    reason_code: str
    detail: str = ""

    def to_dict(self) -> dict:
        """Deterministic dict (fixed keys; JSON-serialisable)."""
        return {
            "trust": self.trust,
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


def _coerce_git_state(git_state) -> GitState | None:
    """Accept a GitState, a dict with its fields, or None."""
    if git_state is None:
        return None
    if isinstance(git_state, GitState):
        return git_state
    if isinstance(git_state, dict):
        return GitState(
            repo=git_state.get("repo"),
            tracked=bool(git_state.get("tracked", False)),
            modified=bool(git_state.get("modified", False)),
            head_commit=git_state.get("head_commit"),
            is_git_repo=bool(git_state.get("is_git_repo", False)),
            error=git_state.get("error"),
        )
    raise TypeError(
        "git_state must be GitState, dict or None, not %s"
        % type(git_state).__name__
    )


def _norm(path) -> str:
    """Normalise a caller-supplied path string for comparison."""
    text = os.fspath(path)
    if isinstance(text, bytes):
        raise TypeError("path must be str, not bytes")
    if not isinstance(text, str) or text == "" or "\x00" in text:
        raise ValueError("path must be a non-empty string")
    return os.path.normpath(text)


def classify_trust(
    resolved_path,
    *,
    repo_root=None,
    home=None,
    git_state=None,
    canonical_path=None,
    is_symlink: bool = False,
    is_symlink_escape: bool | None = None,
    is_import_escape: bool = False,
    exists: bool | None = None,
    precedence_kind: str | None = None,
    scope: str | None = None,
    policy=None,
) -> TrustResult:
    """Classify one source path into (trust, reason_code).

    Arguments:

    * ``resolved_path`` — canonical path after symlink resolution;
      ``None`` when resolution failed (loop / unresolvable), which
      yields NOT_OBSERVED / R009.
    * ``repo_root`` / ``home`` — approved roots (absolute paths, or
      ``None`` when there is no repository / no home root to judge
      against). A repository under the home still counts as a
      repository first: the §13.4 order puts every GIT_* value
      above USER_SCOPE.
    * ``git_state`` — GitState / dict / None (see module docstring).
    * ``canonical_path`` — lexical path before symlink resolution;
      when it differs from ``resolved_path`` (or ``is_symlink`` is
      True) the path was reached through a symlink. Together with
      the roots this derives a symlink escape when
      ``is_symlink_escape`` is not given explicitly.
    * ``is_symlink_escape`` — explicit override: True forces
      SYMLINK_ESCAPE (subject only to the higher IMPORT_ESCAPE);
      False suppresses the derived escape. ``None`` (default)
      derives it: the canonical path lies within an approved root
      while the resolved path lies outside every approved root.
    * ``is_import_escape`` — True when an import/reference edge
      reaching this source escapes the approved roots (edge-level
      fact, supplied by the import-graph task).
    * ``exists`` — whether the resolved target exists; ``None``
      (default) checks the filesystem. A broken symlink therefore
      counts as missing unless an escape outranks it.
    * ``precedence_kind`` — the harness precedence kind for this
      source; ``"UNSPECIFIED"`` yields reason R010 when no more
      specific reason applies (trust unchanged).
    * ``scope`` — the harness scope (``"managed"`` maps to
      USER_SCOPE / R004; see module docstring — contract gap, no
      MANAGED trust value exists). Other scopes do not override
      provenance: a ``"user"``-scope file inside a repository is
      still classified by its Git state.
    * ``policy`` — a policy dict (or ``None`` for defaults). Accepted
      and validated (must be a dict) but never changes the trust
      value; policy only changes the verdict, which is a later
      task's job.
    """
    if policy is not None and not isinstance(policy, dict):
        raise TypeError("policy must be a dict or None, not %s"
                        % type(policy).__name__)
    state = _coerce_git_state(git_state)

    if resolved_path is None:
        return TrustResult(
            trust="NOT_OBSERVED",
            reason_code="R009",
            detail="resolved path is unavailable (symlink loop or "
                   "unresolvable); provenance cannot be observed",
        )
    resolved = _norm(resolved_path)
    canonical = _norm(canonical_path) if canonical_path is not None else resolved
    repo = _norm(repo_root) if repo_root is not None else None
    home_root = _norm(home) if home is not None else None

    if exists is None:
        exists = os.path.exists(resolved)

    # -- SYMLINK_ESCAPE derivation (only when not overridden) --------
    if is_symlink_escape is None:
        symlink_seen = bool(is_symlink) or canonical != resolved
        allowed_roots = tuple(r for r in (repo, home_root) if r is not None)
        if symlink_seen and allowed_roots:
            canonical_within = any(
                is_within_root(canonical, root) for root in allowed_roots
            )
            resolved_within = any(
                is_within_root(resolved, root) for root in allowed_roots
            )
            is_symlink_escape = bool(canonical_within and not resolved_within)
        else:
            is_symlink_escape = False

    # -- §13.4 priority order: first matching condition wins --------
    if is_import_escape:
        result = TrustResult(
            trust="IMPORT_ESCAPE",
            reason_code="R007",
            detail="import/reference edge escapes the approved roots",
        )
    elif is_symlink_escape:
        result = TrustResult(
            trust="SYMLINK_ESCAPE",
            reason_code="R006",
            detail="symlink target escapes the approved roots: "
                   "canonical %s resolves to %s" % (canonical, resolved),
        )
    elif not exists:
        result = TrustResult(
            trust="MISSING",
            reason_code="R008",
            detail="resolved path does not exist: %s" % resolved,
        )
    elif repo is not None and is_within_root(resolved, repo):
        if state is None:
            result = TrustResult(
                trust="NOT_OBSERVED",
                reason_code="R009",
                detail="inside repository but no git state was supplied; "
                       "tracked/modified cannot be observed",
            )
        elif not state.tracked:
            result = TrustResult(
                trust="GIT_UNTRACKED",
                reason_code="R003",
                detail="inside repository but not tracked by git",
            )
        elif state.modified:
            result = TrustResult(
                trust="GIT_MODIFIED",
                reason_code="R002",
                detail="tracked by git and modified against HEAD",
            )
        else:
            result = TrustResult(
                trust="GIT_TRACKED",
                reason_code="R001",
                detail="tracked by git and unmodified against HEAD",
            )
    elif scope == "managed":
        result = TrustResult(
            trust="USER_SCOPE",
            reason_code="R004",
            detail="managed-scope source (no MANAGED trust value in "
                   "the frozen enum; classified as approved non-repo "
                   "scope — see contract issue in TASK_RESULT.md)",
        )
    elif home_root is not None and is_within_root(resolved, home_root):
        result = TrustResult(
            trust="USER_SCOPE",
            reason_code="R004",
            detail="inside the user home and outside any repository",
        )
    else:
        result = TrustResult(
            trust="OUTSIDE_REPO",
            reason_code="R005",
            detail="outside the repository and outside the user home",
        )

    # -- R010: unspecified precedence annotates, never overrides -----
    # Only the two "plain" reasons are annotated: a more specific
    # reason (modified / untracked / escape / missing) already says
    # what matters, and the precedence fact stays visible in the
    # receipt's own precedence field either way.
    if precedence_kind == "UNSPECIFIED" and result.reason_code in ("R001", "R004"):
        return TrustResult(
            trust=result.trust,
            reason_code="R010",
            detail=result.detail + "; precedence is UNSPECIFIED by the "
                   "harness profile (no order invented)",
        )
    return result
