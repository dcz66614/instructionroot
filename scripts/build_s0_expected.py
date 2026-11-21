#!/usr/bin/env python3
"""Build the unified S0 expected index: ``01_s0/expected/*.expected.json``.

One file per fixture (60 total: resolver 20 + imports 16 + fs 12 + s0 12),
in the ``fixtures/README.md`` §3 format (superset: edges also carry
``depth``-free receipt fields ``relative_target`` /
``relative_resolved_target`` so the gate can compare them against both
receipts without source-id brittleness).

How each part is authored (NOT generated from production output):

* resolver/imports ``expected_sources`` / ``expected_edges`` /
  ``expected_not_applicable`` / ``also_discovered_by`` are transcribed
  from the frozen stage expected files (T003/T005). The stage files
  assert discovery/edges only; trust and verdict are added here.
* ``trust`` per source and ``expected_verdict`` per receipt case are
  hand-derived in the ``TRUST_VERDICT`` table below from the frozen
  contracts (``trust.py`` §13.4 priority, ``receipt.py``
  ``derive_verdict`` under the default policy, SPEC-02/SPEC-04,
  coordinator rulings C-05/C-06/CQ-1..CQ-8). The reasoning for every
  non-PASS verdict is recorded in the table comments. The generator
  cross-checks the imports-stage ``expected_verdict`` against this
  table and fails loudly on any disagreement.
* fs ``expected_probes`` are hand-transcribed from the T002 fixture
  trees (``01_s0/fixtures/fs/cases/``) and ``windows-paths.json``.
* s0 cases are fully hand-written in ``S0_TABLE`` (fixtures authored
  by T007, expectations derived before first running them).

No ``receipt_hash`` is ever written here: hashes are compared
production-vs-Oracle only (README §3).

Usage (from the P028 work directory):

    .venv/bin/python scripts/build_s0_expected.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
FIXTURES = WORKDIR / "01_s0" / "fixtures"
EXPECTED_DIR = WORKDIR / "01_s0" / "expected"

# ---------------------------------------------------------------------------
# Hand-derived trust + verdict table.
# Key: case_id -> (expected_verdict, [trust per expected source, in order]).
#
# Derivation rules (default policy unless the case sets its own):
#   BLOCK: any source OUTSIDE_REPO / SYMLINK_ESCAPE / IMPORT_ESCAPE /
#     MISSING (block_* all default true), any NOT_OBSERVED (unconditional
#     fail-closed), or any edge allowed=false.
#   WARN:  any GIT_UNTRACKED (block_repo_untracked=false) /
#     GIT_MODIFIED (block_repo_modified=false) / any source whose
#     precedence kind is UNSPECIFIED (warn_on_unspecified_precedence=true).
#   PASS:  none of the above.
# Git states of the resolver/imports corpora: their repos carry no
# nested .git, so git resolves to the enclosing workdir repository and
# every committed fixture file is GIT_TRACKED; home files are
# USER_SCOPE. (Verified by reading the fixture trees, not by running
# production: no .git exists anywhere under resolver/imports.)
# ---------------------------------------------------------------------------
TRUST_VERDICT: dict[str, tuple[str, list[str]]] = {
    # --- resolver (20) ---
    # PASS: clean ORDERED chain, user + tracked repo files.
    "claude-agents-fallback": ("PASS", ["GIT_TRACKED"] * 3),
    "claude-agents-fallback-blocked": ("PASS", ["GIT_TRACKED"]),
    "claude-basic": ("PASS", ["USER_SCOPE", "USER_SCOPE"] + ["GIT_TRACKED"] * 4),
    # BLOCK: the depth-4 chain itself is allowed (S13), but the fixture
    # also contains @missing.md -> a MISSING edge blocks the receipt.
    "claude-import-depth4": ("BLOCK", ["GIT_TRACKED"]),
    # BLOCK: 5th hop is enumerated with DEPTH_EXCEEDED (S14, SPEC-01: max 4).
    "claude-import-depth5": ("BLOCK", ["GIT_TRACKED"]),
    # WARN: nested / agents-nested sources have UNSPECIFIED precedence.
    "claude-nested": ("WARN", ["GIT_TRACKED"] * 4),
    "claude-nested-disabled": ("PASS", ["GIT_TRACKED"]),
    # WARN: the path-scoped rule has UNSPECIFIED precedence.
    "claude-rules-paths": ("WARN", ["GIT_TRACKED"] * 4),
    "codex-basic": ("PASS", ["USER_SCOPE"] + ["GIT_TRACKED"] * 3),
    "codex-empty": ("PASS", []),
    # BLOCK: repo_root is null (S25), so the repo file is OUTSIDE_REPO;
    # the user file stays USER_SCOPE.
    "codex-norepo": ("BLOCK", ["USER_SCOPE", "OUTSIDE_REPO"]),
    # WARN: AGENTS.override.md has UNSPECIFIED precedence (S11).
    "codex-override": ("WARN", ["USER_SCOPE"] + ["GIT_TRACKED"] * 3),
    "codex-user-only": ("PASS", ["USER_SCOPE"]),
    "copilot-applyto-absent": ("PASS", ["GIT_TRACKED"]),
    "copilot-applyto-match": ("PASS", ["USER_SCOPE", "GIT_TRACKED", "GIT_TRACKED"]),
    "copilot-applyto-nomatch": ("PASS", ["GIT_TRACKED"]),
    "copilot-basic": ("PASS", ["USER_SCOPE"] + ["GIT_TRACKED"] * 7),
    # BLOCK: COPILOT_CUSTOM_INSTRUCTIONS_DIRS points outside the repo;
    # the classifier has no custom-dir root, so both files are
    # OUTSIDE_REPO (production and Oracle agree; recorded in S0_GATE.md
    # as known behaviour for T008/coordinator, not an S0 defect).
    "copilot-custom-dirs": ("BLOCK", ["GIT_TRACKED", "OUTSIDE_REPO", "OUTSIDE_REPO"]),
    "copilot-dedup": ("PASS", ["GIT_TRACKED", "GIT_TRACKED"]),
    "copilot-intermediate": ("PASS", ["GIT_TRACKED"] * 4),
    # --- imports (16): verdicts cross-checked against the stage files ---
    "claude-code-span": ("PASS", ["GIT_TRACKED"]),
    "claude-cycle": ("PASS", ["GIT_TRACKED"]),
    "claude-depth4": ("PASS", ["GIT_TRACKED"]),
    "claude-depth5": ("BLOCK", ["GIT_TRACKED"]),
    "claude-escape": ("BLOCK", ["GIT_TRACKED"]),
    "claude-home-import": ("PASS", ["GIT_TRACKED"]),
    "claude-malformed": ("BLOCK", ["GIT_TRACKED"]),
    "claude-missing": ("BLOCK", ["GIT_TRACKED"]),
    "claude-no-import": ("PASS", ["GIT_TRACKED"]),
    "claude-symlink-escape": ("BLOCK", ["GIT_TRACKED"]),
    "codex-no-import": ("PASS", ["GIT_TRACKED"]),
    "copilot-absolute": ("BLOCK", ["GIT_TRACKED"]),
    "copilot-custom-dir": ("BLOCK", ["OUTSIDE_REPO"]),
    "copilot-no-expand": ("PASS", ["GIT_TRACKED"] * 3),
    "copilot-relative": ("PASS", ["GIT_TRACKED", "GIT_TRACKED"]),
    "copilot-tilde-user": ("BLOCK", ["GIT_TRACKED"]),
}

# Forbidden trust values per case (README §3 rule 7: appearing == FAIL).
# Every case forbids NOT_OBSERVED (fail-closed: unobserved state must
# never appear as a source trust). Clean cases additionally forbid any
# escape/outside/missing trust.
FORBIDDEN_CLEAN = ["NOT_OBSERVED", "SYMLINK_ESCAPE", "IMPORT_ESCAPE",
                   "OUTSIDE_REPO", "MISSING"]
FORBIDDEN_ESCAPE_CASES = {
    # These cases EXPECT an escape trust, so only NOT_OBSERVED is forbidden.
    "claude-import-depth4", "claude-import-depth5", "claude-escape",
    "claude-missing", "claude-malformed", "claude-depth5",
    "claude-symlink-escape", "codex-norepo", "copilot-absolute",
    "copilot-custom-dirs", "copilot-custom-dir", "copilot-tilde-user",
    "s0-git-symlink-escape",
}


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _resolver_expected(case_id: str) -> dict:
    """Transcribe a resolver stage file + hand-derived trust/verdict."""
    stage = _load_json(FIXTURES / "resolver" / case_id / (case_id + ".expected.json"))
    verdict, trusts = TRUST_VERDICT[case_id]
    sources = []
    if len(stage["expected_sources"]) != len(trusts):
        raise ValueError("%s: stage sources %d != trust table %d"
                         % (case_id, len(stage["expected_sources"]), len(trusts)))
    for entry, trust in zip(stage["expected_sources"], trusts):
        sources.append({
            "discovery_rule": entry["discovery_rule"],
            "scope": entry["scope"],
            "phase": entry["phase"],
            "precedence_kind": entry["precedence_kind"],
            "relative_path": entry["relative_path"],
            "trust": trust,
            **({"also_discovered_by": entry["also_discovered_by"]}
               if "also_discovered_by" in entry else {}),
        })
    # Import candidates (resolver stage) -> receipt edges. Reason OK in
    # the candidate vocabulary is WITHIN_REPO in the receipt vocabulary
    # (compare_oracle.py documents the same mapping); MISSING /
    # DEPTH_EXCEEDED carry over. A MISSING target has no resolved path.
    edges = []
    for cand in stage.get("expected_import_candidates", []):
        reason = cand["reason"]
        receipt_reason = "WITHIN_REPO" if reason == "OK" else reason
        target = cand["relative_target"]
        edges.append({
            "from_relative_path": cand["from_relative_path"],
            "syntax": cand["syntax"],
            "depth": cand["depth"],
            "relative_target": target,
            "relative_resolved_target": target if cand["allowed"] else (
                None if reason == "MISSING" else target),
            "allowed": cand["allowed"],
            "reason": receipt_reason,
        })
    return {
        "case_id": case_id,
        "kind": "receipt",
        "expected_verdict": verdict,
        "expected_sources": sources,
        "expected_edges": edges,
        "expected_not_applicable": stage.get("expected_not_applicable", []),
        "expected_source_count": len(sources),
        "forbidden_trust": (["NOT_OBSERVED"] if case_id in FORBIDDEN_ESCAPE_CASES
                            else list(FORBIDDEN_CLEAN)),
        "notes": "Unified S0 expected index (T007). Sources/edges transcribed "
                 "from the T003 stage expected file; trust/verdict hand-derived "
                 "from the frozen contracts (see build_s0_expected.py).",
    }


def _imports_expected(case_id: str) -> dict:
    """Transcribe an imports stage file + hand-derived trust/verdict."""
    stage = _load_json(FIXTURES / "imports" / case_id / (case_id + ".expected.json"))
    verdict, trusts = TRUST_VERDICT[case_id]
    if stage["expected_verdict"] != verdict:
        raise ValueError("%s: stage verdict %r != hand-derived %r"
                         % (case_id, stage["expected_verdict"], verdict))
    # Sources are not in the imports stage file; the discovery set is
    # the resolver-stage set for the same shape, recorded here from the
    # fixture tree (one source per case except copilot-no-expand /
    # copilot-relative, verified against the fixture contents).
    sources = _imports_sources(case_id, trusts)
    edges = [{
        "from_relative_path": e["from_relative_path"],
        "syntax": e["syntax"],
        "depth": e["depth"],
        "relative_target": e["relative_target"],
        "relative_resolved_target": e["relative_resolved_target"],
        "allowed": e["allowed"],
        "reason": e["reason"],
    } for e in stage["expected_edges"]]
    return {
        "case_id": case_id,
        "kind": "receipt",
        "expected_verdict": verdict,
        "expected_sources": sources,
        "expected_edges": edges,
        "expected_not_applicable": [],
        "expected_source_count": len(sources),
        "forbidden_trust": (["NOT_OBSERVED"] if case_id in FORBIDDEN_ESCAPE_CASES
                            else list(FORBIDDEN_CLEAN)),
        "notes": "Unified S0 expected index (T007). Edges transcribed from "
                 "the T005 stage expected file; sources/trust/verdict "
                 "hand-derived from the frozen contracts.",
    }


# Discovery sets of the imports fixtures, read off the fixture trees
# (which file is the importing source, which rule discovers it).
_IMPORTS_SOURCES: dict[str, list[dict]] = {
    "claude-code-span": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-cycle": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-depth4": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-depth5": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-escape": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-home-import": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-malformed": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-missing": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-no-import": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "claude-symlink-escape": [("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md")],
    "codex-no-import": [("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md")],
    "copilot-absolute": [("copilot-cli.agents", "project", "startup", "COMBINE_UNORDERED", "repo/AGENTS.md")],
    "copilot-custom-dir": [("copilot-cli.custom-dirs", "project", "startup", "COMBINE_UNORDERED", "extra/AGENTS.md")],
    "copilot-no-expand": [
        ("copilot-cli.repo-modular", "project", "on_demand", "COMBINE_UNORDERED", "repo/.github/instructions/docs.instructions.md"),
        ("copilot-cli.claude", "project", "startup", "COMBINE_UNORDERED", "repo/.claude/CLAUDE.md"),
        ("copilot-cli.gemini", "project", "startup", "COMBINE_UNORDERED", "repo/GEMINI.md"),
    ],
    "copilot-relative": [
        ("copilot-cli.repo-wide", "project", "startup", "COMBINE_UNORDERED", "repo/.github/copilot-instructions.md"),
        ("copilot-cli.agents", "project", "startup", "COMBINE_UNORDERED", "repo/AGENTS.md"),
    ],
    "copilot-tilde-user": [("copilot-cli.repo-wide", "project", "startup", "COMBINE_UNORDERED", "repo/.github/copilot-instructions.md")],
}


def _imports_sources(case_id: str, trusts: list[str]) -> list[dict]:
    specs = _IMPORTS_SOURCES[case_id]
    if len(specs) != len(trusts):
        raise ValueError("%s: source specs %d != trust table %d"
                         % (case_id, len(specs), len(trusts)))
    return [{
        "discovery_rule": rule, "scope": scope, "phase": phase,
        "precedence_kind": prec, "relative_path": rel, "trust": trust,
    } for (rule, scope, phase, prec, rel), trust in zip(specs, trusts)]


# --- s0 cases: fully hand-written (fixture + expectation, T007) -------
def _src(rule, scope, phase, prec, rel, trust):
    return {"discovery_rule": rule, "scope": scope, "phase": phase,
            "precedence_kind": prec, "relative_path": rel, "trust": trust}


def _edge(frm, syntax, target, resolved, allowed, reason, depth=1):
    return {"from_relative_path": frm, "syntax": syntax, "depth": depth,
            "relative_target": target, "relative_resolved_target": resolved,
            "allowed": allowed, "reason": reason}


S0_TABLE: dict[str, dict] = {
    "s0-git-tracked": {
        "kind": "receipt", "expected_verdict": "PASS",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/payments/AGENTS.md", "GIT_TRACKED"),
        ],
        "expected_edges": [],
        "notes": "Real-git counterpart of codex-basic: clean committed chain.",
    },
    "s0-git-modified": {
        "kind": "receipt", "expected_verdict": "WARN",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/payments/AGENTS.md", "GIT_MODIFIED"),
        ],
        "expected_edges": [],
        "notes": "S05: tracked file modified in the worktree -> WARN under the default policy.",
    },
    "s0-git-modified-block": {
        "kind": "receipt", "expected_verdict": "BLOCK",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/payments/AGENTS.md", "GIT_MODIFIED"),
        ],
        "expected_edges": [],
        "notes": "Same tree as s0-git-modified; block_repo_modified=true escalates WARN to BLOCK.",
    },
    "s0-git-untracked-block": {
        "kind": "receipt", "expected_verdict": "BLOCK",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/payments/AGENTS.md", "GIT_UNTRACKED"),
        ],
        "expected_edges": [],
        "notes": "S04 policy variant (SPEC-02): untracked + block_repo_untracked=true -> BLOCK.",
    },
    "s0-git-staged-new": {
        "kind": "receipt", "expected_verdict": "WARN",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/AGENTS.md", "GIT_MODIFIED"),
        ],
        "expected_edges": [],
        "notes": "T004 ruling: a staged-new file is tracked (ls-files matches) AND modified (status non-empty).",
    },
    "s0-git-symlink-inside": {
        "kind": "receipt", "expected_verdict": "PASS",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/AGENTS.md", "GIT_TRACKED"),
        ],
        "expected_edges": [],
        "notes": "S06: symlink to an in-repo tracked target resolves inside the repo -> GIT_TRACKED.",
    },
    "s0-git-symlink-escape": {
        "kind": "receipt", "expected_verdict": "BLOCK",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/AGENTS.md", "SYMLINK_ESCAPE"),
        ],
        "expected_edges": [],
        "notes": "S07: symlink target is outside/Downloads -> SYMLINK_ESCAPE, BLOCK.",
    },
    "s0-downloads-import": {
        "kind": "receipt", "expected_verdict": "BLOCK",
        "expected_sources": [
            _src("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md", "GIT_TRACKED"),
        ],
        "expected_edges": [
            _edge("repo/CLAUDE.md", "@shared/ok.md", "repo/shared/ok.md", "repo/shared/ok.md", True, "WITHIN_REPO"),
            _edge("repo/CLAUDE.md", "@../outside/Downloads/shared-note.md", "outside/Downloads/shared-note.md", "outside/Downloads/shared-note.md", False, "IMPORT_ESCAPE"),
        ],
        "notes": "S09/S19: in-repo import allowed; Downloads import escapes -> BLOCK.",
    },
    "s0-git-missing-import": {
        "kind": "receipt", "expected_verdict": "BLOCK",
        "expected_sources": [
            _src("claude-code.project", "project", "startup", "ORDERED", "repo/CLAUDE.md", "GIT_TRACKED"),
        ],
        "expected_edges": [
            _edge("repo/CLAUDE.md", "@shared/ok.md", "repo/shared/ok.md", "repo/shared/ok.md", True, "WITHIN_REPO"),
            _edge("repo/CLAUDE.md", "@missing.md", None, None, False, "MISSING"),
        ],
        "notes": "S08 with a real git repo: missing import -> MISSING edge -> BLOCK.",
    },
    "s0-git-unicode": {
        "kind": "receipt", "expected_verdict": "PASS",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/中文/AGENTS.md", "GIT_TRACKED"),
        ],
        "expected_edges": [],
        "notes": "S21: unicode directory names pass through byte-for-byte (Q3).",
    },
    "s0-git-rename": {
        "kind": "receipt", "expected_verdict": "WARN",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services-renamed/AGENTS.md", "GIT_UNTRACKED"),
        ],
        "expected_edges": [],
        "notes": "S24: the renamed directory's file is untracked under its new path (ls-files has only the old path) -> WARN, never silently trusted.",
    },
    "s0-case-sensitive": {
        "kind": "receipt", "expected_verdict": "PASS",
        "expected_sources": [
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/AGENTS.md", "GIT_TRACKED"),
            _src("codex.repo-chain", "project", "startup", "ORDERED", "repo/services/payments/AGENTS.md", "GIT_TRACKED"),
        ],
        "expected_edges": [],
        "notes": "S22: lowercase services/agents.md is not discovered on Linux; only the two AGENTS.md files enter the chain.",
    },
}


def _s0_expected(case_id: str) -> dict:
    entry = dict(S0_TABLE[case_id])
    entry["case_id"] = case_id
    entry["expected_not_applicable"] = []
    entry["expected_source_count"] = len(entry["expected_sources"])
    entry["forbidden_trust"] = (
        ["NOT_OBSERVED"] if case_id in FORBIDDEN_ESCAPE_CASES
        else list(FORBIDDEN_CLEAN))
    entry["notes"] = "Unified S0 expected index (T007). " + entry["notes"]
    return entry


# --- fs probes: hand-transcribed from the T002 fixture trees -----------
# Each probe: (raw, canonical, resolved, exists, is_symlink, is_loop,
# is_broken_symlink). "{case}" is the case directory's absolute path.
FS_PROBES: dict[str, list[tuple]] = {
    "basic": [
        ("repo/AGENTS.md", "{case}/repo/AGENTS.md", "{case}/repo/AGENTS.md", True, False, False, False),
        ("repo/services/../AGENTS.md", "{case}/repo/AGENTS.md", "{case}/repo/AGENTS.md", True, False, False, False),
        ("repo//services///payments//AGENTS.md", "{case}/repo/services/payments/AGENTS.md", "{case}/repo/services/payments/AGENTS.md", True, False, False, False),
        ("~/.codex/AGENTS.md", "{case}/home/.codex/AGENTS.md", "{case}/home/.codex/AGENTS.md", True, False, False, False),
        ("repo/nope.md", "{case}/repo/nope.md", "{case}/repo/nope.md", False, False, False, False),
    ],
    "dotdot": [
        ("repo/services/payments/../../AGENTS.md", "{case}/repo/AGENTS.md", "{case}/repo/AGENTS.md", True, False, False, False),
        ("repo/services/payments/../other/keep.txt", "{case}/repo/services/other/keep.txt", "{case}/repo/services/other/keep.txt", True, False, False, False),
    ],
    "symlink-inside": [
        ("repo/link.md", "{case}/repo/link.md", "{case}/repo/services/AGENTS.md", True, True, False, False),
    ],
    "symlink-escape": [
        ("repo/escape.md", "{case}/repo/escape.md", "{case}/outside/Downloads/AGENTS.md", True, True, False, False),
    ],
    "symlink-loop": [
        ("repo/loop-a", "{case}/repo/loop-a", None, False, True, True, False),
        ("repo/self-loop", "{case}/repo/self-loop", None, False, True, True, False),
    ],
    "symlink-broken": [
        ("repo/broken.md", "{case}/repo/broken.md", "{case}/repo/does-not-exist.md", False, True, False, True),
    ],
    "unicode": [
        ("repo/ünïcode-✓/AGENTS-✓.md", "{case}/repo/ünïcode-✓/AGENTS-✓.md", "{case}/repo/ünïcode-✓/AGENTS-✓.md", True, False, False, False),
        ("repo/中文/说明.md", "{case}/repo/中文/说明.md", "{case}/repo/中文/说明.md", True, False, False, False),
    ],
    "missing": [
        ("repo/nope.md", "{case}/repo/nope.md", "{case}/repo/nope.md", False, False, False, False),
    ],
    "separators": [
        ("repo/services/payments/AGENTS.md/", "{case}/repo/services/payments/AGENTS.md", "{case}/repo/services/payments/AGENTS.md", True, False, False, False),
        ("repo//AGENTS.md", "{case}/repo/AGENTS.md", "{case}/repo/AGENTS.md", True, False, False, False),
    ],
    "deep-chain": [
        ("repo/a/b/c/d/e/f/AGENTS.md", "{case}/repo/a/b/c/d/e/f/AGENTS.md", "{case}/repo/a/b/c/d/e/f/AGENTS.md", True, False, False, False),
        ("repo/a/b/../../AGENTS.md", "{case}/repo/AGENTS.md", "{case}/repo/AGENTS.md", False, False, False, False),
    ],
    "dir-symlink": [
        ("repo/linkdir/AGENTS.md", "{case}/repo/linkdir/AGENTS.md", "{case}/repo/services/AGENTS.md", True, True, False, False),
        ("repo/loopdir-a/x", "{case}/repo/loopdir-a/x", None, False, True, True, False),
    ],
    "windows": [
        ("C:\\repo\\services\\..\\AGENTS.md", "C:/repo/AGENTS.md", "/C:/repo/AGENTS.md", False, False, False, False),
        ("C:/repo//services///AGENTS.md", "C:/repo/services/AGENTS.md", "/C:/repo/services/AGENTS.md", False, False, False, False),
        ("\\\\server\\share\\repo\\AGENTS.md", "//server/share/repo/AGENTS.md", "/server/share/repo/AGENTS.md", False, False, False, False),
        ("D:\\Downloads\\AGENTS.md", "D:/Downloads/AGENTS.md", "/D:/Downloads/AGENTS.md", False, False, False, False),
    ],
}


def _fs_expected(case_id: str) -> dict:
    probes = [{
        "raw": raw, "canonical": canon, "resolved": resolved,
        "exists": exists, "is_symlink": is_symlink, "is_loop": is_loop,
        "is_broken_symlink": is_broken,
    } for (raw, canon, resolved, exists, is_symlink, is_loop, is_broken)
        in FS_PROBES[case_id]]
    return {
        "case_id": "fs/" + case_id,
        "kind": "fs",
        "expected_probes": probes,
        "notes": "Unified S0 expected index (T007). Canonicalize probes "
                 "transcribed from the T002 fixture tree; {case} is the "
                 "case directory. Windows probes are pure-string "
                 "(real junction/drive resolution is NOT_RUN on Linux).",
    }


def main() -> int:
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    resolver_ids = sorted(d.name for d in (FIXTURES / "resolver").iterdir()
                          if (d / "case.json").exists())
    imports_ids = sorted(d.name for d in (FIXTURES / "imports").iterdir()
                         if (d / "case.json").exists())
    s0_ids = sorted(d.name for d in (FIXTURES / "s0").iterdir()
                    if (d / "case.json").exists())
    fs_ids = sorted(d.name for d in (FIXTURES / "fs" / "cases").iterdir()
                    if (d / "case.json").exists())
    if len(resolver_ids) != 20 or len(imports_ids) != 16 \
            or len(s0_ids) != 12 or len(fs_ids) != 12:
        raise SystemExit("corpus counts changed: resolver=%d imports=%d s0=%d fs=%d"
                         % (len(resolver_ids), len(imports_ids), len(s0_ids), len(fs_ids)))
    for case_id in resolver_ids:
        doc = _resolver_expected(case_id)
        _write_expected(case_id, doc, "resolver", index)
    for case_id in imports_ids:
        doc = _imports_expected(case_id)
        _write_expected(case_id, doc, "imports", index)
    for case_id in s0_ids:
        doc = _s0_expected(case_id)
        _write_expected(case_id, doc, "s0", index)
    for case_id in fs_ids:
        doc = _fs_expected(case_id)
        _write_expected("fs/" + case_id, doc, "fs", index)
    (EXPECTED_DIR / "INDEX.json").write_text(
        json.dumps({"generated_by": "scripts/build_s0_expected.py",
                    "synthetic": True, "cases": index},
                   indent=2, sort_keys=True) + "\n", encoding="utf-8")
    n_sources = sum(len(d.get("expected_sources", []))
                    for d in [_resolver_expected(c) for c in resolver_ids]
                    + [_imports_expected(c) for c in imports_ids]
                    + [_s0_expected(c) for c in s0_ids])
    n_edges = sum(len(d.get("expected_edges", []))
                  for d in [_resolver_expected(c) for c in resolver_ids]
                  + [_imports_expected(c) for c in imports_ids]
                  + [_s0_expected(c) for c in s0_ids])
    n_probes = sum(len(_fs_expected(c)["expected_probes"]) for c in fs_ids)
    print("expected files=%d source_entries=%d edge_entries=%d fs_probes=%d"
          % (len(index), n_sources, n_edges, n_probes))
    print("source field assertions=%d edge field assertions=%d"
          % (n_sources * 6, n_edges * 7))
    return 0


def _write_expected(case_id: str, doc: dict, section: str, index: list) -> None:
    path = EXPECTED_DIR / (case_id.replace("/", "__") + ".expected.json")
    path.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False)
                    + "\n", encoding="utf-8")
    index.append({"case_id": case_id, "section": section,
                  "file": path.name, "kind": doc["kind"]})


if __name__ == "__main__":
    raise SystemExit(main())
