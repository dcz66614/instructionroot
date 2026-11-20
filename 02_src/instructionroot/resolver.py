"""Unified harness resolution entry point (T003).

``discover(snapshot, cwd, policy, harness=...)`` returns the
deterministic effective instruction chain — a list of
:class:`instructionroot.profiles._common.SourceCandidate` — for
one harness profile, in that profile's discovery order.

Rules honoured here (all from the frozen contract):

* Unknown precedence is never guessed: any source whose profile
  defines no order carries ``precedence.kind == UNSPECIFIED``
  (the profiles set this; this module never re-orders).
* De-duplication (S10): the same canonical file appears once,
  under the first rule that discovered it; later rules are
  recorded in ``also_discovered_by``. The resolved path is *not*
  the dedup key — two different lexical paths resolving to one
  file are the same source (Q1: canonical is the lexical path,
  so dedup is by canonical path; a symlink alias and its target
  spelling are different canonical paths and are *not* merged —
  see TASK_RESULT.md).
* Policy never changes *which* files are discovered, except for
  the two discovery-affecting fields in ``policy_schema.json``:
  ``allow_nested_on_demand=false`` excludes on-demand sources
  and ``allow_additional_directories=false`` (the default)
  excludes Claude additional-directory sources. All other policy
  fields only change the verdict (T008's job), never discovery.
* Unknown harness id or a profile version that does not match
  the frozen version raises :class:`UnsupportedProfileError`
  (receipt verdict ``UNSUPPORTED_PROFILE``); a missing CWD or an
  invalid policy raises :class:`ValueError` (``INPUT_ERROR``).
  Nothing here fails open to a PASS.

``discover_with_report`` additionally returns the
``considered_but_not_applicable`` list (SPEC-04): paths the
profile considered but excluded (e.g. a Copilot modular file
whose ``applyTo`` matched nothing).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from instructionroot.paths import canonicalize
from instructionroot.profiles import _common as _common
from instructionroot.profiles import claude as _claude
from instructionroot.profiles import codex as _codex
from instructionroot.profiles import copilot as _copilot
from instructionroot.snapshot import FilesystemSnapshot

__all__ = [
    "DEFAULT_POLICY",
    "DiscoveryReport",
    "NotApplicable",
    "Precedence",
    "SourceCandidate",
    "UnsupportedProfileError",
    "discover",
    "discover_with_report",
]

# Re-exported for callers that only import this module.
SourceCandidate = _common.SourceCandidate
Precedence = _common.Precedence
NotApplicable = _common.NotApplicable

#: Frozen default policy (policy_schema.json ``default_policy``).
#: A unit test asserts these values match the contract JSON, so a
#: contract change fails loudly instead of drifting silently.
DEFAULT_POLICY: dict[str, bool] = {
    "allow_user_scope": True,
    "allow_repo_tracked": True,
    "allow_managed_scope": True,
    "allow_nested_on_demand": True,
    "block_repo_untracked": False,
    "block_repo_modified": False,
    "block_outside_repo": True,
    "block_symlink_escape": True,
    "block_import_escape": True,
    "block_missing_reference": True,
    "warn_on_unspecified_precedence": True,
    "treat_warn_as_block": False,
    "allow_additional_directories": False,
}

_PROFILES = {
    "codex": _codex,
    "claude-code": _claude,
    "copilot-cli": _copilot,
}


class UnsupportedProfileError(ValueError):
    """Unknown harness id or non-frozen profile version."""


@dataclass(frozen=True)
class DiscoveryReport:
    """Full discovery result: sources + considered-but-not-applicable."""

    sources: tuple[SourceCandidate, ...]
    not_applicable: tuple[NotApplicable, ...]
    harness: str
    profile_version: str

    def to_dict(self) -> dict:
        return {
            "harness": self.harness,
            "profile_version": self.profile_version,
            "sources": [s.to_dict() for s in self.sources],
            "considered_but_not_applicable": [
                n.to_dict() for n in self.not_applicable
            ],
        }


def _validate_policy(policy) -> dict:
    """Merge a caller policy over the defaults, rejecting bad input."""
    if policy is None:
        return dict(DEFAULT_POLICY)
    if not isinstance(policy, dict):
        raise ValueError("policy must be a dict or None")
    unknown = sorted(set(policy) - set(DEFAULT_POLICY))
    if unknown:
        raise ValueError("unknown policy field(s): %s" % ", ".join(unknown))
    merged = dict(DEFAULT_POLICY)
    for key, value in policy.items():
        if not isinstance(value, bool):
            raise ValueError("policy field %r must be a bool" % key)
        merged[key] = value
    return merged


def _split_env_dirs(value: str | None, *, cwd: str, home: str) -> tuple[str, ...]:
    """Split a comma-separated env dir list into canonical absolutes."""
    if not value:
        return ()
    out: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            from instructionroot.paths import lexical_canonical

            out.append(lexical_canonical(part, cwd=cwd, home=home))
        except (ValueError, TypeError):
            continue
    return tuple(out)


def _canonicalise_list(paths, *, cwd: str, home: str) -> tuple[str, ...]:
    out: list[str] = []
    for raw in paths or ():
        text = raw if isinstance(raw, str) else os.fspath(raw)
        out.append(canonicalize(text, cwd=cwd, home=home).resolved_path
                   or canonicalize(text, cwd=cwd, home=home).canonical_path)
    return tuple(out)


def discover_with_report(
    snapshot,
    cwd=None,
    policy=None,
    harness=None,
    profile_version=None,
    *,
    working_files=(),
    target_files=(),
    additional_dirs=None,
    custom_dirs=None,
    copilot_home=None,
    managed_path=None,
    ancestor_stop=None,
) -> DiscoveryReport:
    """Discover sources for one harness; see :func:`discover`.

    ``harness`` may also be passed as ``profile=...`` via
    ``**kwargs`` in :func:`discover`. ``working_files`` /
    ``target_files`` (aliases) are the files the harness is
    working with — the on-demand triggers. ``additional_dirs`` /
    ``custom_dirs`` / ``copilot_home`` fall back to their
    environment variables when not supplied
    (``CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD``,
    ``COPILOT_CUSTOM_INSTRUCTIONS_DIRS``, ``COPILOT_HOME``).
    ``ancestor_stop`` bounds Claude's upward ancestor walk at a
    directory (the root of the observed filesystem; fixtures pass
    the case directory so the walk cannot escape the fixture).
    """
    if harness is None:
        raise UnsupportedProfileError(
            "no harness given: expected one of codex, claude-code, copilot-cli"
        )
    module = _PROFILES.get(harness)
    if module is None:
        raise UnsupportedProfileError("unknown harness: %r" % harness)
    if profile_version is not None and profile_version != module.PROFILE_VERSION:
        raise UnsupportedProfileError(
            "profile version %r does not match frozen %r for harness %r"
            % (profile_version, module.PROFILE_VERSION, harness)
        )
    if not isinstance(snapshot, FilesystemSnapshot):
        raise TypeError("snapshot must be a FilesystemSnapshot")
    merged_policy = _validate_policy(policy)

    cwd_text = snapshot.cwd if cwd is None else os.fspath(cwd)
    try:
        cwd_canon = canonicalize(cwd_text)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid cwd: %s" % exc) from exc
    if cwd_canon.resolved_path is None or not cwd_canon.exists or not cwd_canon.is_dir:
        raise ValueError("cwd does not exist or is not a directory: %s" % cwd_text)
    cwd_resolved = cwd_canon.resolved_path
    home = snapshot.home
    repo_root = snapshot.repo_root

    triggers = tuple(working_files) + tuple(target_files)
    working = _canonicalise_list(triggers, cwd=cwd_resolved, home=home)

    if additional_dirs is None:
        additional = _split_env_dirs(
            os.environ.get("CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD"),
            cwd=cwd_resolved, home=home,
        )
    else:
        additional = _canonicalise_list(additional_dirs, cwd=cwd_resolved, home=home)
    if custom_dirs is None:
        custom = _split_env_dirs(
            os.environ.get("COPILOT_CUSTOM_INSTRUCTIONS_DIRS"),
            cwd=cwd_resolved, home=home,
        )
    else:
        custom = _canonicalise_list(custom_dirs, cwd=cwd_resolved, home=home)
    if copilot_home is None:
        env_home = os.environ.get("COPILOT_HOME")
        copilot_home_resolved = None
        if env_home:
            try:
                from instructionroot.paths import lexical_canonical

                copilot_home_resolved = lexical_canonical(
                    env_home, cwd=cwd_resolved, home=home
                )
            except (ValueError, TypeError):
                copilot_home_resolved = None
    else:
        copilot_home_resolved = canonicalize(
            os.fspath(copilot_home), cwd=cwd_resolved, home=home
        ).resolved_path or canonicalize(
            os.fspath(copilot_home), cwd=cwd_resolved, home=home
        ).canonical_path

    ctx = _common.ResolveContext(
        snapshot=snapshot,
        cwd=cwd_resolved,
        home=home,
        repo_root=repo_root,
        policy=merged_policy,
        working_files=working,
        additional_dirs=additional,
        custom_dirs=custom,
        copilot_home=copilot_home_resolved,
        managed_path=managed_path,
        ancestor_stop=(
            canonicalize(os.fspath(ancestor_stop), cwd=cwd_resolved, home=home
                         ).resolved_path
            if ancestor_stop is not None else None
        ),
    )
    found = module.discover(ctx)

    # S10 de-duplication: same canonical file appears once, under
    # the first rule that discovered it; later rules are recorded.
    by_canonical: dict[str, SourceCandidate] = {}
    order: list[str] = []
    for cand in found:
        existing = by_canonical.get(cand.canonical_path)
        if existing is None:
            by_canonical[cand.canonical_path] = cand
            order.append(cand.canonical_path)
        else:
            merged_rules = tuple(
                dict.fromkeys(
                    existing.also_discovered_by + (cand.discovery_rule,)
                )
            )
            by_canonical[cand.canonical_path] = _replace_also(existing, merged_rules)
    sources = tuple(by_canonical[key] for key in order)
    return DiscoveryReport(
        sources=sources,
        not_applicable=tuple(ctx.not_applicable),
        harness=harness,
        profile_version=module.PROFILE_VERSION,
    )


def _replace_also(cand: SourceCandidate, rules: tuple[str, ...]) -> SourceCandidate:
    """Return *cand* with ``also_discovered_by`` replaced by *rules*."""
    from dataclasses import replace

    return replace(cand, also_discovered_by=rules)


def discover(
    snapshot,
    cwd=None,
    policy=None,
    harness=None,
    profile_version=None,
    **kwargs,
) -> list[SourceCandidate]:
    """Discover the effective instruction chain for one harness.

    ``discover(snapshot, cwd, policy, harness="codex")`` — the
    ``harness`` keyword (or ``profile=`` alias) selects the
    profile; ``cwd`` defaults to the snapshot cwd and ``policy``
    defaults to the frozen default policy. Returns sources in
    profile discovery order; unknown precedence is never re-sorted
    (see module docstring). Raises :class:`UnsupportedProfileError`
    for an unknown harness/version and :class:`ValueError` for a
    bad cwd or policy.
    """
    if harness is None:
        harness = kwargs.pop("profile", None)
    return list(discover_with_report(
        snapshot, cwd, policy, harness, profile_version, **kwargs
    ).sources)
