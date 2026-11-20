#!/usr/bin/env python3
"""Build the 12 S0 fixtures for P028 T007 (``01_s0/fixtures/s0/``).

Each case is a synthetic workspace with its own real git repository
(where git state matters) so the S0 gate exercises genuinely tracked /
modified / untracked / staged-new / renamed git states -- the
resolver/imports corpora have no ``.git`` inside their repos, so
those states were only ever exercised on the fly by
``compare_oracle.py``'s git scenarios, never as committed fixtures.

Layout follows the existing corpora (T003/T005): ``case.json`` at the
case root, ``home/`` / ``repo/`` / ``outside/`` directly under it
(no ``workspace/`` wrapper). All file content is synthetic
placeholder text; no real user home, no real repo, no malicious
payload. The ``outside/Downloads`` file is a plain placeholder note.

Git commits use fixed author/committer dates so re-running this
generator reproduces the same HEAD SHAs. Idempotent: each case
directory is removed and rebuilt from scratch.

Usage (from the P028 work directory):

    .venv/bin/python 01_s0/fixtures/s0/build_s0_fixtures.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKDIR = HERE.parents[2]

GIT_ENV = dict(os.environ)
GIT_ENV.update({
    "GIT_AUTHOR_NAME": "P028 S0 Fixture",
    "GIT_AUTHOR_EMAIL": "s0@p028.invalid",
    "GIT_COMMITTER_NAME": "P028 S0 Fixture",
    "GIT_COMMITTER_EMAIL": "s0@p028.invalid",
    "GIT_AUTHOR_DATE": "2026-11-18T06:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-11-18T06:00:00+00:00",
})

PLACEHOLDER = "# synthetic placeholder instruction content - P028 S0 fixture\n"


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, env=GIT_ENV,
    )
    if result.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args, result.stderr))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _case_json(case_dir: Path, *, case_id: str, title: str, harness: str,
               profile_version: str, cwd: str, repo_root,
               policy="default", notes: str = "") -> None:
    data = {
        "case_id": case_id,
        "title": title,
        "harness": harness,
        "profile_version": profile_version,
        "cwd": cwd,
        "repo_root": repo_root,
        "home": "home",
        "policy": policy,
        "os": "linux",
        "env": {},
        "working_files": [],
        "notes": notes,
    }
    (case_dir / "case.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _init_repo(case_dir: Path) -> Path:
    """Create home/ (empty) + repo/ with a git repo; return repo path."""
    (case_dir / "home").mkdir(parents=True, exist_ok=True)
    repo = case_dir / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    return repo


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _codex_tree(repo: Path, *, payments: bool = True) -> None:
    """Root + services (+ payments) AGENTS.md chain, all placeholder."""
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(repo / "services" / "AGENTS.md", PLACEHOLDER)
    if payments:
        _write(repo / "services" / "payments" / "AGENTS.md", PLACEHOLDER)


# ---------------------------------------------------------------------------
# The 12 cases
# ---------------------------------------------------------------------------

def case_git_tracked(case_dir: Path) -> None:
    """s0-git-tracked (normal): clean committed codex chain -> PASS."""
    repo = _init_repo(case_dir)
    _codex_tree(repo)
    _commit(repo, "s0-git-tracked: clean chain")
    _case_json(case_dir, case_id="s0-git-tracked",
               title="codex chain, all files git-tracked and clean (S01/S02/S17, real git)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services/payments", repo_root="repo",
               notes="Real-git counterpart of codex-basic: every source GIT_TRACKED.")


def case_git_modified(case_dir: Path) -> None:
    """s0-git-modified (boundary): tracked file modified -> WARN (S05)."""
    repo = _init_repo(case_dir)
    _codex_tree(repo)
    _commit(repo, "s0-git-modified: clean chain")
    _write(repo / "services" / "payments" / "AGENTS.md",
           "# synthetic placeholder instruction content - P028 S0 fixture\n# local edit, not committed\n")
    _case_json(case_dir, case_id="s0-git-modified",
               title="tracked payments AGENTS.md modified in the worktree -> WARN (S05)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services/payments", repo_root="repo",
               notes="Modified file keeps GIT_MODIFIED trust; default policy warns, does not block.")


def case_git_modified_block(case_dir: Path) -> None:
    """s0-git-modified-block (adversarial): modified + block policy -> BLOCK."""
    repo = _init_repo(case_dir)
    _codex_tree(repo)
    _commit(repo, "s0-git-modified-block: clean chain")
    _write(repo / "services" / "payments" / "AGENTS.md",
           "# synthetic placeholder instruction content - P028 S0 fixture\n# local edit, not committed\n")
    _case_json(case_dir, case_id="s0-git-modified-block",
               title="tracked file modified + block_repo_modified=true -> BLOCK (S05 policy variant)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services/payments", repo_root="repo",
               policy={"block_repo_modified": True},
               notes="Same tree as s0-git-modified; only the policy escalates WARN to BLOCK.")


def case_git_untracked_block(case_dir: Path) -> None:
    """s0-git-untracked-block (adversarial): untracked + block policy -> BLOCK (S04)."""
    repo = _init_repo(case_dir)
    _codex_tree(repo, payments=False)
    _commit(repo, "s0-git-untracked-block: root + services tracked")
    _write(repo / "services" / "payments" / "AGENTS.md", PLACEHOLDER)
    _case_json(case_dir, case_id="s0-git-untracked-block",
               title="untracked payments AGENTS.md + block_repo_untracked=true -> BLOCK (S04 policy variant)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services/payments", repo_root="repo",
               policy={"block_repo_untracked": True},
               notes="SPEC-02: default policy would WARN; this policy escalates to BLOCK.")


def case_git_staged_new(case_dir: Path) -> None:
    """s0-git-staged-new (boundary): staged-new file is tracked AND modified (T004 ruling)."""
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _commit(repo, "s0-git-staged-new: root only")
    _write(repo / "services" / "AGENTS.md", PLACEHOLDER)
    _git(repo, "add", "services/AGENTS.md")
    _case_json(case_dir, case_id="s0-git-staged-new",
               title="staged-new services AGENTS.md: tracked + modified -> WARN (T004 ruling)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services", repo_root="repo",
               notes="git ls-files matches a staged file, and status is non-empty: GIT_MODIFIED.")


def case_git_symlink_inside(case_dir: Path) -> None:
    """s0-git-symlink-inside (normal): AGENTS.md symlink to an in-repo target -> PASS (S06)."""
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(repo / "shared" / "target.md", PLACEHOLDER)
    _write(repo / "services" / "AGENTS.md", PLACEHOLDER)
    _commit(repo, "s0-git-symlink-inside: placeholder services file")
    (repo / "services" / "AGENTS.md").unlink()
    os.symlink("../shared/target.md", repo / "services" / "AGENTS.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "s0-git-symlink-inside: services file is a symlink")
    _case_json(case_dir, case_id="s0-git-symlink-inside",
               title="services AGENTS.md is a symlink to an in-repo target -> GIT_TRACKED, PASS (S06)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services", repo_root="repo",
               notes="Canonical path is inside the repo and the resolved target is tracked.")


def case_git_symlink_escape(case_dir: Path) -> None:
    """s0-git-symlink-escape (adversarial): AGENTS.md symlink -> Downloads -> BLOCK (S07)."""
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(case_dir / "outside" / "Downloads" / "AGENTS.md", PLACEHOLDER)
    _write(repo / "services" / "AGENTS.md", PLACEHOLDER)
    _commit(repo, "s0-git-symlink-escape: placeholder services file")
    (repo / "services" / "AGENTS.md").unlink()
    os.symlink("../../outside/Downloads/AGENTS.md",
               repo / "services" / "AGENTS.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "s0-git-symlink-escape: services file links outside")
    _case_json(case_dir, case_id="s0-git-symlink-escape",
               title="services AGENTS.md is a symlink to outside/Downloads -> SYMLINK_ESCAPE, BLOCK (S07)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services", repo_root="repo",
               notes="Synthetic Downloads placeholder only; no malicious payload.")


def case_downloads_import(case_dir: Path) -> None:
    """s0-downloads-import (adversarial): claude import -> Downloads -> BLOCK (S09/S19)."""
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@../outside/Downloads/shared-note.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _write(case_dir / "outside" / "Downloads" / "shared-note.md", PLACEHOLDER)
    _commit(repo, "s0-downloads-import: claude file with two imports")
    _case_json(case_dir, case_id="s0-downloads-import",
               title="claude CLAUDE.md imports ../outside/Downloads file -> IMPORT_ESCAPE, BLOCK (S09/S19)",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="In-repo import is allowed; the Downloads import escapes and blocks.")


def case_git_missing_import(case_dir: Path) -> None:
    """s0-git-missing-import (adversarial): claude import of a missing file -> BLOCK (S08)."""
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@missing.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _commit(repo, "s0-git-missing-import: claude file with a missing import")
    _case_json(case_dir, case_id="s0-git-missing-import",
               title="claude CLAUDE.md imports a missing file -> MISSING, BLOCK (S08, real git)",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="Real-git counterpart of imports/claude-missing.")


def case_git_unicode(case_dir: Path) -> None:
    """s0-git-unicode (normal): unicode directory names, committed -> PASS (S21)."""
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(repo / "中文" / "AGENTS.md", PLACEHOLDER)
    _commit(repo, "s0-git-unicode: unicode directory")
    _case_json(case_dir, case_id="s0-git-unicode",
               title="unicode directory (中文) with AGENTS.md, committed -> PASS (S21)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/中文", repo_root="repo",
               notes="Unicode is passed through byte-for-byte (Q3); no NFC/NFD normalisation.")


def case_git_rename(case_dir: Path) -> None:
    """s0-git-rename (adversarial): directory rename -> new path untracked -> WARN (S24).

    HEAD tracks repo/services/AGENTS.md; the worktree renames the
    directory to services-renamed. Discovery finds the new path,
    but git ls-files has only the old path, so the source is
    GIT_UNTRACKED (the rename is visible as untracked-new-path, not
    silently trusted as the old tracked file).
    """
    repo = _init_repo(case_dir)
    _codex_tree(repo)
    _commit(repo, "s0-git-rename: clean chain")
    shutil.move(str(repo / "services"), str(repo / "services-renamed"))
    _case_json(case_dir, case_id="s0-git-rename",
               title="services/ renamed to services-renamed: new path is untracked -> WARN (S24)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services-renamed", repo_root="repo",
               notes="Rename provenance: the moved file is GIT_UNTRACKED under its new path.")


def case_case_sensitive(case_dir: Path) -> None:
    """s0-case-sensitive (boundary): lowercase agents.md is NOT discovered (S22)."""
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(repo / "services" / "payments" / "AGENTS.md", PLACEHOLDER)
    _commit(repo, "s0-case-sensitive: tracked chain")
    _write(repo / "services" / "agents.md", PLACEHOLDER)
    _case_json(case_dir, case_id="s0-case-sensitive",
               title="lowercase services/agents.md is not discovered on Linux -> PASS (S22)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services/payments", repo_root="repo",
               notes="Linux matching is case-sensitive; the lowercase file never enters the chain.")


def _fill_empty_dirs(case_dir: Path) -> None:
    """Write a .gitkeep into every directory the build left empty.

    Git does not track empty directories, so without this a clean
    git-archive extraction loses the (empty) home/ dirs (P1-01). A
    .gitkeep is not an instruction file, so it cannot change
    discovery; it only preserves the directory in git. Directories
    under a .git component are skipped (regenerated repo internals).
    Deepest directories first, so a parent holding only an empty
    child is not itself mistaken for empty.
    """
    dirs = sorted(
        (p for p in case_dir.rglob("*")
         if p.is_dir() and not p.is_symlink()),
        key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        if ".git" in d.relative_to(case_dir).parts:
            continue
        if not any(d.iterdir()):
            (d / ".gitkeep").write_text("", encoding="utf-8")


BUILDERS = [
    case_git_tracked,
    case_git_modified,
    case_git_modified_block,
    case_git_untracked_block,
    case_git_staged_new,
    case_git_symlink_inside,
    case_git_symlink_escape,
    case_downloads_import,
    case_git_missing_import,
    case_git_unicode,
    case_git_rename,
    case_case_sensitive,
]


def main() -> int:
    root = HERE
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    for builder in BUILDERS:
        name = builder.__name__
        assert name.startswith("case_")
        case_id = "s0-" + name[len("case_"):].replace("_", "-")
        case_dir = root / case_id
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True)
        builder(case_dir)
        _fill_empty_dirs(case_dir)
        cases.append({"case_id": case_id,
                      "title": json.loads((case_dir / "case.json").read_text())["title"]})
    manifest = {
        "generated_by": "01_s0/fixtures/s0/build_s0_fixtures.py",
        "synthetic": True,
        "cases": sorted(cases, key=lambda c: c["case_id"]),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("s0 cases=%d" % len(cases))
    for case in manifest["cases"]:
        print("  %s" % case["case_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
