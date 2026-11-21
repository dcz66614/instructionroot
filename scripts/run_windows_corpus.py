#!/usr/bin/env python3
"""Windows corpus runner for P028 T011 (``fixtures/windows/``).

Checks the 13 receipt cases + 10 pure-string probes in
``fixtures/windows/expected/INDEX.json`` against the hand-written
expectations, on BOTH implementations:

* production Python receipt (``compare_oracle.build_production_receipt``)
  vs Rust Oracle receipt (``oracle resolve``) -- full receipt equality
  + receipt-hash parity + an independent RFC 8785 JCS recomputation;
* both receipts vs the hand-written index (sources incl. trust,
  receipt edges, full import-graph edges with depth, verdict,
  not-applicable, forbidden trust);
* pure-string probes: Oracle ``canonicalize`` AND production
  ``paths.canonicalize`` vs the hand-written probe expectations.

This mirrors the S0 gate's unified-index check
(``scripts/s0_gate.py`` sections 3-4, helpers copied with attribution)
but is scoped to the windows corpus and never touches the S0 gate:
``01_s0/expected/`` and ``scripts/s0_gate.py`` are not read, written,
or modified, and the S0 fixture count stays exactly 60.

The fixture trees are regenerated first (nested ``.git`` dirs cannot
be stored in git, same as the S0 corpus).

Honesty: cases that cannot genuinely execute on this Linux host are
recorded NOT_RUN in the expected index / TASK_RESULT.md and are never
reported as passes. The runner only asserts what runs here.

Usage (from the P028 work directory):

    .venv/bin/python scripts/run_windows_corpus.py [-v]

Exit code 0 only when every receipt case and every probe passes on
both implementations with 100% parity. Writes a machine-readable
summary to ``review/tasks/P028-T011/windows_corpus_summary.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKDIR / "02_src"))
sys.path.insert(0, str(WORKDIR / "scripts"))

import compare_oracle as co  # noqa: E402

WINDOWS_DIR = WORKDIR / "fixtures" / "windows"
EXPECTED_DIR = WINDOWS_DIR / "expected"
REVIEW_DIR = WORKDIR / "review" / "tasks" / "P028-T011"

EXIT_CODES = {"PASS": 0, "WARN": 10, "BLOCK": 20,
              "INPUT_ERROR": 30, "UNSUPPORTED_PROFILE": 40,
              "INTERNAL_ERROR": 50}


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --- helpers mirroring scripts/s0_gate.py (T007), adapted to this corpus ---
def _receipt_sources(receipt: dict, case_dir: Path) -> list:
    out = []
    for src in receipt["sources"]:
        out.append({
            "discovery_rule": src["discovery_rule"],
            "scope": src["scope"], "phase": src["phase"],
            "precedence_kind": src["precedence"]["kind"],
            "relative_path": co._rel(src["canonical_path"], case_dir),
            "trust": src["trust"],
        })
    return out


def _receipt_edges(receipt: dict, case_dir: Path) -> list:
    id_to_canon = {s["source_id"]: s["canonical_path"]
                   for s in receipt["sources"]}
    out = []
    for edge in receipt["edges"]:
        frm = edge["from"]
        canon = id_to_canon.get(frm, frm)
        out.append((
            co._rel(canon, case_dir),
            edge["syntax"],
            co._rel_or_abs(edge.get("resolved_target"), case_dir),
            bool(edge["allowed"]),
            edge["reason"],
        ))
    return sorted(out)


def _explain_edges(explain, case_dir: Path) -> list:
    if not explain:
        return []
    out = []
    for e in explain.get("edges", []):
        reason = e["reason"]
        if reason == "OK" and e["allowed"]:
            reason = "WITHIN_REPO"  # candidate vocabulary -> receipt vocabulary
        out.append((
            co._rel(e["from"], case_dir),
            e["syntax"], e["depth"],
            co._rel_or_abs(e.get("canonical_target"), case_dir),
            co._rel_or_abs(e.get("resolved_target"), case_dir),
            bool(e["allowed"]), reason,
        ))
    return sorted(out)


def _production_graph_edges(case_dir: Path, case: dict):
    """Production import edges with depth (receipt edges carry no depth)."""
    from instructionroot.imports import build_import_graph
    from instructionroot.resolver import discover_with_report
    from instructionroot.snapshot import build_snapshot

    cwd, home, repo_root, policy_arg, working, env = co.resolve_case_paths(
        case_dir, case)
    custom_dirs = [p for p in env.get(
        "COPILOT_CUSTOM_INSTRUCTIONS_DIRS", "").split(",") if p.strip()]
    saved_env = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        snapshot = build_snapshot(cwd=cwd, home=home, repo_root=repo_root,
                                  include_tree=True, tree_root=str(case_dir))
        report = discover_with_report(
            snapshot, cwd=cwd, policy=policy_arg, harness=case["harness"],
            profile_version=case.get("profile_version"),
            working_files=working, ancestor_stop=str(case_dir))
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    graph = build_import_graph(list(report.sources), harness=case["harness"],
                               cwd=cwd, home=home, repo_root=repo_root,
                               custom_dirs=custom_dirs)
    out = []
    for e in graph.edges:
        out.append((
            co._rel(e.from_canonical, case_dir),
            e.syntax, e.depth,
            co._rel_or_abs(e.canonical_target, case_dir),
            co._rel_or_abs(e.resolved_target, case_dir),
            bool(e.allowed), e.reason,
        ))
    return sorted(out), report


def _check_sources_against_index(case_id, actual, expected, harness, failures):
    """actual: list of dicts (rule/scope/phase/precedence/relative_path/trust)."""
    exp_list = expected["expected_sources"]
    if len(actual) != len(exp_list):
        failures.append("%s: source count %d != expected %d (actual=%r)"
                        % (case_id, len(actual), len(exp_list),
                           [(a["discovery_rule"], a["relative_path"]) for a in actual]))
        return
    if "expected_source_count" in expected and \
            expected["expected_source_count"] != len(actual):
        failures.append("%s: source count != expected_source_count" % case_id)
    pairs_actual = [(a["discovery_rule"], a["relative_path"]) for a in actual]
    pairs_exp = [(e["discovery_rule"], e["relative_path"]) for e in exp_list]
    if sorted(pairs_actual) != sorted(pairs_exp):
        failures.append("%s: source set mismatch: expected %r, got %r"
                        % (case_id, sorted(pairs_exp), sorted(pairs_actual)))
        return
    if harness != "copilot-cli" and pairs_actual != pairs_exp:
        failures.append("%s: source order mismatch: expected %r, got %r"
                        % (case_id, pairs_exp, pairs_actual))
    by_key = {(a["discovery_rule"], a["relative_path"]): a for a in actual}
    for exp in exp_list:
        act = by_key[(exp["discovery_rule"], exp["relative_path"])]
        for field in ("scope", "phase", "precedence_kind", "trust"):
            if act[field] != exp[field]:
                failures.append("%s %s: %s expected %r, got %r"
                                % (case_id, exp["relative_path"], field,
                                   exp[field], act[field]))
    forbidden = set(expected.get("forbidden_trust", []))
    leaked = sorted({a["trust"] for a in actual} & forbidden)
    if leaked:
        failures.append("%s: forbidden trust value(s) present: %r"
                        % (case_id, leaked))


def check_receipt_case(oracle, case_dir: Path, index_doc: dict, tmpdir: Path) -> dict:
    """One receipt case: production receipt + Oracle receipt vs the index."""
    case = _load_json(case_dir / "case.json")
    case_id = case["case_id"]
    failures = []
    case_input = co.build_case_input(case_dir, case)
    receipt, explain, exit_code, deterministic = co.run_oracle_resolve(
        oracle, case_input, tmpdir)
    if receipt is None:
        return {"case_id": case_id, "passed": False,
                "failures": ["oracle produced no receipt (exit %s)" % exit_code],
                "source_ok": False, "trust_ok": False, "edge_ok": False,
                "verdict_ok": False, "hash_ok": False}
    if not deterministic:
        failures.append("oracle receipt is not deterministic across two runs")
    prod, prod_err = co.build_production_receipt(case_dir, case)
    if prod_err is not None:
        return {"case_id": case_id, "passed": False,
                "failures": ["production receipt failed: %s" % prod_err],
                "source_ok": False, "trust_ok": False, "edge_ok": False,
                "verdict_ok": False, "hash_ok": False}
    # (a) production vs Oracle: full receipt equality + hash.
    # FIX-F6 closed the only known parity gap (workspace.cwd): there
    # is no special-casing any more — any receipt diff, including a
    # hash mismatch, fails the case. (The index still carries the
    # historical "known_parity_gap" records as data; the runner no
    # longer reads them.)
    diffs = co.deep_diff(receipt, prod)
    hash_ok = receipt.get("receipt_hash") == prod.get("receipt_hash")
    if diffs:
        failures.append("oracle receipt != production receipt (%d diffs): %s"
                        % (len(diffs), "; ".join(diffs[:6])))
    if not hash_ok:
        failures.append("receipt_hash mismatch: oracle %s != production %s"
                        % (receipt.get("receipt_hash"), prod.get("receipt_hash")))
    try:
        recomputed = co.receipt_hash_of(receipt)
    except Exception as exc:  # noqa: BLE001 - any recomputation failure is a failure
        recomputed = None
        failures.append("independent JCS recomputation failed: %r" % (exc,))
    if recomputed is not None and recomputed != receipt.get("receipt_hash"):
        hash_ok = False
        failures.append("receipt_hash != independent JCS hash")
    # (b) both receipts vs the hand-written index.
    for label, rec in (("production", prod), ("oracle", receipt)):
        _check_sources_against_index(
            case_id, _receipt_sources(rec, case_dir), index_doc,
            case["harness"], failures)
        if _receipt_edges(rec, case_dir) != sorted([(
                e["from_relative_path"], e["syntax"],
                e["relative_resolved_target"], bool(e["allowed"]), e["reason"])
                for e in index_doc["expected_edges"]]):
            failures.append("%s: %s receipt edges != index"
                            % (case_id, label))
        if rec.get("verdict") != index_doc["expected_verdict"]:
            failures.append("%s: %s verdict %r != expected %r"
                            % (case_id, label, rec.get("verdict"),
                               index_doc["expected_verdict"]))
        want_exit = EXIT_CODES.get(rec.get("verdict"))
        if label == "oracle" and want_exit is not None and exit_code != want_exit:
            failures.append("%s: oracle exit %s != verdict %s (%s)"
                            % (case_id, exit_code, rec.get("verdict"), want_exit))
    # (c) edges with depth: production graph + Oracle explain vs index.
    prod_graph, prod_report = _production_graph_edges(case_dir, case)
    exp_full = sorted([(
        e["from_relative_path"], e["syntax"], e["depth"],
        e["relative_target"], e["relative_resolved_target"],
        bool(e["allowed"]), e["reason"],
    ) for e in index_doc["expected_edges"]])
    if sorted([(
            e[0], e[1], e[2], e[3], e[4], e[5], e[6],
    ) for e in prod_graph]) != exp_full:
        failures.append("%s: import-graph edge mismatch (with depth): expected %r, got %r"
                        % (case_id, exp_full, prod_graph))
    if _receipt_edges(prod, case_dir) != sorted([(
            e["from_relative_path"], e["syntax"],
            e["relative_resolved_target"], bool(e["allowed"]), e["reason"])
            for e in index_doc["expected_edges"]]):
        failures.append("%s: production receipt edges != index" % case_id)
    oracle_graph = _explain_edges(explain, case_dir)
    if oracle_graph != exp_full:
        failures.append("%s: oracle explain edges != index: expected %r, got %r"
                        % (case_id, exp_full, oracle_graph))
    # (d) not-applicable: production report + Oracle explain.
    exp_na = sorted([(e["relative_path"], e["reason"])
                     for e in index_doc.get("expected_not_applicable", [])])
    prod_na = sorted({(co._rel(n.canonical_path or n.raw_path, case_dir), n.reason)
                      for n in prod_report.not_applicable})
    oracle_na = sorted([
        (co._rel(n.get("canonical_path") or n.get("raw_path"), case_dir) or n.get("raw_path"),
         n["reason"])
        for n in (explain or {}).get("considered_but_not_applicable", [])])
    if prod_na != exp_na:
        failures.append("%s: production not-applicable != index: expected %r, got %r"
                        % (case_id, exp_na, prod_na))
    if oracle_na != exp_na:
        failures.append("%s: oracle not-applicable != index: expected %r, got %r"
                        % (case_id, exp_na, oracle_na))
    # Buckets are strict: any production/Oracle receipt difference fails
    # every bucket, not just the hash bucket.
    parity_clean = (not diffs) and hash_ok
    source_ok = parity_clean and not any("source" in f for f in failures)
    trust_ok = parity_clean and not any(
        "trust" in f or "forbidden" in f for f in failures)
    edge_ok = parity_clean and not any("edge" in f for f in failures)
    verdict_ok = parity_clean and not any(
        "verdict" in f or "exit" in f for f in failures)
    return {"case_id": case_id, "passed": not failures, "failures": failures,
            "source_ok": source_ok, "trust_ok": trust_ok, "edge_ok": edge_ok,
            "verdict_ok": verdict_ok, "hash_ok": parity_clean,
            "receipt_hash": receipt.get("receipt_hash"),
            "verdict": receipt.get("verdict")}


def check_probes(oracle, index_doc: dict, tmpdir: Path, verbose=False) -> dict:
    """Pure-string probes: Oracle canonicalize + production canonicalize
    vs the hand-written expectations (``{corpus}`` = fixtures/windows)."""
    from instructionroot.paths import canonicalize as prod_canonicalize

    corpus = str(WINDOWS_DIR)
    probes = index_doc["expected_probes"]
    cwd = corpus
    home = corpus
    raws = [p["raw"] for p in probes]
    records = co.run_oracle_canonicalize(oracle, cwd, home, raws, tmpdir)
    failures = []
    per_probe = []
    for probe, rec in zip(probes, records):
        canon = probe["canonical"].replace("{corpus}", corpus)
        resolved = probe["resolved"].replace("{corpus}", corpus)
        expected = (canon, resolved, probe["exists"], probe["is_symlink"],
                    probe["is_loop"], probe["is_broken_symlink"])
        got = (rec.get("canonical_path"), rec.get("resolved_path"),
               rec.get("exists"), rec.get("is_symlink"),
               rec.get("is_loop"), rec.get("is_broken_symlink"))
        ok = got == expected
        if not ok:
            failures.append("probe %r: oracle expected %r, got %r"
                            % (probe["raw"], expected, got))
        try:
            prod = prod_canonicalize(probe["raw"], cwd=cwd, home=home)
            prod_got = (prod.canonical_path, prod.resolved_path, prod.exists,
                        prod.is_symlink, prod.is_loop, prod.is_broken_symlink)
            if prod_got != got:
                failures.append("probe %r: oracle %r != production %r"
                                % (probe["raw"], got, prod_got))
                ok = False
            if prod_got != expected:
                failures.append("probe %r: production expected %r, got %r"
                                % (probe["raw"], expected, prod_got))
                ok = False
        except Exception as exc:  # noqa: BLE001 - a raise is a probe failure
            failures.append("probe %r: production canonicalize raised %r"
                            % (probe["raw"], exc))
            ok = False
        per_probe.append({"raw": probe["raw"], "passed": ok})
    if verbose or failures:
        print("[%s] win-probes (%d probes)" % (
            "PASS" if not failures else "FAIL", len(probes)))
        for failure in failures:
            print("       %s" % failure)
    return {"case_id": "win-probes", "passed": not failures,
            "failures": failures, "probes": len(probes),
            "per_probe": per_probe}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P028 T011 windows corpus runner")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    # 0. Regenerate fixtures (nested .git dirs are not stored in git).
    print("== 0. regenerate windows fixtures ==")
    result = subprocess.run(
        [sys.executable, str(WINDOWS_DIR / "build_windows_fixtures.py")],
        capture_output=True, text=True)
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, end="")
        print("RESULT=FAIL (fixture generator failed)")
        return 1

    index = _load_json(EXPECTED_DIR / "INDEX.json")
    by_id = {c["case_id"]: c for c in index["cases"]}
    receipt_ids = sorted(c for c, d in by_id.items() if d["kind"] == "receipt")
    print("== 1. receipt cases: %d ==" % len(receipt_ids))

    oracle = co.build_oracle()
    tmpdir = Path(tempfile.mkdtemp(prefix="windows-corpus-"))
    results = []
    for case_id in receipt_ids:
        case_dir = WINDOWS_DIR / case_id
        result = check_receipt_case(oracle, case_dir, by_id[case_id], tmpdir)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print("[%s] %s (%s, %s)" % (
            status, case_id, result.get("verdict"),
            (result.get("receipt_hash") or "")[:12]))
        for failure in result["failures"]:
            print("       %s" % failure)

    print("== 2. pure-string probes: win-probes ==")
    probe_result = check_probes(oracle, by_id["win-probes"], tmpdir,
                                verbose=args.verbose)
    print("[%s] win-probes (%d probes)" % (
        "PASS" if probe_result["passed"] else "FAIL", probe_result["probes"]))

    # 3. Determinism spot check: 10 production + 10 Oracle runs on a
    # BLOCK case with import edges (win-drive-import); all hashes must
    # agree.
    print("== 3. determinism spot check (win-drive-import x10+10) ==")
    det_failures = []
    case_dir = WINDOWS_DIR / "win-drive-import"
    case = _load_json(case_dir / "case.json")
    hashes = set()
    for _ in range(10):
        try:
            prod, err = co.build_production_receipt(case_dir, case)
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            det_failures.append("production receipt raised: %r" % (exc,))
            break
        if err is not None:
            det_failures.append("production receipt failed: %s" % err)
            break
        hashes.add(prod["receipt_hash"])
    for _ in range(10):
        receipt, _explain, _code, _det = co.run_oracle_resolve(
            oracle, co.build_case_input(case_dir, case), tmpdir)
        if receipt is None:
            det_failures.append("oracle produced no receipt")
            break
        hashes.add(receipt["receipt_hash"])
    det_ok = not det_failures and len(hashes) == 1
    print("determinism=%s distinct_hashes=%d" % (
        "PASS" if det_ok else "FAIL", len(hashes)))
    for failure in det_failures:
        print("       %s" % failure)

    n = len(results)
    passed = sum(1 for r in results if r["passed"])
    buckets = {
        "source": sum(1 for r in results if r["source_ok"]),
        "trust": sum(1 for r in results if r["trust_ok"]),
        "edge": sum(1 for r in results if r["edge_ok"]),
        "verdict": sum(1 for r in results if r["verdict_ok"]),
        "hash": sum(1 for r in results if r["hash_ok"]),
    }
    all_ok = (passed == n and probe_result["passed"] and det_ok)
    print("receipt_cases=%d passed=%d failed=%d" % (n, passed, n - passed))
    for key in ("source", "trust", "edge", "verdict", "hash"):
        print("%s_parity=%d/%d" % (key, buckets[key], n))
    print("probes=%d passed=%s" % (
        probe_result["probes"], probe_result["passed"]))
    print("RESULT=%s" % ("PASS" if all_ok else "FAIL"))

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "task": "P028-T011",
        "receipt_cases": n,
        "receipt_passed": passed,
        "buckets": buckets,
        "probes": probe_result["probes"],
        "probes_passed": probe_result["passed"],
        "determinism_spot_check": det_ok,
        "per_case": [
            {"case_id": r["case_id"], "passed": r["passed"],
             "verdict": r.get("verdict"),
             "receipt_hash": r.get("receipt_hash"),
             "failures": r["failures"]} for r in results],
        "probe_failures": probe_result["failures"],
        "result": "PASS" if all_ok else "FAIL",
    }
    (REVIEW_DIR / "windows_corpus_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
