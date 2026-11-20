"""Unit tests for P028 T005 — import graph + escape detection.

Covers PROJECT_BOOK.md §8.6 / §13.5 (Import Graph) against the
frozen contract (profile_contract.json ``import_syntax`` per
profile; SPEC-01 max depth 4 for Claude) and the T005 module
docstring's check order (absolute/~ → canonicalise → depth →
escape → missing → allowed).

All workspaces are synthetic directories under ``tmp_path`` (zero
real users, never the real home or a real repo). Sources are
discovered with the real T003 resolver and then fed to
``build_import_graph``; a few tests build ``SourceCandidate``
objects directly to pin edge-id / ``to`` mapping behaviour.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_src"))

from instructionroot.imports import (  # noqa: E402
    EDGE_REASONS,
    ImportGraph,
    assign_source_ids,
    build_import_graph,
    expandable_sources,
    source_id_for,
)
from instructionroot.profiles._common import SourceCandidate  # noqa: E402
from instructionroot.resolver import discover  # noqa: E402
from instructionroot.snapshot import build_snapshot  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ws(tmp_path: Path, *, harness: str, files: dict, cwd_rel: str = "repo",
        home_rel: str = "home", repo_rel: str | None = "repo",
        working_files=(), env=None):
    """Build a synthetic workspace, discover sources, return context.

    Returns ``(case_dir, sources, kwargs)`` where ``kwargs`` holds
    the ``build_import_graph`` keyword arguments for the case.
    """
    case_dir = tmp_path
    # build_snapshot requires cwd/home to exist even when empty.
    (case_dir / home_rel).mkdir(parents=True, exist_ok=True)
    (case_dir / cwd_rel).mkdir(parents=True, exist_ok=True)
    if repo_rel is not None:
        (case_dir / repo_rel).mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        _write(case_dir / rel, text)
    cwd = str(case_dir / cwd_rel)
    home = str(case_dir / home_rel)
    repo_root = str(case_dir / repo_rel) if repo_rel is not None else None
    saved = {k: os.environ.get(k) for k in (env or {})}
    try:
        os.environ.update({k: v.replace("{case}", str(case_dir))
                           for k, v in (env or {}).items()})
        snapshot = build_snapshot(
            cwd=cwd, home=home, repo_root=repo_root,
            include_tree=True, tree_root=str(case_dir),
        )
        sources = discover(
            snapshot, cwd=cwd, harness=harness,
            working_files=[str(case_dir / w) for w in working_files],
            ancestor_stop=str(case_dir),
        )
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    custom_dirs = []
    if env and "COPILOT_CUSTOM_INSTRUCTIONS_DIRS" in env:
        custom_dirs = [p.replace("{case}", str(case_dir)) for p in
                       env["COPILOT_CUSTOM_INSTRUCTIONS_DIRS"].split(",") if p.strip()]
    kwargs = dict(harness=harness, cwd=cwd, home=home,
                  repo_root=repo_root, custom_dirs=custom_dirs)
    return case_dir, sources, kwargs


def _graph(case_dir, sources, kwargs):
    return build_import_graph(sources, **kwargs)


def _by_syntax(graph):
    return {e.syntax: e for e in graph.edges}


# ---------------------------------------------------------------------------
# Helpers / ids
# ---------------------------------------------------------------------------

def test_source_id_for_and_assign():
    assert source_id_for(0) == "src-0001"
    assert source_id_for(9) == "src-0010"
    assert source_id_for(123) == "src-0124"


def test_assign_source_ids_discovery_order(tmp_path):
    _, sources, _ = _ws(tmp_path, harness="codex", files={
        "home/.codex/AGENTS.md": "user\n",
        "repo/AGENTS.md": "root\n",
    })
    assert len(sources) == 2
    mapping = assign_source_ids(sources)
    assert mapping[sources[0].canonical_path] == "src-0001"
    assert mapping[sources[1].canonical_path] == "src-0002"


# ---------------------------------------------------------------------------
# Claude: depth 0-4 PASS, depth 5 BLOCK (SPEC-01)
# ---------------------------------------------------------------------------

def test_claude_no_imports_depth0(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "plain instructions, no imports\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert graph.edges == ()
    assert graph.blocked_edges == ()


def test_claude_depth4_pass(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/a.md\n",
        "repo/shared/a.md": "@b.md\n",
        "repo/shared/b.md": "@c.md\n",
        "repo/shared/c.md": "@d.md\n",
        "repo/shared/d.md": "leaf\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert [e.depth for e in graph.edges] == [1, 2, 3, 4]
    assert all(e.allowed for e in graph.edges)
    assert all(e.reason == "WITHIN_REPO" for e in graph.edges)
    assert graph.blocked_edges == ()
    # depth-1 edge names its source; deeper edges name the file path.
    assert graph.edges[0].from_source_id == "src-0001"
    assert graph.edges[0].to_source_id is None  # target is not a source
    assert graph.edges[1].from_source_id is None
    assert graph.edges[1].from_canonical.endswith("/repo/shared/a.md")
    assert graph.edges[0].to_dict()["from"] == "src-0001"
    assert graph.edges[1].to_dict()["from"].endswith("/repo/shared/a.md")


def test_claude_depth5_block(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/a.md\n",
        "repo/shared/a.md": "@b.md\n",
        "repo/shared/b.md": "@c.md\n",
        "repo/shared/c.md": "@d.md\n",
        "repo/shared/d.md": "@e.md\n",
        "repo/shared/e.md": "too deep\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert [e.depth for e in graph.edges] == [1, 2, 3, 4, 5]
    assert graph.edges[4].allowed is False
    assert graph.edges[4].reason == "DEPTH_EXCEEDED"
    assert graph.edges[4].syntax == "@e.md"
    assert len(graph.blocked_edges) == 1
    # The depth-5 target is listed (observable BLOCK) but not expanded:
    # e.md itself contains no import, so the edge count stays 5; add a
    # would-be 6th hop through e.md in a variant below instead.


def test_claude_depth5_target_not_expanded(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/a.md\n",
        "repo/shared/a.md": "@b.md\n",
        "repo/shared/b.md": "@c.md\n",
        "repo/shared/c.md": "@d.md\n",
        "repo/shared/d.md": "@e.md\n",
        "repo/shared/e.md": "@f.md\n",  # must NOT be followed
        "repo/shared/f.md": "never reached\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert [e.syntax for e in graph.edges] == [
        "@shared/a.md", "@b.md", "@c.md", "@d.md", "@e.md",
    ]
    assert "@f.md" not in {e.syntax for e in graph.edges}


def test_claude_cycle_terminates(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/a.md\n",
        "repo/shared/a.md": "@b.md\n",
        "repo/shared/b.md": "@a.md\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert [e.syntax for e in graph.edges] == ["@shared/a.md", "@b.md", "@a.md"]
    assert [e.depth for e in graph.edges] == [1, 2, 3]
    assert all(e.allowed for e in graph.edges)


def test_claude_duplicate_reference_listed_once(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/a.md\n@shared/a.md\n",
        "repo/shared/a.md": "leaf\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 1


# ---------------------------------------------------------------------------
# Claude: escape / missing / malformed (fail-closed)
# ---------------------------------------------------------------------------

def test_claude_dotdot_escape_block(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@../outside/secret.md\n@shared/ok.md\n",
        "repo/shared/ok.md": "ok\n",
        "outside/secret.md": "outside\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    by = _by_syntax(graph)
    assert by["@../outside/secret.md"].allowed is False
    assert by["@../outside/secret.md"].reason == "IMPORT_ESCAPE"
    assert by["@shared/ok.md"].allowed is True
    assert by["@shared/ok.md"].reason == "WITHIN_REPO"


def test_claude_absolute_outside_block_but_inside_allowed(tmp_path):
    case_dir, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "placeholder\n",
        "repo/shared/ok.md": "ok\n",
        "outside/secret.md": "outside\n",
    })
    # Absolute paths are written into the file by the test (the case
    # dir is only known at runtime); rewrite CLAUDE.md accordingly.
    (case_dir / "repo" / "CLAUDE.md").write_text(
        "@%s/shared/ok.md\n@%s/secret.md\n"
        % (case_dir / "repo", case_dir / "outside"), encoding="utf-8")
    graph = _graph(case_dir, sources, kwargs)
    by = _by_syntax(graph)
    inside = "@%s/shared/ok.md" % (case_dir / "repo")
    outside = "@%s/secret.md" % (case_dir / "outside")
    assert by[inside].allowed is True
    assert by[inside].reason == "WITHIN_REPO"
    assert by[outside].allowed is False
    assert by[outside].reason == "IMPORT_ESCAPE"


def test_claude_home_import_allowed(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@~/.claude/shared.md\n",
        "home/.claude/shared.md": "shared\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 1
    assert graph.edges[0].allowed is True
    assert graph.edges[0].reason == "WITHIN_HOME"


def test_claude_missing_block(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@missing.md\n@shared/ok.md\n",
        "repo/shared/ok.md": "ok\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    by = _by_syntax(graph)
    missing = by["@missing.md"]
    assert missing.allowed is False
    assert missing.reason == "MISSING"
    assert missing.resolved_target is None
    assert missing.canonical_target is None
    assert missing.to_source_id is None
    assert by["@shared/ok.md"].allowed is True


def test_claude_directory_target_is_missing(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared\n",
        "repo/shared/ok.md": "ok\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 1
    assert graph.edges[0].allowed is False
    assert graph.edges[0].reason == "MISSING"


def test_claude_url_reference_is_missing_not_fetched(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@https://example.invalid/x.md\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 1
    assert graph.edges[0].allowed is False
    assert graph.edges[0].reason == "MISSING"
    # No network was read: the reference is a literal relative path.


def test_claude_code_spans_and_quotes_not_imported(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": (
            "```\n@shared/hidden.md\n```\n"
            "see `@shared/inline.md` for details\n"
            "see @\"shared/quoted.md\" here\n"
            "@shared/real.md\n"
        ),
        "repo/shared/real.md": "real\n",
        "repo/shared/hidden.md": "hidden\n",
        "repo/shared/inline.md": "inline\n",
        "repo/shared/quoted.md": "quoted\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert [e.syntax for e in graph.edges] == ["@shared/real.md"]


def test_claude_quote_before_at_is_parsed_by_shared_parser(tmp_path):
    # Contract wording ("a path wrapped in quotes is never
    # imported") vs T003's parser: the shared parser excludes only
    # ``@"path"`` (quote AFTER @), not ``"@path"`` (quote before @).
    # T005 reuses the T003 parser verbatim for edge parity and does
    # NOT silently change it; the gap is recorded as a contract
    # question in TASK_RESULT.md for the coordinator / T003.
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": 'see "@shared/quoted.md" here\n',
        "repo/shared/quoted.md": "quoted\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert [e.syntax for e in graph.edges] == ["@shared/quoted.md"]


def test_claude_tilde_user_unresolvable(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@~nosuchuser/x.md\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 1
    assert graph.edges[0].allowed is False
    assert graph.edges[0].reason == "UNRESOLVABLE"
    assert graph.edges[0].resolved_target is None


def test_claude_symlink_escape_block(tmp_path):
    case_dir, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/link.md\n",
        "outside/secret.md": "outside\n",
    })
    (case_dir / "repo" / "shared").mkdir(parents=True, exist_ok=True)
    os.symlink(str(case_dir / "outside" / "secret.md"),
               str(case_dir / "repo" / "shared" / "link.md"))
    graph = _graph(case_dir, sources, kwargs)
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.allowed is False
    assert edge.reason == "IMPORT_ESCAPE"
    assert edge.canonical_target.endswith("/repo/shared/link.md")
    assert edge.resolved_target.endswith("/outside/secret.md")


def test_claude_rules_files_not_expanded(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "plain\n",
        "repo/.claude/rules/team.md": "@shared/secret.md\n",
        "repo/shared/secret.md": "secret\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert graph.edges == ()


def test_claude_escaped_space_path(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/my\\ file.md\n",
        "repo/shared/my file.md": "with space\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 1
    assert graph.edges[0].syntax == "@shared/my file.md"
    assert graph.edges[0].allowed is True


def test_claude_to_mapping_when_target_is_a_source(tmp_path):
    # The import target (the user file) is itself a discovered
    # source, so `to` names it.
    _, sources2, kwargs2 = _ws(tmp_path, harness="claude-code", files={
        "home/.claude/CLAUDE.md": "user\n",
        "repo/CLAUDE.md": "@../home/.claude/CLAUDE.md\n",
    })
    graph = _graph(tmp_path, sources2, kwargs2)
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.allowed is True
    assert edge.reason == "WITHIN_HOME"
    assert edge.to_source_id == "src-0001"  # the user file is a source
    assert edge.to_dict()["to"] == "src-0001"


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------

def test_copilot_relative_within_repo_pass(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="copilot-cli", files={
        "repo/AGENTS.md": "@shared/rules.md\n",
        "repo/shared/rules.md": "@more.md\n",
        "repo/shared/more.md": "more\n",
        "repo/.github/copilot-instructions.md": "@../shared/repo-wide.md\n",
        "repo/shared/repo-wide.md": "wide\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 3
    assert all(e.allowed for e in graph.edges)
    assert all(e.reason == "WITHIN_REPO" for e in graph.edges)
    # Nested references are expanded for Copilot too.
    assert {e.syntax for e in graph.edges} == {
        "@shared/rules.md", "@more.md", "@../shared/repo-wide.md",
    }


def test_copilot_absolute_and_home_block(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="copilot-cli", files={
        "repo/AGENTS.md": "@/etc/nope.md\n@~/Downloads/x.md\n@shared/ok.md\n",
        "repo/shared/ok.md": "ok\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    by = _by_syntax(graph)
    assert by["@/etc/nope.md"].allowed is False
    assert by["@/etc/nope.md"].reason == "IMPORT_ESCAPE"
    assert by["@~/Downloads/x.md"].allowed is False
    assert by["@~/Downloads/x.md"].reason == "IMPORT_ESCAPE"
    assert by["@shared/ok.md"].allowed is True


def test_copilot_dotdot_escape_block(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="copilot-cli", files={
        "repo/AGENTS.md": "@../outside/secret.md\n",
        "outside/secret.md": "outside\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 1
    assert graph.edges[0].allowed is False
    assert graph.edges[0].reason == "IMPORT_ESCAPE"


def test_copilot_gemini_and_instructions_not_expanded(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="copilot-cli", files={
        "repo/GEMINI.md": "@shared/x.md\n",
        "repo/.claude/CLAUDE.md": "@shared/x.md\n",
        "repo/.github/instructions/docs.instructions.md":
            "---\napplyTo: \"**/*.py\"\n---\n@shared/x.md\n",
        "repo/shared/x.md": "x\n",
        "repo/src/app.py": "print(1)\n",
    }, working_files=["repo/src/app.py"])
    graph = _graph(tmp_path, sources, kwargs)
    # The modular file IS a source (applyTo matched) and the
    # .claude/CLAUDE.md IS a source, but neither expands @.
    assert len(sources) == 3
    assert graph.edges == ()


def test_copilot_custom_dirs(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="copilot-cli", files={
        "extra/AGENTS.md": "@local.md\n@../repo/shared/x.md\n@../outside/y.md\n",
        "extra/local.md": "local\n",
        "repo/shared/x.md": "x\n",
        "outside/y.md": "y\n",
    }, env={"COPILOT_CUSTOM_INSTRUCTIONS_DIRS": "{case}/extra"})
    graph = _graph(tmp_path, sources, kwargs)
    by = _by_syntax(graph)
    assert by["@local.md"].allowed is True
    assert by["@local.md"].reason == "WITHIN_CUSTOM_DIR"
    assert by["@../repo/shared/x.md"].allowed is True
    assert by["@../repo/shared/x.md"].reason == "WITHIN_REPO"
    assert by["@../outside/y.md"].allowed is False
    assert by["@../outside/y.md"].reason == "IMPORT_ESCAPE"


def test_copilot_missing_block(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="copilot-cli", files={
        "repo/AGENTS.md": "@missing.md\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert len(graph.edges) == 1
    assert graph.edges[0].reason == "MISSING"
    assert graph.edges[0].allowed is False


def test_copilot_no_depth_cap_but_cycle_terminates(tmp_path):
    # Copilot has no contract max depth; a 6-hop chain is allowed,
    # and a cycle still terminates (each file expanded once).
    _, sources, kwargs = _ws(tmp_path, harness="copilot-cli", files={
        "repo/AGENTS.md": "@a.md\n",
        "repo/a.md": "@b.md\n",
        "repo/b.md": "@c.md\n",
        "repo/c.md": "@d.md\n",
        "repo/d.md": "@e.md\n",
        "repo/e.md": "@f.md\n",
        "repo/f.md": "@a.md\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert [e.depth for e in graph.edges] == [1, 2, 3, 4, 5, 6, 7]
    assert all(e.allowed for e in graph.edges)


# ---------------------------------------------------------------------------
# Codex: no import syntax
# ---------------------------------------------------------------------------

def test_codex_at_text_not_parsed(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="codex", files={
        "repo/AGENTS.md": "@../outside/x.md\n@shared/y.md\n",
        "repo/shared/y.md": "y\n",
        "outside/x.md": "x\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    assert graph.edges == ()


def test_expandable_sources_per_harness(tmp_path):
    _, codex_sources, _ = _ws(tmp_path, harness="codex", files={
        "repo/AGENTS.md": "@x.md\n",
    })
    assert expandable_sources(codex_sources, harness="codex") == []
    assert expandable_sources(codex_sources, harness="unknown-harness") == []


def test_build_import_graph_rejects_empty_harness(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="codex", files={
        "repo/AGENTS.md": "x\n",
    })
    with pytest.raises(ValueError):
        build_import_graph(sources, harness="", cwd=kwargs["cwd"],
                           home=kwargs["home"])


# ---------------------------------------------------------------------------
# Edge shape / reason vocabulary
# ---------------------------------------------------------------------------

def test_edge_to_dict_is_receipt_shaped(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/a.md\n@missing.md\n",
        "repo/shared/a.md": "a\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    for edge in graph.edges:
        d = edge.to_dict()
        assert set(d) == {
            "edge_id", "from", "syntax", "to", "resolved_target",
            "allowed", "reason",
        }
        assert edge.reason in EDGE_REASONS
        assert edge.edge_id.startswith("edge-")
    assert [e.edge_id for e in graph.edges] == ["edge-0001", "edge-0002"]
    assert isinstance(graph, ImportGraph)
    assert graph.to_dict_list() == [e.to_dict() for e in graph.edges]
    assert len(graph.escape_edges) == 0  # MISSING is not an escape
    assert len(graph.blocked_edges) == 1


def test_import_graph_json_serialisable(tmp_path):
    _, sources, kwargs = _ws(tmp_path, harness="claude-code", files={
        "repo/CLAUDE.md": "@shared/a.md\n",
        "repo/shared/a.md": "a\n",
    })
    graph = _graph(tmp_path, sources, kwargs)
    text = json.dumps(graph.to_dict_list(), ensure_ascii=False)
    assert json.loads(text) == graph.to_dict_list()
