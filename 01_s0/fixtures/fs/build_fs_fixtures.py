#!/usr/bin/env python3
"""Build the synthetic T002 filesystem fixtures (P028, T002).

Generates, deterministically and idempotently, the fixture trees under
``01_s0/fixtures/fs/cases/`` plus ``manifest.json``. All content is
synthetic placeholder text; no real user home, no real repo, no real
instruction-file content, no malicious payload (PROJECT_BOOK.md §15.1).

Usage (from the P028 work directory):

    .venv/bin/python 01_s0/fixtures/fs/build_fs_fixtures.py [--root DIR]

``--root`` defaults to the directory containing this script. Re-running
deletes and rebuilds ``cases/`` and ``manifest.json`` from scratch, so
the committed trees are always exactly what this script produces.

Layout per case (``cases/<case-id>/``):

    basic/            repo + home + outside trees, plain files
    dotdot/           deep tree exercised with ``..`` spellings
    symlink-inside/   in-repo symlink -> in-repo target
    symlink-escape/   in-repo symlink -> outside-repo target (S07 shape)
    symlink-loop/     a <-> b symlink loop (must not hang)
    symlink-broken/   symlink -> missing target
    unicode/          Unicode directory / file names
    missing/          empty tree; tests address paths that do not exist
    separators/       plain tree; tests use ``//`` and trailing ``/``
    deep-chain/       a/b/c/d/e/f chain
    dir-symlink/      symlink to a directory + a dir-symlink loop pair
    windows/          windows-paths.json: pure-string cases only
                      (no real Windows FS on Linux — NOT_RUN, T011)

Each case directory also gets a ``case.json`` describing the case.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

PLACEHOLDER = "synthetic placeholder instruction content — P028 T002 fixture\n"

CASES = {
    "basic": "repo + home + outside trees, plain files",
    "dotdot": "deep tree exercised with .. spellings",
    "symlink-inside": "in-repo symlink -> in-repo target",
    "symlink-escape": "in-repo symlink -> outside-repo target (S07 shape)",
    "symlink-loop": "a <-> b symlink loop (must not hang)",
    "symlink-broken": "symlink -> missing target",
    "unicode": "Unicode directory / file names",
    "missing": "empty tree; tests address paths that do not exist",
    "separators": "plain tree; tests use // and trailing /",
    "deep-chain": "a/b/c/d/e/f chain",
    "dir-symlink": "symlink to a directory + a dir-symlink loop pair",
}


def _write(path: Path, content: str = PLACEHOLDER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _link(link: Path, target: str) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, link)


def build(root: Path) -> dict:
    cases_dir = root / "cases"
    if cases_dir.exists():
        shutil.rmtree(cases_dir)
    cases_dir.mkdir(parents=True)

    def case(name: str, title: str | None = None) -> Path:
        d = cases_dir / name
        d.mkdir(parents=True)
        (d / "case.json").write_text(
            json.dumps(
                {"case_id": name, "title": title or CASES[name], "os": "linux",
                 "synthetic": True},
                indent=2, sort_keys=True, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        return d

    # basic
    d = case("basic")
    _write(d / "home" / ".codex" / "AGENTS.md")
    _write(d / "repo" / "AGENTS.md")
    _write(d / "repo" / "services" / "AGENTS.md")
    _write(d / "repo" / "services" / "payments" / "AGENTS.md")
    _write(d / "outside" / "Downloads" / "AGENTS.md")

    # dotdot
    d = case("dotdot")
    _write(d / "repo" / "AGENTS.md")
    _write(d / "repo" / "services" / "payments" / "AGENTS.md")
    _write(d / "repo" / "services" / "other" / "keep.txt", "keep\n")

    # symlink-inside (relative target, stays inside repo)
    d = case("symlink-inside")
    _write(d / "repo" / "AGENTS.md")
    _write(d / "repo" / "services" / "AGENTS.md")
    _link(d / "repo" / "link.md", "services/AGENTS.md")

    # symlink-escape (relative target, leaves the repo)
    d = case("symlink-escape")
    _write(d / "repo" / "AGENTS.md")
    _write(d / "outside" / "Downloads" / "AGENTS.md")
    _link(d / "repo" / "escape.md", "../outside/Downloads/AGENTS.md")

    # symlink-loop
    d = case("symlink-loop")
    _write(d / "repo" / "AGENTS.md")
    _link(d / "repo" / "loop-a", "loop-b")
    _link(d / "repo" / "loop-b", "loop-a")
    _link(d / "repo" / "self-loop", "self-loop")

    # symlink-broken
    d = case("symlink-broken")
    _write(d / "repo" / "AGENTS.md")
    _link(d / "repo" / "broken.md", "does-not-exist.md")

    # unicode
    d = case("unicode")
    _write(d / "repo" / "ünïcode-✓" / "AGENTS-✓.md")
    _write(d / "repo" / "中文" / "说明.md", "synthetic unicode placeholder\n")
    _write(d / "repo" / "AGENTS.md")

    # missing (empty tree apart from case.json)
    case("missing")

    # separators
    d = case("separators")
    _write(d / "repo" / "services" / "payments" / "AGENTS.md")
    _write(d / "repo" / "AGENTS.md")

    # deep-chain
    d = case("deep-chain")
    _write(d / "repo" / "a" / "b" / "c" / "d" / "e" / "f" / "AGENTS.md")

    # dir-symlink (symlink to a dir; loop pair must not hang a walk)
    d = case("dir-symlink")
    _write(d / "repo" / "services" / "AGENTS.md")
    _link(d / "repo" / "linkdir", "services")
    _link(d / "repo" / "loopdir-a", "loopdir-b")
    _link(d / "repo" / "loopdir-b", "loopdir-a")

    # windows: pure-string cases only — no real Windows FS on Linux.
    d = case("windows", "Windows-style spellings (pure string, NOT_RUN on Linux)")
    (d / "windows-paths.json").write_text(
        json.dumps(
            {
                "note": "Pure-string normalisation cases only. Real "
                        "junction / drive-letter resolution is NOT_RUN "
                        "on Linux (see test_paths.py); T011 owns the "
                        "Windows runner cases.",
                "cases": [
                    {"raw": "C:\\repo\\services\\..\\AGENTS.md",
                     "expected": "C:/repo/AGENTS.md"},
                    {"raw": "C:/repo//services///AGENTS.md",
                     "expected": "C:/repo/services/AGENTS.md"},
                    {"raw": "\\\\server\\share\\repo\\AGENTS.md",
                     "expected": "//server/share/repo/AGENTS.md"},
                    {"raw": "D:\\Downloads\\AGENTS.md",
                     "expected": "D:/Downloads/AGENTS.md"},
                ],
            },
            indent=2, sort_keys=True, ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "generated_by": "01_s0/fixtures/fs/build_fs_fixtures.py",
        "synthetic": True,
        "cases": [
            {"case_id": name, "title": CASES[name]}
            for name in sorted(CASES)
        ] + [{"case_id": "windows",
              "title": "Windows-style spellings (pure string, NOT_RUN on Linux)"}],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent
    args = list(argv)
    if args and args[0] == "--root" and len(args) > 1:
        root = Path(args[1])
    elif args and not args[0].startswith("--"):
        root = Path(args[0])
    manifest = build(root)
    print("built %d cases under %s" % (len(manifest["cases"]), root / "cases"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
