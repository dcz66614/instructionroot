"""Unit tests for P028 T004 — trust classifier.

Covers PROJECT_BOOK.md §13.4 (Trust Classification, priority order)
and §8.5 (trust enum) against the frozen contract
(receipt_schema.json ``trust_enum`` / ``trust_priority``;
profile_contract.json SPEC-02 / SPEC-03).

All paths are synthetic directories under ``tmp_path`` (zero real
users, never the real home or a real repo). Git states are either
hand-built :class:`instructionroot.git.GitState` values or produced
by the real read-only Git layer from a synthetic repo in
``test_git.py`` style; the end-to-end test at the bottom wires the
two together.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_src"))

from instructionroot.git import GitState, get_git_state  # noqa: E402
from instructionroot.trust import (  # noqa: E402
    REASON_CODES,
    REASON_TO_TRUST,
    TRUST_ENUM,
    TRUST_PRIORITY,
    classify_trust,
    trust_priority_index,
)

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t004-test",
    "GIT_AUTHOR_EMAIL": "t004@example.invalid",
    "GIT_COMMITTER_NAME": "t004-test",
    "GIT_COMMITTER_EMAIL": "t004@example.invalid",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
}


@pytest.fixture()
def roots(tmp_path):
    """Synthetic home / repo / outside trees (repo NOT under home)."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    (home / ".codex").mkdir(parents=True)
    (repo / "sub").mkdir(parents=True)
    (outside / "Downloads").mkdir(parents=True)
    for path, text in (
        (home / ".codex" / "AGENTS.md", "user\n"),
        (repo / "AGENTS.md", "root\n"),
        (repo / "sub" / "AGENTS.md", "sub\n"),
        (outside / "Downloads" / "AGENTS.md", "dl\n"),
    ):
        path.write_text(text, encoding="utf-8")
    return {"tmp": tmp_path, "home": home, "repo": repo, "outside": outside}


def gs(tracked, modified, repo=None):
    return GitState(
        repo=repo, tracked=tracked, modified=modified,
        head_commit="a" * 40 if tracked else None, is_git_repo=True,
    )


def classify(resolved, roots, **kw):
    kw.setdefault("repo_root", str(roots["repo"]))
    kw.setdefault("home", str(roots["home"]))
    return classify_trust(str(resolved), **kw)


# ---------------------------------------------------------------------------
# 1. reason-code coverage: every R001–R010 is produced by some input
# ---------------------------------------------------------------------------

def test_reason_code_table_is_complete():
    assert sorted(REASON_CODES) == ["R%03d" % i for i in range(1, 11)]
    assert REASON_CODES == {
        "R001": "WITHIN_REPO_TRACKED",
        "R002": "WITHIN_REPO_MODIFIED",
        "R003": "WITHIN_REPO_UNTRACKED",
        "R004": "USER_SCOPE",
        "R005": "OUTSIDE_REPO",
        "R006": "SYMLINK_ESCAPE",
        "R007": "IMPORT_ESCAPE",
        "R008": "MISSING",
        "R009": "NOT_OBSERVED",
        "R010": "UNSPECIFIED_PRECEDENCE",
    }
    # Every code except R010 maps to exactly one trust value; R010
    # annotates a provenance-derived trust and maps to None.
    assert REASON_TO_TRUST["R001"] == "GIT_TRACKED"
    assert REASON_TO_TRUST["R002"] == "GIT_MODIFIED"
    assert REASON_TO_TRUST["R003"] == "GIT_UNTRACKED"
    assert REASON_TO_TRUST["R004"] == "USER_SCOPE"
    assert REASON_TO_TRUST["R005"] == "OUTSIDE_REPO"
    assert REASON_TO_TRUST["R006"] == "SYMLINK_ESCAPE"
    assert REASON_TO_TRUST["R007"] == "IMPORT_ESCAPE"
    assert REASON_TO_TRUST["R008"] == "MISSING"
    assert REASON_TO_TRUST["R009"] == "NOT_OBSERVED"
    assert REASON_TO_TRUST["R010"] is None


def test_trust_priority_order_matches_contract():
    assert TRUST_PRIORITY == (
        "IMPORT_ESCAPE",
        "SYMLINK_ESCAPE",
        "MISSING",
        "OUTSIDE_REPO",
        "GIT_UNTRACKED",
        "GIT_MODIFIED",
        "GIT_TRACKED",
        "USER_SCOPE",
    )
    assert TRUST_ENUM == TRUST_PRIORITY + ("NOT_OBSERVED",)
    assert trust_priority_index("IMPORT_ESCAPE") == 0
    assert trust_priority_index("USER_SCOPE") == 7
    # SPEC-03: NOT_OBSERVED has no priority position.
    assert trust_priority_index("NOT_OBSERVED") is None
    assert trust_priority_index("NOPE") is None


def test_all_reason_codes_reachable(roots):
    """One concrete input per reason code (R001–R010)."""
    repo, home, outside = roots["repo"], roots["home"], roots["outside"]
    seen = {}
    seen["R001"] = classify(repo / "AGENTS.md", roots, git_state=gs(True, False))
    seen["R002"] = classify(repo / "AGENTS.md", roots, git_state=gs(True, True))
    seen["R003"] = classify(repo / "AGENTS.md", roots, git_state=gs(False, False))
    seen["R004"] = classify(home / ".codex" / "AGENTS.md", roots)
    seen["R005"] = classify(outside / "Downloads" / "AGENTS.md", roots)
    seen["R006"] = classify(
        outside / "Downloads" / "AGENTS.md", roots,
        canonical_path=str(repo / "AGENTS.md"), is_symlink=True)
    seen["R007"] = classify(
        outside / "Downloads" / "AGENTS.md", roots, is_import_escape=True)
    seen["R008"] = classify(repo / "gone.md", roots, git_state=gs(False, False))
    seen["R009"] = classify_trust(None)
    seen["R010"] = classify(
        repo / "AGENTS.md", roots, git_state=gs(True, False),
        precedence_kind="UNSPECIFIED")
    assert set(seen) == set(REASON_CODES)
    assert seen["R001"].trust == "GIT_TRACKED"
    assert seen["R002"].trust == "GIT_MODIFIED"
    assert seen["R003"].trust == "GIT_UNTRACKED"
    assert seen["R004"].trust == "USER_SCOPE"
    assert seen["R005"].trust == "OUTSIDE_REPO"
    assert seen["R006"].trust == "SYMLINK_ESCAPE"
    assert seen["R007"].trust == "IMPORT_ESCAPE"
    assert seen["R008"].trust == "MISSING"
    assert seen["R009"].trust == "NOT_OBSERVED"
    # R010 keeps the provenance-derived trust, only the reason changes.
    assert seen["R010"].trust == "GIT_TRACKED"
    assert seen["R010"].reason_code == "R010"


# ---------------------------------------------------------------------------
# 2. in-repo git states
# ---------------------------------------------------------------------------

def test_tracked_unmodified(roots):
    r = classify(roots["repo"] / "AGENTS.md", roots, git_state=gs(True, False))
    assert (r.trust, r.reason_code) == ("GIT_TRACKED", "R001")


def test_tracked_modified(roots):
    r = classify(roots["repo"] / "AGENTS.md", roots, git_state=gs(True, True))
    assert (r.trust, r.reason_code) == ("GIT_MODIFIED", "R002")


def test_untracked_in_repo(roots):
    r = classify(roots["repo"] / "AGENTS.md", roots, git_state=gs(False, False))
    assert (r.trust, r.reason_code) == ("GIT_UNTRACKED", "R003")


def test_git_state_as_dict_is_accepted(roots):
    r = classify(roots["repo"] / "AGENTS.md", roots,
                 git_state={"tracked": True, "modified": False})
    assert (r.trust, r.reason_code) == ("GIT_TRACKED", "R001")


def test_bad_git_state_type_raises(roots):
    with pytest.raises(TypeError):
        classify(roots["repo"] / "AGENTS.md", roots, git_state="tracked")


def test_in_repo_without_git_state_is_not_observed(roots):
    # The classifier must not guess tracked/modified when no Git
    # state was supplied: NOT_OBSERVED, not a silent GIT_TRACKED.
    r = classify(roots["repo"] / "AGENTS.md", roots, git_state=None)
    assert (r.trust, r.reason_code) == ("NOT_OBSERVED", "R009")


def test_repo_under_home_still_classifies_by_git(roots):
    # §13.4 puts every GIT_* value above USER_SCOPE, so a repository
    # that happens to live under the home is still a repository.
    home_repo = roots["home"] / "myrepo"
    (home_repo / "AGENTS.md").parent.mkdir(parents=True, exist_ok=True)
    (home_repo / "AGENTS.md").write_text("x\n", encoding="utf-8")
    r = classify_trust(
        str(home_repo / "AGENTS.md"), repo_root=str(home_repo),
        home=str(roots["home"]), git_state=gs(True, False))
    assert (r.trust, r.reason_code) == ("GIT_TRACKED", "R001")


# ---------------------------------------------------------------------------
# 3. user scope / outside repo
# ---------------------------------------------------------------------------

def test_user_scope_file(roots):
    r = classify(roots["home"] / ".codex" / "AGENTS.md", roots)
    assert (r.trust, r.reason_code) == ("USER_SCOPE", "R004")


def test_outside_repo_file(roots):
    r = classify(roots["outside"] / "Downloads" / "AGENTS.md", roots)
    assert (r.trust, r.reason_code) == ("OUTSIDE_REPO", "R005")


def test_prefix_trap_is_not_within_repo(roots):
    # /tmp/.../repo2 must not count as within /tmp/.../repo.
    sibling = roots["tmp"] / "repo2"
    sibling.mkdir()
    target = sibling / "AGENTS.md"
    target.write_text("x\n", encoding="utf-8")
    r = classify(target, roots)
    assert (r.trust, r.reason_code) == ("OUTSIDE_REPO", "R005")


def test_non_git_workspace_home_file_is_user_scope(roots):
    r = classify_trust(
        str(roots["home"] / ".codex" / "AGENTS.md"),
        repo_root=None, home=str(roots["home"]))
    assert (r.trust, r.reason_code) == ("USER_SCOPE", "R004")


def test_non_git_workspace_other_file_is_outside_repo(roots):
    r = classify_trust(
        str(roots["outside"] / "Downloads" / "AGENTS.md"),
        repo_root=None, home=str(roots["home"]))
    assert (r.trust, r.reason_code) == ("OUTSIDE_REPO", "R005")


def test_managed_scope_maps_to_user_scope(roots):
    # Contract gap (see TASK_RESULT.md): the frozen enum has no
    # MANAGED value, yet the default policy permits managed scope, so
    # a managed-scope source is classified USER_SCOPE / R004 keyed
    # off scope="managed" rather than OUTSIDE_REPO.
    r = classify_trust(
        "/etc/claude-code/CLAUDE.md", repo_root=str(roots["repo"]),
        home=str(roots["home"]), scope="managed", exists=True)
    assert (r.trust, r.reason_code) == ("USER_SCOPE", "R004")


# ---------------------------------------------------------------------------
# 4. missing / escapes / priority order
# ---------------------------------------------------------------------------

def test_missing_file_inside_repo(roots):
    r = classify(roots["repo"] / "gone.md", roots, git_state=gs(False, False))
    assert (r.trust, r.reason_code) == ("MISSING", "R008")


def test_missing_beats_untracked(roots):
    # MISSING outranks GIT_UNTRACKED in the §13.4 order.
    r = classify(roots["repo"] / "gone.md", roots, git_state=gs(False, False))
    assert r.trust == "MISSING"


def test_explicit_exists_false_wins_over_disk(roots):
    # A caller-supplied exists=False (e.g. from a snapshot) is
    # honoured even if the path happens to exist on disk now.
    r = classify(roots["repo"] / "AGENTS.md", roots,
                 git_state=gs(True, False), exists=False)
    assert (r.trust, r.reason_code) == ("MISSING", "R008")


def test_symlink_escape_derived_from_canonical_vs_resolved(roots):
    # Lexical path inside the repo, resolved target outside it.
    r = classify(
        roots["outside"] / "Downloads" / "AGENTS.md", roots,
        canonical_path=str(roots["repo"] / "AGENTS.md"), is_symlink=True,
        git_state=gs(False, False))
    assert (r.trust, r.reason_code) == ("SYMLINK_ESCAPE", "R006")


def test_symlink_within_repo_is_not_an_escape(roots):
    # A symlink whose target stays inside the repo is classified by
    # its Git state, not as an escape.
    target = roots["repo"] / "sub" / "AGENTS.md"
    link = roots["repo"] / "link.md"
    os.symlink(str(target), str(link))
    r = classify(link, roots, canonical_path=str(link),
                 is_symlink=True, git_state=gs(True, False))
    assert (r.trust, r.reason_code) == ("GIT_TRACKED", "R001")


def test_symlink_under_home_pointing_inside_home_is_user_scope(roots):
    target = roots["home"] / ".codex" / "AGENTS.md"
    link = roots["home"] / "link.md"
    os.symlink(str(target), str(link))
    r = classify(link, roots, canonical_path=str(link), is_symlink=True)
    assert (r.trust, r.reason_code) == ("USER_SCOPE", "R004")


def test_explicit_symlink_escape_flag_overrides_derivation(roots):
    r = classify(roots["repo"] / "AGENTS.md", roots,
                 git_state=gs(True, False), is_symlink_escape=True)
    assert (r.trust, r.reason_code) == ("SYMLINK_ESCAPE", "R006")
    r2 = classify(
        roots["outside"] / "Downloads" / "AGENTS.md", roots,
        canonical_path=str(roots["repo"] / "AGENTS.md"), is_symlink=True,
        is_symlink_escape=False, git_state=gs(False, False))
    assert (r2.trust, r2.reason_code) == ("OUTSIDE_REPO", "R005")


def test_broken_symlink_escaping_repo_is_symlink_escape(roots):
    # SYMLINK_ESCAPE outranks MISSING: the escape is the deciding fact.
    r = classify(
        roots["outside"] / "Downloads" / "gone.md", roots,
        canonical_path=str(roots["repo"] / "link.md"), is_symlink=True,
        exists=False)
    assert (r.trust, r.reason_code) == ("SYMLINK_ESCAPE", "R006")


def test_broken_symlink_inside_repo_is_missing(roots):
    r = classify(
        roots["repo"] / "gone.md", roots,
        canonical_path=str(roots["repo"] / "gone.md"), is_symlink=True,
        exists=False, git_state=gs(False, False))
    assert (r.trust, r.reason_code) == ("MISSING", "R008")


def test_import_escape_beats_symlink_escape(roots):
    r = classify(
        roots["outside"] / "Downloads" / "AGENTS.md", roots,
        canonical_path=str(roots["repo"] / "AGENTS.md"), is_symlink=True,
        is_import_escape=True)
    assert (r.trust, r.reason_code) == ("IMPORT_ESCAPE", "R007")


def test_import_escape_beats_missing(roots):
    r = classify(roots["repo"] / "gone.md", roots,
                 is_import_escape=True, exists=False)
    assert (r.trust, r.reason_code) == ("IMPORT_ESCAPE", "R007")


def test_outside_beats_untracked(roots):
    # A file outside the repo is OUTSIDE_REPO regardless of git flags.
    r = classify(roots["outside"] / "Downloads" / "AGENTS.md", roots,
                 git_state=gs(False, False))
    assert (r.trust, r.reason_code) == ("OUTSIDE_REPO", "R005")


def test_unresolved_path_is_not_observed():
    r = classify_trust(None)
    assert (r.trust, r.reason_code) == ("NOT_OBSERVED", "R009")


# ---------------------------------------------------------------------------
# 5. unspecified precedence (R010) and policy
# ---------------------------------------------------------------------------

def test_unspecified_precedence_annotates_tracked(roots):
    r = classify(roots["repo"] / "AGENTS.md", roots,
                 git_state=gs(True, False), precedence_kind="UNSPECIFIED")
    assert r.trust == "GIT_TRACKED"
    assert r.reason_code == "R010"


def test_unspecified_precedence_annotates_user_scope(roots):
    r = classify(roots["home"] / ".codex" / "AGENTS.md", roots,
                 precedence_kind="UNSPECIFIED")
    assert r.trust == "USER_SCOPE"
    assert r.reason_code == "R010"


def test_unspecified_precedence_does_not_hide_specific_reasons(roots):
    # Untracked / escape / missing are more specific than the
    # precedence fact, so they keep their own reason codes.
    r = classify(roots["repo"] / "AGENTS.md", roots,
                 git_state=gs(False, False), precedence_kind="UNSPECIFIED")
    assert (r.trust, r.reason_code) == ("GIT_UNTRACKED", "R003")
    r2 = classify(roots["outside"] / "Downloads" / "AGENTS.md", roots,
                  precedence_kind="UNSPECIFIED")
    assert (r2.trust, r2.reason_code) == ("OUTSIDE_REPO", "R005")


def test_ordered_precedence_keeps_plain_reason(roots):
    r = classify(roots["repo"] / "AGENTS.md", roots,
                 git_state=gs(True, False), precedence_kind="ORDERED")
    assert (r.trust, r.reason_code) == ("GIT_TRACKED", "R001")


def test_policy_never_changes_trust(roots):
    # SPEC-02: block_repo_untracked only changes the verdict
    # (WARN -> BLOCK); the trust stays GIT_UNTRACKED either way.
    base = classify(roots["repo"] / "AGENTS.md", roots, git_state=gs(False, False))
    strict = classify(roots["repo"] / "AGENTS.md", roots,
                      git_state=gs(False, False),
                      policy={"block_repo_untracked": True})
    assert base == strict
    assert base.trust == "GIT_UNTRACKED"
    with pytest.raises(TypeError):
        classify(roots["repo"] / "AGENTS.md", roots,
                 git_state=gs(False, False), policy="strict")


# ---------------------------------------------------------------------------
# 6. end-to-end: real git state + classifier
# ---------------------------------------------------------------------------

def _run_git(cwd, *args):
    env = dict(os.environ)
    env.update(_GIT_ENV)
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env
    )


def test_end_to_end_with_real_git_repo(tmp_path):
    import shutil
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    home.mkdir()
    (repo / "sub").mkdir(parents=True)
    outside.mkdir()
    assert _run_git(repo, "init", "-b", "main").returncode == 0
    (repo / "AGENTS.md").write_text("root\n", encoding="utf-8")
    (repo / "sub" / "AGENTS.md").write_text("sub\n", encoding="utf-8")
    assert _run_git(repo, "add", ".").returncode == 0
    assert _run_git(repo, "commit", "-m", "init").returncode == 0
    (repo / "sub" / "AGENTS.md").write_text("sub changed\n", encoding="utf-8")
    (repo / "new.md").write_text("new\n", encoding="utf-8")
    (home / "AGENTS.md").write_text("home\n", encoding="utf-8")
    (outside / "AGENTS.md").write_text("out\n", encoding="utf-8")

    cases = [
        (repo / "AGENTS.md", "GIT_TRACKED", "R001"),
        (repo / "sub" / "AGENTS.md", "GIT_MODIFIED", "R002"),
        (repo / "new.md", "GIT_UNTRACKED", "R003"),
        (home / "AGENTS.md", "USER_SCOPE", "R004"),
        (outside / "AGENTS.md", "OUTSIDE_REPO", "R005"),
    ]
    for target, want_trust, want_reason in cases:
        state = get_git_state(target)
        result = classify_trust(
            str(target), repo_root=str(repo), home=str(home),
            git_state=state)
        assert (result.trust, result.reason_code) == (want_trust, want_reason), target
