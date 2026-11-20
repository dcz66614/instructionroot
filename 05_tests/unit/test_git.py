"""Unit tests for P028 T004 — read-only Git + provenance assembly.

Covers PROJECT_BOOK.md §13.3 (Git Provenance) and §8.4 (FR-04)
against the frozen contract (receipt_schema.json ``git`` object:
``repo`` / ``tracked`` / ``modified`` / ``head_commit``).

Every Git repository in these tests is synthesised under ``tmp_path``
(zero real users, never the real home or a real repo) with fixed
author/committer dates so commit SHAs are deterministic. No test
touches the network, and no test issues any Git command outside the
four-command allowlist in ``instructionroot.git``.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_src"))

from instructionroot import git as gitmod  # noqa: E402
from instructionroot.git import GitState, find_repo_root, get_git_state, is_git_repo  # noqa: E402
from instructionroot.provenance import Provenance, build_provenance, provenance_for_entry  # noqa: E402
from instructionroot.snapshot import snapshot_entry  # noqa: E402

SRC_DIR = Path(__file__).resolve().parents[2] / "02_src" / "instructionroot"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t004-test",
    "GIT_AUTHOR_EMAIL": "t004@example.invalid",
    "GIT_COMMITTER_NAME": "t004-test",
    "GIT_COMMITTER_EMAIL": "t004@example.invalid",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
}

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary not available"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run_git(cwd, *args):
    env = dict(os.environ)
    env.update(_GIT_ENV)
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env
    )


def make_repo(tmp_path, name="repo"):
    """Create a repo with one committed file; return (repo, head_sha)."""
    repo = tmp_path / name
    (repo / "sub").mkdir(parents=True)
    assert _run_git(repo, "init", "-b", "main").returncode == 0
    (repo / "AGENTS.md").write_text("root\n", encoding="utf-8")
    (repo / "sub" / "AGENTS.md").write_text("sub\n", encoding="utf-8")
    assert _run_git(repo, "add", ".").returncode == 0
    assert _run_git(repo, "commit", "-m", "initial").returncode == 0
    head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert len(head) == 40
    return repo, head


# ---------------------------------------------------------------------------
# 1. non-git directories (S25)
# ---------------------------------------------------------------------------

def test_non_git_directory_returns_not_git_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "AGENTS.md").write_text("x\n", encoding="utf-8")
    assert find_repo_root(plain) is None
    assert find_repo_root(plain / "AGENTS.md") is None
    assert is_git_repo(plain) is False
    state = get_git_state(plain / "AGENTS.md")
    assert state == GitState(
        repo=None, tracked=False, modified=False,
        head_commit=None, is_git_repo=False, error=None,
    )
    assert state.to_dict() == {
        "repo": None, "tracked": False,
        "modified": False, "head_commit": None,
    }


def test_repo_root_found_from_nested_directory(tmp_path):
    repo, _head = make_repo(tmp_path)
    assert find_repo_root(repo / "sub") == str(repo)
    assert find_repo_root(repo / "sub" / "AGENTS.md") == str(repo)
    assert is_git_repo(repo / "sub" / "AGENTS.md") is True


def test_missing_path_inside_repo_still_finds_repo(tmp_path):
    repo, _head = make_repo(tmp_path)
    missing = repo / "sub" / "nope.md"
    assert find_repo_root(missing) == str(repo)
    state = get_git_state(missing)
    assert state.is_git_repo is True
    assert state.repo == str(repo)
    assert state.tracked is False
    assert state.modified is False
    assert state.head_commit is None


# ---------------------------------------------------------------------------
# 2. tracked / modified / untracked
# ---------------------------------------------------------------------------

def test_tracked_unmodified_file(tmp_path):
    repo, head = make_repo(tmp_path)
    state = get_git_state(repo / "AGENTS.md")
    assert state.is_git_repo is True
    assert state.repo == str(repo)
    assert state.tracked is True
    assert state.modified is False
    assert state.head_commit == head


def test_tracked_file_in_subdirectory(tmp_path):
    repo, head = make_repo(tmp_path)
    state = get_git_state(repo / "sub" / "AGENTS.md")
    assert state.tracked is True
    assert state.modified is False
    assert state.head_commit == head


def test_modified_working_tree_file(tmp_path):
    repo, head = make_repo(tmp_path)
    target = repo / "AGENTS.md"
    target.write_text("root changed\n", encoding="utf-8")
    state = get_git_state(target)
    assert state.tracked is True
    assert state.modified is True
    assert state.head_commit == head


def test_staged_modification_counts_as_modified(tmp_path):
    repo, head = make_repo(tmp_path)
    target = repo / "AGENTS.md"
    target.write_text("staged\n", encoding="utf-8")
    assert _run_git(repo, "add", "AGENTS.md").returncode == 0
    state = get_git_state(target)
    assert state.tracked is True
    assert state.modified is True
    assert state.head_commit == head


def test_untracked_file(tmp_path):
    repo, _head = make_repo(tmp_path)
    target = repo / "sub" / "new.md"
    target.write_text("new\n", encoding="utf-8")
    state = get_git_state(target)
    assert state.is_git_repo is True
    assert state.tracked is False
    # Receipt schema: modified is False for untracked files even
    # though `git status` shows "??" for them.
    assert state.modified is False
    assert state.head_commit is None


def test_deleted_tracked_file(tmp_path):
    repo, head = make_repo(tmp_path)
    target = repo / "AGENTS.md"
    target.unlink()
    state = get_git_state(target)
    assert state.tracked is True  # still in the index
    assert state.modified is True  # working tree differs from HEAD
    assert state.head_commit == head


def test_staged_but_uncommitted_file_is_tracked_without_head(tmp_path):
    repo, _head = make_repo(tmp_path)
    target = repo / "added.md"
    target.write_text("added\n", encoding="utf-8")
    assert _run_git(repo, "add", "added.md").returncode == 0
    state = get_git_state(target)
    assert state.tracked is True  # present in the index
    # It differs from HEAD (the file does not exist there), so it
    # counts as modified under the receipt-schema definition, even
    # though the index matches the working tree.
    assert state.modified is True
    assert state.head_commit is None  # no commit touches it yet


def test_repo_with_no_commits_yet(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    assert _run_git(repo, "init", "-b", "main").returncode == 0
    target = repo / "AGENTS.md"
    target.write_text("x\n", encoding="utf-8")
    assert find_repo_root(target) == str(repo)
    state = get_git_state(target)
    assert state.is_git_repo is True
    assert state.tracked is False
    assert state.modified is False
    assert state.head_commit is None


def test_explicit_repo_root_and_path_outside_it(tmp_path):
    repo, _head = make_repo(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("x\n", encoding="utf-8")
    state = get_git_state(outside, repo_root=str(repo))
    assert state.repo is None
    assert state.is_git_repo is False
    assert state.tracked is False
    assert state.head_commit is None


def test_unicode_and_space_filenames_are_tracked(tmp_path):
    # Q3: Unicode is passed to git byte-for-byte, no normalisation.
    repo, head = make_repo(tmp_path)
    uni = repo / "caf\u00e9 \u6d4b\u8bd5.md"
    uni.write_text("uni\n", encoding="utf-8")
    spaced = repo / "my file.md"
    spaced.write_text("sp\n", encoding="utf-8")
    assert _run_git(repo, "add", ".").returncode == 0
    assert _run_git(repo, "commit", "-m", "unicode").returncode == 0
    for target in (uni, spaced):
        state = get_git_state(target)
        assert state.tracked is True
        assert state.modified is False
        assert state.head_commit is not None
        assert state.head_commit != head  # newer commit touches it


def test_symlink_inside_repo_is_observed_not_followed_for_git(tmp_path):
    repo, _head = make_repo(tmp_path)
    outside = tmp_path / "outside-target.md"
    outside.write_text("out\n", encoding="utf-8")
    link = repo / "link.md"
    os.symlink(str(outside), str(link))
    state = get_git_state(link)
    assert state.is_git_repo is True
    assert state.tracked is False  # the link itself is untracked
    assert state.head_commit is None


# ---------------------------------------------------------------------------
# 3. allowlist guard: no other git subcommand can be issued
# ---------------------------------------------------------------------------

def test_allowlist_refuses_non_allowlisted_invocations(tmp_path):
    repo, _head = make_repo(tmp_path)
    with pytest.raises(ValueError):
        gitmod._run_git(["fetch", "origin"], cwd=str(repo))
    with pytest.raises(ValueError):
        gitmod._run_git(["pull"], cwd=str(repo))
    with pytest.raises(ValueError):
        gitmod._run_git(["push", "origin", "main"], cwd=str(repo))
    with pytest.raises(ValueError):
        gitmod._run_git(["checkout", "main"], cwd=str(repo))
    with pytest.raises(ValueError):
        gitmod._run_git(["reset", "--hard"], cwd=str(repo))
    with pytest.raises(ValueError):
        gitmod._run_git(["clean", "-fd"], cwd=str(repo))
    with pytest.raises(ValueError):
        gitmod._run_git(["status"], cwd=str(repo))  # missing required args
    with pytest.raises(ValueError):
        gitmod._run_git(["log", "--oneline"], cwd=str(repo))
    # The four allowed forms pass the guard (run against a real repo).
    assert gitmod._run_git(["rev-parse", "--show-toplevel"], cwd=str(repo)) is not None


def test_no_mutation_or_network_calls_in_t004_sources():
    """Static guard: the T004 sources contain no mutation/network git
    subcommand names, no shell=True, and do use shell=False."""
    forbidden = ("fetch", "pull", "push", "checkout", "reset", "clean")
    for name in ("git.py", "provenance.py", "trust.py"):
        text = (SRC_DIR / name).read_text(encoding="utf-8")
        for word in forbidden:
            assert word not in text, "%s contains forbidden word %r" % (name, word)
        assert "shell=True" not in text, "%s contains shell=True" % name
        assert "os.system" not in text, "%s contains os.system" % name
    git_text = (SRC_DIR / "git.py").read_text(encoding="utf-8")
    assert "shell=False" in git_text
    assert "subprocess.run" in git_text


# ---------------------------------------------------------------------------
# 4. provenance assembly
# ---------------------------------------------------------------------------

def test_provenance_tracked_file(tmp_path):
    repo, head = make_repo(tmp_path)
    target = repo / "AGENTS.md"
    prov = build_provenance(target)
    assert isinstance(prov, Provenance)
    assert prov.repo == str(repo)
    assert prov.tracked is True
    assert prov.modified is False
    assert prov.head_commit == head
    assert prov.sha256 == hashlib.sha256(b"root\n").hexdigest()
    assert prov.canonical_path == str(target)
    assert prov.resolved_path == str(target)
    assert prov.error is None
    assert prov.to_dict() == {
        "git": {"repo": str(repo), "tracked": True,
                "modified": False, "head_commit": head},
        "sha256": hashlib.sha256(b"root\n").hexdigest(),
    }


def test_provenance_untracked_file_still_hashes(tmp_path):
    repo, _head = make_repo(tmp_path)
    target = repo / "new.md"
    target.write_text("new\n", encoding="utf-8")
    prov = build_provenance(target)
    assert prov.tracked is False
    assert prov.modified is False
    assert prov.head_commit is None
    assert prov.sha256 == hashlib.sha256(b"new\n").hexdigest()


def test_provenance_missing_file_has_no_hash(tmp_path):
    repo, _head = make_repo(tmp_path)
    prov = build_provenance(repo / "gone.md")
    assert prov.tracked is False
    assert prov.sha256 is None
    assert prov.head_commit is None
    assert prov.resolved_path == str(repo / "gone.md")


def test_provenance_compute_hash_false_skips_hash(tmp_path):
    repo, _head = make_repo(tmp_path)
    prov = build_provenance(repo / "AGENTS.md", compute_hash=False)
    assert prov.tracked is True
    assert prov.sha256 is None


def test_provenance_relative_path_with_explicit_cwd(tmp_path):
    repo, head = make_repo(tmp_path)
    prov = build_provenance("AGENTS.md", cwd=str(repo), home=str(tmp_path))
    assert prov.tracked is True
    assert prov.head_commit == head
    assert prov.sha256 == hashlib.sha256(b"root\n").hexdigest()


def test_provenance_accepts_precomputed_git_state(tmp_path):
    repo, head = make_repo(tmp_path)
    injected = GitState(repo=str(repo), tracked=True, modified=True,
                        head_commit=head, is_git_repo=True)
    prov = build_provenance(repo / "AGENTS.md", git_state=injected)
    assert prov.tracked is True
    assert prov.modified is True
    assert prov.head_commit == head


def test_provenance_symlink_uses_resolved_target(tmp_path):
    repo, _head = make_repo(tmp_path)
    outside = tmp_path / "real.md"
    outside.write_text("real\n", encoding="utf-8")
    link = repo / "link.md"
    os.symlink(str(outside), str(link))
    prov = build_provenance(link)
    assert prov.canonical_path == str(link)
    assert prov.resolved_path == str(outside)
    assert prov.sha256 == hashlib.sha256(b"real\n").hexdigest()
    assert prov.tracked is False  # the link itself is untracked


def test_provenance_for_snapshot_entry(tmp_path):
    repo, head = make_repo(tmp_path)
    entry = snapshot_entry(
        "AGENTS.md", cwd=str(repo), home=str(tmp_path), repo_root=str(repo)
    )
    assert entry.sha256 == hashlib.sha256(b"root\n").hexdigest()
    prov = provenance_for_entry(entry)
    assert prov.tracked is True
    assert prov.head_commit == head
    assert prov.sha256 == entry.sha256
    assert prov.resolved_path == entry.resolved_path
