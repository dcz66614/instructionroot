#!/usr/bin/env python3
"""P028 T014 — measure CLI ``verify`` wall time on a synthetic case.

Reads ``manifest.json`` in the case dir (built by
``scripts/build_perf_case.py``), runs the repo launcher
``./instructionroot verify`` ``--runs`` times (default 21) with
``COPILOT_CUSTOM_INSTRUCTIONS_DIRS`` set from the manifest, and
prints wall-time statistics (n / p50 / p95 / max / mean, seconds and
ms) plus the per-run exit code, verdict and receipt hash.

Wall time is measured around the whole subprocess (interpreter
startup + discovery + git provenance + import graph + receipt), i.e.
what a user/CI invoking the CLI actually pays. Percentiles use the
nearest-rank method. With ``--json-out`` the per-run table is also
written as JSON (receipt hashes let the caller confirm the runs all
produced the same receipt). No network. Exit 0 unless a run fails
to produce a receipt hash (non-zero verify exit codes are *not*
failures here — BLOCK/WARN are legitimate verdicts — but they are
reported per run).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]


def _percentile(sorted_values: list[float], pct: float) -> float:
    rank = math.ceil(pct / 100.0 * len(sorted_values))
    return sorted_values[max(0, min(len(sorted_values) - 1, rank - 1))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default=str(
        Path(tempfile.gettempdir()) / "p028-perf-case"),
                        help="case directory containing manifest.json")
    parser.add_argument("--runs", type=int, default=21)
    parser.add_argument("--launcher", default=str(WORKDIR / "instructionroot"))
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    case = Path(args.case)
    manifest = json.loads((case / "manifest.json").read_text(encoding="utf-8"))
    env = {**os.environ,
           "COPILOT_CUSTOM_INSTRUCTIONS_DIRS": ",".join(manifest["custom_dirs"])}
    cmd = [args.launcher, "verify", "--harness", manifest["harness"],
           "--cwd", manifest["cwd"], "--home", manifest["home"],
           "--working-file", manifest["working_file"]]
    runs: list[dict] = []
    for i in range(args.runs):
        start = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        elapsed = time.perf_counter() - start
        receipt_hash = None
        verdict = None
        for line in proc.stdout.splitlines():
            if line.startswith("receipt_hash:"):
                receipt_hash = line.split(":", 1)[1].strip()
            if line.startswith("VERDICT:"):
                verdict = line.split(":", 1)[1].strip()
        runs.append({"run": i + 1, "wall_s": round(elapsed, 3),
                     "exit": proc.returncode, "verdict": verdict,
                     "receipt_hash": receipt_hash})
        print("run %2d: %.3fs exit=%s verdict=%s hash=%s"
              % (i + 1, elapsed, proc.returncode, verdict,
                 (receipt_hash or "?")[:12]), flush=True)
    times = sorted(r["wall_s"] for r in runs)
    hashes = {r["receipt_hash"] for r in runs}
    stats = {
        "n": len(runs),
        "p50_s": round(_percentile(times, 50), 3),
        "p95_s": round(_percentile(times, 95), 3),
        "max_s": round(times[-1], 3),
        "min_s": round(times[0], 3),
        "mean_s": round(sum(times) / len(times), 3),
        "distinct_receipt_hashes": len(hashes),
        "exits": sorted({r["exit"] for r in runs}),
        "verdicts": sorted({r["verdict"] for r in runs}),
    }
    print(json.dumps(stats, indent=2, sort_keys=True))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"stats": stats, "runs": runs}, indent=2,
                       sort_keys=True) + "\n", encoding="utf-8")
    if None in hashes or len(hashes) != 1:
        print("WARNING: runs did not all produce the same receipt hash",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
