#!/usr/bin/env python3
"""Rebuild the T008 CLI demo fixtures deterministically (P028 T008).

Why a generator instead of committing the fixture repos: each demo
fixture is itself a real git repository (``verify`` needs real Git
state: tracked files for the PASS demo, a symlink escape for the
BLOCK demo), and git cannot store a nested repository's contents —
``git add`` records only an empty gitlink, so a fresh checkout
would lose the fixture files. This is the same problem T007 hit
with the S0 corpus (FIX-S0-SETUP); the fix is the same: the
fixture directories are git-ignored (see ``.gitignore``) and this
generator rebuilds them byte-identically, with fixed author /
committer dates so the HEAD commit is deterministic.

Fixtures built:

* ``fixtures/demo/`` — codex PASS demo: tracked ``AGENTS.md`` at
  the repo root, ``services/`` and ``services/payments/``, plus a
  synthetic home with ``.codex/AGENTS.md``. CWD
  ``fixtures/demo/services/payments`` verifies PASS (exit 0).
* ``fixtures/demo-block/`` — codex BLOCK demo: same shape, but
  ``services/payments/AGENTS.md`` is a symlink to
  ``fixtures/outside/AGENTS.md``, which lies outside the demo-block
  repository → SYMLINK_ESCAPE → BLOCK (exit 20).
* ``fixtures/outside/AGENTS.md`` — the escape target (plain file,
  committed to the outer repo; it is outside the demo-block repo).

All content is synthetic placeholder text. No network, no real
home contents. Idempotent: re-running rebuilds from scratch.

Usage (from the P028 work directory):

    python3 fixtures/build_demo_fixtures.py
    ./instructionroot verify --harness codex --cwd fixtures/demo
    ./instructionroot verify --harness codex --cwd fixtures/demo-block/services/payments --home fixtures/demo-block/home
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
FIXTURES = WORKDIR / "fixtures"

GIT_ENV = dict(os.environ)
GIT_ENV.update({
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_AUTHOR_DATE": "2026-11-18T07:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-11-18T07:00:00+00:00",
})


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, env=GIT_ENV)
    if result.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args, result.stderr))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_repo(repo: Path, message: str) -> str:
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, env=GIT_ENV)
    return result.stdout.strip()


def build_demo() -> str:
    repo = FIXTURES / "demo"
    shutil.rmtree(repo, ignore_errors=True)
    _write(repo / "home" / ".codex" / "AGENTS.md",
           "# Synthetic demo global instructions (placeholder only).\n")
    _write(repo / "AGENTS.md",
           "# Synthetic demo repo instructions (placeholder only).\n")
    _write(repo / "services" / "AGENTS.md",
           "# Synthetic demo service instructions (placeholder only).\n")
    _write(repo / "services" / "payments" / "AGENTS.md",
           "# Synthetic demo payments instructions (placeholder only).\n")
    return _init_repo(repo, "synthetic demo fixture")


def build_demo_block() -> str:
    repo = FIXTURES / "demo-block"
    shutil.rmtree(repo, ignore_errors=True)
    _write(FIXTURES / "outside" / "AGENTS.md",
           "# Synthetic outside-repo instructions (placeholder only).\n")
    _write(repo / "home" / ".codex" / "AGENTS.md",
           "# Synthetic demo-block global instructions (placeholder only).\n")
    _write(repo / "AGENTS.md",
           "# Synthetic demo-block repo instructions (placeholder only).\n")
    _write(repo / "services" / "AGENTS.md",
           "# Synthetic demo-block service instructions (placeholder only).\n")
    link = repo / "services" / "payments" / "AGENTS.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    # Relative link (portable across checkouts): services/payments/
    # -> fixtures/outside/, i.e. outside the demo-block repository.
    link.symlink_to("../../../outside/AGENTS.md")
    return _init_repo(repo, "synthetic demo-block fixture")


def main() -> int:
    demo_head = build_demo()
    block_head = build_demo_block()
    print("fixtures/demo HEAD %s" % demo_head)
    print("fixtures/demo-block HEAD %s" % block_head)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
