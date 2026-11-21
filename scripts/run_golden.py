#!/usr/bin/env python3
"""Golden runner for P028 (T003 owns the ``resolver`` stage,
T005 owns the ``imports`` stage).

Usage (from the P028 work directory):

    .venv/bin/python scripts/run_golden.py --stage resolver [--cases S01,S02] [-v]
    .venv/bin/python scripts/run_golden.py --stage imports [--cases ...] [-v]

Resolver stage (T003): for each case under
``01_s0/fixtures/resolver/<case-id>/`` it builds a snapshot,
discovers sources and compares them against
``<case-id>.expected.json`` (set + order + not-applicable +
Claude import candidates). Output:

    golden_source_order=100.0%
    golden_source_set=100.0%
    cases=20 passed=20 failed=0

Imports stage (T005): for each case under
``01_s0/fixtures/imports/<case-id>/`` it builds a snapshot,
discovers sources, builds the import graph
(``instructionroot.imports.build_import_graph``) and compares the
edges against ``<case-id>.expected.json`` — edge parity over
``(from, syntax, depth, canonical target, resolved target,
allowed, reason)`` — plus escape detection (every expected
blocked edge must be produced with ``allowed=false``) and the
verdict derived by ``receipt.derive_verdict`` over receipt
sources built with *synthetic trust* (in-repo files treated as
GIT_TRACKED, home files as USER_SCOPE, via the real T004
classifier; real Git state is T004/T007's job, not this
stage's). Output:

    golden_edge_parity=100.0%
    golden_escape_detection=100.0%
    cases=15 passed=15 failed=0

Exit code 0 only when both metrics are 100% (and, for resolver,
both source metrics are 100%). No network, no wall-clock in any
comparison; only paths, rules, phases, precedence kinds, import
depths, reasons and verdicts are compared — never file contents.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKDIR / "02_src"))

from instructionroot.profiles import claude as claude_profile  # noqa: E402
from instructionroot.resolver import discover_with_report  # noqa: E402
from instructionroot.snapshot import build_snapshot  # noqa: E402

FIXTURES_DIR = WORKDIR / "01_s0" / "fixtures" / "resolver"


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _rel(canonical: str | None, case_dir: Path) -> str | None:
    if canonical is None:
        return None
    try:
        return os.path.relpath(canonical, str(case_dir)).replace(os.sep, "/")
    except ValueError:
        return canonical


def run_case(case_dir: Path, *, verbose: bool = False) -> dict:
    """Run one resolver case; return its comparison result."""
    case = _load_json(case_dir / "case.json")
    expected = _load_json(case_dir / (case["case_id"] + ".expected.json"))
    case_id = case["case_id"]
    failures: list[str] = []

    def _resolve(rel_path, *, allow_none=False):
        if rel_path is None:
            if allow_none:
                return None
            raise ValueError("null path where a path is required")
        return str(case_dir / rel_path)

    cwd = _resolve(case["cwd"])
    home = _resolve(case["home"])
    repo_root = _resolve(case["repo_root"], allow_none=True)
    policy = case.get("policy", "default")
    if policy == "default":
        policy_arg = None
    elif isinstance(policy, dict):
        policy_arg = policy
    else:
        raise ValueError("unsupported policy value in %s" % case_id)

    working = [_resolve(p) for p in case.get("working_files", [])]
    env_overrides = {
        k: v.replace("{case}", str(case_dir))
        for k, v in (case.get("env") or {}).items()
    }

    saved_env = {k: os.environ.get(k) for k in env_overrides}
    try:
        os.environ.update(env_overrides)
        snapshot = build_snapshot(
            cwd=cwd, home=home, repo_root=repo_root,
            include_tree=True, tree_root=str(case_dir),
        )
        report = discover_with_report(
            snapshot, cwd=cwd, policy=policy_arg,
            harness=case["harness"],
            profile_version=case.get("profile_version"),
            working_files=working,
            ancestor_stop=str(case_dir),
        )
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # --- sources: set + order -------------------------------------
    actual_pairs = [
        (s.discovery_rule, _rel(s.canonical_path, case_dir))
        for s in report.sources
    ]
    expected_pairs = [
        (e["discovery_rule"], e["relative_path"])
        for e in expected["expected_sources"]
    ]
    set_ok = sorted(actual_pairs) == sorted(expected_pairs)
    if not set_ok:
        failures.append(
            "source set mismatch: expected %r, got %r"
            % (sorted(expected_pairs), sorted(actual_pairs))
        )
    if case["harness"] == "copilot-cli":
        # COMBINE_UNORDERED: order is not asserted (see README).
        order_ok = set_ok
    else:
        order_ok = actual_pairs == expected_pairs
        if not order_ok:
            failures.append(
                "source order mismatch: expected %r, got %r"
                % (expected_pairs, actual_pairs)
            )

    # --- per-source fields (scope/phase/precedence/also) ----------
    for exp in expected["expected_sources"]:
        matches = [
            s for s in report.sources
            if s.discovery_rule == exp["discovery_rule"]
            and _rel(s.canonical_path, case_dir) == exp["relative_path"]
        ]
        if not matches:
            continue  # already reported as a set mismatch
        actual = matches[0]
        for field, key in (
            ("scope", "scope"), ("phase", "phase"),
        ):
            if exp.get(key) is not None and getattr(actual, field) != exp[key]:
                failures.append(
                    "%s %s: %s expected %r, got %r"
                    % (exp["relative_path"], exp["discovery_rule"], field,
                       exp[key], getattr(actual, field))
                )
        if exp.get("precedence_kind") is not None and \
                actual.precedence.kind != exp["precedence_kind"]:
            failures.append(
                "%s %s: precedence_kind expected %r, got %r"
                % (exp["relative_path"], exp["discovery_rule"],
                   exp["precedence_kind"], actual.precedence.kind)
            )
        if "also_discovered_by" in exp and \
                sorted(actual.also_discovered_by) != sorted(exp["also_discovered_by"]):
            failures.append(
                "%s %s: also_discovered_by expected %r, got %r"
                % (exp["relative_path"], exp["discovery_rule"],
                   exp["also_discovered_by"], list(actual.also_discovered_by))
            )

    # --- expected source count ------------------------------------
    if "expected_source_count" in expected and \
            expected["expected_source_count"] != len(report.sources):
        failures.append(
            "source count expected %d, got %d"
            % (expected["expected_source_count"], len(report.sources))
        )

    # --- not-applicable -------------------------------------------
    expected_na = [
        (e["relative_path"], e["reason"])
        for e in expected.get("expected_not_applicable", [])
    ]
    if expected_na:
        actual_na = sorted({
            (_rel(n.canonical_path, case_dir) or n.raw_path, n.reason)
            for n in report.not_applicable
        })
        # Not-applicable entries may carry a raw path when the
        # canonical path was never computed; normalise both sides
        # to case-relative form for comparison.
        def _norm(pair):
            rel_path, reason = pair
            if rel_path is None:
                return (None, reason)
            if os.path.isabs(rel_path):
                return (_rel(rel_path, case_dir), reason)
            return (rel_path, reason)

        actual_na = sorted({_norm(p) for p in actual_na})
        expected_na = sorted({_norm(p) for p in expected_na})
        if actual_na != expected_na:
            failures.append(
                "not-applicable mismatch: expected %r, got %r"
                % (expected_na, actual_na)
            )

    # --- Claude import candidates ---------------------------------
    expected_imports = expected.get("expected_import_candidates", [])
    if expected_imports:
        candidates = claude_profile.iter_import_candidates(
            _report_ctx(report, snapshot), list(report.sources)
        )
        actual_imports = sorted([
            (
                _rel(c.from_canonical, case_dir),
                c.syntax,
                c.depth,
                _rel(c.canonical_target, case_dir),
                c.allowed,
                c.reason,
            )
            for c in candidates
        ])
        expected_tuples = sorted([
            (
                e["from_relative_path"],
                e["syntax"],
                e["depth"],
                e["relative_target"],
                e["allowed"],
                e["reason"],
            )
            for e in expected_imports
        ])
        if actual_imports != expected_tuples:
            failures.append(
                "import candidates mismatch: expected %r, got %r"
                % (expected_tuples, actual_imports)
            )

    if verbose or failures:
        status = "PASS" if not failures else "FAIL"
        print("[%s] %s (%s)" % (status, case_id, case["harness"]))
        for failure in failures:
            print("       %s" % failure)
    return {
        "case_id": case_id,
        "harness": case["harness"],
        "order_ok": order_ok,
        "set_ok": set_ok,
        "passed": not failures,
        "failures": failures,
    }


def _report_ctx(report, snapshot):
    """Rebuild the ResolveContext the import walk needs.

    The candidates walk needs the same context the discovery used
    (cwd/home/policy/working files); the report itself does not
    carry it, so it is reconstructed from the snapshot + report.
    """
    from instructionroot.profiles._common import ResolveContext
    from instructionroot.resolver import DEFAULT_POLICY

    return ResolveContext(
        snapshot=snapshot,
        cwd=snapshot.cwd,
        home=snapshot.home,
        repo_root=snapshot.repo_root,
        policy=dict(DEFAULT_POLICY),
    )


# ---------------------------------------------------------------------------
# Imports stage (T005)
# ---------------------------------------------------------------------------

IMPORTS_FIXTURES_DIR = WORKDIR / "01_s0" / "fixtures" / "imports"


def _rel_or_abs(canonical: str | None, case_dir: Path) -> str | None:
    """Case-relative path, or the absolute path when outside the case.

    Expected files write in-case targets case-relative, but an
    absolute target outside the case tree (e.g. ``/etc/...``) is
    written absolute — the comparison must use the same form.
    """
    if canonical is None:
        return None
    rel = os.path.relpath(canonical, str(case_dir)).replace(os.sep, "/")
    if rel == ".." or rel.startswith("../"):
        return canonical
    return rel


def run_imports_case(case_dir: Path, *, verbose: bool = False) -> dict:
    """Run one imports case; return its comparison result."""
    from instructionroot.git import GitState
    from instructionroot.imports import build_import_graph
    from instructionroot.receipt import build_receipt, build_source_record
    from instructionroot.trust import classify_trust

    case = _load_json(case_dir / "case.json")
    expected = _load_json(case_dir / (case["case_id"] + ".expected.json"))
    case_id = case["case_id"]
    failures: list[str] = []

    def _resolve(rel_path, *, allow_none=False):
        if rel_path is None:
            if allow_none:
                return None
            raise ValueError("null path where a path is required")
        return str(case_dir / rel_path)

    cwd = _resolve(case["cwd"])
    home = _resolve(case["home"])
    repo_root = _resolve(case["repo_root"], allow_none=True)
    policy = case.get("policy", "default")
    if policy == "default":
        policy_arg = None
    elif isinstance(policy, dict):
        policy_arg = policy
    else:
        raise ValueError("unsupported policy value in %s" % case_id)

    working = [_resolve(p) for p in case.get("working_files", [])]
    env_overrides = {
        k: v.replace("{case}", str(case_dir))
        for k, v in (case.get("env") or {}).items()
    }
    custom_dirs = [
        p for p in
        env_overrides.get("COPILOT_CUSTOM_INSTRUCTIONS_DIRS", "").split(",")
        if p.strip()
    ]

    saved_env = {k: os.environ.get(k) for k in env_overrides}
    try:
        os.environ.update(env_overrides)
        snapshot = build_snapshot(
            cwd=cwd, home=home, repo_root=repo_root,
            include_tree=True, tree_root=str(case_dir),
        )
        report = discover_with_report(
            snapshot, cwd=cwd, policy=policy_arg,
            harness=case["harness"],
            profile_version=case.get("profile_version"),
            working_files=working,
            ancestor_stop=str(case_dir),
        )
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    graph = build_import_graph(
        list(report.sources),
        harness=case["harness"],
        cwd=cwd, home=home, repo_root=repo_root,
        custom_dirs=custom_dirs,
    )

    # --- edges: exact multiset --------------------------------------
    actual_edges = sorted([
        (
            _rel(e.from_canonical, case_dir),
            e.syntax,
            e.depth,
            _rel_or_abs(e.canonical_target, case_dir),
            _rel_or_abs(e.resolved_target, case_dir),
            e.allowed,
            e.reason,
        )
        for e in graph.edges
    ])
    expected_edges = sorted([
        (
            e["from_relative_path"],
            e["syntax"],
            e["depth"],
            e["relative_target"],
            e["relative_resolved_target"],
            e["allowed"],
            e["reason"],
        )
        for e in expected["expected_edges"]
    ])
    edge_ok = actual_edges == expected_edges
    if not edge_ok:
        failures.append(
            "edge mismatch: expected %r, got %r"
            % (expected_edges, actual_edges)
        )
    if "expected_edge_count" in expected and \
            expected["expected_edge_count"] != len(graph.edges):
        failures.append(
            "edge count expected %d, got %d"
            % (expected["expected_edge_count"], len(graph.edges))
        )

    # --- escape detection: every expected blocked edge must block --
    expected_blocked = [
        (e["from_relative_path"], e["syntax"])
        for e in expected["expected_edges"] if not e["allowed"]
    ]
    actual_blocked = {
        (_rel(e.from_canonical, case_dir), e.syntax)
        for e in graph.edges if not e.allowed
    }
    blocked_detected = sum(
        1 for key in expected_blocked if key in actual_blocked
    )
    blocked_total = len(expected_blocked)
    escape_ok = blocked_detected == blocked_total

    # --- verdict under synthetic trust ------------------------------
    # In-repo files are treated as GIT_TRACKED, home files as
    # USER_SCOPE (real Git state is T004/T007's job). The verdict
    # pins the edge -> BLOCK link (any blocked edge blocks) and
    # the clean-chain PASS.
    synthetic_git = GitState(
        repo=repo_root, tracked=True, modified=False, head_commit=None,
        is_git_repo=repo_root is not None, error=None,
    )
    records = []
    for index, src in enumerate(report.sources):
        trust = classify_trust(
            src.resolved_path, repo_root=repo_root, home=home,
            git_state=synthetic_git, canonical_path=src.canonical_path,
            is_symlink=src.is_symlink, exists=True,
            precedence_kind=src.precedence.kind, scope=src.scope,
        )
        records.append(build_source_record(
            src, git=synthetic_git, trust=trust.trust,
            source_id="src-%04d" % (index + 1),
        ))
    receipt = build_receipt(
        profile=case["harness"],
        profile_version=case.get("profile_version"),
        cwd=cwd, repo_root=repo_root, home=home,
        sources=records, edges=graph.to_dict_list(), policy=policy_arg,
    )
    if receipt["verdict"] != expected["expected_verdict"]:
        failures.append(
            "verdict mismatch: expected %r, got %r"
            % (expected["expected_verdict"], receipt["verdict"])
        )

    if verbose or failures:
        status = "PASS" if not failures else "FAIL"
        print("[%s] %s (%s)" % (status, case_id, case["harness"]))
        for failure in failures:
            print("       %s" % failure)
    return {
        "case_id": case_id,
        "harness": case["harness"],
        "edge_ok": edge_ok,
        "blocked_detected": blocked_detected,
        "blocked_total": blocked_total,
        "escape_ok": escape_ok,
        "passed": not failures,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P028 golden runner")
    parser.add_argument("--stage", required=True,
                        help="golden stage to run (resolver, imports)")
    parser.add_argument("--cases", default=None,
                        help="comma-separated case ids to run (default: all)")
    parser.add_argument("--root", default=None,
                        help="work directory (default: repository root)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.stage not in ("resolver", "imports"):
        print("stage %r is not implemented (only: resolver, imports)"
              % args.stage)
        return 2
    if args.root is not None:
        global FIXTURES_DIR
        if args.stage == "resolver":
            FIXTURES_DIR = Path(args.root) / "01_s0" / "fixtures" / "resolver"
        else:
            global IMPORTS_FIXTURES_DIR
            IMPORTS_FIXTURES_DIR = (
                Path(args.root) / "01_s0" / "fixtures" / "imports"
            )

    wanted = None
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",") if c.strip()}

    if args.stage == "imports":
        case_dirs = sorted(
            d for d in IMPORTS_FIXTURES_DIR.iterdir()
            if d.is_dir() and (d / "case.json").exists()
        )
        if wanted is not None:
            case_dirs = [d for d in case_dirs if d.name in wanted]
        if not case_dirs:
            print("no imports cases found under %s" % IMPORTS_FIXTURES_DIR)
            return 2
        results = [run_imports_case(d, verbose=args.verbose) for d in case_dirs]
        n = len(results)
        edge_ok = sum(1 for r in results if r["edge_ok"])
        blocked_detected = sum(r["blocked_detected"] for r in results)
        blocked_total = sum(r["blocked_total"] for r in results)
        passed = sum(1 for r in results if r["passed"])
        print("cases=%d passed=%d failed=%d" % (n, passed, n - passed))
        print("golden_edge_parity=%.1f%%" % (100.0 * edge_ok / n))
        escape_pct = (
            100.0 if blocked_total == 0
            else 100.0 * blocked_detected / blocked_total
        )
        print("golden_escape_detection=%.1f%%" % escape_pct)
        return 0 if (passed == n and edge_ok == n
                     and blocked_detected == blocked_total) else 1

    case_dirs = sorted(
        d for d in FIXTURES_DIR.iterdir()
        if d.is_dir() and (d / "case.json").exists()
    )
    if wanted is not None:
        case_dirs = [d for d in case_dirs if d.name in wanted]
    if not case_dirs:
        print("no resolver cases found under %s" % FIXTURES_DIR)
        return 2

    results = [run_case(d, verbose=args.verbose) for d in case_dirs]
    n = len(results)
    order_ok = sum(1 for r in results if r["order_ok"])
    set_ok = sum(1 for r in results if r["set_ok"])
    passed = sum(1 for r in results if r["passed"])
    print("cases=%d passed=%d failed=%d" % (n, passed, n - passed))
    print("golden_source_order=%.1f%%" % (100.0 * order_ok / n))
    print("golden_source_set=%.1f%%" % (100.0 * set_ok / n))
    return 0 if (order_ok == n and set_ok == n) else 1


if __name__ == "__main__":
    raise SystemExit(main())
