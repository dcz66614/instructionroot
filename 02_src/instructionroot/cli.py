"""Command-line interface for P028 InstructionRoot Resolve (T008).

Thin shell over the frozen production modules — it *reuses* the
resolver / trust / import / receipt machinery and adds no new
resolution semantics of its own:

* discovery: :func:`instructionroot.resolver.discover_with_report`
* git state: :func:`instructionroot.git.get_git_state`
* trust: :func:`instructionroot.trust.classify_trust`
* import graph: :func:`instructionroot.imports.build_import_graph`
* receipt + verdict + exit codes:
  :func:`instructionroot.receipt.build_receipt` /
  :func:`instructionroot.receipt.exit_code_for_verdict`

The receipt assembly in :func:`build_receipt_for` *is* the shared
assembly path: ``scripts/compare_oracle.py::build_production_receipt``
delegates to it (FIX-R5), so the CLI's receipts agree with the Oracle
on the same input — the ``oracle`` subcommand checks exactly that.

Commands (PROJECT_BOOK.md §14.1 / IMPLEMENTATION_PLAN.md §13.1)::

    instructionroot inspect [--harness ... --cwd ... --format ...]
    instructionroot verify  [--harness ... --cwd ... --policy ...]
    instructionroot export  [--harness ... --cwd ... --format ... --output ...]
    instructionroot profile list
    instructionroot oracle  [--harness ... --cwd ...]
    instructionroot version

Exit codes (PROJECT_BOOK.md §8.8 / receipt_schema.json — the book
wins where the two disagree; see TASK_RESULT.md for the one
conflict found)::

    PASS                 0
    WARN                10
    BLOCK               20
    INPUT_ERROR         30
    UNSUPPORTED_PROFILE 40
    INTERNAL_ERROR      50

``verify`` exits with the verdict's code (``--allow-warn`` makes a
WARN verdict exit 0). ``inspect`` / ``export`` / ``profile list`` /
``oracle`` exit 0 whenever they successfully produce their output,
whatever the receipt verdict is — they are reporting tools, not
gates; only ``verify`` is the gate. All three error verdicts exit
non-zero and never emit a PASS verdict.

Fail-closed rules:

* unknown harness id or a profile version that is not the frozen
  version for that id → UNSUPPORTED_PROFILE (40);
* missing CWD, unreadable / malformed policy file, unknown policy
  field, non-bool policy value → INPUT_ERROR (30);
* any unexpected failure → INTERNAL_ERROR (50), never a PASS.
* policy is validated with :func:`instructionroot.receipt.validate_policy`
  (unknown fields / non-bool values raise ``ValueError``) before any
  discovery runs.

Policy file format: a JSON object with the 13 frozen
``policy_schema.json`` fields (flat), or the same object wrapped as
``{"values": {...}}`` (the receipt's ``policy`` shape) or
``{"policy": {...}}``. Omitted fields take the frozen defaults.
``--strict`` sets ``treat_warn_as_block=true`` on top of the
file/default policy.

Formats: ``terminal`` (human summary, home redacted as ``<HOME>``
for display only — the receipt hash always uses the unredacted
canonical path), ``json`` (the receipt dict, pretty-printed),
``md`` (Markdown report) and ``html`` (standalone static HTML, no
external references). ``--format`` accepts one value for
``inspect`` / ``verify`` and a comma-separated list for ``export``.

``oracle`` runs the independent Rust Oracle binary
(``03_oracle/rust/target/release/instructionroot-oracle``; built
with ``cargo build --release --locked`` when it is missing) on the
same harness / CWD / home / policy input and reports per-bucket
parity (sources, trust, edges, verdict, receipt hash). A parity
mismatch is INTERNAL_ERROR (50): the two implementations disagree,
so no verdict from either side may be trusted. This subcommand
delegates the *full-corpus* comparison to
``scripts/compare_oracle.py --all``; it only checks the one input
it was given.

No network, no LLM, no instruction content is ever printed: only
paths, hashes, Git state, trust values and rule ids leave this
module.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

__all__ = [
    "CLI_VERSION",
    "CliError",
    "EXIT_CODES",
    "PROFILES",
    "build_receipt_for",
    "format_html",
    "format_json",
    "format_markdown",
    "format_terminal",
    "load_policy_file",
    "main",
]

#: CLI version (``instructionroot version``). The receipt / profile
#: versions are frozen in the contract and are reported separately.
CLI_VERSION = "1.0.0"

#: Exit codes (PROJECT_BOOK.md §8.8 / receipt_schema.json).
EXIT_CODES: dict[str, int] = {
    "PASS": 0,
    "WARN": 10,
    "BLOCK": 20,
    "INPUT_ERROR": 30,
    "UNSUPPORTED_PROFILE": 40,
    "INTERNAL_ERROR": 50,
}

#: Frozen profile metadata (00_contract/profile_contract.json).
#: Mirrors instructionroot.receipt.PROFILE_VERSIONS /
#: PROFILE_RULES_HASHES; display names and source URLs are copied
#: verbatim from the contract so `profile list` needs no contract
#: file at runtime.
PROFILES: tuple[dict[str, str], ...] = (
    {
        "id": "codex",
        "version": "codex-2026-11",
        "display_name": "OpenAI Codex CLI",
        "source_url": (
            "https://developers.openai.com/cookbook/examples/"
            "gpt-5/codex_prompting_guide"
        ),
        "rules_hash": (
            "sha256:a0a03c1cdd77f8d9110ccbc77dae937e30e288a2609e6b04b60d26d15af5dc23"
        ),
    },
    {
        "id": "claude-code",
        "version": "claude-code-2026-11",
        "display_name": "Anthropic Claude Code",
        "source_url": "https://docs.anthropic.com/zh-CN/docs/claude-code/memory",
        "rules_hash": (
            "sha256:7f1d074dc0bb8dde1eace4c01498f8899b8ef58aa47f71c32c649768104f6058"
        ),
    },
    {
        "id": "copilot-cli",
        "version": "copilot-cli-2026-11",
        "display_name": "GitHub Copilot CLI",
        "source_url": (
            "https://docs.github.com/en/copilot/how-tos/copilot-cli/"
            "customize-copilot/add-custom-instructions"
        ),
        "rules_hash": (
            "sha256:76a5f6c8fbd7fc4ff910bf5f471ecb9291ab2a575d871f93338fb1b298c73d0e"
        ),
    },
)

_PROFILE_VERSIONS = {p["id"]: p["version"] for p in PROFILES}

#: Environment variables the Oracle case input must carry so the
#: Oracle sees the same discovery inputs as production (the Oracle
#: reads env only from its case file, never from the process env).
_ORACLE_ENV_KEYS = (
    "COPILOT_CUSTOM_INSTRUCTIONS_DIRS",
    "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD",
    "COPILOT_HOME",
)

_WORKDIR = Path(__file__).resolve().parents[2]
_ORACLE_MANIFEST = _WORKDIR / "03_oracle" / "rust" / "Cargo.toml"
_ORACLE_BIN = (
    _WORKDIR / "03_oracle" / "rust" / "target" / "release"
    / "instructionroot-oracle"
)


class CliError(Exception):
    """A CLI failure with a frozen verdict (never a PASS).

    ``verdict`` is one of INPUT_ERROR / UNSUPPORTED_PROFILE /
    INTERNAL_ERROR; :func:`main` maps it to the frozen exit code.
    """

    def __init__(self, message: str, verdict: str = "INPUT_ERROR") -> None:
        if verdict not in ("INPUT_ERROR", "UNSUPPORTED_PROFILE", "INTERNAL_ERROR"):
            raise ValueError("unknown error verdict: %r" % verdict)
        super().__init__(message)
        self.message = message
        self.verdict = verdict

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.verdict]


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------

def load_policy_file(path) -> dict:
    """Load and validate a policy JSON file; return merged policy values.

    Accepts the flat 13-field object, or the same object wrapped as
    ``{"values": {...}}`` / ``{"policy": {...}}``. Unknown fields and
    non-bool values raise :class:`CliError` (INPUT_ERROR) via
    :func:`instructionroot.receipt.validate_policy`; unreadable or
    malformed JSON likewise. Never returns a partial policy.
    """
    from instructionroot.receipt import validate_policy

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError("cannot read policy file %s: %s" % (path, exc)) from exc
    try:
        raw = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise CliError(
            "policy file %s is not valid JSON: %s" % (path, exc)
        ) from exc
    if isinstance(raw, dict) and isinstance(raw.get("values"), dict):
        raw = raw["values"]
    elif isinstance(raw, dict) and isinstance(raw.get("policy"), dict):
        raw = raw["policy"]
    if not isinstance(raw, dict):
        raise CliError(
            "policy file %s must contain a JSON object of policy fields"
            % path
        )
    try:
        return validate_policy(raw)
    except ValueError as exc:
        raise CliError("invalid policy in %s: %s" % (path, exc)) from exc


# ---------------------------------------------------------------------------
# Receipt assembly (reuses the production modules; this IS the shared
# assembly path — scripts/compare_oracle.py::build_production_receipt
# delegates here, FIX-R5)
# ---------------------------------------------------------------------------

def _split_env_dirs(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def build_receipt_for(
    *,
    harness: str,
    cwd,
    home=None,
    repo_root=None,
    policy=None,
    profile_version: str | None = None,
    working_files=(),
    ancestor_stop=None,
):
    """Build the deterministic receipt for one harness run.

    Returns ``(receipt, report)`` where ``report`` is the
    :class:`instructionroot.resolver.DiscoveryReport` (sources +
    ``considered_but_not_applicable``). Raises
    :class:`instructionroot.resolver.UnsupportedProfileError` for an
    unknown harness / version and :class:`ValueError` for a missing
    CWD or an invalid policy — the caller maps those to the frozen
    error verdicts. The snapshot is built without a tree walk: the
    profiles read directory listings live and
    :func:`instructionroot.profiles._common.make_candidate` falls
    back to a live content hash when no snapshot entry exists, so a
    tree walk would only cost time, not change the receipt.

    This is the *single* receipt-assembly path:
    ``scripts/compare_oracle.py::build_production_receipt`` delegates
    to this function (with ``ancestor_stop`` set to the case dir),
    so the CLI and the frozen library path cannot drift apart again
    (FIX-R5). ``ancestor_stop`` is ``None`` for real runs (the real
    filesystem root bounds the ancestor walk); fixtures pass their
    case directory so the walk cannot escape the fixture.

    FIX-R5 (F6-in-CLI): the receipt's ``workspace`` fields carry the
    *lexical* CWD / repo root / home (the frozen schema's "canonical
    absolute path", FIX-F6 in the Oracle) — the same spelling the
    library path passes — while discovery itself runs on the resolved
    snapshot CWD. Passing the resolved CWD here made ``workspace.cwd``
    (and the receipt hash) differ from the library whenever the CWD
    went through a symlink/junction.

    FIX-R5 (repo_root=None): ``repo_root=None`` means *no repository*
    — it is NOT auto-detected here. The old code called
    ``find_repo_root(cwd)`` when ``repo_root`` was ``None``, which
    made a fixture with an explicit null repo root (``codex-norepo``:
    "chain is the CWD only") silently pick up the enclosing git repo
    and return 3 sources / PASS where the library and the Oracle
    return 2 sources / BLOCK. Auto-detection is a CLI-command concern
    (``--repo-root`` help: "default: auto-detected") and lives in
    :func:`_run_receipt_command`, which resolves it and passes the
    result explicitly — so this function is a pure function of its
    inputs, exactly like the Oracle's ``resolve_case``.
    """
    from instructionroot.git import get_git_state
    from instructionroot.imports import build_import_graph
    from instructionroot.paths import lexical_canonical
    from instructionroot.receipt import (
        build_receipt,
        build_source_record,
        validate_policy,
    )
    from instructionroot.resolver import discover_with_report
    from instructionroot.snapshot import build_snapshot
    from instructionroot.trust import classify_trust

    if not isinstance(harness, str) or harness == "":
        from instructionroot.resolver import UnsupportedProfileError

        raise UnsupportedProfileError("no harness given")
    merged_policy = validate_policy(policy)

    cwd_text = os.path.abspath(os.fspath(cwd))
    if not os.path.isdir(cwd_text):
        raise ValueError("cwd does not exist or is not a directory: %s" % cwd_text)
    home_text = (
        os.path.abspath(os.path.expanduser("~"))
        if home is None else os.path.abspath(os.fspath(home))
    )
    if not os.path.isdir(home_text):
        raise ValueError("home does not exist or is not a directory: %s" % home_text)
    if repo_root is None:
        # No repository (FIX-R5): do NOT auto-detect here — see the
        # docstring. The CLI command layer resolves --repo-root
        # auto-detection and passes it explicitly.
        repo_root_text = None
    else:
        repo_root_text = os.path.abspath(os.fspath(repo_root))
        if not os.path.isdir(repo_root_text):
            raise ValueError(
                "repo_root does not exist or is not a directory: %s"
                % repo_root_text
            )
    # Lexical workspace spellings (FIX-R5 / FIX-F6): what the receipt
    # records. Discovery below still runs on the resolved snapshot
    # paths; only the receipt (and the import graph, which the library
    # path feeds with the same raw spellings) sees the lexical form.
    cwd_lexical = lexical_canonical(cwd_text)
    home_lexical = lexical_canonical(home_text)
    repo_lexical = (
        None if repo_root_text is None
        else lexical_canonical(repo_root_text)
    )

    snapshot = build_snapshot(
        cwd=cwd_text, home=home_text, repo_root=repo_root_text,
    )
    cwd_resolved = snapshot.cwd
    home_resolved = snapshot.home
    repo_resolved = snapshot.repo_root

    report = discover_with_report(
        snapshot, cwd=cwd_resolved, policy=merged_policy, harness=harness,
        profile_version=profile_version,
        working_files=tuple(working_files),
        ancestor_stop=ancestor_stop,
    )
    custom_dirs = _split_env_dirs(os.environ.get("COPILOT_CUSTOM_INSTRUCTIONS_DIRS"))
    graph = build_import_graph(
        list(report.sources),
        harness=harness,
        cwd=cwd_lexical, home=home_lexical, repo_root=repo_lexical,
        custom_dirs=custom_dirs,
    )
    # Import-escape trust override (same rule as compare_oracle.py):
    # a source reached by an escaping import edge is IMPORT_ESCAPE.
    escape_targets = {
        e.canonical_target for e in graph.edges
        if e.reason == "IMPORT_ESCAPE" and e.canonical_target is not None
    }
    records = []
    for index, src in enumerate(report.sources):
        probe = src.resolved_path or src.canonical_path
        git_state = get_git_state(probe, repo_root=repo_resolved)
        is_import_escape = src.canonical_path in escape_targets and any(
            e.canonical_target == src.canonical_path
            and e.reason == "IMPORT_ESCAPE" for e in graph.edges
        )
        trust = classify_trust(
            src.resolved_path, repo_root=repo_resolved, home=home_resolved,
            git_state=git_state, canonical_path=src.canonical_path,
            is_symlink=src.is_symlink, exists=True,
            is_import_escape=is_import_escape,
            precedence_kind=src.precedence.kind, scope=src.scope,
        )
        records.append(build_source_record(
            src, git=git_state, trust=trust.trust,
            source_id="src-%04d" % (index + 1),
        ))
    receipt = build_receipt(
        profile=harness,
        profile_version=profile_version,
        cwd=cwd_lexical, repo_root=repo_lexical, home=home_lexical,
        sources=records, edges=graph.to_dict_list(), policy=merged_policy,
    )
    return receipt, report


def _run_receipt_command(args) -> tuple[dict, object]:
    """Shared input handling for inspect / verify / export / oracle.

    Loads the policy file (if any), applies ``--strict``, and builds
    the receipt. Maps production exceptions to :class:`CliError`:
    unknown harness/version → UNSUPPORTED_PROFILE (40), bad
    cwd/policy → INPUT_ERROR (30), anything else → INTERNAL_ERROR
    (50). Never returns a receipt on an error path.
    """
    from instructionroot.resolver import UnsupportedProfileError

    policy = None
    if args.policy:
        policy = load_policy_file(args.policy)
    if getattr(args, "strict", False):
        base = dict(policy) if policy is not None else {}
        base["treat_warn_as_block"] = True
        policy = base
    # --repo-root auto-detection lives here (FIX-R5): build_receipt_for
    # treats repo_root=None as "no repository", so the command layer
    # resolves the documented default ("auto-detected") and passes the
    # result explicitly. The Oracle case input is built from the
    # production receipt, so both sides still see the same repo_root.
    repo_root = args.repo_root
    if repo_root is None:
        from instructionroot.git import find_repo_root

        repo_root = find_repo_root(args.cwd)
    try:
        receipt, report = build_receipt_for(
            harness=args.harness,
            cwd=args.cwd,
            home=args.home,
            repo_root=repo_root,
            policy=policy,
            profile_version=args.profile_version,
            working_files=getattr(args, "working_file", None) or (),
        )
    except UnsupportedProfileError as exc:
        raise CliError(str(exc), "UNSUPPORTED_PROFILE") from exc
    except ValueError as exc:
        raise CliError(str(exc), "INPUT_ERROR") from exc
    except Exception as exc:  # fail-closed: never a PASS on surprise
        raise CliError("internal error: %s: %s"
                       % (exc.__class__.__name__, exc), "INTERNAL_ERROR") from exc
    return receipt, report


# ---------------------------------------------------------------------------
# Formatters (display only — the receipt dict is never mutated)
# ---------------------------------------------------------------------------

def _display_path(path: str | None, home: str | None) -> str:
    if path is None:
        return "(none)"
    if home:
        from instructionroot.paths import redact_home

        try:
            return redact_home(path, home)
        except (TypeError, ValueError):
            return path
    return path


def _git_state_label(git: dict) -> str:
    """Display label for a receipt ``git`` object.

    ``no-repo`` when the file is in no repository at all (the
    receipt's ``tracked: false`` alone would read as "untracked",
    which wrongly implies a repository exists).
    """
    if git.get("repo") is None:
        return "no-repo"
    if git.get("tracked") and not git.get("modified"):
        return "tracked"
    if git.get("modified"):
        return "modified"
    return "untracked"


def _verdict_line(receipt: dict) -> str:
    sources = receipt.get("sources", [])
    blocked = sum(1 for s in sources if s.get("trust") in (
        "OUTSIDE_REPO", "SYMLINK_ESCAPE", "IMPORT_ESCAPE", "MISSING",
        "NOT_OBSERVED"))
    warnings = sum(1 for s in sources if s.get("trust") in (
        "GIT_UNTRACKED", "GIT_MODIFIED"))
    return "sources=%d blocked=%d warnings=%d" % (len(sources), blocked, warnings)


def format_terminal(receipt: dict, report=None) -> str:
    """Human-readable summary (PROJECT_BOOK.md §7.1 / §19.2 shape)."""
    from instructionroot.receipt import exit_code_for_verdict

    home = receipt.get("workspace", {}).get("home")
    lines = [
        "InstructionRoot Resolve %s" % CLI_VERSION,
        "Harness: %s (%s)"
        % (receipt["profile"]["id"], receipt["profile"]["version"]),
        "CWD:     %s" % _display_path(receipt["workspace"]["cwd"], home),
        "Repo:    %s"
        % _display_path(receipt["workspace"].get("repo_root"), home),
        "",
        "VERDICT: %s (exit %d)"
        % (receipt["verdict"], exit_code_for_verdict(receipt["verdict"])),
        _verdict_line(receipt),
        "",
    ]
    for index, src in enumerate(receipt.get("sources", []), 1):
        git_state = _git_state_label(src.get("git", {}))
        sha = src.get("sha256") or "(missing)"
        lines.append("%d  %s" % (index, _display_path(src["canonical_path"], home)))
        lines.append("   %s / %s / %s / %s"
                     % (src.get("trust"), src.get("scope"),
                        src.get("phase"), git_state))
        lines.append("   discovered_by: %s" % src.get("discovery_rule"))
        lines.append("   sha256: %s" % sha[:12] if len(sha) >= 12 else "   sha256: %s" % sha)
    if receipt.get("edges"):
        lines.append("")
        lines.append("Import edges:")
        for edge in receipt["edges"]:
            lines.append("  %s --%s--> %s [%s, allowed=%s]"
                         % (edge.get("from"), edge.get("syntax"),
                            edge.get("to") or edge.get("resolved_target") or "(missing)",
                            edge.get("reason"), edge.get("allowed")))
    if report is not None and getattr(report, "not_applicable", ()):
        lines.append("")
        lines.append("Considered but not applicable (not in the receipt):")
        for item in report.not_applicable:
            lines.append("  %s [%s] %s"
                         % (_display_path(item.canonical_path or item.raw_path, home),
                            item.discovery_rule, item.reason))
    lines.append("")
    lines.append("receipt_hash: %s" % receipt.get("receipt_hash"))
    return "\n".join(lines) + "\n"


def format_json(receipt: dict) -> str:
    """The receipt dict as deterministic pretty-printed JSON."""
    return json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def format_markdown(receipt: dict, report=None) -> str:
    """Markdown report: verdict header, source table, edges, hash."""
    home = receipt.get("workspace", {}).get("home")
    lines = [
        "# InstructionRoot Resolve — receipt",
        "",
        "- **Harness:** %s (%s)"
        % (receipt["profile"]["id"], receipt["profile"]["version"]),
        "- **CWD:** `%s`" % _display_path(receipt["workspace"]["cwd"], home),
        "- **Repo:** `%s`"
        % _display_path(receipt["workspace"].get("repo_root"), home),
        "- **Verdict:** **%s**" % receipt["verdict"],
        "- **Receipt hash:** `%s`" % receipt.get("receipt_hash"),
        "",
        "## Sources (%d)" % len(receipt.get("sources", [])),
        "",
        "| # | Path | Trust | Scope | Phase | Discovery rule | Git | SHA-256 |",
        "|---|------|-------|-------|-------|----------------|-----|---------|",
    ]
    for index, src in enumerate(receipt.get("sources", []), 1):
        git_state = _git_state_label(src.get("git", {}))
        lines.append("| %d | `%s` | %s | %s | %s | %s | %s | `%s` |"
                     % (index, _display_path(src["canonical_path"], home),
                        src.get("trust"), src.get("scope"), src.get("phase"),
                        src.get("discovery_rule"), git_state,
                        (src.get("sha256") or "")[:12]))
    lines.append("")
    lines.append("## Import edges (%d)" % len(receipt.get("edges", [])))
    lines.append("")
    if receipt.get("edges"):
        lines.append("| From | Reference | To | Allowed | Reason |")
        lines.append("|------|-----------|----|---------|--------|")
        for edge in receipt["edges"]:
            lines.append("| `%s` | `%s` | `%s` | %s | %s |"
                         % (edge.get("from"), edge.get("syntax"),
                            edge.get("to") or edge.get("resolved_target") or "",
                            edge.get("allowed"), edge.get("reason")))
    else:
        lines.append("None.")
    if report is not None and getattr(report, "not_applicable", ()):
        lines.append("")
        lines.append("## Considered but not applicable (not in the receipt)")
        lines.append("")
        for item in report.not_applicable:
            lines.append("- `%s` [%s] %s"
                         % (_display_path(item.canonical_path or item.raw_path, home),
                            item.discovery_rule, item.reason))
    lines.append("")
    lines.append("Receipt hash: `%s`" % receipt.get("receipt_hash"))
    return "\n".join(lines) + "\n"


def format_html(receipt: dict, report=None) -> str:
    """Standalone static HTML report (no external references)."""
    home = receipt.get("workspace", {}).get("home")
    esc = html_lib.escape
    verdict = receipt["verdict"]
    colour = {"PASS": "#1a7f37", "WARN": "#9a6700", "BLOCK": "#cf222e"}.get(
        verdict, "#57606a")
    rows = []
    for index, src in enumerate(receipt.get("sources", []), 1):
        git_state = _git_state_label(src.get("git", {}))
        rows.append(
            "<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td></tr>"
            % (index, esc(_display_path(src["canonical_path"], home)),
               esc(str(src.get("trust"))), esc(str(src.get("scope"))),
               esc(str(src.get("phase"))), esc(str(src.get("discovery_rule"))),
               esc(git_state), esc((src.get("sha256") or "")[:12])))
    edge_rows = []
    for edge in receipt.get("edges", []):
        edge_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (esc(str(edge.get("from"))), esc(str(edge.get("syntax"))),
               esc(str(edge.get("to") or edge.get("resolved_target") or "")),
               esc(str(edge.get("allowed"))), esc(str(edge.get("reason")))))
    na = ""
    if report is not None and getattr(report, "not_applicable", ()):
        items = "".join(
            "<li>%s [%s] %s</li>"
            % (esc(_display_path(i.canonical_path or i.raw_path, home)),
               esc(i.discovery_rule), esc(i.reason))
            for i in report.not_applicable)
        na = "<h2>Considered but not applicable (not in the receipt)</h2><ul>%s</ul>" % items
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>InstructionRoot Resolve — %s</title>\n"
        "<style>body{font-family:system-ui,sans-serif;margin:2em;max-width:960px}"
        "h1 .v{color:%s}table{border-collapse:collapse;width:100%%}"
        "th,td{border:1px solid #ccc;padding:4px 8px;text-align:left;"
        "font-size:14px}th{background:#f6f8fa}code{font-size:13px}"
        "pre{background:#f6f8fa;padding:1em;overflow:auto}</style>\n"
        "</head>\n<body>\n"
        "<h1>InstructionRoot Resolve — <span class=\"v\">%s</span></h1>\n"
        "<p>Harness: %s (%s)<br>CWD: <code>%s</code><br>Repo: <code>%s</code><br>"
        "%s<br>Receipt hash: <code>%s</code></p>\n"
        "<h2>Sources (%d)</h2>\n"
        "<table><tr><th>#</th><th>Path</th><th>Trust</th><th>Scope</th>"
        "<th>Phase</th><th>Discovery rule</th><th>Git</th><th>SHA-256</th></tr>%s</table>\n"
        "<h2>Import edges (%d)</h2>\n"
        "<table><tr><th>From</th><th>Reference</th><th>To</th>"
        "<th>Allowed</th><th>Reason</th></tr>%s</table>\n"
        "%s"
        "<h2>Raw receipt (JSON)</h2>\n<pre>%s</pre>\n"
        "</body>\n</html>\n"
        % (esc(verdict), colour, esc(verdict),
           esc(receipt["profile"]["id"]), esc(receipt["profile"]["version"]),
           esc(_display_path(receipt["workspace"]["cwd"], home)),
           esc(_display_path(receipt["workspace"].get("repo_root"), home)),
           esc(_verdict_line(receipt)), esc(str(receipt.get("receipt_hash"))),
           len(receipt.get("sources", [])), "".join(rows),
           len(receipt.get("edges", [])), "".join(edge_rows), na,
           esc(format_json(receipt)))
    )


_FORMATTERS = {
    "terminal": format_terminal,
    "json": format_json,
    "md": format_markdown,
    "html": format_html,
}


def render(receipt: dict, fmt: str, report=None) -> str:
    """Render *receipt* in one format (``terminal``/``json``/``md``/``html``)."""
    try:
        formatter = _FORMATTERS[fmt]
    except KeyError:
        raise CliError("unknown format: %r" % fmt) from None
    if fmt == "json":
        return formatter(receipt)
    return formatter(receipt, report)


# ---------------------------------------------------------------------------
# Oracle subcommand
# ---------------------------------------------------------------------------

def _ensure_oracle_binary() -> Path:
    """Return the Oracle binary path, building it once if missing."""
    if _ORACLE_BIN.exists():
        return _ORACLE_BIN
    cargo_dir = Path.home() / ".cargo" / "bin"
    env = dict(os.environ)
    env["PATH"] = str(cargo_dir) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["cargo", "build", "--release", "--locked",
         "--manifest-path", str(_ORACLE_MANIFEST)],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0 or not _ORACLE_BIN.exists():
        raise CliError(
            "cannot build the Oracle binary: %s%s"
            % (result.stdout, result.stderr),
            "INTERNAL_ERROR",
        )
    return _ORACLE_BIN


def _oracle_case_input(receipt: dict, report, args, policy: dict) -> dict:
    """Build the Oracle case input for the same run (mirrors
    scripts/compare_oracle.py::build_case_input)."""
    workspace = receipt["workspace"]
    env = {
        key: os.environ[key] for key in _ORACLE_ENV_KEYS if key in os.environ
    }
    return {
        "case_id": "cli-oracle",
        "harness": receipt["profile"]["id"],
        "profile_version": receipt["profile"]["version"],
        "cwd": workspace["cwd"],
        "home": workspace["home"],
        "repo_root": workspace.get("repo_root"),
        "policy": policy,
        "working_files": list(getattr(args, "working_file", None) or ()),
        "env": env,
        "ancestor_stop": None,
    }


def _compare_receipts(production: dict, oracle: dict) -> dict[str, bool]:
    """Per-bucket parity between a production and an Oracle receipt."""
    def _src_key(receipt):
        return [
            (s["discovery_rule"], s["canonical_path"], s["scope"],
             s["phase"], s["precedence"]["kind"])
            for s in receipt.get("sources", [])
        ]

    def _trust_key(receipt):
        return [
            (s["canonical_path"], s["trust"],
             s["git"]["tracked"], s["git"]["modified"],
             s["git"]["head_commit"])
            for s in receipt.get("sources", [])
        ]

    def _edge_key(receipt):
        return sorted(
            (e["from"], e["syntax"], e["to"],
             e.get("resolved_target"), e["allowed"], e["reason"])
            for e in receipt.get("edges", [])
        )

    return {
        "sources": _src_key(production) == _src_key(oracle),
        "trust": _trust_key(production) == _trust_key(oracle),
        "edges": _edge_key(production) == _edge_key(oracle),
        "verdict": production.get("verdict") == oracle.get("verdict"),
        "receipt_hash": (
            production.get("receipt_hash") == oracle.get("receipt_hash")),
    }


def cmd_oracle(args) -> int:
    """Run the Rust Oracle on the same input; report parity."""
    receipt, report = _run_receipt_command(args)
    # The merged policy is already in the receipt (build_receipt
    # always includes it); reuse it so the Oracle sees exactly the
    # policy production used — no second policy load.
    merged_policy = receipt["policy"]["values"]
    oracle_bin = _ensure_oracle_binary()
    case_input = _oracle_case_input(receipt, report, args, merged_policy)
    with tempfile.TemporaryDirectory(prefix="instructionroot-oracle-") as tmp:
        case_path = Path(tmp) / "case.json"
        case_path.write_text(json.dumps(case_input), encoding="utf-8")
        explain_path = Path(tmp) / "explain.json"
        try:
            result = subprocess.run(
                [str(oracle_bin), "resolve", str(case_path),
                 "--explain", str(explain_path)],
                capture_output=True, text=True, timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CliError("oracle run failed: %s" % exc, "INTERNAL_ERROR") from exc
    try:
        oracle_receipt = json.loads(result.stdout)
    except ValueError:
        raise CliError(
            "oracle produced no receipt (exit %d): %s"
            % (result.returncode, result.stderr.strip()[:500]),
            "INTERNAL_ERROR",
        ) from None
    parity = _compare_receipts(receipt, oracle_receipt)
    lines = [
        "InstructionRoot Oracle parity — %s / %s"
        % (receipt["profile"]["id"], receipt["workspace"]["cwd"]),
        "production receipt_hash: %s" % receipt.get("receipt_hash"),
        "oracle     receipt_hash: %s" % oracle_receipt.get("receipt_hash"),
        "production verdict: %s / oracle verdict: %s"
        % (receipt.get("verdict"), oracle_receipt.get("verdict")),
    ]
    for bucket in ("sources", "trust", "edges", "verdict", "receipt_hash"):
        lines.append("  %s_parity=%s" % (bucket, "100%" if parity[bucket] else "FAIL"))
    all_ok = all(parity.values())
    lines.append("RESULT: %s" % ("PARITY" if all_ok else "MISMATCH"))
    print("\n".join(lines))
    if not all_ok:
        raise CliError(
            "production/Oracle parity mismatch: %s"
            % ", ".join(k for k, v in parity.items() if not v),
            "INTERNAL_ERROR",
        )
    return 0


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _write_output(text: str, output: str | None, fmt: str) -> None:
    """Write *text* to *output* (or stdout when None)."""
    if output is None:
        print(text, end="" if text.endswith("\n") else "\n")
        return
    Path(output).write_text(text, encoding="utf-8")
    print("wrote %s (%s)" % (output, fmt))


def cmd_inspect(args) -> int:
    receipt, report = _run_receipt_command(args)
    text = render(receipt, args.format, report)
    _write_output(text, args.output, args.format)
    return 0


def cmd_verify(args) -> int:
    from instructionroot.receipt import exit_code_for_verdict

    receipt, report = _run_receipt_command(args)
    text = render(receipt, args.format, report)
    _write_output(text, args.output, args.format)
    code = exit_code_for_verdict(receipt["verdict"])
    if args.allow_warn and receipt["verdict"] == "WARN":
        code = 0
    return code


def _export_paths(output: str | None, cwd: str, formats: list[str]) -> dict[str, str]:
    """Resolve one output path per format for ``export``.

    Default: ``<cwd>/.instructionroot/receipt.<ext>`` (the
    PROJECT_BOOK.md §7.1 receipt location). ``--output`` naming an
    existing directory (or ending in ``/``) writes
    ``receipt.<ext>`` inside it; otherwise it is a file stem
    (``<stem>.json`` …) — except for a single format, where it is
    the exact file path.
    """
    if output is None:
        base_dir = Path(cwd) / ".instructionroot"
        return {fmt: str(base_dir / ("receipt." + fmt)) for fmt in formats}
    out = Path(output)
    if output.endswith("/") or (out.exists() and out.is_dir()):
        return {fmt: str(out / ("receipt." + fmt)) for fmt in formats}
    if len(formats) == 1:
        return {formats[0]: output}
    return {fmt: output + "." + fmt for fmt in formats}


def cmd_export(args) -> int:
    receipt, report = _run_receipt_command(args)
    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    unknown = [f for f in formats if f not in _FORMATTERS]
    if not formats or unknown:
        raise CliError("unknown format(s): %s" % ", ".join(unknown or ["(none)"]))
    paths = _export_paths(args.output, receipt["workspace"]["cwd"], formats)
    for fmt in formats:
        target = Path(paths[fmt])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(receipt, fmt, report), encoding="utf-8")
        print("wrote %s (%s)" % (target, fmt))
    return 0


def cmd_profile_list(args) -> int:
    if args.format == "json":
        print(json.dumps(
            {"profiles": list(PROFILES)}, indent=2, sort_keys=True,
            ensure_ascii=False))
        return 0
    lines = ["InstructionRoot profiles (frozen contract):", ""]
    for profile in PROFILES:
        lines.append("%s  %s" % (profile["id"], profile["version"]))
        lines.append("  %s" % profile["display_name"])
        lines.append("  source: %s" % profile["source_url"])
        lines.append("  rules_hash: %s" % profile["rules_hash"])
        lines.append("")
    print("\n".join(lines))
    return 0


def cmd_version(args) -> int:
    print("instructionroot %s" % CLI_VERSION)
    print("python %s" % sys.version.split()[0])
    for profile in PROFILES:
        print("profile %s %s" % (profile["id"], profile["version"]))
    if _ORACLE_BIN.exists():
        try:
            result = subprocess.run(
                [str(_ORACLE_BIN), "--version"],
                capture_output=True, text=True, timeout=30,
            )
            print(result.stdout.strip() or "oracle: (no version output)")
        except (OSError, subprocess.TimeoutExpired):
            print("oracle: (binary present, version check failed)")
    else:
        print("oracle: not built (run `instructionroot oracle` once to build)")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing / entry point
# ---------------------------------------------------------------------------

def _add_common_arguments(parser) -> None:
    parser.add_argument("--harness", required=True,
                        help="harness profile: codex, claude-code, copilot-cli")
    parser.add_argument("--cwd", default=".",
                        help="working directory the harness would start in (default: .)")
    parser.add_argument("--home", default=None,
                        help="home directory for user-scope resolution (default: ~)")
    parser.add_argument("--repo-root", default=None,
                        help="git repository top level (default: auto-detected)")
    parser.add_argument("--policy", default=None,
                        help="policy JSON file (13 frozen policy_schema v1 fields)")
    parser.add_argument("--profile-version", default=None,
                        help="required profile version; must match the frozen version")
    parser.add_argument("--working-file", action="append", default=[],
                        help="file the harness is working with (on-demand trigger; repeatable)")
    parser.add_argument("--strict", action="store_true",
                        help="treat WARN as BLOCK (treat_warn_as_block=true)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="instructionroot",
        description=(
            "InstructionRoot Resolve: determine which instruction files "
            "a coding-agent harness would load for a CWD, with provenance "
            "and a deterministic receipt. Local only, no network, no LLM."),
    )
    parser.add_argument("--version", action="version",
                        version="instructionroot %s" % CLI_VERSION)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("inspect", help="show the effective instruction chain + receipt")
    _add_common_arguments(p)
    p.add_argument("--format", default="terminal",
                   choices=["terminal", "json", "md", "html"],
                   help="output format (default: terminal)")
    p.add_argument("--output", default=None,
                   help="write the output to this file instead of stdout")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("verify", help="gate: exit non-zero on BLOCK (and WARN by default)")
    _add_common_arguments(p)
    p.add_argument("--format", default="terminal",
                   choices=["terminal", "json", "md", "html"],
                   help="output format (default: terminal)")
    p.add_argument("--output", default=None,
                   help="write the output to this file instead of stdout")
    p.add_argument("--allow-warn", action="store_true",
                   help="a WARN verdict exits 0 instead of 10")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("export", help="write the receipt to files")
    _add_common_arguments(p)
    p.add_argument("--format", default="json",
                   help="comma-separated formats: json, md, html, terminal (default: json)")
    p.add_argument("--output", default=None,
                   help="output file stem, directory, or exact path (default: <cwd>/.instructionroot/receipt.<ext>)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("profile", help="harness profile commands")
    profile_sub = p.add_subparsers(dest="profile_command", metavar="PROFILE_COMMAND")
    p_list = profile_sub.add_parser("list", help="list the frozen harness profiles")
    p_list.add_argument("--format", default="terminal",
                        choices=["terminal", "json"],
                        help="output format (default: terminal)")
    p_list.set_defaults(func=cmd_profile_list)

    p = sub.add_parser("oracle", help="run the Rust Oracle on the same input and check parity")
    _add_common_arguments(p)
    p.set_defaults(func=cmd_oracle)

    p = sub.add_parser("version", help="print versions (CLI, Python, profiles, Oracle)")
    p.set_defaults(func=cmd_version)

    return parser


def main(argv=None) -> int:
    """CLI entry point; returns the process exit code (never raises
    for an expected failure — those become a stderr error line and
    the frozen non-zero exit code)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except CliError as exc:
        print("ERROR: %s: %s" % (exc.verdict, exc.message), file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:
        return 0
    except Exception as exc:  # last-resort fail-closed guard
        print("ERROR: INTERNAL_ERROR: %s: %s"
              % (exc.__class__.__name__, exc), file=sys.stderr)
        return EXIT_CODES["INTERNAL_ERROR"]


if __name__ == "__main__":
    raise SystemExit(main())
