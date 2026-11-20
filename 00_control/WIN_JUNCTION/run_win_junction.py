#!/usr/bin/env python3
"""Windows runner for P028 WIN-JUNCTION (P1-02): the 4 real-NTFS-junction cases.

Runs ONLY on Windows (sys.platform must be "win32"). Reuses the frozen
checker from scripts/run_windows_corpus.py (check_receipt_case) and the
receipt builders from scripts/compare_oracle.py -- it does not reimplement
any verdict/parity logic, and it never touches the Linux corpus
(fixtures/windows/) or the S0 gate.

What it does:
  0. Preflight: Python >= 3.12, git and cargo on PATH, fixtures present,
     every case's repo/linked is a real NTFS junction (reparse tag
     0xA0000003) -- otherwise fail fast with a clear message.
  1. Build the Rust Oracle natively on this machine
     (cargo build --release --locked) and use the .exe. The Linux ELF
     binary from dist.zip is never used.
  2. For each of the 4 junction cases: production receipt + Oracle receipt
     (Oracle run twice for determinism), full receipt deep-diff, receipt
     hash parity, independent JCS recomputation, and a check against the
     hand-written expectations in fixtures/windows/expected/INDEX.json
     (sources incl. trust, edges with depth, verdict, not-applicable).
  3. Determinism spot check: 10 production + 10 Oracle runs on
     win-junction-import-escape (BLOCK case with import edges); all 20
     receipt hashes must be identical.
  4. Write per-case production/Oracle receipts + Oracle explain sidecars
     and a machine-readable summary to the evidence directory.

Exit code 0 only when all 4 cases pass with 100% parity on all five
buckets (source/trust/edge/verdict/hash) and the determinism check passes.
A failure is a result, not an accident: keep the evidence, record the
failure per case, do not re-run until it passes, do not edit expectations
or fixtures.

Usage (PowerShell, from the extracted P028 source tree):

    python .\\00_control\\WIN_JUNCTION\\run_win_junction.py --repo C:\\p028-src --fixtures C:\\p028-src\\fixtures\\win-junction --evidence C:\\p028-win-evidence

NOTE: this script was written on a Linux VM and has NOT been executed on
Windows (the author has no Windows machine). The executing agent must
read any traceback in full, record it, and stop rather than improvising
a workaround if the script itself fails.
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

CASE_IDS = [
    "win-junction-inside",
    "win-junction-escape",
    "win-junction-import-inside",
    "win-junction-import-escape",
]
DET_CASE = "win-junction-import-escape"  # BLOCK case with import edges
JUNCTION_REPARSE_TAG = 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT


def _fail(msg: str) -> "SystemExit":
    print("PREFLIGHT FAIL: %s" % msg, file=sys.stderr)
    return SystemExit(2)


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P028 WIN-JUNCTION windows runner")
    parser.add_argument("--repo", required=True,
                        help="extracted P028 source tree (e.g. C:\\p028-src)")
    parser.add_argument("--fixtures", required=True,
                        help="junction fixtures root (e.g. C:\\p028-src\\fixtures\\win-junction)")
    parser.add_argument("--evidence", required=True,
                        help="evidence directory (e.g. C:\\p028-win-evidence)")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    fixtures = Path(args.fixtures)
    evidence = Path(args.evidence)

    # --- 0. Preflight (fail fast, never work around) ---
    if sys.platform != "win32":
        print("PREFLIGHT FAIL: this script runs on Windows only "
              "(sys.platform=%s). Do not run it on Linux: the Linux "
              "corpus runner is scripts/run_windows_corpus.py, and its "
              "results are not Windows evidence." % sys.platform,
              file=sys.stderr)
        return 2
    if sys.version_info < (3, 12):
        print("PREFLIGHT FAIL: Python >= 3.12 required, found %s"
              % sys.version.split()[0], file=sys.stderr)
        return 2
    for tool in ("git", "cargo"):
        if shutil.which(tool) is None:
            print("PREFLIGHT FAIL: %r not found on PATH. Stop and report; "
                  "do not proceed without it." % tool, file=sys.stderr)
            return 2
    index_path = repo / "fixtures" / "windows" / "expected" / "INDEX.json"
    if not index_path.is_file():
        print("PREFLIGHT FAIL: INDEX.json not found: %s (is --repo the "
              "extracted P028 source tree?)" % index_path, file=sys.stderr)
        return 2
    for case_id in CASE_IDS:
        case_dir = fixtures / case_id
        if not (case_dir / "case.json").is_file():
            print("PREFLIGHT FAIL: fixture missing: %s (run "
                  "build_win_junction_fixtures.ps1 first)"
                  % (case_dir / "case.json"), file=sys.stderr)
            return 2
        link = case_dir / "repo" / "linked"
        try:
            # FIX-R2: os.lstat, NOT os.stat -- os.stat follows the junction
            # and returns the target's attributes (reparse tag 0x0), which
            # misjudges a real junction as "not a junction" (exit 2).
            # os.lstat returns the link itself (tag 0xa0000003).
            tag = os.lstat(link).st_reparse_tag
        except AttributeError:
            print("PREFLIGHT WARN: os.stat has no st_reparse_tag on this "
                  "Python; junction proof relies on the fsutil evidence "
                  "(E04-3). Continuing.")
            tag = None
        except OSError as exc:
            print("PREFLIGHT FAIL: cannot stat junction %s: %r"
                  % (link, exc), file=sys.stderr)
            return 2
        if tag is not None and tag != JUNCTION_REPARSE_TAG:
            print("PREFLIGHT FAIL: %s is not an NTFS junction "
                  "(reparse tag 0x%x, expected 0x%x). Do not substitute a "
                  "symlink or a plain directory." % (link, tag, JUNCTION_REPARSE_TAG),
                  file=sys.stderr)
            return 2

    # Reuse the frozen checker (import after preflight so a missing
    # source tree fails with the message above, not an ImportError).
    sys.path.insert(0, str(repo / "scripts"))
    sys.path.insert(0, str(repo / "02_src"))
    import compare_oracle as co  # noqa: E402
    import run_windows_corpus as rwc  # noqa: E402

    evidence.mkdir(parents=True, exist_ok=True)

    env_info = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "git": _run(["git", "--version"]).stdout.strip(),
        "cargo": _run(["cargo", "--version"]).stdout.strip(),
        "rustc": _run(["rustc", "--version"]).stdout.strip(),
        "repo": str(repo),
        "fixtures": str(fixtures),
    }

    # --- 1. Build the Oracle natively (never use the dist.zip ELF) ---
    print("== 0. build Oracle (native Windows) ==")
    oracle_manifest = repo / "03_oracle" / "rust" / "Cargo.toml"
    result = _run(["cargo", "build", "--release", "--locked",
                   "--manifest-path", str(oracle_manifest)])
    (evidence / "cargo_build.log").write_text(
        result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        print("RESULT=FAIL (cargo build failed; see cargo_build.log -- "
              "do NOT install a C++ workload, change target, or install "
              "MinGW on your own; record the log and report)")
        return 1
    oracle = repo / "03_oracle" / "rust" / "target" / "release" / "instructionroot-oracle.exe"
    if not oracle.is_file():
        print("RESULT=FAIL (cargo build exited 0 but %s is missing)" % oracle)
        return 1
    env_info["oracle"] = str(oracle)
    env_info["oracle_version"] = _run([str(oracle), "--version"]).stdout.strip()
    print("oracle: %s (%s)" % (oracle, env_info["oracle_version"]))

    # --- 2. The 4 junction cases ---
    index = json.loads(index_path.read_text(encoding="utf-8"))
    by_id = {c["case_id"]: c for c in index["cases"]}
    missing = [c for c in CASE_IDS if c not in by_id]
    if missing:
        print("RESULT=FAIL (INDEX.json has no expectations for: %s)" % missing)
        return 1

    tmpdir = Path(tempfile.mkdtemp(prefix="win-junction-"))
    results = []
    print("== 1. receipt cases: %d ==" % len(CASE_IDS))
    for case_id in CASE_IDS:
        case_dir = fixtures / case_id
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        result_case = rwc.check_receipt_case(oracle, case_dir, by_id[case_id], tmpdir)
        results.append(result_case)
        status = "PASS" if result_case["passed"] else "FAIL"
        print("[%s] %s (%s, %s)" % (
            status, case_id, result_case.get("verdict"),
            (result_case.get("receipt_hash") or "")[:12]))
        for failure in result_case["failures"]:
            print("       %s" % failure)
        # Dump both receipts + explain sidecar as evidence (independent
        # of the checker's verdict bookkeeping).
        try:
            prod, prod_err = co.build_production_receipt(case_dir, case)
            if prod_err is None:
                (evidence / ("%s-production-receipt.json" % case_id)).write_text(
                    json.dumps(prod, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            else:
                (evidence / ("%s-production-error.txt" % case_id)).write_text(
                    str(prod_err) + "\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            (evidence / ("%s-production-error.txt" % case_id)).write_text(
                "production receipt raised: %r\n" % (exc,), encoding="utf-8")
        try:
            receipt, explain, _code, _det = co.run_oracle_resolve(
                oracle, co.build_case_input(case_dir, case), tmpdir)
            if receipt is not None:
                (evidence / ("%s-oracle-receipt.json" % case_id)).write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            if explain is not None:
                (evidence / ("%s-oracle-explain.json" % case_id)).write_text(
                    json.dumps(explain, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            (evidence / ("%s-oracle-error.txt" % case_id)).write_text(
                "oracle receipt raised: %r\n" % (exc,), encoding="utf-8")

    # --- 3. Determinism spot check: 10 production + 10 Oracle runs ---
    print("== 2. determinism spot check (%s x10+10) ==" % DET_CASE)
    det_failures = []
    det_case_dir = fixtures / DET_CASE
    det_case = json.loads((det_case_dir / "case.json").read_text(encoding="utf-8"))
    hashes = set()
    for _ in range(10):
        try:
            prod, err = co.build_production_receipt(det_case_dir, det_case)
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            det_failures.append("production receipt raised: %r" % (exc,))
            break
        if err is not None:
            det_failures.append("production receipt failed: %s" % err)
            break
        hashes.add(prod["receipt_hash"])
    for _ in range(10):
        receipt, _explain, _code, _det = co.run_oracle_resolve(
            oracle, co.build_case_input(det_case_dir, det_case), tmpdir)
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
    all_ok = (passed == n and det_ok)
    print("receipt_cases=%d passed=%d failed=%d" % (n, passed, n - passed))
    for key in ("source", "trust", "edge", "verdict", "hash"):
        print("%s_parity=%d/%d" % (key, buckets[key], n))
    print("RESULT=%s" % ("PASS" if all_ok else "FAIL"))

    summary = {
        "task": "P028-WIN-JUNCTION",
        "environment": env_info,
        "receipt_cases": n,
        "receipt_passed": passed,
        "buckets": buckets,
        "determinism_case": DET_CASE,
        "determinism_spot_check": det_ok,
        "determinism_distinct_hashes": len(hashes),
        "per_case": [
            {"case_id": r["case_id"], "passed": r["passed"],
             "verdict": r.get("verdict"),
             "receipt_hash": r.get("receipt_hash"),
             "failures": r["failures"]} for r in results],
        "result": "PASS" if all_ok else "FAIL",
    }
    (evidence / "win_junction_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
