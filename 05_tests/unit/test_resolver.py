"""Unit tests for P028 T003 — harness resolution engine.

Covers PROJECT_BOOK.md §8.3 / §13.2 (Harness Resolution) against
the frozen contract (22 rules in profile_contract.json).

All trees are built under ``tmp_path`` (synthetic, zero real
users, never the real home or a real repo). Claude's upward walk
is bounded at ``tmp_path`` (``ancestor_stop``) so it cannot escape
the fixture and pick up real files above it.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_src"))

from instructionroot.profiles import claude as claude_profile  # noqa: E402
from instructionroot.profiles._common import (  # noqa: E402
    ancestor_chain,
    chain_dirs,
    glob_matches,
    parse_applyto,
    parse_frontmatter,
    parse_paths_frontmatter,
    relative_posix,
)
from instructionroot.profiles.claude import parse_imports  # noqa: E402
from instructionroot.resolver import (  # noqa: E402
    DEFAULT_POLICY,
    UnsupportedProfileError,
    discover,
    discover_with_report,
)
from instructionroot.snapshot import build_snapshot  # noqa: E402

WORKDIR = Path(__file__).resolve().parents[2]
PLACEHOLDER = "synthetic placeholder instruction content — P028 T003 test\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def ws(tmp_path):
    """Synthetic workspace: home/ + repo/ (+ outside/), all under tmp."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    (home / ".codex").mkdir(parents=True)
    (home / ".claude").mkdir(parents=True)
    (home / ".copilot").mkdir(parents=True)
    (repo / "services" / "payments").mkdir(parents=True)
    (outside / "Downloads").mkdir(parents=True)
    return {"tmp": tmp_path, "home": home, "repo": repo, "outside": outside}


def write(path: Path, content: str = PLACEHOLDER) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def snap(ws, *, cwd=None, repo_root="repo", tree=True):
    """Build a snapshot of the whole synthetic workspace."""
    return build_snapshot(
        cwd=str(cwd or ws["repo"] / "services" / "payments"),
        home=str(ws["home"]),
        repo_root=None if repo_root is None else str(ws["repo"]),
        include_tree=tree,
        tree_root=str(ws["tmp"]),
    )


def rules_of(sources):
    return [s.discovery_rule for s in sources]


def canon_paths(sources, base):
    return [s.canonical_path.replace(str(base), "<ws>") for s in sources]


# ---------------------------------------------------------------------------
# 1. resolver interface: errors and policy
# ---------------------------------------------------------------------------

def test_unknown_harness_raises(ws):
    s = snap(ws)
    with pytest.raises(UnsupportedProfileError):
        discover(s, harness="vscode")


def test_no_harness_raises(ws):
    s = snap(ws)
    with pytest.raises(UnsupportedProfileError):
        discover(s)


def test_wrong_profile_version_raises(ws):
    s = snap(ws)
    with pytest.raises(UnsupportedProfileError):
        discover(s, harness="codex", profile_version="codex-1999-01")


def test_correct_profile_version_ok(ws):
    write(ws["repo"] / "AGENTS.md")
    s = snap(ws)
    assert discover(s, harness="codex", profile_version="codex-2026-11")


def test_missing_cwd_raises(ws):
    s = snap(ws)
    with pytest.raises(ValueError):
        discover(s, cwd=str(ws["tmp"] / "no-such-dir"), harness="codex")


def test_unknown_policy_field_raises(ws):
    s = snap(ws)
    with pytest.raises(ValueError):
        discover(s, harness="codex", policy={"block_everything": True})


def test_non_bool_policy_field_raises(ws):
    s = snap(ws)
    with pytest.raises(ValueError):
        discover(s, harness="codex", policy={"block_repo_untracked": "yes"})


def test_default_policy_matches_contract_json():
    contract = json.loads(
        (WORKDIR / "00_contract" / "policy_schema.json").read_text(encoding="utf-8")
    )
    assert DEFAULT_POLICY == contract["default_policy"]


def test_discover_is_deterministic(ws):
    write(ws["home"] / ".codex" / "AGENTS.md")
    write(ws["repo"] / "AGENTS.md")
    write(ws["repo"] / "services" / "AGENTS.md")
    write(ws["repo"] / "services" / "payments" / "AGENTS.md")
    s = snap(ws)
    first = discover(s, harness="codex")
    second = discover(s, harness="codex")
    assert [c.canonical_path for c in first] == [c.canonical_path for c in second]
    assert [c.sha256 for c in first] == [c.sha256 for c in second]


def test_profile_kwarg_alias(ws):
    write(ws["repo"] / "AGENTS.md")
    s = snap(ws)
    assert discover(s, profile="codex")


# ---------------------------------------------------------------------------
# 2. Codex
# ---------------------------------------------------------------------------

def test_codex_root_to_leaf_order(ws):
    write(ws["home"] / ".codex" / "AGENTS.md")
    write(ws["repo"] / "AGENTS.md")
    write(ws["repo"] / "services" / "AGENTS.md")
    write(ws["repo"] / "services" / "payments" / "AGENTS.md")
    s = snap(ws)
    found = discover(s, harness="codex")
    assert rules_of(found) == [
        "codex.user",
        "codex.repo-chain",
        "codex.repo-chain",
        "codex.repo-chain",
    ]
    assert [c.precedence.kind for c in found] == ["ORDERED"] * 4
    assert [c.scope for c in found] == ["user", "project", "project", "project"]
    assert canon_paths(found, ws["tmp"]) == [
        "<ws>/home/.codex/AGENTS.md",
        "<ws>/repo/AGENTS.md",
        "<ws>/repo/services/AGENTS.md",
        "<ws>/repo/services/payments/AGENTS.md",
    ]


def test_codex_override_is_unspecified_not_guessed(ws):
    write(ws["repo"] / "services" / "AGENTS.md")
    write(ws["repo"] / "services" / "AGENTS.override.md")
    s = snap(ws)
    found = discover(s, harness="codex")
    override = [c for c in found if c.discovery_rule == "codex.override-fallback"]
    assert len(override) == 1
    assert override[0].precedence.kind == "UNSPECIFIED"
    assert override[0].scope == "project" and override[0].phase == "startup"


def test_codex_empty_chain(ws):
    s = snap(ws)
    assert discover(s, harness="codex") == []


def test_codex_non_git_cwd_only(ws):
    write(ws["home"] / ".codex" / "AGENTS.md")
    write(ws["repo"] / "AGENTS.md")
    write(ws["repo"] / "services" / "payments" / "AGENTS.md")
    s = snap(ws, repo_root=None)
    found = discover(s, harness="codex")
    assert canon_paths(found, ws["tmp"]) == [
        "<ws>/home/.codex/AGENTS.md",
        "<ws>/repo/services/payments/AGENTS.md",
    ]


def test_codex_sha256_matches_file_bytes(ws):
    import hashlib

    content = "codex user instructions\n"
    write(ws["home"] / ".codex" / "AGENTS.md", content)
    s = snap(ws)
    found = discover(s, harness="codex")
    assert found[0].sha256 == hashlib.sha256(content.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 3. Claude: chain, fallback, rules, nested
# ---------------------------------------------------------------------------

def test_claude_chain_order(ws):
    write(ws["home"] / ".claude" / "CLAUDE.md")
    write(ws["repo"] / "CLAUDE.md")
    write(ws["repo"] / "services" / ".claude" / "CLAUDE.md")
    write(ws["repo"] / "services" / "payments" / "CLAUDE.local.md")
    s = snap(ws)
    found = discover(s, harness="claude-code", ancestor_stop=str(ws["tmp"]))
    assert rules_of(found) == [
        "claude-code.user",
        "claude-code.project",
        "claude-code.project",
        "claude-code.local",
    ]
    assert [c.precedence.kind for c in found] == ["ORDERED"] * 4


def test_claude_agents_fallback_only_without_claude(ws):
    write(ws["repo"] / "AGENTS.md")
    write(ws["repo"] / "services" / "AGENTS.md")
    s = snap(ws)
    found = discover(s, harness="claude-code", ancestor_stop=str(ws["tmp"]))
    assert rules_of(found) == [
        "claude-code.agents-fallback", "claude-code.agents-fallback",
    ]


def test_claude_agents_fallback_blocked_by_one_claude(ws):
    write(ws["repo"] / "CLAUDE.md")
    write(ws["repo"] / "AGENTS.md")
    write(ws["repo"] / "services" / "payments" / "AGENTS.md")
    s = snap(ws)
    found = discover(s, harness="claude-code", ancestor_stop=str(ws["tmp"]))
    assert rules_of(found) == ["claude-code.project"]


def test_claude_user_rules_before_project_rules(ws):
    write(ws["home"] / ".claude" / "rules" / "personal.md")
    write(ws["repo"] / "CLAUDE.md")
    write(ws["repo"] / ".claude" / "rules" / "team.md")
    s = snap(ws)
    found = discover(s, harness="claude-code", ancestor_stop=str(ws["tmp"]))
    assert rules_of(found) == [
        "claude-code.rules-user",
        "claude-code.project",
        "claude-code.rules-startup",
    ]


def test_claude_path_scoped_rule_match_and_nomatch(ws):
    write(ws["repo"] / "CLAUDE.md")
    write(ws["repo"] / ".claude" / "rules" / "py.md",
          '---\npaths:\n  - "src/**/*.py"\n---\ntext\n')
    write(ws["repo"] / ".claude" / "rules" / "docs.md",
          '---\npaths: ["docs/**"]\n---\ntext\n')
    write(ws["repo"] / "src" / "app.py", "print(1)\n")
    s = snap(ws)
    report = discover_with_report(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
        working_files=[str(ws["repo"] / "src" / "app.py")],
    )
    assert rules_of(report.sources) == [
        "claude-code.project", "claude-code.rules-path-scoped",
    ]
    assert report.sources[1].precedence.kind == "UNSPECIFIED"
    assert report.sources[1].phase == "on_demand"
    assert [(n.reason) for n in report.not_applicable] == ["PATH_SCOPED_NO_MATCH"]


def test_claude_path_scoped_rule_needs_trigger(ws):
    write(ws["repo"] / ".claude" / "rules" / "py.md",
          '---\npaths: ["src/**"]\n---\ntext\n')
    s = snap(ws)
    report = discover_with_report(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
    )
    assert len(report.sources) == 0
    assert [n.reason for n in report.not_applicable] == ["PATH_SCOPED_NO_TRIGGER"]


def test_claude_unparseable_frontmatter_loads_as_no_paths(ws):
    write(ws["repo"] / ".claude" / "rules" / "broken.md",
          "---\n: bad\n---\ntext\n")
    s = snap(ws)
    found = discover(s, harness="claude-code", ancestor_stop=str(ws["tmp"]))
    assert rules_of(found) == ["claude-code.rules-startup"]


def test_claude_nested_on_demand(ws):
    write(ws["repo"] / "CLAUDE.md")
    write(ws["repo"] / "services" / "payments" / "CLAUDE.md")
    write(ws["repo"] / "services" / "payments" / "app.py", "print(1)\n")
    s = snap(ws, cwd=ws["repo"])
    found = discover(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
        working_files=[str(ws["repo"] / "services" / "payments" / "app.py")],
    )
    assert rules_of(found) == ["claude-code.project", "claude-code.nested"]
    assert found[1].scope == "nested" and found[1].phase == "on_demand"
    assert found[1].precedence.kind == "UNSPECIFIED"


def test_claude_nested_disabled_by_policy(ws):
    write(ws["repo"] / "CLAUDE.md")
    write(ws["repo"] / "services" / "payments" / "CLAUDE.md")
    s = snap(ws, cwd=ws["repo"])
    report = discover_with_report(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
        policy={"allow_nested_on_demand": False},
        working_files=[str(ws["repo"] / "services" / "payments" / "app.py")],
    )
    assert rules_of(report.sources) == ["claude-code.project"]
    assert [n.reason for n in report.not_applicable] == [
        "ON_DEMAND_DISABLED_BY_POLICY"
    ]


def test_claude_additional_dirs_policy(ws):
    extra = ws["tmp"] / "extra"
    write(extra / "CLAUDE.md")
    s = snap(ws)
    blocked = discover(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
        additional_dirs=[str(extra)],
    )
    assert blocked == []
    allowed = discover(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
        policy={"allow_additional_directories": True},
        additional_dirs=[str(extra)],
    )
    assert rules_of(allowed) == ["claude-code.additional-dirs"]
    assert allowed[0].precedence.kind == "UNSPECIFIED"


def test_claude_oversize_claude_md_skipped(ws):
    write(ws["repo"] / "CLAUDE.md", "x" * (claude_profile.CLAUDE_MD_MAX_BYTES + 1))
    s = snap(ws)
    report = discover_with_report(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
    )
    assert len(report.sources) == 0
    assert [n.reason for n in report.not_applicable] == ["OVERSIZE_CLAUDE_MD"]


def test_claude_managed_path_override(ws, tmp_path):
    managed = tmp_path / "managed-CLAUDE.md"
    write(managed)
    s = snap(ws)
    found = discover(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
        managed_path=str(managed),
    )
    assert rules_of(found) == ["claude-code.managed"]
    assert found[0].scope == "managed"


# ---------------------------------------------------------------------------
# 4. Claude @ imports: parsing + depth counting (SPEC-01: max 4 hops)
# ---------------------------------------------------------------------------

def test_parse_imports_skips_code_and_quotes():
    text = (
        "see @real/one.md and @../shared/two.md\n"
        "```\n@code/block.md\n```\n"
        "inline `@code/span.md` here\n"
        'quoted @"quoted.md" never\n'
        "escaped @with\\ space.md ok\n"
    )
    assert parse_imports(text) == [
        "real/one.md", "../shared/two.md", "with space.md",
    ]


def test_import_depth_4_pass_depth_5_block(ws):
    write(ws["repo"] / "CLAUDE.md", "@a.md\n")
    write(ws["repo"] / "a.md", "@b.md\n")
    write(ws["repo"] / "b.md", "@c.md\n")
    write(ws["repo"] / "c.md", "@d.md\n")
    write(ws["repo"] / "d.md", "@e.md\n")
    write(ws["repo"] / "e.md", "leaf\n")
    s = snap(ws)
    report = discover_with_report(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
    )
    from instructionroot.profiles._common import ResolveContext
    from instructionroot.resolver import DEFAULT_POLICY

    ctx = ResolveContext(
        snapshot=s, cwd=s.cwd, home=s.home, repo_root=s.repo_root,
        policy=dict(DEFAULT_POLICY),
    )
    cands = claude_profile.iter_import_candidates(ctx, list(report.sources))
    assert [(c.depth, c.allowed, c.reason) for c in cands] == [
        (1, True, "OK"),
        (2, True, "OK"),
        (3, True, "OK"),
        (4, True, "OK"),
        (5, False, "DEPTH_EXCEEDED"),
    ]


def test_import_missing_target(ws):
    write(ws["repo"] / "CLAUDE.md", "@nope.md\n")
    s = snap(ws)
    report = discover_with_report(
        s, harness="claude-code", ancestor_stop=str(ws["tmp"]),
    )
    from instructionroot.profiles._common import ResolveContext
    from instructionroot.resolver import DEFAULT_POLICY

    ctx = ResolveContext(
        snapshot=s, cwd=s.cwd, home=s.home, repo_root=s.repo_root,
        policy=dict(DEFAULT_POLICY),
    )
    cands = claude_profile.iter_import_candidates(ctx, list(report.sources))
    assert len(cands) == 1
    assert cands[0].allowed is False and cands[0].reason == "MISSING"
    assert cands[0].canonical_target is None


# ---------------------------------------------------------------------------
# 5. Copilot
# ---------------------------------------------------------------------------

def test_copilot_all_combine_unordered(ws):
    write(ws["home"] / ".copilot" / "copilot-instructions.md")
    write(ws["repo"] / ".github" / "copilot-instructions.md")
    write(ws["repo"] / "AGENTS.md")
    write(ws["repo"] / "CLAUDE.md")
    write(ws["repo"] / "GEMINI.md")
    s = snap(ws)
    found = discover(s, harness="copilot-cli")
    assert rules_of(found) == [
        "copilot-cli.user",
        "copilot-cli.repo-wide",
        "copilot-cli.agents",
        "copilot-cli.claude",
        "copilot-cli.gemini",
    ]
    assert {c.precedence.kind for c in found} == {"COMBINE_UNORDERED"}


def test_copilot_applyto_match_and_nomatch(ws):
    write(ws["repo"] / ".github" / "instructions" / "py.instructions.md",
          '---\napplyTo: "**/*.py"\n---\ntext\n')
    write(ws["repo"] / ".github" / "instructions" / "docs.instructions.md",
          '---\napplyTo: "docs/**"\n---\ntext\n')
    write(ws["repo"] / "src" / "app.py", "print(1)\n")
    s = snap(ws)
    report = discover_with_report(
        s, harness="copilot-cli",
        working_files=[str(ws["repo"] / "src" / "app.py")],
    )
    assert rules_of(report.sources) == ["copilot-cli.repo-modular"]
    assert report.sources[0].phase == "on_demand"
    assert [n.reason for n in report.not_applicable] == ["APPLYTO_NO_MATCH"]


def test_copilot_applyto_absent_is_excluded_not_guessed(ws):
    write(ws["repo"] / ".github" / "instructions" / "plain.instructions.md")
    write(ws["repo"] / "src" / "app.py", "print(1)\n")
    s = snap(ws)
    report = discover_with_report(
        s, harness="copilot-cli",
        working_files=[str(ws["repo"] / "src" / "app.py")],
    )
    assert len(report.sources) == 0
    assert [n.reason for n in report.not_applicable] == [
        "APPLYTO_ABSENT_UNVERIFIED"
    ]


def test_copilot_applyto_needs_working_file(ws):
    write(ws["repo"] / ".github" / "instructions" / "py.instructions.md",
          '---\napplyTo: "**/*.py"\n---\ntext\n')
    s = snap(ws)
    report = discover_with_report(s, harness="copilot-cli")
    assert len(report.sources) == 0
    assert [n.reason for n in report.not_applicable] == [
        "APPLYTO_NO_WORKING_FILE"
    ]


def test_copilot_repo_modular_excludes_intermediate_dirs(ws):
    write(ws["repo"] / ".github" / "instructions" / "root.instructions.md",
          '---\napplyTo: "**/*.py"\n---\ntext\n')
    write(ws["repo"] / "services" / ".github" / "instructions" / "mid.instructions.md",
          '---\napplyTo: "**/*.py"\n---\ntext\n')
    write(ws["repo"] / "services" / ".github" / "copilot-instructions.md")
    write(ws["repo"] / "services" / "payments" / "app.py", "print(1)\n")
    s = snap(ws)
    found = discover(
        s, harness="copilot-cli",
        working_files=[str(ws["repo"] / "services" / "payments" / "app.py")],
    )
    # repo-wide in the intermediate dir IS included; repo-modular is not.
    assert rules_of(found) == ["copilot-cli.repo-wide", "copilot-cli.repo-modular"]
    assert found[0].canonical_path.endswith("services/.github/copilot-instructions.md")
    assert found[1].canonical_path.endswith("root.instructions.md")


def test_copilot_dedup_same_file_once(ws):
    write(ws["repo"] / "AGENTS.md")
    s = snap(ws)
    found = discover(
        s, harness="copilot-cli", custom_dirs=[str(ws["repo"])],
    )
    assert len(found) == 1
    assert found[0].discovery_rule == "copilot-cli.agents"
    assert found[0].also_discovered_by == ("copilot-cli.custom-dirs",)


def test_copilot_custom_dirs_env(ws, monkeypatch):
    extra = ws["tmp"] / "extra"
    write(extra / "AGENTS.md")
    monkeypatch.setenv("COPILOT_CUSTOM_INSTRUCTIONS_DIRS", str(extra))
    s = snap(ws)
    found = discover(s, harness="copilot-cli")
    assert rules_of(found) == ["copilot-cli.custom-dirs"]


# ---------------------------------------------------------------------------
# 6. frontmatter + glob helpers
# ---------------------------------------------------------------------------

def test_parse_frontmatter_variants():
    assert parse_frontmatter("no frontmatter\n") is None
    assert parse_frontmatter("---\napplyTo: \"**/*.py\"\n---\nbody\n") == {
        "applyTo": "**/*.py"
    }
    assert parse_frontmatter("---\npaths:\n  - a/**\n  - b/*.py\n---\n") == {
        "paths": ["a/**", "b/*.py"]
    }
    assert parse_frontmatter("---\npaths: [a/**, b/*.py]\n---\n") == {
        "paths": ["a/**", "b/*.py"]
    }
    assert parse_frontmatter("---\n: bad\n---\n") is None
    assert parse_frontmatter("---\nunclosed\n") is None


def test_parse_applyto_comma_separated():
    text = '---\napplyTo: "**/*.py, **/*.pyi"\n---\n'
    assert parse_applyto(text) == ["**/*.py", "**/*.pyi"]
    assert parse_paths_frontmatter("---\npaths: docs/**\n---\n") == ["docs/**"]


def test_glob_matches_double_star_zero_dirs():
    assert glob_matches("src/**/*.py", "src/app.py")
    assert glob_matches("src/**/*.py", "src/a/b.py")
    assert not glob_matches("src/**/*.py", "other/app.py")
    assert glob_matches("**/*.py", "app.py")
    assert glob_matches("*.py", "src/app.py")
    assert not glob_matches("*.py", "src/app.md")
    assert glob_matches("docs/**", "docs/a/b.md")


def test_unicode_path_stable(ws):
    write(ws["repo"] / "ünïcode-✓" / "AGENTS-✓.md")
    write(ws["repo"] / "AGENTS.md")
    s = snap(ws)
    found = discover(s, harness="codex")
    assert len(found) == 1  # only repo/AGENTS.md is on the chain
    assert found[0].canonical_path.endswith("/repo/AGENTS.md")


# ---------------------------------------------------------------------------
# FIX-R3 B: Windows path helpers (V2 root cause B)
#
# chain_dirs / relative_posix / ancestor_chain all did
# os.path.normpath + "/"-separator comparison, which on Windows
# (normpath -> backslashes) fails every time. They now normalise
# inputs to C:/ form first; the Oracle builds the identical chains
# (its normpath_posix + "/" splits), so these values are the parity
# target. POSIX behaviour is unchanged (normpath is already "/").
# ---------------------------------------------------------------------------

def test_fixr3_b_chain_dirs_windows_spellings():
    # V2 class 1: ["…\repo\shared"] (1 source) instead of both dirs.
    assert chain_dirs("C:\\repo", "C:\\repo\\shared") == [
        "C:/repo", "C:/repo/shared"]
    assert chain_dirs("C:/repo", "C:\\repo\\shared") == [
        "C:/repo", "C:/repo/shared"]
    assert chain_dirs("C:\\repo", "C:\\repo") == ["C:/repo"]
    assert chain_dirs(None, "C:\\repo\\shared") == ["C:/repo/shared"]
    assert chain_dirs("C:\\other", "C:\\repo\\shared") == [
        "C:/repo/shared"]  # cwd not under root: just [cwd]
    # POSIX unchanged.
    assert chain_dirs("/repo", "/repo/shared") == ["/repo", "/repo/shared"]
    assert chain_dirs("/repo", "/repo") == ["/repo"]
    assert chain_dirs(None, "/repo/shared") == ["/repo/shared"]


def test_fixr3_b_relative_posix_windows_spellings():
    # V2: None instead of "AGENTS.md".
    assert (relative_posix("C:\\repo\\AGENTS.md", "C:\\repo")
            == "AGENTS.md")
    assert (relative_posix("C:/repo/shared/ok.md", "C:\\repo")
            == "shared/ok.md")
    assert relative_posix("C:\\repo", "C:\\repo") == ""
    assert relative_posix("C:\\repo\\x.md", "C:/") == "repo/x.md"
    assert relative_posix("C:\\other\\x.md", "C:\\repo") is None
    # POSIX unchanged.
    assert relative_posix("/repo/AGENTS.md", "/repo") == "AGENTS.md"
    assert relative_posix("/repo/AGENTS.md", "/") == "repo/AGENTS.md"
    assert relative_posix("/repo", "/repo") == ""
    assert relative_posix("/other/x.md", "/repo") is None


def test_fixr3_b_ancestor_chain_windows_spellings():
    # V2: ["…\repo"] (one backslash component) instead of the chain.
    # No stop: the full chain, exactly as the Oracle builds it.
    assert ancestor_chain("C:\\repo\\shared") == [
        "/", "/C:", "/C:/repo", "/C:/repo/shared"]
    assert ancestor_chain("C:/repo/shared") == [
        "/", "/C:", "/C:/repo", "/C:/repo/shared"]
    # With a stop the Oracle's identical algorithm also returns
    # just [cwd]: its chain entries are "/-prefixed, so a "C:/..."
    # stop never matches one — parity, not a bug to fix alone.
    assert ancestor_chain("C:\\repo\\shared", stop="C:\\repo") == [
        "C:/repo/shared"]
    # POSIX unchanged.
    assert ancestor_chain("/a/b/c") == ["/", "/a", "/a/b", "/a/b/c"]
    assert ancestor_chain("/a/b/c", stop="/a") == ["/a", "/a/b", "/a/b/c"]
    assert ancestor_chain("/a/b/c", stop="/") == ["/", "/a", "/a/b", "/a/b/c"]


def test_fixr5_ancestor_chain_windows_drive_form():
    # FIX-R5: on a Windows host the chain is drive-form, because the
    # "/-prefixed" shape is unconsumable there: ``canonicalize`` feeds
    # "/C:/..." to Windows ``ntpath.normpath``, which mangles it into
    # a UNC spelling ("\\\\C:\\...") that never exists — so every
    # claude-code ancestor probe missed and the CLI returned 0 sources
    # (V4 E08-5 fail-open), while the runner's stop-collapsed [cwd]
    # walk still found the file. The drive-form chain is consumable
    # (drive branch) and the stop filter now matches, so the walk is
    # [stop..cwd] instead of the degenerate [cwd] FIX-R3 recorded.
    # The Oracle mirrors this shape (profiles.rs, cfg!(windows)).
    assert ancestor_chain("C:\\repo\\shared", os_name="nt") == [
        "C:/", "C:/repo", "C:/repo/shared"]
    assert ancestor_chain("C:/repo/shared", os_name="nt") == [
        "C:/", "C:/repo", "C:/repo/shared"]
    assert ancestor_chain("C:\\repo\\shared", stop="C:\\repo",
                          os_name="nt") == ["C:/repo", "C:/repo/shared"]
    assert ancestor_chain("C:/repo/shared", stop="C:/",
                          os_name="nt") == [
        "C:/", "C:/repo", "C:/repo/shared"]
    assert ancestor_chain("C:/", os_name="nt") == ["C:/"]
    # POSIX unchanged on any host; on Linux a Windows spelling keeps
    # the pinned "/C:" shape (FIX-R3 simulation behaviour).
    assert ancestor_chain("C:\\repo\\shared") == [
        "/", "/C:", "/C:/repo", "/C:/repo/shared"]
    assert ancestor_chain("/a/b/c", os_name="nt") == [
        "/", "/a", "/a/b", "/a/b/c"]
