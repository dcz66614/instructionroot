#!/usr/bin/env python3
"""Build the synthetic T005 import-graph golden fixtures (P028, T005).

Generates, deterministically and idempotently, the fixture cases
under ``01_s0/fixtures/imports/<case-id>/``. Each case directory
holds ``case.json`` (input, per 01_s0/fixtures/README.md §2 plus
the T003 extensions: ``working_files`` / ``env`` / ``policy``)
and ``<case-id>.expected.json`` (expected import edges + verdict).

All content is synthetic placeholder text; no real user home, no
real repo, no real instruction-file content, no malicious payload
(PROJECT_BOOK.md §15.1). The ancestor walk is bounded at the case
directory by the golden runner (``ancestor_stop``), so Claude's
upward discovery cannot escape the fixture. ``{case}`` inside a
file body is replaced with the case directory's absolute path at
generation time (used only where a test needs a literal absolute
path; no case below needs one — absolute-import cases use
``/etc/...`` so the fixtures stay portable).

Usage (from the P028 work directory):

    .venv/bin/python 01_s0/fixtures/imports/build_imports_fixtures.py [--root DIR]

``--root`` defaults to the directory containing this script.
Re-running deletes and rebuilds only the generated case
directories (subdirectories containing a ``case.json``) and
``manifest.json`` — never this script or README.md.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

PLACEHOLDER = "synthetic placeholder instruction content — P028 T005 fixture\n"


def edge(from_rel, syntax, depth, target, resolved, allowed, reason):
    return {
        "from_relative_path": from_rel,
        "syntax": syntax,
        "depth": depth,
        "relative_target": target,
        "relative_resolved_target": resolved,
        "allowed": allowed,
        "reason": reason,
    }


def case_def(case_id, harness, version, cwd, repo_root, files, expected_edges,
             verdict, title, working_files=None, env=None, policy="default",
             symlinks=None, dirs=None):
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
        "symlinks": symlinks or {},
        "expected_edges": expected_edges,
        "expected_verdict": verdict,
    }


CODEX_V = "codex-2026-11"
CLAUDE_V = "claude-code-2026-11"
COPILOT_V = "copilot-cli-2026-11"

CASES = [
    # --- Claude: depth 0 ---------------------------------------------
    case_def(
        "claude-no-import", "claude-code", CLAUDE_V,
        "repo", "repo",
        {"repo/CLAUDE.md": "plain instructions, no imports\n"},
        [], "PASS",
        "no imports at all (depth 0): no edges, PASS",
    ),
    # --- Claude: depth 4 PASS (SPEC-01 S13) --------------------------
    case_def(
        "claude-depth4", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": "@shared/a.md\n",
            "repo/shared/a.md": "@b.md\n",
            "repo/shared/b.md": "@c.md\n",
            "repo/shared/c.md": "@d.md\n",
            "repo/shared/d.md": "leaf\n",
        },
        [
            edge("repo/CLAUDE.md", "@shared/a.md", 1,
                 "repo/shared/a.md", "repo/shared/a.md", True, "WITHIN_REPO"),
            edge("repo/shared/a.md", "@b.md", 2,
                 "repo/shared/b.md", "repo/shared/b.md", True, "WITHIN_REPO"),
            edge("repo/shared/b.md", "@c.md", 3,
                 "repo/shared/c.md", "repo/shared/c.md", True, "WITHIN_REPO"),
            edge("repo/shared/c.md", "@d.md", 4,
                 "repo/shared/d.md", "repo/shared/d.md", True, "WITHIN_REPO"),
        ],
        "PASS",
        "import chain of 4 hops is allowed (SPEC-01: S13 = depth 4 PASS)",
    ),
    # --- Claude: depth 5 BLOCK (SPEC-01 S14) -------------------------
    case_def(
        "claude-depth5", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": "@shared/a.md\n",
            "repo/shared/a.md": "@b.md\n",
            "repo/shared/b.md": "@c.md\n",
            "repo/shared/c.md": "@d.md\n",
            "repo/shared/d.md": "@e.md\n",
            "repo/shared/e.md": "too deep\n",
        },
        [
            edge("repo/CLAUDE.md", "@shared/a.md", 1,
                 "repo/shared/a.md", "repo/shared/a.md", True, "WITHIN_REPO"),
            edge("repo/shared/a.md", "@b.md", 2,
                 "repo/shared/b.md", "repo/shared/b.md", True, "WITHIN_REPO"),
            edge("repo/shared/b.md", "@c.md", 3,
                 "repo/shared/c.md", "repo/shared/c.md", True, "WITHIN_REPO"),
            edge("repo/shared/c.md", "@d.md", 4,
                 "repo/shared/d.md", "repo/shared/d.md", True, "WITHIN_REPO"),
            edge("repo/shared/d.md", "@e.md", 5,
                 "repo/shared/e.md", "repo/shared/e.md", False, "DEPTH_EXCEEDED"),
        ],
        "BLOCK",
        "import chain of 5 hops: the 5th hop is BLOCKed (S14)",
    ),
    # --- Claude: escapes ----------------------------------------------
    case_def(
        "claude-escape", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": (
                "@../outside/secret.md\n"
                "@shared/ok.md\n"
                "@/etc/instructionroot-no-such-file.md\n"
            ),
            "repo/shared/ok.md": "ok\n",
            "outside/secret.md": "outside\n",
        },
        [
            edge("repo/CLAUDE.md", "@../outside/secret.md", 1,
                 "outside/secret.md", "outside/secret.md", False, "IMPORT_ESCAPE"),
            edge("repo/CLAUDE.md", "@shared/ok.md", 1,
                 "repo/shared/ok.md", "repo/shared/ok.md", True, "WITHIN_REPO"),
            edge("repo/CLAUDE.md", "@/etc/instructionroot-no-such-file.md", 1,
                 "/etc/instructionroot-no-such-file.md",
                 "/etc/instructionroot-no-such-file.md", False, "IMPORT_ESCAPE"),
        ],
        "BLOCK",
        "dotdot escape + absolute outside escape BLOCK; in-repo import PASS (S09)",
    ),
    # --- Claude: missing ----------------------------------------------
    case_def(
        "claude-missing", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": "@missing.md\n@shared/ok.md\n",
            "repo/shared/ok.md": "ok\n",
        },
        [
            edge("repo/CLAUDE.md", "@missing.md", 1,
                 None, None, False, "MISSING"),
            edge("repo/CLAUDE.md", "@shared/ok.md", 1,
                 "repo/shared/ok.md", "repo/shared/ok.md", True, "WITHIN_REPO"),
        ],
        "BLOCK",
        "missing import BLOCKs (S08); in-repo import PASS",
    ),
    # --- Claude: cycle -------------------------------------------------
    case_def(
        "claude-cycle", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": "@shared/a.md\n",
            "repo/shared/a.md": "@b.md\n",
            "repo/shared/b.md": "@a.md\n",
        },
        [
            edge("repo/CLAUDE.md", "@shared/a.md", 1,
                 "repo/shared/a.md", "repo/shared/a.md", True, "WITHIN_REPO"),
            edge("repo/shared/a.md", "@b.md", 2,
                 "repo/shared/b.md", "repo/shared/b.md", True, "WITHIN_REPO"),
            edge("repo/shared/b.md", "@a.md", 3,
                 "repo/shared/a.md", "repo/shared/a.md", True, "WITHIN_REPO"),
        ],
        "PASS",
        "import cycle a<->b terminates (each file expanded once)",
    ),
    # --- Claude: code spans / quotes -----------------------------------
    case_def(
        "claude-code-span", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": (
                "```\n@shared/hidden.md\n```\n"
                "see `@shared/inline.md` for details\n"
                "see @\"shared/quoted.md\" here\n"
                "@shared/real.md\n"
            ),
            "repo/shared/real.md": "real\n",
            "repo/shared/hidden.md": "hidden\n",
            "repo/shared/inline.md": "inline\n",
            "repo/shared/quoted.md": "quoted\n",
        },
        [
            edge("repo/CLAUDE.md", "@shared/real.md", 1,
                 "repo/shared/real.md", "repo/shared/real.md", True, "WITHIN_REPO"),
        ],
        "PASS",
        "imports in fenced code / inline code / quotes are not expanded",
    ),
    # --- Claude: symlink escape ----------------------------------------
    case_def(
        "claude-symlink-escape", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": "@shared/link.md\n",
            "outside/secret.md": "outside\n",
        },
        [
            edge("repo/CLAUDE.md", "@shared/link.md", 1,
                 "repo/shared/link.md", "outside/secret.md", False, "IMPORT_ESCAPE"),
        ],
        "BLOCK",
        "import target is a symlink inside the repo pointing outside (S07/S09)",
        symlinks={"repo/shared/link.md": "outside/secret.md"},
    ),
    # --- Claude: malformed (fail-closed) --------------------------------
    case_def(
        "claude-malformed", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": (
                "@https://example.invalid/x.md\n"
                "@shared\n"
                "@\n"
                "@\"shared/quoted.md\"\n"
            ),
            "repo/shared/quoted.md": "quoted\n",
            "repo/shared/ok.md": "ok\n",
        },
        [
            edge("repo/CLAUDE.md", "@https://example.invalid/x.md", 1,
                 None, None, False, "MISSING"),
            edge("repo/CLAUDE.md", "@shared", 1,
                 None, None, False, "MISSING"),
        ],
        "BLOCK",
        "URL reference (never fetched) + directory target are MISSING; "
        "bare @ and quoted @ produce no edge; malformed never PASSes",
        dirs=["repo/shared"],
    ),
    # --- Claude: home import --------------------------------------------
    case_def(
        "claude-home-import", "claude-code", CLAUDE_V,
        "repo", "repo",
        {
            "repo/CLAUDE.md": "@~/.claude/shared.md\n",
            "home/.claude/shared.md": "shared\n",
        },
        [
            edge("repo/CLAUDE.md", "@~/.claude/shared.md", 1,
                 "home/.claude/shared.md", "home/.claude/shared.md",
                 True, "WITHIN_HOME"),
        ],
        "PASS",
        "import resolving inside the home directory is WITHIN_HOME",
    ),
    # --- Copilot: relative within repo ----------------------------------
    case_def(
        "copilot-relative", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "repo/AGENTS.md": "@shared/rules.md\n",
            "repo/shared/rules.md": "@more.md\n",
            "repo/shared/more.md": "more\n",
            "repo/.github/copilot-instructions.md": "@../shared/repo-wide.md\n",
            "repo/shared/repo-wide.md": "wide\n",
        },
        [
            edge("repo/AGENTS.md", "@shared/rules.md", 1,
                 "repo/shared/rules.md", "repo/shared/rules.md", True, "WITHIN_REPO"),
            edge("repo/shared/rules.md", "@more.md", 2,
                 "repo/shared/more.md", "repo/shared/more.md", True, "WITHIN_REPO"),
            edge("repo/.github/copilot-instructions.md",
                 "@../shared/repo-wide.md", 1,
                 "repo/shared/repo-wide.md", "repo/shared/repo-wide.md",
                 True, "WITHIN_REPO"),
        ],
        "PASS",
        "repo-relative references allowed, incl. nested references",
    ),
    # --- Copilot: absolute / ~/ BLOCK ------------------------------------
    case_def(
        "copilot-absolute", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "repo/AGENTS.md": (
                "@/etc/nope.md\n@~/Downloads/x.md\n@shared/ok.md\n"
            ),
            "repo/shared/ok.md": "ok\n",
        },
        [
            edge("repo/AGENTS.md", "@/etc/nope.md", 1,
                 "/etc/nope.md", "/etc/nope.md", False, "IMPORT_ESCAPE"),
            edge("repo/AGENTS.md", "@~/Downloads/x.md", 1,
                 "home/Downloads/x.md", "home/Downloads/x.md",
                 False, "IMPORT_ESCAPE"),
            edge("repo/AGENTS.md", "@shared/ok.md", 1,
                 "repo/shared/ok.md", "repo/shared/ok.md", True, "WITHIN_REPO"),
        ],
        "BLOCK",
        "absolute path and ~/ reference are not loaded (IMPORT_ESCAPE)",
    ),
    # --- Copilot: @~user/... fails closed (C-08 NOT reproduced) -------
    # Coordinator-verified (2026-11-18): the current code yields an
    # edge allowed=False, reason=UNRESOLVABLE (canonicalisation
    # raises "~user expansion is unsupported"), no crash. FIX-C06
    # adds this case to pin that fail-closed behaviour.
    case_def(
        "copilot-tilde-user", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "repo/.github/copilot-instructions.md": (
                "@~user/evil.md\n"
            ),
        },
        [
            edge("repo/.github/copilot-instructions.md", "@~user/evil.md", 1,
                 None, None, False, "UNRESOLVABLE"),
        ],
        "BLOCK",
        "Copilot @~user/... reference fails closed: UNRESOLVABLE, no crash (C-08)",
    ),
    # --- Copilot: GEMINI.md / *.instructions.md / .claude/CLAUDE.md -----
    case_def(
        "copilot-no-expand", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "repo/GEMINI.md": "@shared/x.md\n",
            "repo/.claude/CLAUDE.md": "@shared/x.md\n",
            "repo/.github/instructions/docs.instructions.md":
                "---\napplyTo: \"**/*.py\"\n---\n@shared/x.md\n",
            "repo/shared/x.md": "x\n",
            "repo/src/app.py": "print(1)\n",
        },
        [],
        "PASS",
        "@ is NOT expanded in GEMINI.md, *.instructions.md or "
        ".claude/CLAUDE.md (UNVERIFIED) — zero edges",
        working_files=["repo/src/app.py"],
    ),
    # --- Copilot: custom dirs ---------------------------------------------
    case_def(
        "copilot-custom-dir", "copilot-cli", COPILOT_V,
        "repo", "repo",
        {
            "extra/AGENTS.md": (
                "@local.md\n@../repo/shared/x.md\n@../outside/y.md\n"
            ),
            "extra/local.md": "local\n",
            "repo/shared/x.md": "x\n",
            "outside/y.md": "y\n",
        },
        [
            edge("extra/AGENTS.md", "@local.md", 1,
                 "extra/local.md", "extra/local.md", True, "WITHIN_CUSTOM_DIR"),
            edge("extra/AGENTS.md", "@../repo/shared/x.md", 1,
                 "repo/shared/x.md", "repo/shared/x.md", True, "WITHIN_REPO"),
            edge("extra/AGENTS.md", "@../outside/y.md", 1,
                 "outside/y.md", "outside/y.md", False, "IMPORT_ESCAPE"),
        ],
        "BLOCK",
        "custom-dir AGENTS.md: in-dir + in-repo references allowed, "
        "escape outside both BLOCKs",
        env={"COPILOT_CUSTOM_INSTRUCTIONS_DIRS": "{case}/extra"},
    ),
    # --- Codex: @ text is not an import ------------------------------------
    case_def(
        "codex-no-import", "codex", CODEX_V,
        "repo", "repo",
        {
            "repo/AGENTS.md": "@../outside/x.md\n@shared/y.md\n",
            "repo/shared/y.md": "y\n",
            "outside/x.md": "x\n",
        },
        [],
        "PASS",
        "Codex documents no @-import syntax: @ text produces no edges",
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


def _write_case(root: Path, case: dict) -> None:
    case_dir = root / case["case_id"]
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)
    (case_dir / "home").mkdir(parents=True)
    for rel in case["dirs"]:
        (case_dir / rel).mkdir(parents=True, exist_ok=True)
    for rel, text in case["files"].items():
        path = case_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace("{case}", str(case_dir)), encoding="utf-8")
    for link_rel, target_rel in case["symlinks"].items():
        link = case_dir / link_rel
        link.parent.mkdir(parents=True, exist_ok=True)
        # Relative target (P1-01): the fixture must resolve identically
        # from any absolute extraction path. An absolute target binds
        # the fixture to the build machine and breaks clean-archive
        # reproduction (the old code symlinked case_dir / target_rel).
        target = os.path.relpath(case_dir / target_rel, link.parent)
        os.symlink(target, str(link))
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
    (case_dir / "case.json").write_text(
        json.dumps(case_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    expected = {
        "case_id": case["case_id"],
        "expected_verdict": case["expected_verdict"],
        "expected_edge_count": len(case["expected_edges"]),
        "expected_edges": case["expected_edges"],
        "notes": "Imports-stage expected file: asserts import edges "
                 "(from + syntax + depth + targets + allowed + reason) "
                 "and the verdict under synthetic trust (in-repo files "
                 "are treated as GIT_TRACKED, home files as USER_SCOPE; "
                 "real Git state is T004/T007's job, not this stage's). "
                 "No receipt_hash is asserted here.",
    }
    (case_dir / (case["case_id"] + ".expected.json")).write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _fill_empty_dirs(case_dir)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build P028 T005 import fixtures")
    parser.add_argument("--root", default=None,
                        help="fixtures/imports directory (default: this script's dir)")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parent
    # Remove only previously generated case dirs (those with case.json).
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "case.json").exists():
            shutil.rmtree(child)
    for case in CASES:
        _write_case(root, case)
    manifest = {
        "cases": [
            {"case_id": c["case_id"], "title": c["title"]} for c in CASES
        ],
        "generated_by": "01_s0/fixtures/imports/build_imports_fixtures.py",
        "synthetic": True,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("built %d import cases under %s" % (len(CASES), root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
