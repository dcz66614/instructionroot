"""Unit tests for P028 T002 — canonical paths + filesystem snapshot.

Covers PROJECT_BOOK.md §13.1 (Canonical Path) and §8.2 (Filesystem
Discovery) against the frozen contract (receipt_schema.json source
fields ``canonical_path`` / ``resolved_path`` / ``is_symlink`` /
``symlink_target``).

All trees are built under ``tmp_path`` (synthetic, zero real users,
never the real home or a real repo). The one test that touches the
committed fixtures only reads ``01_s0/fixtures/fs/cases/basic``.

Windows junction / drive-letter *resolution* cannot be verified on
this Linux host: those tests are explicitly ``skip`` (NOT_RUN), and
only pure-string Windows normalisation is asserted here. Nothing
about Windows is faked as passing. Section 8 is the one exception
to "faked": it runs the Windows drive branch on Linux through the
FIX-R2 injectable ``fs`` / ``os_name`` probe with an in-memory fake
filesystem — those tests prove the *branch logic* (drive root,
``..`` stop, reparse-tag following, ``\\\\?\\`` normalisation, drive
switch, loop fail-closed), not that real Windows behaves that way;
real-Windows proof still belongs to the V2 pack on Sam's PC.
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_src"))

from instructionroot.paths import (  # noqa: E402
    MAX_SYMLINK_HOPS,
    _normalize_windows_readlink_target,
    canonicalize,
    detect_escape,
    is_windows_style_path,
    is_within_root,
    lexical_canonical,
    normalize_windows_path,
    redact_home,
)
from instructionroot.snapshot import (  # noqa: E402
    FilesystemSnapshot,
    SnapshotError,
    build_snapshot,
    hash_file,
    snapshot_entry,
    snapshot_tree,
)

FIXTURES_FS = Path(__file__).resolve().parents[2] / "01_s0" / "fixtures" / "fs"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def ws(tmp_path):
    """A synthetic workspace: home/ + repo/ (+ outside/), all under tmp."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    (home / ".codex").mkdir(parents=True)
    (repo / "services" / "payments").mkdir(parents=True)
    (outside / "Downloads").mkdir(parents=True)
    (home / ".codex" / "AGENTS.md").write_text("user\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("root\n", encoding="utf-8")
    (repo / "services" / "AGENTS.md").write_text("services\n", encoding="utf-8")
    (repo / "services" / "payments" / "AGENTS.md").write_text(
        "payments\n", encoding="utf-8")
    (outside / "Downloads" / "AGENTS.md").write_text("dl\n", encoding="utf-8")
    return {"tmp": tmp_path, "home": home, "repo": repo, "outside": outside}


def canon(raw, *, cwd, home):
    return canonicalize(raw, cwd=str(cwd), home=str(home))


# ---------------------------------------------------------------------------
# 1. lexical canonicalisation: absolute / relative / .. / separators
# ---------------------------------------------------------------------------

def test_absolute_path_unchanged(ws):
    c = canon(str(ws["repo"] / "AGENTS.md"), cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(ws["repo"] / "AGENTS.md")
    assert c.resolved_path == c.canonical_path
    assert c.exists and c.is_file and not c.is_symlink


def test_relative_path_resolves_against_cwd(ws):
    c = canon("services/payments/AGENTS.md",
              cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(ws["repo"] / "services" / "payments" / "AGENTS.md")
    assert c.exists


def test_dotdot_normalisation(ws):
    a = canon("services/../AGENTS.md", cwd=ws["repo"], home=ws["home"])
    b = canon("AGENTS.md", cwd=ws["repo"], home=ws["home"])
    assert a.canonical_path == b.canonical_path
    assert a.resolved_path == b.resolved_path


def test_dot_and_dotdot_mix(ws):
    c = canon("./services/./payments/../AGENTS.md",
              cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(ws["repo"] / "services" / "AGENTS.md")


def test_dotdot_above_cwd_stays_absolute(ws):
    c = canon("../../outside/Downloads/AGENTS.md",
              cwd=ws["repo"] / "services", home=ws["home"])
    assert c.canonical_path == str(ws["outside"] / "Downloads" / "AGENTS.md")
    assert c.exists


def test_duplicate_separators_collapsed(ws):
    c = canon("services//payments///AGENTS.md",
              cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(ws["repo"] / "services" / "payments" / "AGENTS.md")


def test_trailing_slash_stripped_for_dir(ws):
    c = canon("services/payments/", cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(ws["repo"] / "services" / "payments")
    assert c.is_dir


def test_filesystem_root_preserved(ws):
    assert lexical_canonical("/", cwd=ws["repo"], home=ws["home"]) == "/"
    c = canon("/", cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == "/" and c.resolved_path == "/"


def test_relative_without_cwd_raises(ws):
    with pytest.raises(ValueError):
        canonicalize("AGENTS.md", home=str(ws["home"]))


def test_empty_path_raises(ws):
    with pytest.raises(ValueError):
        canonicalize("", cwd=str(ws["repo"]), home=str(ws["home"]))


def test_nul_byte_raises(ws):
    with pytest.raises(ValueError):
        canonicalize("a\x00b", cwd=str(ws["repo"]), home=str(ws["home"]))


def test_bytes_path_rejected(ws):
    with pytest.raises(TypeError):
        canonicalize(b"AGENTS.md", cwd=str(ws["repo"]), home=str(ws["home"]))


def test_canonicalisation_is_idempotent(ws):
    c1 = canon("services/../AGENTS.md", cwd=ws["repo"], home=ws["home"])
    c2 = canon(c1.canonical_path, cwd=ws["repo"], home=ws["home"])
    assert c2.canonical_path == c1.canonical_path
    assert c2.resolved_path == c1.resolved_path


def test_home_expansion_with_explicit_home(ws):
    c = canon("~/.codex/AGENTS.md", cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(ws["home"] / ".codex" / "AGENTS.md")
    assert c.exists


def test_tilde_without_home_raises(ws):
    with pytest.raises(ValueError):
        canonicalize("~/.codex/AGENTS.md", cwd=str(ws["repo"]))


def test_tilde_user_rejected(ws):
    with pytest.raises(ValueError):
        canonicalize("~someone/AGENTS.md",
                     cwd=str(ws["repo"]), home=str(ws["home"]))


def test_backslash_is_not_a_separator_on_posix(tmp_path):
    # POSIX: backslash is a valid filename character, not a separator.
    weird = tmp_path / "a\\b"
    weird.write_text("x\n", encoding="utf-8")
    c = canonicalize(str(weird), cwd=str(tmp_path), home=str(tmp_path))
    assert c.canonical_path == str(weird)
    assert c.exists


# ---------------------------------------------------------------------------
# 2. lexical vs resolved dual record + symlinks
# ---------------------------------------------------------------------------

def test_lexical_vs_resolved_equal_for_plain_file(ws):
    c = canon("AGENTS.md", cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == c.resolved_path
    assert not c.is_symlink and c.symlink_target is None
    assert c.symlink_chain == ()


def test_symlink_inside_repo_dual_record(ws):
    os.symlink("services/AGENTS.md", ws["repo"] / "link.md")
    c = canon("link.md", cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(ws["repo"] / "link.md")
    assert c.resolved_path == str(ws["repo"] / "services" / "AGENTS.md")
    assert c.canonical_path != c.resolved_path
    assert c.is_symlink and c.exists and c.is_file
    assert c.symlink_target == "services/AGENTS.md"
    assert c.symlink_chain == ("services/AGENTS.md",)


def test_symlink_chain_resolves_fully(ws):
    os.symlink("services/AGENTS.md", ws["repo"] / "link1.md")
    os.symlink("link1.md", ws["repo"] / "link2.md")
    c = canon("link2.md", cwd=ws["repo"], home=ws["home"])
    assert c.resolved_path == str(ws["repo"] / "services" / "AGENTS.md")
    assert c.symlink_chain == ("link1.md", "services/AGENTS.md")


def test_symlink_to_dir_then_child(ws):
    os.symlink("services", ws["repo"] / "linkdir")
    c = canon("linkdir/payments/AGENTS.md", cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(ws["repo"] / "linkdir" / "payments" / "AGENTS.md")
    assert c.resolved_path == str(ws["repo"] / "services" / "payments" / "AGENTS.md")
    assert c.is_symlink and c.exists


def test_file_under_symlinked_dir_is_symlink(ws):
    os.symlink("services", ws["repo"] / "linkdir")
    c = canon("linkdir/AGENTS.md", cwd=ws["repo"], home=ws["home"])
    assert c.is_symlink  # a parent component is a symlink
    assert c.symlink_target is None  # the file itself is not a symlink


def test_absolute_symlink_target(ws):
    target = ws["outside"] / "Downloads" / "AGENTS.md"
    os.symlink(str(target), ws["repo"] / "abs.md")
    c = canon("abs.md", cwd=ws["repo"], home=ws["home"])
    assert c.resolved_path == str(target)
    assert c.symlink_target == str(target)


def test_broken_symlink_is_missing_not_fabricated(ws):
    os.symlink("does-not-exist.md", ws["repo"] / "broken.md")
    c = canon("broken.md", cwd=ws["repo"], home=ws["home"])
    assert c.is_symlink and c.is_broken_symlink
    assert not c.exists and not c.is_file
    assert c.valid and c.error is None
    # Resolved path still names the (missing) target.
    assert c.resolved_path == str(ws["repo"] / "does-not-exist.md")


def test_symlink_loop_fails_closed_without_hanging(ws):
    os.symlink("loop-b", ws["repo"] / "loop-a")
    os.symlink("loop-a", ws["repo"] / "loop-b")
    start = time.monotonic()
    c = canon("loop-a", cwd=ws["repo"], home=ws["home"])
    assert time.monotonic() - start < 5.0
    assert c.is_loop and not c.valid
    assert c.error == "SYMLINK_LOOP"
    assert c.resolved_path is None  # fail-closed: no resolved path asserted
    assert not c.exists


def test_self_symlink_loop(ws):
    os.symlink("self-loop", ws["repo"] / "self-loop")
    c = canon("self-loop", cwd=ws["repo"], home=ws["home"])
    assert c.is_loop and c.error == "SYMLINK_LOOP" and c.resolved_path is None


def test_long_symlink_chain_hits_hop_bound(ws):
    prev = ws["repo"] / "AGENTS.md"
    for i in range(MAX_SYMLINK_HOPS + 5):
        link = ws["repo"] / ("chain-%02d" % i)
        os.symlink(prev.name, link)
        prev = link
    c = canon("chain-%02d" % (MAX_SYMLINK_HOPS + 4),
              cwd=ws["repo"], home=ws["home"])
    assert c.is_loop and c.error == "SYMLINK_LOOP" and not c.valid


# ---------------------------------------------------------------------------
# 3. missing paths
# ---------------------------------------------------------------------------

def test_missing_path_recorded_not_fabricated(ws):
    c = canon("nope/AGENTS.md", cwd=ws["repo"], home=ws["home"])
    assert not c.exists and not c.is_file and not c.is_dir
    assert c.valid and c.error is None
    assert c.canonical_path == str(ws["repo"] / "nope" / "AGENTS.md")
    assert c.resolved_path == c.canonical_path  # lexical rest appended


def test_missing_intermediate_directory(ws):
    c = canon("ghost/deep/AGENTS.md", cwd=ws["repo"], home=ws["home"])
    assert not c.exists
    assert c.resolved_path == str(ws["repo"] / "ghost" / "deep" / "AGENTS.md")


# ---------------------------------------------------------------------------
# 4. Unicode paths
# ---------------------------------------------------------------------------

def test_unicode_path_round_trip(ws):
    uni = ws["repo"] / "ünïcode-✓" / "AGENTS-✓.md"
    uni.parent.mkdir(parents=True)
    uni.write_text("u\n", encoding="utf-8")
    c = canon(str(uni), cwd=ws["repo"], home=ws["home"])
    assert c.canonical_path == str(uni)
    assert c.exists and c.is_file
    # Canonical JSON round-trips the name byte-identically (UTF-8).
    blob = json.dumps(c.to_dict(), ensure_ascii=False)
    assert "AGENTS-✓.md" in blob
    assert json.loads(blob)["canonical_path"] == str(uni)


def test_unicode_cjk_path(ws):
    p = ws["repo"] / "中文" / "说明.md"
    p.parent.mkdir(parents=True)
    p.write_text("zh\n", encoding="utf-8")
    c = canon(str(p), cwd=ws["repo"], home=ws["home"])
    assert c.exists and c.canonical_path == str(p)


# ---------------------------------------------------------------------------
# 5. root containment + escape detection
# ---------------------------------------------------------------------------

def test_containment_inside_repo(ws):
    assert is_within_root(str(ws["repo"] / "services" / "AGENTS.md"),
                          str(ws["repo"]))
    assert is_within_root(str(ws["repo"]), str(ws["repo"]))  # root itself
    assert is_within_root(str(ws["repo"] / "services"), str(ws["repo"]))


def test_containment_outside_repo(ws):
    assert not is_within_root(str(ws["outside"] / "Downloads" / "AGENTS.md"),
                              str(ws["repo"]))
    assert not is_within_root(str(ws["tmp"] / "other"), str(ws["repo"]))


def test_containment_prefix_is_not_containment(ws):
    # /repo2 shares a string prefix with /repo but is not inside it.
    assert not is_within_root(str(ws["tmp"] / "repo2" / "x.md"),
                              str(ws["repo"]))
    assert not is_within_root(str(ws["tmp"] / "repo-sibling"),
                              str(ws["repo"]))


def test_containment_dotdot_escape(ws):
    assert not is_within_root(
        lexical_canonical("services/../../outside/Downloads/AGENTS.md",
                          cwd=str(ws["repo"]), home=str(ws["home"])),
        str(ws["repo"]))


def test_containment_root_slash_contains_all(ws):
    assert is_within_root(str(ws["repo"] / "AGENTS.md"), "/")


def test_symlink_escape_lexical_inside_resolved_outside(ws):
    os.symlink("../outside/Downloads/AGENTS.md", ws["repo"] / "escape.md")
    c = canon("escape.md", cwd=ws["repo"], home=ws["home"])
    assert is_within_root(c.canonical_path, str(ws["repo"]))      # lexical: inside
    assert not is_within_root(c.resolved_path, str(ws["repo"]))   # resolved: outside
    esc = detect_escape(c.resolved_path, (str(ws["repo"]),))
    assert esc.escaped and esc.within_roots == ()


def test_escape_with_multiple_roots_user_scope_not_escaped(ws):
    c = canon("~/.codex/AGENTS.md", cwd=ws["repo"], home=ws["home"])
    esc = detect_escape(c.resolved_path, (str(ws["repo"]), str(ws["home"])))
    assert not esc.escaped
    assert esc.within_roots == (str(ws["home"]),)


def test_escape_with_no_roots_is_fail_closed(ws):
    c = canon("AGENTS.md", cwd=ws["repo"], home=ws["home"])
    assert detect_escape(c.resolved_path, ()).escaped
    assert detect_escape(None, (str(ws["repo"]),)).escaped  # loop: no path


def test_redact_home(ws):
    assert redact_home(str(ws["home"] / ".codex" / "AGENTS.md"),
                       str(ws["home"])) == "<HOME>/.codex/AGENTS.md"
    assert redact_home(str(ws["home"]), str(ws["home"])) == "<HOME>"
    assert redact_home(str(ws["repo"] / "AGENTS.md"),
                       str(ws["home"])) == str(ws["repo"] / "AGENTS.md")


# ---------------------------------------------------------------------------
# 6. Windows-style spellings (pure string only — no FS resolution)
# ---------------------------------------------------------------------------

def test_windows_drive_letter_normalisation():
    assert normalize_windows_path("C:\\repo\\services\\..\\AGENTS.md") == "C:/repo/AGENTS.md"
    assert normalize_windows_path("C:/repo//services///AGENTS.md") == "C:/repo/services/AGENTS.md"
    assert normalize_windows_path("D:\\Downloads\\AGENTS.md") == "D:/Downloads/AGENTS.md"


def test_windows_unc_normalisation():
    assert normalize_windows_path("\\\\server\\share\\repo\\AGENTS.md") == "//server/share/repo/AGENTS.md"


def test_windows_style_detection():
    assert is_windows_style_path("C:\\a\\b")
    assert is_windows_style_path("C:/a/b")
    assert is_windows_style_path("\\\\server\\share\\x")
    assert not is_windows_style_path("/repo/AGENTS.md")
    assert not is_windows_style_path("services/AGENTS.md")


def test_windows_drive_relative_rejected():
    with pytest.raises(ValueError):
        normalize_windows_path("C:foo\\bar")


def test_windows_cases_from_committed_fixture():
    data = json.loads((FIXTURES_FS / "cases" / "windows" / "windows-paths.json")
                      .read_text(encoding="utf-8"))
    assert data["cases"]
    for item in data["cases"]:
        assert normalize_windows_path(item["raw"]) == item["expected"]


@pytest.mark.skip(reason="NOT_RUN on Linux: real junction resolution needs "
                         "a Windows filesystem (T011 owns the Windows runner)")
def test_windows_junction_resolution():
    raise AssertionError("must not run on Linux")


@pytest.mark.skip(reason="NOT_RUN on Linux: real drive-letter resolution needs "
                         "a Windows filesystem (T011 owns the Windows runner)")
def test_windows_drive_letter_resolution():
    raise AssertionError("must not run on Linux")


# ---------------------------------------------------------------------------
# 7. snapshot: single entries, workspace, determinism
# ---------------------------------------------------------------------------

def test_snapshot_entry_plain_file(ws):
    e = snapshot_entry("AGENTS.md", cwd=str(ws["repo"]),
                       home=str(ws["home"]), repo_root=str(ws["repo"]))
    assert e.exists and e.is_file
    assert e.sha256 == hashlib.sha256(b"root\n").hexdigest()
    assert e.size == 5
    assert e.contained_in == {"home": False, "repo": True}
    assert not e.escapes_all_roots
    assert e.error is None


def test_snapshot_entry_missing_path(ws):
    e = snapshot_entry("ghost.md", cwd=str(ws["repo"]),
                       home=str(ws["home"]), repo_root=str(ws["repo"]))
    assert not e.exists and e.sha256 is None and e.size is None
    assert e.error is None  # missing is a state, not an error


def test_snapshot_entry_broken_symlink(ws):
    os.symlink("gone.md", ws["repo"] / "broken.md")
    e = snapshot_entry("broken.md", cwd=str(ws["repo"]),
                       home=str(ws["home"]), repo_root=str(ws["repo"]))
    assert e.is_broken_symlink and not e.exists and e.sha256 is None


def test_snapshot_entry_symlink_escape_flagged(ws):
    os.symlink("../outside/Downloads/AGENTS.md", ws["repo"] / "escape.md")
    e = snapshot_entry("escape.md", cwd=str(ws["repo"]),
                       home=str(ws["home"]), repo_root=str(ws["repo"]))
    assert e.is_symlink
    assert e.contained_in == {"home": False, "repo": False}
    assert e.escapes_all_roots


def test_snapshot_entry_loop_is_error_not_hang(ws):
    os.symlink("loop-b", ws["repo"] / "loop-a")
    os.symlink("loop-a", ws["repo"] / "loop-b")
    start = time.monotonic()
    e = snapshot_entry("loop-a", cwd=str(ws["repo"]),
                       home=str(ws["home"]), repo_root=str(ws["repo"]))
    assert time.monotonic() - start < 5.0
    assert e.is_loop and e.error == "SYMLINK_LOOP"
    assert e.resolved_path is None and e.sha256 is None


def test_snapshot_entry_unicode(ws):
    p = ws["repo"] / "中文" / "说明.md"
    p.parent.mkdir(parents=True)
    p.write_text("zh\n", encoding="utf-8")
    e = snapshot_entry(str(p), cwd=str(ws["repo"]),
                       home=str(ws["home"]), repo_root=str(ws["repo"]))
    assert e.exists and e.canonical_path == str(p)


def test_build_snapshot_workspace_fields(ws):
    snap = build_snapshot(cwd=str(ws["repo"] / "services"),
                          home=str(ws["home"]), repo_root=str(ws["repo"]),
                          paths=["AGENTS.md", "../AGENTS.md"])
    assert snap.cwd == str(ws["repo"] / "services")
    assert snap.home == str(ws["home"])
    assert snap.repo_root == str(ws["repo"])
    assert [e.canonical_path for e in snap.entries] == sorted(
        e.canonical_path for e in snap.entries)


def test_build_snapshot_repo_root_none_allowed(ws):
    snap = build_snapshot(cwd=str(ws["repo"]), home=str(ws["home"]),
                          repo_root=None, paths=["AGENTS.md"])
    assert snap.repo_root is None
    assert len(snap.entries) == 1


def test_build_snapshot_missing_cwd_fails_closed(ws):
    with pytest.raises(SnapshotError):
        build_snapshot(cwd=str(ws["tmp"] / "nope"), home=str(ws["home"]))


def test_build_snapshot_missing_home_fails_closed(ws):
    with pytest.raises(SnapshotError):
        build_snapshot(cwd=str(ws["repo"]), home=str(ws["tmp"] / "nope"))


def test_build_snapshot_deduplicates_paths(ws):
    snap = build_snapshot(cwd=str(ws["repo"]), home=str(ws["home"]),
                          repo_root=str(ws["repo"]),
                          paths=["AGENTS.md", "./AGENTS.md",
                                 "services/../AGENTS.md"])
    assert len(snap.entries) == 1


def test_snapshot_deterministic_byte_identical(ws):
    kwargs = dict(cwd=str(ws["repo"]), home=str(ws["home"]),
                  repo_root=str(ws["repo"]), include_tree=True)
    snap1 = build_snapshot(**kwargs)
    snap2 = build_snapshot(**kwargs)
    assert snap1.to_canonical_json() == snap2.to_canonical_json()
    assert snap1.snapshot_hash() == snap2.snapshot_hash()
    assert snap1.snapshot_hash() == hashlib.sha256(
        snap1.to_canonical_json().encode("utf-8")).hexdigest()


def test_snapshot_has_no_wall_clock_fields(ws):
    snap = build_snapshot(cwd=str(ws["repo"]), home=str(ws["home"]),
                          repo_root=str(ws["repo"]), include_tree=True)
    blob = snap.to_canonical_json()
    lowered = blob.lower()
    for banned in ("timestamp", "wall-clock", "wall_clock", "duration",
                   "username", "created_at"):
        assert banned not in lowered


def test_snapshot_hash_changes_when_content_changes(ws):
    kwargs = dict(cwd=str(ws["repo"]), home=str(ws["home"]),
                  repo_root=str(ws["repo"]), paths=["AGENTS.md"])
    before = build_snapshot(**kwargs).snapshot_hash()
    (ws["repo"] / "AGENTS.md").write_text("changed\n", encoding="utf-8")
    after = build_snapshot(**kwargs).snapshot_hash()
    assert before != after


def test_snapshot_hash_stable_when_only_mtime_changes(ws):
    kwargs = dict(cwd=str(ws["repo"]), home=str(ws["home"]),
                  repo_root=str(ws["repo"]), paths=["AGENTS.md"])
    before = build_snapshot(**kwargs)
    os.utime(ws["repo"] / "AGENTS.md", (1_700_000_000, 1_700_000_000))
    after = build_snapshot(**kwargs)
    assert before.snapshot_hash() == after.snapshot_hash()
    assert before.to_canonical_json() == after.to_canonical_json()


def test_snapshot_tree_finds_all_files_sorted(ws):
    entries = snapshot_tree(ws["repo"], cwd=str(ws["repo"]),
                            home=str(ws["home"]), repo_root=str(ws["repo"]))
    paths = [e.canonical_path for e in entries]
    assert paths == sorted(paths)
    assert str(ws["repo"] / "services" / "payments" / "AGENTS.md") in paths
    assert str(ws["repo"] / "AGENTS.md") in paths
    # Root itself is the first entry by sort order (shortest prefix).
    assert entries[0].canonical_path == str(ws["repo"])
    assert entries[0].is_dir


def test_snapshot_tree_missing_root_is_single_entry(ws):
    entries = snapshot_tree(ws["repo"] / "ghost", cwd=str(ws["repo"]),
                            home=str(ws["home"]), repo_root=str(ws["repo"]))
    assert len(entries) == 1
    assert not entries[0].exists


def test_snapshot_tree_does_not_follow_dir_symlink_by_default(ws):
    os.symlink("services", ws["repo"] / "linkdir")
    entries = snapshot_tree(ws["repo"], cwd=str(ws["repo"]),
                            home=str(ws["home"]), repo_root=str(ws["repo"]))
    linkdir = [e for e in entries
               if e.canonical_path == str(ws["repo"] / "linkdir")]
    assert len(linkdir) == 1 and linkdir[0].is_symlink
    # Nothing under linkdir/ appears: the target's files are listed once,
    # under their real path.
    assert not [e for e in entries
                if e.canonical_path.startswith(str(ws["repo"] / "linkdir") + "/")]


def test_snapshot_tree_dir_symlink_loop_terminates(ws):
    os.symlink("loopdir-b", ws["repo"] / "loopdir-a")
    os.symlink("loopdir-a", ws["repo"] / "loopdir-b")
    start = time.monotonic()
    entries = snapshot_tree(ws["repo"], cwd=str(ws["repo"]),
                            home=str(ws["home"]), repo_root=str(ws["repo"]),
                            follow_dir_symlinks=True)
    assert time.monotonic() - start < 5.0
    assert [e for e in entries if e.is_loop]  # loop dirs recorded, not followed


def test_snapshot_tree_max_depth(ws):
    deep = ws["repo"]
    for i in range(5):
        deep = deep / ("d%d" % i)
    deep.mkdir(parents=True)
    (deep / "AGENTS.md").write_text("deep\n", encoding="utf-8")
    entries = snapshot_tree(ws["repo"], cwd=str(ws["repo"]),
                            home=str(ws["home"]), repo_root=str(ws["repo"]),
                            max_depth=2)
    assert [e for e in entries if e.error == "MAX_DEPTH"]
    assert not [e for e in entries
                if e.canonical_path.endswith("AGENTS.md")
                and "d4" in e.canonical_path]


def test_hash_file_matches_hashlib(ws):
    assert hash_file(str(ws["repo"] / "AGENTS.md")) == hashlib.sha256(
        b"root\n").hexdigest()


def test_committed_basic_fixture_snapshot_is_deterministic():
    case = FIXTURES_FS / "cases" / "basic"
    assert (case / "repo" / "AGENTS.md").exists()
    kwargs = dict(cwd=str(case / "repo"), home=str(case / "home"),
                  repo_root=str(case / "repo"), include_tree=True)
    snap1 = build_snapshot(**kwargs)
    snap2 = build_snapshot(**kwargs)
    assert snap1.to_canonical_json() == snap2.to_canonical_json()
    assert len(snap1.entries) == 6  # repo + services + payments + 3 AGENTS.md
    assert snap1.entries[0].canonical_path == str(case / "repo")


def test_committed_fixture_manifest_lists_all_cases():
    manifest = json.loads((FIXTURES_FS / "manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    ids = {c["case_id"] for c in manifest["cases"]}
    assert {"basic", "symlink-loop", "symlink-escape", "symlink-broken",
            "unicode", "missing", "windows"} <= ids
    for item in manifest["cases"]:
        assert (FIXTURES_FS / "cases" / item["case_id"] / "case.json").exists()


def test_snapshot_is_frozen_dataclass(ws):
    snap = build_snapshot(cwd=str(ws["repo"]), home=str(ws["home"]))
    assert isinstance(snap, FilesystemSnapshot)
    with pytest.raises(Exception):
        snap.cwd = "/other"  # frozen: assignment must fail


# ---------------------------------------------------------------------------
# 8. Windows drive branch via injected fake FS (FIX-R2 D3)
#
# Runs the Windows branch on Linux: canonicalize(..., fs=fake,
# os_name="nt"). The fake models real Windows Python (OQ-5):
# islink() returns False even for junctions — only reparse_tag()
# reveals them — so a passing test proves the resolver used the tag
# rule, not islink. These tests prove branch logic only; real
# Windows proof still belongs to the V2 pack on Sam's PC.
# ---------------------------------------------------------------------------

def _win_lexical_norm(path: str) -> str:
    """Lexically normalise a ``C:/...`` (or UNC) path: ``.`` / ``..``.

    ``..`` pops the last component and stops at the drive root (or
    at the share for UNC): it never crosses a drive.
    """
    drive = re.match(r"^([A-Za-z]:)/", path)
    unc = re.match(r"^//([^/]+)/([^/]+)/", path)
    if drive:
        root, rest = drive.group(1) + "/", path[len(drive.group(1)) + 1:]
        floor: list[str] = []
    elif unc:
        root, rest = "//" + unc.group(1) + "/" + unc.group(2) + "/", path[len(unc.group(0)):]
        floor = []
    elif path.startswith("//"):
        root, rest = "//", path[2:]
        floor = []
    else:
        root, rest = "/", path
        floor = []
    stack = list(floor)
    for comp in rest.split("/"):
        if comp in ("", "."):
            continue
        if comp == "..":
            if stack:
                stack.pop()
            continue
        stack.append(comp)
    return root + "/".join(stack)


class FakeWindowsFS:
    """In-memory Windows filesystem for FIX-R2 branch tests.

    Nodes: ``{normalised "C:/..." path: {"kind": "file" | "dir" |
    "link", "target": raw readlink string, "tag": reparse tag}}``.
    ``islink`` deliberately returns False for every node (real
    Windows ``os.path.islink`` returns False for junctions); the
    link rule lives in ``reparse_tag``. ``exists`` / ``isfile`` /
    ``isdir`` follow links to their final node.
    """

    JUNCTION = 0xA0000003
    SYMLINK = 0xA000000C

    def __init__(self, nodes):
        self._nodes = {self._norm(k): dict(v) for k, v in nodes.items()}

    @staticmethod
    def _norm(path: str) -> str:
        p = path.replace("\\", "/")
        if len(p) > 3 and p.endswith("/"):
            p = p.rstrip("/")
        return p

    def _node(self, path):
        return self._nodes.get(self._norm(path))

    def lexists(self, path):
        return self._node(path) is not None

    def islink(self, path):
        # Models real Windows Python (OQ-5): junctions are NOT links
        # by os.path.islink. The resolver must use reparse_tag.
        return False

    def reparse_tag(self, path):
        node = self._node(path)
        if node is None:
            raise FileNotFoundError(path)
        return node.get("tag")

    def readlink(self, path):
        node = self._node(path)
        if node is None or node["kind"] != "link":
            raise OSError("not a link: %s" % path)
        return node["target"]

    def _follow(self, path):
        p = self._norm(path)
        seen: set[str] = set()
        for _ in range(MAX_SYMLINK_HOPS + 1):
            node = self._nodes.get(p)
            if node is None:
                return None
            if node["kind"] != "link":
                return p
            if p in seen:
                return None
            seen.add(p)
            target = _normalize_windows_readlink_target(node["target"])
            if _DRIVE_ABS.match(target):
                p = _win_lexical_norm(target)
            elif target.startswith("//"):
                p = _win_lexical_norm(target)
            elif target.startswith("/"):
                p = _win_lexical_norm(p[:2] + target)
            else:
                parent = p.rsplit("/", 1)[0] or p[:2]
                p = _win_lexical_norm(parent + "/" + target)
        return None

    def exists(self, path):
        return self._follow(path) is not None

    def isfile(self, path):
        final = self._follow(path)
        return final is not None and self._nodes[final]["kind"] == "file"

    def isdir(self, path):
        final = self._follow(path)
        return final is not None and self._nodes[final]["kind"] == "dir"


_DRIVE_ABS = re.compile(r"^[A-Za-z]:/")


def _win_file():
    return {"kind": "file"}


def _win_dir(tag=None):
    return {"kind": "dir", "tag": tag}


def _win_link(target, tag=FakeWindowsFS.JUNCTION):
    return {"kind": "link", "target": target, "tag": tag}


def _win_canon(raw, fs):
    return canonicalize(raw, cwd="C:/repo", home="C:/home",
                        fs=fs, os_name="nt")


def test_windows_branch_drive_root_resolution():
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/AGENTS.md": _win_file(),
    })
    c = _win_canon("C:/repo/AGENTS.md", fs)
    assert c.canonical_path == "C:/repo/AGENTS.md"
    assert c.resolved_path == "C:/repo/AGENTS.md"  # no leading "/C:/"
    assert c.exists and c.is_file and not c.is_symlink
    root = _win_canon("C:/", fs)
    assert root.canonical_path == "C:/" and root.resolved_path == "C:/"
    assert root.exists and root.is_dir


def test_fixr5_leading_slash_drive_spelling_unconsumable_on_windows():
    # FIX-R5 mechanism (V4 E08-5): the ancestor chain used to emit
    # "/C:/..." entries. On a Windows host that spelling is
    # unconsumable — Windows ``ntpath.normpath("/C:/x")`` mangles it
    # into a UNC spelling ("\\\\C:\\x") that never exists — so every
    # claude-code ancestor probe missed and the CLI returned 0 sources
    # (fail-open) while the runner's stop-collapsed [cwd] walk still
    # found the file. The drive-form spelling resolves fine. This test
    # pins the mechanism (it passes before and after the fix; the
    # regression test is the chain shape in test_resolver.py).
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/CLAUDE.md": _win_file(),
    })
    missing = canonicalize("/C:/repo/CLAUDE.md", cwd="C:/repo",
                           home="C:/home", fs=fs, os_name="nt")
    assert not missing.exists and not missing.is_file
    found = canonicalize("C:/repo/CLAUDE.md", cwd="C:/repo",
                         home="C:/home", fs=fs, os_name="nt")
    assert found.exists and found.is_file
    assert found.resolved_path == "C:/repo/CLAUDE.md"


def test_windows_branch_dotdot_stops_at_drive_root():
    # Junction target ".."s past the drive root: the resolver must
    # stop at C:/, never cross to another drive or to "/".
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/link": _win_link("../../outside"),
        "C:/outside": _win_dir(),
        "C:/outside/x.md": _win_file(),
    })
    c = _win_canon("C:/repo/link/x.md", fs)
    assert c.resolved_path == "C:/outside/x.md"
    assert c.exists and c.is_symlink
    assert c.symlink_chain == ("../../outside",)


def test_windows_branch_junction_followed_via_reparse_tag():
    # Mirrors win-junction-inside: linked is a real NTFS junction
    # (tag 0xA0000003) pointing at the sibling dir "shared".
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/shared": _win_dir(),
        "C:/repo/shared/AGENTS.md": _win_file(),
        "C:/repo/linked": _win_link("shared"),
    })
    # The fake models OQ-5: islink() is False for the junction, so
    # this passing proves the resolver used the reparse tag, not it.
    assert fs.islink("C:/repo/linked") is False
    assert fs.reparse_tag("C:/repo/linked") == 0xA0000003
    c = _win_canon("C:/repo/linked/AGENTS.md", fs)
    assert c.canonical_path == "C:/repo/linked/AGENTS.md"
    assert c.resolved_path == "C:/repo/shared/AGENTS.md"
    assert c.is_symlink and c.exists and c.is_file
    assert c.symlink_chain == ("shared",)
    leaf = _win_canon("C:/repo/linked", fs)
    assert leaf.resolved_path == "C:/repo/shared"
    assert leaf.symlink_target == "shared"  # final-component target too


def test_windows_branch_readlink_verbatim_prefix_normalised():
    # CPython returns junction targets as \\?\C:\... ; the Oracle
    # returns the same target as C:\... — the prefix must be stripped
    # (and backslashes folded) before splitting and recording.
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/linked": _win_link("\\\\?\\C:\\p028-src\\shared"),
        "C:/p028-src": _win_dir(),
        "C:/p028-src/shared": _win_dir(),
        "C:/p028-src/shared/AGENTS.md": _win_file(),
    })
    c = _win_canon("C:/repo/linked/AGENTS.md", fs)
    assert c.resolved_path == "C:/p028-src/shared/AGENTS.md"
    assert c.symlink_chain == ("C:/p028-src/shared",)
    assert c.exists and c.is_symlink
    leaf = _win_canon("C:/repo/linked", fs)
    assert leaf.symlink_target == "C:/p028-src/shared"


def test_windows_branch_absolute_target_switches_drive():
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/link": _win_link("D:/other/file.md"),
        "D:/": _win_dir(),
        "D:/other": _win_dir(),
        "D:/other/file.md": _win_file(),
    })
    c = _win_canon("C:/repo/link", fs)
    assert c.resolved_path == "D:/other/file.md"
    assert c.exists and c.is_file and c.is_symlink
    assert c.symlink_target == "D:/other/file.md"
    assert c.symlink_chain == ("D:/other/file.md",)


def test_windows_branch_symlink_loop_fail_closed():
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/link-a": _win_link("link-b", tag=FakeWindowsFS.SYMLINK),
        "C:/repo/link-b": _win_link("link-a", tag=FakeWindowsFS.SYMLINK),
    })
    start = time.monotonic()
    c = _win_canon("C:/repo/link-a", fs)
    assert time.monotonic() - start < 5.0
    assert c.is_loop and not c.valid
    assert c.error == "SYMLINK_LOOP"
    assert c.resolved_path is None  # fail-closed: no resolved path asserted
    assert not c.exists


def test_windows_branch_broken_junction_missing_not_fabricated():
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/linked": _win_link("gone"),
    })
    c = _win_canon("C:/repo/linked", fs)
    assert c.is_symlink and c.is_broken_symlink
    assert not c.exists and not c.is_file
    assert c.valid and c.error is None
    assert c.resolved_path == "C:/repo/gone"


def test_windows_branch_non_link_reparse_tag_not_followed():
    # D2 is a tag *set*, not "any reparse point": a directory carrying
    # an unrelated tag (e.g. dedup 0x80000000) is not a link.
    fs = FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/plain": _win_dir(tag=0x80000000),
        "C:/repo/plain/file.md": _win_file(),
    })
    c = _win_canon("C:/repo/plain/file.md", fs)
    assert c.resolved_path == "C:/repo/plain/file.md"
    assert not c.is_symlink and c.exists and c.is_file


def test_linux_drive_letter_resolution_unchanged():
    # D1: on Linux a drive-letter spelling still resolves to /C:/...
    # (pinned by the S0 fs/windows probes and the copilot-absolute
    # fixture) — no kwargs, no fake FS, real os functions.
    c = canonicalize("C:/repo/AGENTS.md", cwd="/tmp", home="/tmp")
    assert c.canonical_path == "C:/repo/AGENTS.md"
    assert c.resolved_path == "/C:/repo/AGENTS.md"
    assert not c.exists and not c.is_symlink


# ---------------------------------------------------------------------------
# 9. FIX-R3 A + B: Windows path normalisation (V2 root causes A/B)
#
# V2 on Sam's PC (2026-11-19, RESULT=FAIL, 4/4): relative imports
# joined onto a backslash cwd fell back to "/C:\..." (A), and the
# normpath + "/" helper family failed on every Windows spelling (B).
# These tests reproduce both on Linux: the backslash cwd makes
# os.path.join produce the same mixed-separator spelling real
# Windows Python produces, and the fake FS + os_name="nt" runs the
# Windows drive branch. They prove branch logic only; real Windows
# proof still belongs to the Windows runner (V3 pack).
# ---------------------------------------------------------------------------

def _win_repo_fs():
    """Fake Windows FS mirroring win-junction-inside (class 1/3)."""
    return FakeWindowsFS({
        "C:/": _win_dir(),
        "C:/repo": _win_dir(),
        "C:/repo/shared": _win_dir(),
        "C:/repo/shared/ok.md": _win_file(),
        "C:/repo/shared/AGENTS.md": _win_file(),
        "C:/repo/linked": _win_link("shared"),
        "C:/outside": _win_dir(),
        "C:/outside/x.md": _win_file(),
    })


def test_fixr3_a_relative_import_joined_onto_backslash_cwd():
    # V2 root cause A: import "@shared/ok.md" + cwd "C:\repo" was
    # joined to "C:\repo\shared\ok.md" and never re-normalised, so
    # the drive-letter branch missed and the path became
    # "/C:\repo\shared\ok.md" -> IMPORT_ESCAPE. Before the fix this
    # canonicalises to "/C:\repo/shared/ok.md" and does not exist.
    fs = _win_repo_fs()
    c = canonicalize("shared/ok.md", cwd="C:\\repo", home="C:/home",
                     fs=fs, os_name="nt")
    assert c.canonical_path == "C:/repo/shared/ok.md"
    assert c.resolved_path == "C:/repo/shared/ok.md"
    assert c.exists and c.is_file and not c.is_symlink


def test_fixr3_a_relative_import_follows_junction():
    # V2 class 3: "@linked/also.md" must follow the junction to
    # repo/shared, not stop at repo/linked.
    fs = _win_repo_fs()
    c = canonicalize("linked/ok.md", cwd="C:\\repo", home="C:/home",
                     fs=fs, os_name="nt")
    assert c.canonical_path == "C:/repo/linked/ok.md"
    assert c.resolved_path == "C:/repo/shared/ok.md"
    assert c.exists and c.is_symlink
    assert c.symlink_chain == ("shared",)


def test_fixr3_a_relative_import_dotdot_and_backslash_ref():
    fs = _win_repo_fs()
    c = canonicalize("..\\..\\outside\\x.md", cwd="C:\\repo\\shared",
                     home="C:/home", fs=fs, os_name="nt")
    assert c.canonical_path == "C:/outside/x.md"
    assert c.resolved_path == "C:/outside/x.md"
    assert c.exists and c.is_file
    # A backslash-spelled relative reference joins the same way.
    c2 = canonicalize("shared\\ok.md", cwd="C:\\repo", home="C:/home",
                      fs=fs, os_name="nt")
    assert c2.canonical_path == "C:/repo/shared/ok.md"
    assert c2.exists


def test_fixr3_a_lexical_join_result_renormalised():
    # The join itself, without any filesystem: on Linux
    # os.path.join("C:\\repo", "shared/ok.md") is the mixed spelling
    # "C:\\repo/shared/ok.md" — it must still normalise to C:/ form.
    assert (lexical_canonical("shared/ok.md", cwd="C:\\repo",
                              home="C:/home")
            == "C:/repo/shared/ok.md")
    assert (lexical_canonical("shared\\ok.md", cwd="C:\\repo",
                              home="C:/home")
            == "C:/repo/shared/ok.md")
    # Absolute raw spellings are unaffected (already covered above).
    assert (lexical_canonical("C:\\repo\\shared\\ok.md", cwd="/tmp",
                              home="/tmp")
            == "C:/repo/shared/ok.md")


def test_fixr3_a_tilde_expands_against_backslash_home():
    # "~" expansion concatenates a backslash home with "/x"; the
    # result is a Windows spelling and must be normalised too.
    assert (lexical_canonical("~/x.md", home="C:\\Users\\Du")
            == "C:/Users/Du/x.md")
    assert lexical_canonical("~", home="C:\\Users\\Du") == "C:/Users/Du"


def test_fixr3_b_is_within_root_windows_spellings():
    # V2 root cause B: is_within_root("C:\repo\shared\AGENTS.md",
    # "C:\repo") was False (normpath backslashes vs "/" prefix).
    assert is_within_root("C:\\repo\\shared\\AGENTS.md", "C:\\repo")
    assert is_within_root("C:/repo/shared/AGENTS.md", "C:\\repo")
    assert is_within_root("C:\\repo\\shared\\AGENTS.md", "C:/repo")
    assert is_within_root("C:\\repo", "C:\\repo")  # root itself
    assert is_within_root("C:/repo/x.md", "C:/")  # drive root
    assert is_within_root("C:\\repo\\x.md", "C:/")
    assert not is_within_root("C:\\repo2\\x.md", "C:\\repo")
    assert not is_within_root("C:\\other\\x.md", "C:\\repo")
    assert not is_within_root("D:\\repo\\x.md", "C:\\repo")
    # POSIX behaviour is byte-identical (normpath is already "/").
    assert is_within_root("/repo/x.md", "/repo")
    assert not is_within_root("/repo2/x.md", "/repo")
    assert is_within_root("/repo/x.md", "/")
