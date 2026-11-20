"""Unit tests for P028 FIX-R5 — CLI vs frozen-library receipt parity.

FIX-R5 root cause (V4 Windows run, E08-5): the production CLI
(``python -m instructionroot verify/inspect``) produced different
receipts from the frozen library path
(``scripts/compare_oracle.py::build_production_receipt``) on the same
input — claude-code cases came back 0 source / PASS via the CLI while
the library gave 1 source / 2 edges (BLOCK on import-escape), so
``verify`` exited 0 where 20 was required. The same input run through
both paths must now agree on verdict, receipt_hash, sources and edges,
and ``verify`` must exit 20 on the import-escape case.

Two distinct defects are covered here:

* F6-in-CLI (reproduces on Linux): ``build_receipt_for`` passed the
  *resolved* CWD to ``build_receipt`` while the library passes the
  *lexical* CWD, so ``workspace.cwd`` (and the receipt hash) differed
  whenever the CWD went through a symlink/junction — the two codex
  junction cases below failed on ``receipt_hash`` before the fix
  although sources/verdict agreed.
* The Windows ancestor-chain defect does NOT reproduce on Linux (the
  ``"/C:/..."`` chain entries only break under Windows ``ntpath``);
  it is covered by ``test_fixr5_ancestor_chain_windows_drive_form``
  in test_resolver.py (``os_name="nt"`` shape) and by the mechanism
  test in test_paths.py. This file proves the *observable* CLI/library
  agreement on every input class, including the exit code.

All data is synthetic (tmp_path git repos + placeholder instruction
files + dir symlinks standing in for NTFS junctions, exactly like
``fixtures/windows/win-junction-*``); no network, no real home.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

WORKDIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKDIR / "02_src"))
sys.path.insert(0, str(WORKDIR / "scripts"))

import compare_oracle as co  # noqa: E402
from instructionroot.cli import build_receipt_for  # noqa: E402

LAUNCHER = WORKDIR / "instructionroot"
PLACEHOLDER = "# synthetic placeholder instruction content - P028 windows fixture\n"


def _git(repo: Path, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _git_init_repo(repo: Path, files: dict[str, str]):
    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "core.eol", "lf")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")


def _case(case_id, harness, profile_version, cwd, repo_root="repo"):
    return {
        "case_id": case_id, "cwd": cwd, "env": {},
        "harness": harness, "home": "home", "os": "linux",
        "policy": "default", "profile_version": profile_version,
        "repo_root": repo_root, "working_files": [],
    }


def _build_plain(tmp_path: Path):
    case_dir = tmp_path / "plain-repo"
    (case_dir / "home").mkdir(parents=True, exist_ok=True)
    _git_init_repo(case_dir / "repo", {"CLAUDE.md": PLACEHOLDER})
    return case_dir, _case("plain-repo", "claude-code",
                           "claude-code-2026-11", "repo")


def _build_inside(tmp_path: Path):
    case_dir = tmp_path / "win-junction-inside"
    (case_dir / "home").mkdir(parents=True, exist_ok=True)
    _git_init_repo(case_dir / "repo", {
        "AGENTS.md": PLACEHOLDER, "shared/AGENTS.md": PLACEHOLDER})
    os.symlink("shared", case_dir / "repo" / "linked")
    return case_dir, _case("win-junction-inside", "codex",
                           "codex-2026-11", "repo/linked")


def _build_escape(tmp_path: Path):
    case_dir = tmp_path / "win-junction-escape"
    (case_dir / "home").mkdir(parents=True, exist_ok=True)
    _git_init_repo(case_dir / "repo", {"AGENTS.md": PLACEHOLDER})
    (case_dir / "outside" / "Downloads").mkdir(parents=True)
    (case_dir / "outside" / "Downloads" / "AGENTS.md").write_text(
        PLACEHOLDER, encoding="utf-8")
    os.symlink("../outside/Downloads", case_dir / "repo" / "linked")
    return case_dir, _case("win-junction-escape", "codex",
                           "codex-2026-11", "repo/linked")


def _build_import_inside(tmp_path: Path):
    case_dir = tmp_path / "win-junction-import-inside"
    (case_dir / "home").mkdir(parents=True, exist_ok=True)
    _git_init_repo(case_dir / "repo", {
        "CLAUDE.md": PLACEHOLDER + "@shared/ok.md\n@linked/also.md\n",
        "shared/ok.md": PLACEHOLDER, "shared/also.md": PLACEHOLDER})
    os.symlink("shared", case_dir / "repo" / "linked")
    return case_dir, _case("win-junction-import-inside", "claude-code",
                           "claude-code-2026-11", "repo")


def _build_import_escape(tmp_path: Path):
    case_dir = tmp_path / "win-junction-import-escape"
    (case_dir / "home").mkdir(parents=True, exist_ok=True)
    _git_init_repo(case_dir / "repo", {
        "CLAUDE.md": PLACEHOLDER + "@shared/ok.md\n@linked/secret.md\n",
        "shared/ok.md": PLACEHOLDER})
    (case_dir / "outside" / "Downloads").mkdir(parents=True)
    (case_dir / "outside" / "Downloads" / "secret.md").write_text(
        PLACEHOLDER, encoding="utf-8")
    os.symlink("../outside/Downloads", case_dir / "repo" / "linked")
    return case_dir, _case("win-junction-import-escape", "claude-code",
                           "claude-code-2026-11", "repo")


BUILDERS = [
    _build_plain,
    _build_inside,
    _build_escape,
    _build_import_inside,
    _build_import_escape,
]

EXPECTED = {
    "plain-repo": ("PASS", 0),
    "win-junction-inside": ("PASS", 0),
    "win-junction-escape": ("BLOCK", 20),
    "win-junction-import-inside": ("PASS", 0),
    "win-junction-import-escape": ("BLOCK", 20),
}


def _summarise(receipt):
    return {
        "verdict": receipt["verdict"],
        "receipt_hash": receipt["receipt_hash"],
        "sources": [(s["canonical_path"], s["trust"], s["discovery_rule"])
                    for s in receipt["sources"]],
        "edges": [(e["from"], e["syntax"], e.get("resolved_target"),
                   e["reason"], e["allowed"]) for e in receipt["edges"]],
    }


@pytest.mark.parametrize("build", BUILDERS, ids=[b.__name__ for b in BUILDERS])
def test_cli_receipt_equals_library_receipt(tmp_path, build):
    """Same input, both paths: verdict/hash/sources/edges all equal."""
    case_dir, case = build(tmp_path)
    lib_receipt, lib_err = co.build_production_receipt(case_dir, case)
    assert lib_err is None, lib_err
    cli_receipt, _report = build_receipt_for(
        harness=case["harness"],
        cwd=str(case_dir / case["cwd"]),
        home=str(case_dir / case["home"]),
        repo_root=str(case_dir / case["repo_root"]),
    )
    assert _summarise(cli_receipt) == _summarise(lib_receipt), (
        "CLI receipt != library receipt for %s" % case["case_id"])
    want_verdict, _want_exit = EXPECTED[case["case_id"]]
    assert lib_receipt["verdict"] == want_verdict
    assert cli_receipt["verdict"] == want_verdict


@pytest.mark.parametrize("build", BUILDERS, ids=[b.__name__ for b in BUILDERS])
def test_cli_verify_exit_code_matches_library_verdict(tmp_path, build):
    """The real CLI ``verify`` exits with the library verdict's code."""
    case_dir, case = build(tmp_path)
    _want_verdict, want_exit = EXPECTED[case["case_id"]]
    proc = subprocess.run(
        [str(LAUNCHER), "verify",
         "--harness", case["harness"],
         "--cwd", str(case_dir / case["cwd"]),
         "--home", str(case_dir / case["home"]),
         "--repo-root", str(case_dir / case["repo_root"]),
         "--format", "json"],
        capture_output=True, text=True, cwd=str(WORKDIR))
    assert proc.returncode == want_exit, (proc.stdout, proc.stderr)
    receipt = json.loads(proc.stdout)
    lib_receipt, lib_err = co.build_production_receipt(case_dir, case)
    assert lib_err is None, lib_err
    assert receipt["receipt_hash"] == lib_receipt["receipt_hash"]


def test_repo_root_none_means_no_repo_not_autodetect():
    # FIX-R5 (S0 regression, codex-norepo): repo_root=None means NO
    # repository. The old build_receipt_for auto-detected the enclosing
    # git repo (this fixture sits inside the P028 worktree), so the
    # chain walked past the CWD and returned 3 sources / PASS where
    # the library and the Oracle return 2 sources / BLOCK. The CLI
    # command layer still auto-detects --repo-root (documented
    # default); the shared assembly function does not.
    case_dir = WORKDIR / "01_s0" / "fixtures" / "resolver" / "codex-norepo"
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    assert case["repo_root"] is None
    lib_receipt, lib_err = co.build_production_receipt(case_dir, case)
    assert lib_err is None, lib_err
    cwd = case_dir / case["cwd"]
    home = case_dir / case["home"]
    receipt, _report = build_receipt_for(
        harness="codex", cwd=cwd, home=home, repo_root=None,
        profile_version=case.get("profile_version"),
        ancestor_stop=str(case_dir),
    )
    assert receipt == lib_receipt
    assert receipt["workspace"]["repo_root"] is None
    assert len(receipt["sources"]) == 2
    assert receipt["verdict"] == "BLOCK"
