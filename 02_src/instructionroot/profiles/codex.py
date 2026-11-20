"""Codex harness profile (T003).

Implements the frozen contract (``00_contract/profile_contract.json``,
profile ``codex``, version ``codex-2026-11``):

* ``codex.user`` (VERIFIED, ORDERED, startup): ``~/.codex/AGENTS.md``,
  first in the chain.
* ``codex.repo-chain`` (VERIFIED, ORDERED, startup): one ``AGENTS.md``
  per directory from the repo root down to the CWD inclusive,
  root-to-leaf; later (deeper) directories override earlier ones.
* ``codex.override-fallback`` (UNVERIFIED, UNSPECIFIED, startup):
  ``<dir>/AGENTS.override.md`` in the same directories. Only the
  name is attested; whether it replaces or supplements ``AGENTS.md``
  in the same directory, and which directory's file wins, are
  unspecified — so the file is *listed* as a candidate with
  ``precedence.kind == UNSPECIFIED`` and no override semantics are
  implemented. The list position (directly after its directory's
  ``AGENTS.md``) is discovery enumeration order, not a precedence
  claim.

Not implemented (contract says not to until a primary source
defines them): any ``@``-import mechanism for Codex, any size cap
(the doc states a cap exists but gives no value), and any repo-root
determination other than the snapshot's ``repo_root`` (a CWD
outside a git repository has no defined repo root, so the chain is
just the CWD — see ``_common.chain_dirs``).
"""

from __future__ import annotations

from instructionroot.profiles._common import (
    Precedence,
    ResolveContext,
    SourceCandidate,
    chain_dirs,
    make_candidate,
)

__all__ = [
    "PROFILE_ID",
    "PROFILE_VERSION",
    "RULES_HASH",
    "SOURCE_URL",
    "discover",
]

PROFILE_ID = "codex"
PROFILE_VERSION = "codex-2026-11"
SOURCE_URL = (
    "https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide"
)
RULES_HASH = (
    "sha256:a0a03c1cdd77f8d9110ccbc77dae937e30e288a2609e6b04b60d26d15af5dc23"
)

_ORDERED_USER = Precedence(
    kind="ORDERED",
    detail="First in the chain: global instructions are injected before "
    "repo instructions.",
)
_ORDERED_CHAIN = Precedence(
    kind="ORDERED",
    detail="Root-to-leaf order: global first, then repo root, then each "
    "deeper directory; later (deeper) directories override earlier ones.",
)
_UNSPECIFIED_OVERRIDE = Precedence(
    kind="UNSPECIFIED",
    detail="Not defined in the fetched source: whether AGENTS.override.md "
    "replaces or supplements AGENTS.md in the same directory, and which "
    "directory's file wins, are unspecified.",
)


def discover(ctx: ResolveContext) -> list[SourceCandidate]:
    """Discover Codex instruction sources for ``ctx``.

    Order: user file first, then the repo-root-to-CWD chain, each
    directory contributing ``AGENTS.md`` (ORDERED) followed by
    ``AGENTS.override.md`` (UNSPECIFIED) when present. Only files
    that exist on disk become candidates.
    """
    out: list[SourceCandidate] = []

    user = make_candidate(
        ctx,
        "~/.codex/AGENTS.md",
        scope="user",
        phase="startup",
        discovery_rule="codex.user",
        precedence=_ORDERED_USER,
    )
    if user is not None:
        out.append(user)

    for directory in chain_dirs(ctx.repo_root, ctx.cwd):
        agents = make_candidate(
            ctx,
            directory + "/AGENTS.md",
            scope="project",
            phase="startup",
            discovery_rule="codex.repo-chain",
            precedence=_ORDERED_CHAIN,
        )
        if agents is not None:
            out.append(agents)
        override = make_candidate(
            ctx,
            directory + "/AGENTS.override.md",
            scope="project",
            phase="startup",
            discovery_rule="codex.override-fallback",
            precedence=_UNSPECIFIED_OVERRIDE,
        )
        if override is not None:
            out.append(override)

    return out
