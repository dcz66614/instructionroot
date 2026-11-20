#!/usr/bin/env python3
"""Build the Windows corpus for P028 T011 (``fixtures/windows/``).

13 receipt cases + 1 pure-string probe set (``win-probes``, 10 probes,
asserted in ``expected/INDEX.json``). Layout follows the S0 corpus
(``01_s0/fixtures/s0/build_s0_fixtures.py``): ``case.json`` at the case
root, ``home/`` / ``repo/`` / ``outside/`` directly under it, each case
with its own real git repository where git state matters (fixed
author/committer dates, so re-running reproduces the same HEAD SHAs).
Idempotent: each case directory is removed and rebuilt from scratch.

Honesty rule (same as S0's S12 precedent): this VM is Linux. Anything
that cannot genuinely execute here is NOT_RUN and is recorded as such
in the expected index / TASK_RESULT.md, covered by pure-string probes
only where the code path is genuinely exercised, and never reported as
a pass. In particular:

* A real NTFS junction is NOT_RUN on Linux. The two "junction" cases
  use a Linux directory symlink as a *junction analogue*: the resolver
  code path exercised (lexical vs resolved path, containment on the
  resolved path, SYMLINK_ESCAPE derivation) is identical, but the
  reparse-point mechanism itself is not tested. The case notes say so.
* Real drive-letter resolution against a Windows filesystem, real
  case-insensitive filesystem matching, real UNC share access, and
  real Windows Git behaviour (core.ignorecase, case-only rename) are
  NOT_RUN. The corpus pins the Linux behaviour and records, per case,
  how the Windows outcome is expected to differ (see the "windows"
  field in each expected file and TASK_RESULT.md findings F1-F4).
* The pure-string probes (``win-probes``) exercise only
  ``normalize_windows_path`` / ``lexical_canonical`` /
  ``canonicalize`` on spellings -- no filesystem resolution is
  claimed for them (``exists`` is always False).

All file content is synthetic placeholder text; no real user home, no
real repo, no malicious payload. The ``outside/Downloads`` file is a
plain placeholder note.

Usage (from the P028 work directory):

    .venv/bin/python fixtures/windows/build_windows_fixtures.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKDIR = HERE.parents[1]

GIT_ENV = dict(os.environ)
GIT_ENV.update({
    "GIT_AUTHOR_NAME": "P028 Windows Fixture",
    "GIT_AUTHOR_EMAIL": "win@p028.invalid",
    "GIT_COMMITTER_NAME": "P028 Windows Fixture",
    "GIT_COMMITTER_EMAIL": "win@p028.invalid",
    "GIT_AUTHOR_DATE": "2026-11-18T07:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-11-18T07:00:00+00:00",
})

PLACEHOLDER = "# synthetic placeholder instruction content - P028 windows fixture\n"


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
               policy="default", notes: str = "", windows_note: str = "") -> None:
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
        "windows_note": windows_note,
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
# The 13 receipt cases
# ---------------------------------------------------------------------------

def case_case_variant(case_dir: Path) -> None:
    """win-case-variant: lowercase services/Agents.md is NOT discovered (S22).

    Linux discovery matches the exact filename ``AGENTS.md`` only, so
    the case-variant file never enters the chain even though it sits
    in a chain directory. On a case-insensitive Windows filesystem the
    same directory probe for ``AGENTS.md`` would find ``Agents.md``,
    so the Windows receipt would carry an extra source -- see F1.
    """
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(repo / "services" / "payments" / "AGENTS.md", PLACEHOLDER)
    _commit(repo, "win-case-variant: tracked chain (root + payments only)")
    _write(repo / "services" / "Agents.md", PLACEHOLDER)
    _case_json(case_dir, case_id="win-case-variant",
               title="lowercase services/Agents.md is not discovered on Linux -> PASS (S22, Windows variant)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services/payments", repo_root="repo",
               notes="Linux matching is case-sensitive; the variant file never enters the chain.",
               windows_note="NOT_RUN: real case-insensitive matching. On Windows the probe for AGENTS.md would find Agents.md (extra source, GIT_UNTRACKED). Finding F1: production has no case-insensitive discovery mode.")


def case_case_both(case_dir: Path) -> None:
    """win-case-both: AGENTS.md and AGENTS.MD coexist on Linux; one is found.

    Both files are committed. Only the exact-case ``AGENTS.md`` is
    discovered. On Windows the two spellings cannot coexist in one
    directory at all, so this workspace is unrepresentable there --
    the case pins the Linux behaviour only.
    """
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(repo / "services" / "AGENTS.md", PLACEHOLDER)
    _write(repo / "services" / "AGENTS.MD", PLACEHOLDER)
    _commit(repo, "win-case-both: exact + all-caps-extension variant")
    _case_json(case_dir, case_id="win-case-both",
               title="services/AGENTS.md + services/AGENTS.MD committed; only exact-case file discovered -> PASS (S22)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services", repo_root="repo",
               notes="Only the exact-case AGENTS.md enters the chain.",
               windows_note="NOT_RUN: the workspace itself is unrepresentable on Windows (AGENTS.md and AGENTS.MD cannot coexist on a case-insensitive filesystem).")


def case_junction_inside(case_dir: Path) -> None:
    """win-junction-inside: directory symlink (junction analogue) to in-repo target -> PASS.

    ``repo/linked`` is a symlink to ``repo/shared``; CWD is
    ``repo/linked``. Discovery runs on the RESOLVED cwd (both
    implementations canonicalise the CWD first -- see finding F6),
    so the chain is repo + repo/shared and the discovered file is
    ``repo/shared/AGENTS.md`` (tracked, inside the repo): the chain
    never contains the symlink component. The resolver code path
    (lexical vs resolved, containment on the resolved path) is the
    one a junction exercises; only the reparse-point mechanism
    differs -- real NTFS junction resolution stays NOT_RUN (F: junction).
    """
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(repo / "shared" / "AGENTS.md", PLACEHOLDER)
    os.symlink("shared", repo / "linked")
    _commit(repo, "win-junction-inside: linked dir is a symlink to in-repo shared")
    _case_json(case_dir, case_id="win-junction-inside",
               title="repo/linked is a dir symlink to in-repo shared -> GIT_TRACKED, PASS (junction analogue)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/linked", repo_root="repo",
               notes="Junction analogue: Linux dir symlink stands in for an NTFS junction. Discovery runs on the resolved CWD (repo/shared), so the discovered file is repo/shared/AGENTS.md. Known parity gap F6: production records workspace.cwd lexically, the Oracle resolved, so the receipt hashes differ.",
               windows_note="NOT_RUN: real NTFS junction resolution (reparse point). The symlink analogue exercises the same lexical/resolved + containment path. Known parity gap F6 (workspace.cwd) applies on Linux too.")


def case_junction_escape(case_dir: Path) -> None:
    """win-junction-escape: directory symlink (junction analogue) to outside/Downloads -> BLOCK.

    ``repo/linked`` is a symlink to ``outside/Downloads``; CWD is
    ``repo/linked``. Discovery runs on the RESOLVED cwd (both
    implementations canonicalise the CWD first -- see finding F6):
    the resolved CWD (``outside/Downloads``) is outside the repo,
    so ``chain_dirs`` returns [cwd] alone and only
    ``outside/Downloads/AGENTS.md`` is discovered, with trust
    OUTSIDE_REPO (its canonical path contains no symlink component,
    so no SYMLINK_ESCAPE is derived) and verdict BLOCK. The repo
    root file is NOT in the chain. Real NTFS junction resolution
    stays NOT_RUN.
    """
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(case_dir / "outside" / "Downloads" / "AGENTS.md", PLACEHOLDER)
    os.symlink("../outside/Downloads", repo / "linked")
    _commit(repo, "win-junction-escape: linked dir is a symlink outside")
    _case_json(case_dir, case_id="win-junction-escape",
               title="repo/linked is a dir symlink to outside/Downloads -> SYMLINK_ESCAPE, BLOCK (junction analogue)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/linked", repo_root="repo",
               notes="Junction analogue (see win-junction-inside); the resolved CWD is outside the repo, so the chain is [cwd] alone and only the Downloads file is discovered (OUTSIDE_REPO, BLOCK). Known parity gap F6: production records workspace.cwd lexically, the Oracle resolved, so the receipt hashes differ.",
               windows_note="NOT_RUN: real NTFS junction resolution. A real junction to Downloads must BLOCK the same way; only the symlink analogue was executed. Known parity gap F6 (workspace.cwd) applies on Linux too.")


def case_unicode_chain(case_dir: Path) -> None:
    """win-unicode-chain: unicode directory names in the chain, committed -> PASS (S21).

    Windows note: NTFS stores names as UTF-16 and normalises to NFC
    in practice; production applies no NFC/NFD normalisation (contract
    Q3), so two spellings differing only in normalisation form stay
    distinct byte strings. The Linux run pins the no-normalisation
    behaviour; real Windows NFC handling is NOT_RUN.
    """
    repo = _init_repo(case_dir)
    _write(repo / "AGENTS.md", PLACEHOLDER)
    _write(repo / "日本語" / "AGENTS.md", PLACEHOLDER)
    _write(repo / "日本語" / "子目录" / "AGENTS.md", PLACEHOLDER)
    _commit(repo, "win-unicode-chain: unicode directories")
    _case_json(case_dir, case_id="win-unicode-chain",
               title="unicode chain (日本語/子目录) with AGENTS.md, committed -> PASS (S21)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/日本語/子目录", repo_root="repo",
               notes="Unicode is passed through byte-for-byte (Q3); no NFC/NFD normalisation.",
               windows_note="NOT_RUN: real Windows UTF-16/NFC handling. Production does no normalisation on either platform by design (contract Q3).")


def case_git_deleted_chain(case_dir: Path) -> None:
    """win-git-deleted-chain: tracked chain file deleted in the worktree -> chain shrinks, PASS (S23).

    HEAD tracks root + services + payments AGENTS.md; the worktree
    deletes services/AGENTS.md (unstaged). Discovery finds only the
    two surviving files. The deletion is visible in ``git status``
    but the resolver reports no MISSING source for a chain file --
    a deleted chain file silently drops out of the chain (finding F3:
    observation, not a defect -- a deleted file will not load, so
    silence is arguably correct, but an auditor gets no receipt entry
    for it, unlike a missing import target).
    """
    repo = _init_repo(case_dir)
    _codex_tree(repo)
    _commit(repo, "win-git-deleted-chain: clean chain")
    (repo / "services" / "AGENTS.md").unlink()
    _case_json(case_dir, case_id="win-git-deleted-chain",
               title="tracked services AGENTS.md deleted in worktree: chain shrinks to root + payments -> PASS (S23)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services/payments", repo_root="repo",
               notes="A deleted chain file silently drops out of the chain; no MISSING source is reported (finding F3).",
               windows_note="NOT_RUN: real Windows Git deletion behaviour. The Linux git state (deleted, unstaged) is the exercised state.")


def case_git_deleted_import(case_dir: Path) -> None:
    """win-git-deleted-import: claude import of a tracked-then-deleted file -> MISSING, BLOCK (S08/S23).

    HEAD tracks shared/gone.md; the worktree deletes it (unstaged).
    The import resolves within the repo but the target does not exist,
    so the edge is MISSING (null targets, allowed=false) and the
    verdict is BLOCK. This is the import-side counterpart of
    win-git-deleted-chain: unlike a chain file, a missing import
    target IS reported.
    """
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@shared/gone.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _write(repo / "shared" / "gone.md", PLACEHOLDER)
    _commit(repo, "win-git-deleted-import: claude file with two imports")
    (repo / "shared" / "gone.md").unlink()
    _case_json(case_dir, case_id="win-git-deleted-import",
               title="claude CLAUDE.md imports a tracked-then-deleted file -> MISSING, BLOCK (S08/S23)",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="Deleted import target: MISSING edge, BLOCK. Contrast win-git-deleted-chain (silent).",
               windows_note="NOT_RUN: real Windows Git deletion behaviour; the exercised state is Linux git (deleted, unstaged).")


def case_git_case_rename(case_dir: Path) -> None:
    """win-git-case-rename: case-only rename AGENTS.md -> Agents.md (worktree, unstaged) -> PASS.

    After the rename, the services directory holds ``Agents.md``
    only, which Linux discovery does not match, so the chain shrinks
    to the root file. Git records the old path as deleted and the new
    path as untracked. On Windows a case-only rename is a no-op for
    the filesystem (same file, different case spelling) and Git with
    core.ignorecase would treat it differently -- real Windows Git
    behaviour is NOT_RUN.
    """
    repo = _init_repo(case_dir)
    _codex_tree(repo, payments=False)
    _commit(repo, "win-git-case-rename: clean chain")
    shutil.move(str(repo / "services" / "AGENTS.md"),
                str(repo / "services" / "Agents.md"))
    _case_json(case_dir, case_id="win-git-case-rename",
               title="services/AGENTS.md renamed to Agents.md (worktree): new spelling not discovered -> PASS (S24, case variant)",
               harness="codex", profile_version="codex-2026-11",
               cwd="repo/services", repo_root="repo",
               notes="Case-only rename: the new path is untracked AND undiscoverable on Linux.",
               windows_note="NOT_RUN: real Windows Git case-only rename (core.ignorecase). On Windows the rename is a filesystem no-op and the file would still be found as AGENTS.md.")


def case_drive_import(case_dir: Path) -> None:
    """win-drive-import: claude import of a Windows drive path -> IMPORT_ESCAPE, BLOCK.

    Hand-derivation (imports.py + paths.py, not production output):
    ``parse_imports`` leaves ``C:\\shared\\drive-note.md`` intact
    (no ``\\\\`` sequence to collapse); ``lexical_canonical`` sees a
    drive-letter spelling and normalises it to ``C:/shared/drive-note.md``;
    the component-wise resolver yields resolved ``/C:/shared/drive-note.md``
    on Linux; containment against repo/cwd/home fails, so the edge is
    IMPORT_ESCAPE (allowed=false). The file does not exist anywhere in
    the fixture -- escape is judged before existence, so the edge is
    IMPORT_ESCAPE, not MISSING.
    """
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@C:\\shared\\drive-note.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _commit(repo, "win-drive-import: claude file with a drive-letter import")
    _case_json(case_dir, case_id="win-drive-import",
               title="claude CLAUDE.md imports C:\\shared\\drive-note.md -> IMPORT_ESCAPE, BLOCK",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="Drive-letter import escapes (resolved /C:/... is outside every approved root). Pure-string path handling only; no Windows filesystem is involved.",
               windows_note="NOT_RUN: real drive-letter resolution. On Windows C:\\shared\\drive-note.md would resolve against the C: drive; the escape verdict would still hold (outside the repo).")


def case_unc_import(case_dir: Path) -> None:
    """win-unc-import: claude import of a UNC path as naturally spelled -> MISSING, BLOCK.

    Hand-derivation: the file spells the reference ``@\\\\server\\share\\note.md``
    (two leading backslashes, the natural Windows UNC spelling).
    ``parse_imports`` collapses ``\\\\`` -> ``\\`` (backslash-escape
    removal), yielding ``\\server\\share\\note.md`` with ONE leading
    backslash. That is not a Windows-style spelling (the UNC detector
    needs two), not absolute, so it is joined onto the importing
    file's directory as a relative path with backslashes in its name
    and does not exist -> MISSING (null targets), BLOCK. Finding F2:
    UNC imports are not recognised as UNC -- they degrade to MISSING
    instead of IMPORT_ESCAPE. The pure-string UNC normalisation
    (win-probes P3/P4) is a separate code path and is unaffected.
    """
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@\\\\server\\share\\note.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _commit(repo, "win-unc-import: claude file with a UNC import")
    _case_json(case_dir, case_id="win-unc-import",
               title="claude CLAUDE.md imports \\\\server\\share\\note.md (natural UNC spelling) -> MISSING, BLOCK (finding F2)",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="UNC import degrades to MISSING: parse_imports collapses \\\\ to \\, so the UNC spelling is lost before canonicalisation (finding F2).",
               windows_note="NOT_RUN: real UNC share access. The misparse happens before any filesystem access, so it would occur on Windows too (a rooted \\server\\... path is not a UNC path there either).")


def case_drive_relative_import(case_dir: Path) -> None:
    """win-drive-relative-import: claude import of a drive-relative path -> MISSING, BLOCK.

    Hand-derivation: the file spells ``@C:shared\\note.md``.
    ``is_windows_style_path`` requires a separator after the colon,
    so ``C:shared\\note.md`` is NOT detected as Windows-style and
    ``lexical_canonical`` joins it onto the importing file's
    directory as a relative path (``repo/C:shared\\note.md``, colon
    and backslash as filename characters on Linux). It is within the
    repo but does not exist -> MISSING (null targets), BLOCK.
    Finding F4: the drive-relative rejection in
    ``normalize_windows_path`` is unreachable from the import path --
    a drive-relative spelling silently becomes a relative filename
    instead of UNRESOLVABLE. (The rejection itself is covered by
    unit tests on both implementations calling
    ``normalize_windows_path`` directly.)
    """
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@C:shared\\note.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _commit(repo, "win-drive-relative-import: claude file with a drive-relative import")
    _case_json(case_dir, case_id="win-drive-relative-import",
               title="claude CLAUDE.md imports C:shared\\note.md (drive-relative) -> MISSING, BLOCK (finding F4)",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="Drive-relative import becomes a relative path (colon/backslash as filename chars) and is MISSING, not UNRESOLVABLE (finding F4).",
               windows_note="NOT_RUN: real drive-relative resolution (C: means 'current directory on drive C:' on Windows). The spelling is misclassified before any filesystem access.")


def case_tilde_user_import(case_dir: Path) -> None:
    """win-tilde-user-import: claude import of a ~user path -> UNRESOLVABLE, BLOCK.

    Hand-derivation: ``@~other/shared.md`` -- ``lexical_canonical``
    rejects ``~user`` expansion outright (ValueError), so
    ``build_import_graph`` emits UNRESOLVABLE (null targets,
    allowed=false) and the verdict is BLOCK. This is the reachable
    UNRESOLVABLE case (contrast win-drive-relative-import, where the
    spelling never reaches the rejecting function).
    """
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@~other/shared.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _commit(repo, "win-tilde-user-import: claude file with a ~user import")
    _case_json(case_dir, case_id="win-tilde-user-import",
               title="claude CLAUDE.md imports ~other/shared.md -> UNRESOLVABLE, BLOCK",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="~user expansion is unsupported: the edge is UNRESOLVABLE (fail-closed), BLOCK.",
               windows_note="NOT_RUN: no Windows-specific behaviour; ~user is rejected on every platform by design.")


def case_copilot_drive_ref(case_dir: Path) -> None:
    """win-copilot-drive-ref: copilot reference to a Windows drive path -> IMPORT_ESCAPE, BLOCK.

    Hand-derivation: ``.github/copilot-instructions.md`` references
    ``@C:\\shared\\drive-note.md``. The Copilot syntactic block
    (``_is_copilot_blocked_reference`` on the raw ref) matches the
    drive-letter spelling, so the edge is emitted IMPORT_ESCAPE
    (allowed=false) with canonical ``C:/shared/drive-note.md`` and
    resolved ``/C:/shared/drive-note.md``. Only the repo-wide
    copilot-instructions file is discovered (home is empty, no
    AGENTS.md / .github/instructions files exist).
    """
    repo = _init_repo(case_dir)
    _write(repo / ".github" / "copilot-instructions.md",
           PLACEHOLDER + "@../shared/ok.md\n@C:\\shared\\drive-note.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _commit(repo, "win-copilot-drive-ref: copilot file with a drive-letter reference")
    _case_json(case_dir, case_id="win-copilot-drive-ref",
               title="copilot .github/copilot-instructions.md references C:\\shared\\drive-note.md -> IMPORT_ESCAPE, BLOCK",
               harness="copilot-cli", profile_version="copilot-cli-2026-11",
               cwd="repo", repo_root="repo",
               notes="Copilot drive-letter reference is blocked at the syntactic level (IMPORT_ESCAPE).",
               windows_note="NOT_RUN: real drive-letter resolution. The escape verdict would still hold on Windows (outside the repo).")


def case_junction_import_inside(case_dir: Path) -> None:
    """win-junction-import-inside: claude import through a dir symlink (junction analogue) to an in-repo target -> PASS.

    ``repo/linked`` is a symlink to ``repo/shared``; CLAUDE.md
    imports ``@linked/also.md``. Canonical target is
    ``repo/linked/also.md``; resolution follows the symlink to
    ``repo/shared/also.md`` (tracked, inside the repo), so the edge
    is WITHIN_REPO / allowed. Unlike the chain junction cases, the
    CWD itself is not symlinked, so production and Oracle agree
    exactly here -- this case pins the junction code path working
    identically on both implementations.
    """
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@linked/also.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _write(repo / "shared" / "also.md", PLACEHOLDER)
    os.symlink("shared", repo / "linked")
    _commit(repo, "win-junction-import-inside: import through in-repo dir symlink")
    _case_json(case_dir, case_id="win-junction-import-inside",
               title="claude import @linked/also.md through a dir symlink to in-repo shared -> WITHIN_REPO, PASS (junction analogue)",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="Junction analogue on the import path (CWD is not symlinked, so both implementations agree).",
               windows_note="NOT_RUN: real NTFS junction resolution (reparse point). The Linux dir symlink exercises the identical lexical/resolved + containment path.")


def case_junction_import_escape(case_dir: Path) -> None:
    """win-junction-import-escape: claude import through a dir symlink (junction analogue) to outside -> IMPORT_ESCAPE, BLOCK.

    ``repo/linked`` is a symlink to ``outside/Downloads``; CLAUDE.md
    imports ``@linked/secret.md``. Canonical target is
    ``repo/linked/secret.md``; resolution follows the symlink to
    ``outside/Downloads/secret.md``, outside every approved root,
    so the edge is IMPORT_ESCAPE (allowed=false) and the verdict is
    BLOCK. CWD is not symlinked, so both implementations agree.
    """
    repo = _init_repo(case_dir)
    _write(repo / "CLAUDE.md", PLACEHOLDER + "@shared/ok.md\n@linked/secret.md\n")
    _write(repo / "shared" / "ok.md", PLACEHOLDER)
    _write(case_dir / "outside" / "Downloads" / "secret.md", PLACEHOLDER)
    os.symlink("../outside/Downloads", repo / "linked")
    _commit(repo, "win-junction-import-escape: import through dir symlink outside")
    _case_json(case_dir, case_id="win-junction-import-escape",
               title="claude import @linked/secret.md through a dir symlink to outside/Downloads -> IMPORT_ESCAPE, BLOCK (junction analogue)",
               harness="claude-code", profile_version="claude-code-2026-11",
               cwd="repo", repo_root="repo",
               notes="Junction analogue on the import path (CWD is not symlinked, so both implementations agree).",
               windows_note="NOT_RUN: real NTFS junction resolution (reparse point). The Linux dir symlink exercises the identical lexical/resolved + containment path.")


BUILDERS = [
    case_case_variant,
    case_case_both,
    case_junction_inside,
    case_junction_escape,
    case_junction_import_inside,
    case_junction_import_escape,
    case_unicode_chain,
    case_git_deleted_chain,
    case_git_deleted_import,
    case_git_case_rename,
    case_drive_import,
    case_unc_import,
    case_drive_relative_import,
    case_tilde_user_import,
    case_copilot_drive_ref,
]


def main() -> int:
    root = HERE
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    for builder in BUILDERS:
        name = builder.__name__
        assert name.startswith("case_")
        case_id = "win-" + name[len("case_"):].replace("_", "-")
        case_dir = root / case_id
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True)
        builder(case_dir)
        cases.append({"case_id": case_id,
                      "title": json.loads((case_dir / "case.json").read_text())["title"]})
    manifest = {
        "generated_by": "fixtures/windows/build_windows_fixtures.py",
        "synthetic": True,
        "cases": sorted(cases, key=lambda c: c["case_id"]),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("windows receipt cases=%d" % len(cases))
    for case in manifest["cases"]:
        print("  %s" % case["case_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
