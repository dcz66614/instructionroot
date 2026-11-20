#!/usr/bin/env python3
"""Build the synthetic T003 resolver golden fixtures (P028, T003).

Generates, deterministically and idempotently, the fixture cases
under ``01_s0/fixtures/resolver/<case-id>/``. Each case directory
holds ``case.json`` (input, per 01_s0/fixtures/README.md §2 plus
the T003 extensions documented in README.md next to this script)
and ``<case-id>.expected.json`` (expected discovery output).

All content is synthetic placeholder text; no real user home, no
real repo, no real instruction-file content, no malicious payload
(PROJECT_BOOK.md §15.1). The ancestor walk is bounded at the case
directory by the golden runner (``ancestor_stop``), so Claude's
upward discovery cannot escape the fixture.

Usage (from the P028 work directory):

    .venv/bin/python 01_s0/fixtures/resolver/build_resolver_fixtures.py [--root DIR]

``--root`` defaults to the directory containing this script.
Re-running deletes and rebuilds only the generated case
directories (subdirectories containing a ``case.json``) and
``manifest.json`` — never this script or README.md.

NOTE (2026-11-18): the first version of this script did
``shutil.rmtree(root)`` and deleted itself; the rebuild below only
removes generated case directories.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PLACEHOLDER = "synthetic placeholder instruction content — P028 T003 fixture\n"

FRONTMATTER_PATHS = """\
---
paths:
  - "%s"
---
synthetic placeholder instruction content — P028 T003 fixture
"""

FRONTMATTER_APPLYTO = """\
---
applyTo: "%s"
---
synthetic placeholder instruction content — P028 T003 fixture
"""

BROKEN_FRONTMATTER = """\
---
: bad
---
synthetic placeholder instruction content — P028 T003 fixture
"""

IMPORT_CLAUDE = """\
synthetic placeholder instruction content — P028 T003 fixture
@shared/a.md
@missing.md
"""


def src(rule, scope, phase, rel, kind, also=None):
    entry = {
        "discovery_rule": rule,
        "scope": scope,
        "phase": phase,
        "relative_path": rel,
        "precedence_kind": kind,
    }
    if also:
        entry["also_discovered_by"] = also
    return entry


def na(rel, reason):
    return {"relative_path": rel, "reason": reason}


def case_def(case_id, harness, version, cwd, repo_root, files, expected,
             title, working_files=None, env=None, policy="default",
             not_applicable=None, import_candidates=None, dirs=None):
    return {
        "case_id": case_id,
        "title": title,
        "harness": harness,
        "profile_version": version,
        "cwd": cwd,
        "repo_root": repo_root,
        "home": "home",
        "policy": policy,
        "os": "linux",
        "working_files": working_files or [],
        "env": env or {},
        "dirs": dirs or [],
        "files": files,
        "expected_sources": expected,
        "expected_not_applicable": not_applicable or [],
        "expected_import_candidates": import_candidates or [],
    }


CODEX_V = "codex-2026-11"
CLAUDE_V = "claude-code-2026-11"
COPILOT_V = "copilot-cli-2026-11"

CASES = [
    # --- Codex -------------------------------------------------------
    case_def(
        "codex-basic", "codex", CODEX_V,
        "repo/services/payments", "repo",
        {
            "home/.codex/AGENTS.md": PLACEHOLDER,
            "repo/AGENTS.md": PLACEHOLDER,
            "repo/services/AGENTS.md": PLACEHOLDER,
            "repo/services/payments/AGENTS.md": PLACEHOLDER,
        },
        [
            src("codex.user", "user", "startup", "home/.codex/AGENTS.md", "ORDERED"),
            src("codex.repo-chain", "project", "startup", "repo/AGENTS.md", "ORDERED"),
            src("codex.repo-chain", "project", "startup", "repo/services/AGENTS.md", "ORDERED"),
            src("codex.repo-chain", "project", "startup", "repo/services/payments/AGENTS.md", "ORDERED"),
        ],
        "user + repo-root-to-CWD chain, root-to-leaf order (S03/S17)",
    ),
    case_def(
        "codex-override", "codex", CODEX_V,
        "repo/services", "repo",
        {
            "home/.codex/AGENTS.md": PLACEHOLDER,
            "repo/AGENTS.md": PLACEHOLDER,
            "repo/services/AGENTS.md": PLACEHOLDER,
            "repo/services/AGENTS.override.md": PLACEHOLDER,
        },
        [
            src("codex.user", "user", "startup", "home/.codex/AGENTS.md", "ORDERED"),
            src("codex.repo-chain", "project", "startup", "repo/AGENTS.md", "ORDERED"),
            src("codex.repo-chain", "project", "startup", "repo/services/AGENTS.md", "ORDERED"),
            src("codex.override-fallback", "project", "startup",
                "repo/services/AGENTS.override.md", "UNSPECIFIED"),
        ],
        "AGENTS.override.md listed with UNSPECIFIED precedence (UNVERIFIED rule)",
    ),
    case_def(
        "codex-user-only", "codex", CODEX_V,
        "repo/services/payments", "repo",
        {"home/.codex/AGENTS.md": PLACEHOLDER},
        [src("codex.user", "user", "startup", "home/.codex/AGENTS.md", "ORDERED")],
        "only the user file exists",
        dirs=["repo/services/payments"],
    ),
    case_def(
        "codex-empty", "codex", CODEX_V,
        "repo/services/payments", "repo",
        {},
        [],
        "no instruction files anywhere: empty chain",
        dirs=["repo/services/payments"],
    ),
    case_def(
        "codex-norepo", "codex", CODEX_V,
        "repo/services/payments", None,
        {
            "home/.codex/AGENTS.md": PLACEHOLDER,
            "repo/AGENTS.md": PLACEHOLDER,
            "repo/services/payments/AGENTS.md": PLACEHOLDER,
        },
        [
            src("codex.user", "user", "startup", "home/.codex/AGENTS.md", "ORDERED"),
            src("codex.repo-chain", "project", "startup",
                "repo/services/payments/AGENTS.md", "ORDERED"),
        ],
        "non-git workspace (repo_root null, S25): chain is the CWD only",
    ),
    # --- Claude ------------------------------------------------------
    case_def(
        "claude-basic", "claude-code", CLAUDE_V,
        "repo/services/payments", "repo",
        {
            "home/.claude/CLAUDE.md": PLACEHOLDER,
            "home/.claude/rules/personal.md": PLACEHOLDER,
            "repo/CLAUDE.md": PLACEHOLDER,
            "repo/.claude/rules/team.md": PLACEHOLDER,
            "repo/services/.claude/CLAUDE.md": PLACEHOLDER,
            "repo/services/payments/CLAUDE.local.md": PLACEHOLDER,
        },
        [
            src("claude-code.user", "user", "startup", "home/.claude/CLAUDE.md", "ORDERED"),
            src("claude-code.rules-user", "user", "startup", "home/.claude/rules/personal.md", "ORDERED"),
            src("claude-code.project", "project", "startup", "repo/CLAUDE.md", "ORDERED"),
            src("claude-code.rules-startup", "project", "startup", "repo/.claude/rules/team.md", "ORDERED"),
            src("claude-code.project", "project", "startup", "repo/services/.claude/CLAUDE.md", "ORDERED"),
            src("claude-code.local", "project", "startup", "repo/services/payments/CLAUDE.local.md", "ORDERED"),
        ],
        "managed absent; user + project chain + user/project rules (S01/S02/S03)",
    ),
    case_def(
        "claude-agents-fallback", "claude-code", CLAUDE_V,
        "repo/services/payments", "repo",
        {
            "repo/AGENTS.md": PLACEHOLDER,
            "repo/services/AGENTS.md": PLACEHOLDER,
            "repo/services/payments/.claude/AGENTS.md": PLACEHOLDER,
        },
        [
            src("claude-code.agents-fallback", "project", "startup", "repo/AGENTS.md", "ORDERED"),
            src("claude-code.agents-fallback", "project", "startup", "repo/services/AGENTS.md", "ORDERED"),
            src("claude-code.agents-fallback", "project", "startup", "repo/services/payments/.claude/AGENTS.md", "ORDERED"),
        ],
        "no CLAUDE file anywhere: AGENTS.md chain is the fallback",
    ),
    case_def(
        "claude-agents-fallback-blocked", "claude-code", CLAUDE_V,
        "repo/services/payments", "repo",
        {
            "repo/CLAUDE.md": PLACEHOLDER,
            "repo/AGENTS.md": PLACEHOLDER,
            "repo/services/AGENTS.md": PLACEHOLDER,
            "repo/services/payments/AGENTS.md": PLACEHOLDER,
        },
        [src("claude-code.project", "project", "startup", "repo/CLAUDE.md", "ORDERED")],
        "one CLAUDE.md at the root disables the AGENTS.md fallback everywhere",
    ),
    case_def(
        "claude-rules-paths", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": PLACEHOLDER,
            "repo/.claude/rules/always.md": PLACEHOLDER,
            "repo/.claude/rules/python-only.md": FRONTMATTER_PATHS % "src/**/*.py",
            "repo/.claude/rules/docs-only.md": FRONTMATTER_PATHS % "docs/**",
            "repo/.claude/rules/broken.md": BROKEN_FRONTMATTER,
            "repo/src/app.py": "print('synthetic')\n",
        },
        [
            src("claude-code.project", "project", "startup", "repo/CLAUDE.md", "ORDERED"),
            src("claude-code.rules-startup", "project", "startup", "repo/.claude/rules/always.md", "ORDERED"),
            src("claude-code.rules-startup", "project", "startup", "repo/.claude/rules/broken.md", "ORDERED"),
            src("claude-code.rules-path-scoped", "project", "on_demand", "repo/.claude/rules/python-only.md", "UNSPECIFIED"),
        ],
        "paths-scoped rule matching the working file loads on demand; "
        "non-matching rule is absent; unparseable frontmatter loads as no-paths",
        working_files=["repo/src/app.py"],
        not_applicable=[na("repo/.claude/rules/docs-only.md", "PATH_SCOPED_NO_MATCH")],
    ),
    case_def(
        "claude-nested", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": PLACEHOLDER,
            "repo/services/AGENTS.md": PLACEHOLDER,
            "repo/services/payments/CLAUDE.md": PLACEHOLDER,
            "repo/services/payments/CLAUDE.local.md": PLACEHOLDER,
            "repo/services/payments/app.py": "print('synthetic')\n",
        },
        [
            src("claude-code.project", "project", "startup", "repo/CLAUDE.md", "ORDERED"),
            src("claude-code.agents-nested", "nested", "on_demand", "repo/services/AGENTS.md", "UNSPECIFIED"),
            src("claude-code.nested", "nested", "on_demand", "repo/services/payments/CLAUDE.md", "UNSPECIFIED"),
            src("claude-code.nested", "nested", "on_demand", "repo/services/payments/CLAUDE.local.md", "UNSPECIFIED"),
        ],
        "working file in a subdir triggers nested CLAUDE.md / AGENTS.md on demand",
        working_files=["repo/services/payments/app.py"],
    ),
    case_def(
        "claude-nested-disabled", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": PLACEHOLDER,
            "repo/services/payments/CLAUDE.md": PLACEHOLDER,
            "repo/services/payments/app.py": "print('synthetic')\n",
        },
        [src("claude-code.project", "project", "startup", "repo/CLAUDE.md", "ORDERED")],
        "allow_nested_on_demand=false: nested sources are excluded, not BLOCKed",
        working_files=["repo/services/payments/app.py"],
        policy={"allow_nested_on_demand": False},
        not_applicable=[na("repo/services/payments/app.py", "ON_DEMAND_DISABLED_BY_POLICY")],
    ),
    case_def(
        "claude-import-depth4", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": IMPORT_CLAUDE,
            "repo/shared/a.md": "@b.md\n",
            "repo/shared/b.md": "@c.md\n",
            "repo/shared/c.md": "@d.md\n",
            "repo/shared/d.md": "synthetic leaf\n",
        },
        [src("claude-code.project", "project", "startup", "repo/CLAUDE.md", "ORDERED")],
        "import chain of 4 hops is allowed (SPEC-01: S13 = depth 4 PASS)",
        import_candidates=[
            {"from_relative_path": "repo/CLAUDE.md", "syntax": "@shared/a.md",
             "depth": 1, "relative_target": "repo/shared/a.md", "allowed": True, "reason": "OK"},
            {"from_relative_path": "repo/CLAUDE.md", "syntax": "@missing.md",
             "depth": 1, "relative_target": None, "allowed": False, "reason": "MISSING"},
            {"from_relative_path": "repo/shared/a.md", "syntax": "@b.md",
             "depth": 2, "relative_target": "repo/shared/b.md", "allowed": True, "reason": "OK"},
            {"from_relative_path": "repo/shared/b.md", "syntax": "@c.md",
             "depth": 3, "relative_target": "repo/shared/c.md", "allowed": True, "reason": "OK"},
            {"from_relative_path": "repo/shared/c.md", "syntax": "@d.md",
             "depth": 4, "relative_target": "repo/shared/d.md", "allowed": True, "reason": "OK"},
        ],
    ),
    case_def(
        "claude-import-depth5", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": "@shared/a.md\n",
            "repo/shared/a.md": "@b.md\n",
            "repo/shared/b.md": "@c.md\n",
            "repo/shared/c.md": "@d.md\n",
            "repo/shared/d.md": "@e.md\n",
            "repo/shared/e.md": "synthetic leaf\n",
        },
        [src("claude-code.project", "project", "startup", "repo/CLAUDE.md", "ORDERED")],
        "import chain of 5 hops: the 5th hop is enumerated but BLOCKed (S14)",
        import_candidates=[
            {"from_relative_path": "repo/CLAUDE.md", "syntax": "@shared/a.md",
             "depth": 1, "relative_target": "repo/shared/a.md", "allowed": True, "reason": "OK"},
            {"from_relative_path": "repo/shared/a.md", "syntax": "@b.md",
             "depth": 2, "relative_target": "repo/shared/b.md", "allowed": True, "reason": "OK"},
            {"from_relative_path": "repo/shared/b.md", "syntax": "@c.md",
             "depth": 3, "relative_target": "repo/shared/c.md", "allowed": True, "reason": "OK"},
            {"from_relative_path": "repo/shared/c.md", "syntax": "@d.md",
             "depth": 4, "relative_target": "repo/shared/d.md", "allowed": True, "reason": "OK"},
            {"from_relative_path": "repo/shared/d.md", "syntax": "@e.md",
             "depth": 5, "relative_target": "repo/shared/e.md", "allowed": False, "reason": "DEPTH_EXCEEDED"},
        ],
    ),
    # --- Copilot -----------------------------------------------------
    case_def(
        "copilot-basic", "copilot-cli", COPILOT_V,
        "repo/services/payments", "repo",
        {
            "home/.copilot/copilot-instructions.md": PLACEHOLDER,
            "repo/.github/copilot-instructions.md": PLACEHOLDER,
            "repo/services/.github/copilot-instructions.md": PLACEHOLDER,
            "repo/AGENTS.md": PLACEHOLDER,
            "repo/services/payments/AGENTS.md": PLACEHOLDER,
            "repo/CLAUDE.md": PLACEHOLDER,
            "repo/services/.claude/CLAUDE.md": PLACEHOLDER,
            "repo/GEMINI.md": PLACEHOLDER,
        },
        [
            src("copilot-cli.user", "user", "startup", "home/.copilot/copilot-instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.repo-wide", "project", "startup", "repo/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.repo-wide", "project", "startup", "repo/services/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.agents", "project", "startup", "repo/AGENTS.md", "COMBINE_UNORDERED"),
            src("copilot-cli.claude", "project", "startup", "repo/CLAUDE.md", "COMBINE_UNORDERED"),
            src("copilot-cli.gemini", "project", "startup", "repo/GEMINI.md", "COMBINE_UNORDERED"),
            src("copilot-cli.claude", "project", "startup", "repo/services/.claude/CLAUDE.md", "COMBINE_UNORDERED"),
            src("copilot-cli.agents", "project", "startup", "repo/services/payments/AGENTS.md", "COMBINE_UNORDERED"),
        ],
        "user + repo-wide (incl. intermediate dir) + agents + claude + gemini, all COMBINE_UNORDERED",
    ),
    case_def(
        "copilot-applyto-match", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "home/.copilot/instructions/python.instructions.md": FRONTMATTER_APPLYTO % "**/*.py",
            "repo/.github/instructions/py.instructions.md": FRONTMATTER_APPLYTO % "src/**/*.py",
            "repo/.github/copilot-instructions.md": PLACEHOLDER,
            "repo/src/app.py": "print('synthetic')\n",
        },
        [
            src("copilot-cli.user-modular", "user", "on_demand", "home/.copilot/instructions/python.instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.repo-wide", "project", "startup", "repo/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.repo-modular", "project", "on_demand", "repo/.github/instructions/py.instructions.md", "COMBINE_UNORDERED"),
        ],
        "modular instructions whose applyTo matches the working file (S15)",
        working_files=["repo/src/app.py"],
    ),
    case_def(
        "copilot-applyto-nomatch", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "repo/.github/instructions/docs.instructions.md": FRONTMATTER_APPLYTO % "docs/**",
            "repo/.github/copilot-instructions.md": PLACEHOLDER,
            "repo/src/app.py": "print('synthetic')\n",
        },
        [
            src("copilot-cli.repo-wide", "project", "startup", "repo/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
        ],
        "applyTo no-match: the file is absent from sources (S16 / SPEC-04)",
        working_files=["repo/src/app.py"],
        not_applicable=[na("repo/.github/instructions/docs.instructions.md", "APPLYTO_NO_MATCH")],
    ),
    case_def(
        "copilot-applyto-absent", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "repo/.github/instructions/plain.instructions.md": PLACEHOLDER,
            "repo/.github/copilot-instructions.md": PLACEHOLDER,
            "repo/src/app.py": "print('synthetic')\n",
        },
        [
            src("copilot-cli.repo-wide", "project", "startup", "repo/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
        ],
        "applyTo absent: behaviour is UNVERIFIED, so the file is excluded, never guessed in",
        working_files=["repo/src/app.py"],
        not_applicable=[na("repo/.github/instructions/plain.instructions.md", "APPLYTO_ABSENT_UNVERIFIED")],
    ),
    case_def(
        "copilot-custom-dirs", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "extra/AGENTS.md": PLACEHOLDER,
            "extra/team.instructions.md": FRONTMATTER_APPLYTO % "**/*.py",
            "repo/.github/copilot-instructions.md": PLACEHOLDER,
            "repo/src/app.py": "print('synthetic')\n",
        },
        [
            src("copilot-cli.repo-wide", "project", "startup", "repo/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.custom-dirs", "project", "startup", "extra/AGENTS.md", "COMBINE_UNORDERED"),
            src("copilot-cli.custom-dirs", "project", "startup", "extra/team.instructions.md", "COMBINE_UNORDERED"),
        ],
        "COPILOT_CUSTOM_INSTRUCTIONS_DIRS: AGENTS.md + applyTo-gated *.instructions.md",
        working_files=["repo/src/app.py"],
        env={"COPILOT_CUSTOM_INSTRUCTIONS_DIRS": "{case}/extra"},
    ),
    case_def(
        "copilot-intermediate", "copilot-cli", COPILOT_V,
        "repo/services/payments", "repo",
        {
            "repo/.github/copilot-instructions.md": PLACEHOLDER,
            "repo/services/.github/copilot-instructions.md": PLACEHOLDER,
            "repo/.github/instructions/root.instructions.md": FRONTMATTER_APPLYTO % "**/*.py",
            "repo/services/.github/instructions/mid.instructions.md": FRONTMATTER_APPLYTO % "**/*.py",
            "repo/services/payments/.github/instructions/leaf.instructions.md": FRONTMATTER_APPLYTO % "**/*.py",
            "repo/services/payments/sub/app.py": "print('synthetic')\n",
        },
        [
            src("copilot-cli.repo-wide", "project", "startup", "repo/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.repo-wide", "project", "startup", "repo/services/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.repo-modular", "project", "on_demand", "repo/.github/instructions/root.instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.repo-modular", "project", "on_demand", "repo/services/payments/.github/instructions/leaf.instructions.md", "COMBINE_UNORDERED"),
        ],
        "repo-modular excludes intermediate dirs; repo-wide includes them",
        working_files=["repo/services/payments/sub/app.py"],
    ),
    case_def(
        "copilot-dedup", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "repo/AGENTS.md": PLACEHOLDER,
            "repo/.github/copilot-instructions.md": PLACEHOLDER,
        },
        [
            src("copilot-cli.repo-wide", "project", "startup", "repo/.github/copilot-instructions.md", "COMBINE_UNORDERED"),
            src("copilot-cli.agents", "project", "startup", "repo/AGENTS.md", "COMBINE_UNORDERED",
                also=["copilot-cli.custom-dirs"]),
        ],
        "same AGENTS.md via agents rule and custom-dirs: one source, second rule recorded (S10)",
        env={"COPILOT_CUSTOM_INSTRUCTIONS_DIRS": "{case}/repo"},
    ),
]


def _fill_empty_dirs(case_dir: Path) -> None:
    """Write a .gitkeep into every directory the build left empty.

    Git does not track empty directories, so without this the snapshot
    fails closed (cwd/home must exist) on a clean git-archive
    extraction (P1-01). A .gitkeep is not an instruction file, so it
    cannot change discovery; it only preserves the directory in git.
    Deepest directories first, so a parent holding only an empty
    child is not itself mistaken for empty.
    """
    dirs = sorted(
        (p for p in case_dir.rglob("*")
         if p.is_dir() and not p.is_symlink()),
        key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        if not any(d.iterdir()):
            (d / ".gitkeep").write_text("", encoding="utf-8")


def build(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    # Remove ONLY previously generated case directories (those with a
    # case.json) and the manifest — never this script or README.md.
    for child in list(root.iterdir()):
        if child.is_dir() and (child / "case.json").exists():
            shutil.rmtree(child)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    manifest_cases = []
    for case in CASES:
        d = root / case["case_id"]
        d.mkdir(parents=True)
        # The snapshot requires home + cwd to exist as directories,
        # even when a case defines no files under them.
        (d / "home").mkdir(parents=True, exist_ok=True)
        (d / case["cwd"]).mkdir(parents=True, exist_ok=True)
        if case["repo_root"]:
            (d / case["repo_root"]).mkdir(parents=True, exist_ok=True)
        for rel in case["dirs"]:
            (d / rel).mkdir(parents=True, exist_ok=True)
        for rel, content in case["files"].items():
            path = d / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        case_json = {
            "case_id": case["case_id"],
            "title": case["title"],
            "harness": case["harness"],
            "profile_version": case["profile_version"],
            "cwd": case["cwd"],
            "repo_root": case["repo_root"],
            "home": case["home"],
            "policy": case["policy"],
            "os": case["os"],
            "working_files": case["working_files"],
            "env": case["env"],
            "notes": case["title"],
        }
        (d / "case.json").write_text(
            json.dumps(case_json, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        expected = {
            "case_id": case["case_id"],
            "expected_sources": case["expected_sources"],
            "expected_not_applicable": case["expected_not_applicable"],
            "expected_import_candidates": case["expected_import_candidates"],
            "expected_source_count": len(case["expected_sources"]),
            "notes": (
                "Resolver-stage expected file: asserts discovery fields only "
                "(rule/scope/phase/precedence_kind/relative_path). trust and "
                "verdict are T004/T008 concerns and are asserted by T007's "
                "full expected files, not here."
            ),
        }
        (d / (case["case_id"] + ".expected.json")).write_text(
            json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _fill_empty_dirs(d)
        manifest_cases.append({"case_id": case["case_id"], "title": case["title"]})
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "generated_by": "01_s0/fixtures/resolver/build_resolver_fixtures.py",
                "synthetic": True,
                "cases": sorted(manifest_cases, key=lambda c: c["case_id"]),
            },
            indent=2, sort_keys=True, ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    return {"cases": manifest_cases}


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent
    args = list(argv)
    if args and args[0] == "--root" and len(args) > 1:
        root = Path(args[1])
    elif args and not args[0].startswith("--"):
        root = Path(args[0])
    result = build(root)
    print("built %d cases under %s" % (len(result["cases"]), root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
