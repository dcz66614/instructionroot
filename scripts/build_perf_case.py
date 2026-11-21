#!/usr/bin/env python3
"""P028 T014 — deterministic generator for the synthetic perf case.

Builds, under ``--out`` (default ``<tmp>/p028-perf-case`` — deliberately
outside any git repository, so the CWD has no repo root of its own
and each custom dir's own repo is the one probed; building inside
the workdir would make the outer repo the single root for every
source), a case with exactly:

* 500 modular Copilot candidates: 10 custom instruction directories
  (``repos/r00`` … ``repos/r09``), each holding 50
  ``*.instructions.md`` files with ``applyTo: "**/*.py"`` frontmatter;
* 10 ``AGENTS.md`` files (one per custom dir), each with 10 ``@``
  references to files inside the same dir → 100 import edges;
* 10 git roots: each custom dir is its own git repository (one
  deterministic commit, fixed author/committer dates);
* a non-git CWD (``cwd/``, with working file ``src/app.py``) and an
  empty synthetic home (``home/``), so the only git roots probed are
  the 10 custom-dir repos.

All content is synthetic placeholder text only — no real instruction
content, no network, no real user files. Deterministic: fixed file
contents, fixed git author/committer dates, sorted enumeration. Run
the case with ``scripts/measure_perf.py`` (or by hand)::

    COPILOT_CUSTOM_INSTRUCTIONS_DIRS="$(python3 -c \
      "import json;print(','.join(json.load(open('/tmp/p028-perf-case/manifest.json'))['custom_dirs']))")" \
    ./instructionroot verify --harness copilot-cli \
      --cwd /tmp/p028-perf-case/cwd --home /tmp/p028-perf-case/home \
      --working-file /tmp/p028-perf-case/cwd/src/app.py

Writes ``manifest.json`` in the case root describing the case.
Exit 0 on success. Re-running rebuilds the case from scratch.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]

N_REPOS = 10
N_MODULAR_PER_REPO = 50
N_IMPORTS_PER_AGENTS = 10

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Perf Fixture",
    "GIT_AUTHOR_EMAIL": "perf@example.invalid",
    "GIT_COMMITTER_NAME": "Perf Fixture",
    "GIT_COMMITTER_EMAIL": "perf@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}

PLACEHOLDER = "# Synthetic P028 perf fixture (placeholder only, no real instruction content).\n"


def _run(argv: list[str], *, cwd: Path) -> None:
    subprocess.run(argv, cwd=str(cwd), env=GIT_ENV, check=True,
                   capture_output=True, text=True)


def build(out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    cwd_dir = out / "cwd" / "src"
    cwd_dir.mkdir(parents=True)
    (cwd_dir / "app.py").write_text(
        "# Synthetic working file for the P028 perf case.\n", encoding="utf-8")
    (out / "home").mkdir(parents=True)

    custom_dirs: list[str] = []
    for r in range(N_REPOS):
        repo = out / "repos" / ("r%02d" % r)
        (repo / "imports").mkdir(parents=True)
        imports = "".join(
            "@./imports/i%02d.md\n" % i for i in range(N_IMPORTS_PER_AGENTS))
        (repo / "AGENTS.md").write_text(
            PLACEHOLDER + "\n" + imports, encoding="utf-8")
        for i in range(N_IMPORTS_PER_AGENTS):
            (repo / "imports" / ("i%02d.md" % i)).write_text(
                PLACEHOLDER, encoding="utf-8")
        for m in range(N_MODULAR_PER_REPO):
            (repo / ("m%02d.instructions.md" % m)).write_text(
                "---\napplyTo: \"**/*.py\"\n---\n" + PLACEHOLDER,
                encoding="utf-8")
        _run(["git", "init", "-q", "-b", "main"], cwd=repo)
        _run(["git", "add", "-A"], cwd=repo)
        _run(["git", "commit", "-q", "-m", "P028 perf fixture r%02d" % r],
             cwd=repo)
        custom_dirs.append(str(repo.resolve()))

    manifest = {
        "case": "p028-perf-500-100-10",
        "harness": "copilot-cli",
        "cwd": str((out / "cwd").resolve()),
        "home": str((out / "home").resolve()),
        "working_file": str((out / "cwd" / "src" / "app.py").resolve()),
        "custom_dirs": custom_dirs,
        "expected": {
            "modular_candidates": N_REPOS * N_MODULAR_PER_REPO,
            "agents_files": N_REPOS,
            "sources": N_REPOS * N_MODULAR_PER_REPO + N_REPOS,
            "edges": N_REPOS * N_IMPORTS_PER_AGENTS,
            "git_roots": N_REPOS,
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(
        Path(tempfile.gettempdir()) / "p028-perf-case"),
                        help="case directory to build (rebuilt from scratch)")
    args = parser.parse_args(argv)
    manifest = build(Path(args.out))
    print("perf case built: %s" % args.out)
    print(json.dumps(manifest["expected"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
