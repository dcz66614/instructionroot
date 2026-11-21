#!/usr/bin/env python3
"""Oracle parity checker for P028 T006 (reused by T007's S0 gate).

Runs the Rust Oracle binary against every golden fixture and compares
it with (a) the committed ``.expected.json`` files and (b) a production
reference receipt assembled from the production modules
(``discover_with_report`` + real git state + ``classify_trust`` +
``build_import_graph`` + ``build_receipt``), and (c) an independent
RFC 8785 JCS + SHA-256 recomputation written here from the RFC text
(stdlib only — it never imports the production receipt module or the
Oracle's JCS code, so a hash agreement is genuine cross-checking).

Sections:

* ``resolver`` — 20 cases under ``01_s0/fixtures/resolver/``:
  source set + order + per-source fields, not-applicable (from the
  Oracle's ``--explain`` sidecar), Claude import candidates (reason
  vocabulary mapped ``OK`` <-> ``WITHIN_REPO``/``WITHIN_HOME``),
  full receipt equality vs the production reference, hash parity.
* ``imports`` — 15 cases under ``01_s0/fixtures/imports/``:
  edge multiset + verdict vs ``.expected.json``, full receipt
  equality vs the production reference, hash parity.
* ``fs`` — 12 cases under ``01_s0/fixtures/fs/cases/``:
  ``oracle canonicalize`` probes with hardcoded expectations, plus a
  cross-check against production ``paths.canonicalize`` on the same
  inputs (including the Windows pure-string cases from the committed
  ``windows-paths.json``; real Windows resolution stays NOT_RUN).
* ``git`` — T004 git/trust scenarios built on the fly in temp repos
  (tracked clean, modified worktree, staged modification, untracked,
  staged-new-file, non-git workspace): Oracle receipt git/trust
  fields vs hardcoded expectations and vs the production reference.

Output (``--all``)::

    source_parity=100.0% trust_parity=100.0% edge_parity=100.0%
    verdict_parity=100.0% hash_parity=100.0%
    fs=... git=...

Exit code 0 only when every parity is 100% and fs/git are clean.
No network. The Oracle binary is built once with
``cargo build --release --locked``; it never reads production output.

Usage (from the P028 work directory):

    .venv/bin/python scripts/compare_oracle.py --all
    .venv/bin/python scripts/compare_oracle.py --resolver --cases claude-basic
    .venv/bin/python scripts/compare_oracle.py --imports --fs --git -v
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKDIR / "02_src"))

ORACLE_MANIFEST = WORKDIR / "03_oracle" / "rust" / "Cargo.toml"
ORACLE_BIN = WORKDIR / "03_oracle" / "rust" / "target" / "release" / "instructionroot-oracle"

RESOLVER_DIR = WORKDIR / "01_s0" / "fixtures" / "resolver"
IMPORTS_DIR = WORKDIR / "01_s0" / "fixtures" / "imports"
FS_DIR = WORKDIR / "01_s0" / "fixtures" / "fs" / "cases"


# ---------------------------------------------------------------------------
# Independent RFC 8785 JCS (written here from the RFC text; stdlib only)
# ---------------------------------------------------------------------------

def _utf16_key(key: str) -> bytes:
    """Sort key: the string encoded as UTF-16 big-endian code units."""
    return key.encode("utf-16-be")


def _escape_string(text: str) -> str:
    out = ['"']
    for ch in text:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\r":
            out.append("\\r")
        elif code < 0x20:
            out.append("\\u%04x" % code)
        else:
            # Non-ASCII (including astral characters) is emitted raw.
            out.append(ch)
    out.append('"')
    return "".join(out)


def _number_to_string(value) -> str:
    """ECMAScript Number::toString (RFC 8785 §3.2.3).

    Integers in the safe range print as decimal; anything else goes
    through the shortest-round-trip decimal expansion, then the
    k/n digit rules (k = digit count, value = 0.digits × 10^n).
    """
    if isinstance(value, bool):
        raise ValueError("boolean passed as number")
    if isinstance(value, int):
        if -(2**53) < value < 2**53:
            return str(value)
        value = float(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("non-finite numbers are not JSON")
        if value == 0:
            return "0"
    text = repr(value)
    if "e" not in text and "E" not in text:
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    mantissa, _, exp = text.lower().partition("e")
    exponent = int(exp)
    digits = mantissa.replace(".", "").replace("-", "")
    digits = digits.lstrip("0") or "0"
    digits = digits.rstrip("0") or "0"
    # Recompute the decimal exponent from the cleaned digits: the
    # value is digits × 10^(exponent - (len(digits)-1)) when the
    # mantissa had one digit before the point.
    point = mantissa.find(".")
    if point == -1:
        int_digits = len(mantissa.lstrip("-"))
    else:
        int_digits = len(mantissa[:point].lstrip("-"))
    n = exponent + int_digits
    k = len(digits)
    sign = "-" if value < 0 else ""
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    if k == 1:
        return sign + digits + "e" + ("+" if n - 1 >= 0 else "") + str(n - 1)
    return (
        sign + digits[0] + "." + digits[1:]
        + "e" + ("+" if n - 1 >= 0 else "") + str(n - 1)
    )


def jcs_canonical(value) -> str:
    """RFC 8785 JSON Canonicalization Scheme (no whitespace, UTF-16
    key order, ECMAScript numbers, minimal string escaping)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _escape_string(value)
    if isinstance(value, (int, float)):
        return _number_to_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(jcs_canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value.keys(), key=_utf16_key)
        return "{" + ",".join(
            _escape_string(k) + ":" + jcs_canonical(value[k]) for k in keys
        ) + "}"
    raise TypeError("not a JSON value: %r" % (value,))


def receipt_hash_of(receipt: dict) -> str:
    """SHA-256 of the canonical receipt without its receipt_hash."""
    body = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    return hashlib.sha256(jcs_canonical(body).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Oracle runner
# ---------------------------------------------------------------------------

def build_oracle() -> Path:
    env = dict(os.environ)
    cargo = Path.home() / ".cargo" / "bin"
    env["PATH"] = str(cargo) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["cargo", "build", "--release", "--locked",
         "--manifest-path", str(ORACLE_MANIFEST)],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "cargo build failed:\n%s\n%s" % (result.stdout, result.stderr)
        )
    return ORACLE_BIN


def run_oracle_resolve(oracle: Path, case_input: dict, tmpdir: Path):
    """Run `oracle resolve` twice (determinism) and return
    (receipt, explain, exit_code, determinism_ok)."""
    case_path = tmpdir / "case-input.json"
    case_path.write_text(json.dumps(case_input), encoding="utf-8")
    explain_path = tmpdir / "explain.json"
    cmd = [str(oracle), "resolve", str(case_path),
           "--explain", str(explain_path)]
    first = subprocess.run(cmd, capture_output=True, text=True)
    second = subprocess.run(cmd, capture_output=True, text=True)
    deterministic = first.stdout == second.stdout
    receipt = json.loads(first.stdout) if first.stdout.strip() else None
    explain = None
    if explain_path.exists():
        explain = json.loads(explain_path.read_text(encoding="utf-8"))
    return receipt, explain, first.returncode, deterministic


def run_oracle_canonicalize(oracle: Path, cwd: str, home: str, paths, tmpdir: Path):
    input_path = tmpdir / "canon-input.json"
    input_path.write_text(
        json.dumps({"cwd": cwd, "home": home, "paths": list(paths)}),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(oracle), "canonicalize", str(input_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("canonicalize failed: %s" % result.stderr)
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _rel(canonical, case_dir: Path):
    if canonical is None:
        return None
    try:
        return os.path.relpath(canonical, str(case_dir)).replace(os.sep, "/")
    except ValueError:
        return canonical


def _rel_or_abs(canonical, case_dir: Path):
    """Case-relative path, or the absolute path when outside the case."""
    if canonical is None:
        return None
    rel = os.path.relpath(canonical, str(case_dir)).replace(os.sep, "/")
    if rel == ".." or rel.startswith("../"):
        return canonical
    return rel


def resolve_case_paths(case_dir: Path, case: dict):
    """Absolute cwd/home/repo_root/working_files + env substitution,
    exactly as run_golden.py does."""

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
        raise ValueError("unsupported policy value")
    working = [_resolve(p) for p in case.get("working_files", [])]
    env = {
        k: v.replace("{case}", str(case_dir))
        for k, v in (case.get("env") or {}).items()
    }
    return cwd, home, repo_root, policy_arg, working, env


def build_case_input(case_dir: Path, case: dict) -> dict:
    cwd, home, repo_root, policy_arg, working, env = resolve_case_paths(
        case_dir, case)
    return {
        "case_id": case["case_id"],
        "harness": case["harness"],
        "profile_version": case.get("profile_version"),
        "cwd": cwd,
        "home": home,
        "repo_root": repo_root,
        "policy": case.get("policy", "default"),
        "working_files": working,
        "env": env,
        "ancestor_stop": str(case_dir),
    }


def deep_diff(a, b, path="$"):
    """Order-sensitive deep diff; returns a list of readable diffs."""
    diffs = []
    if type(a) is not type(b) and not (
        isinstance(a, (int, float)) and isinstance(b, (int, float))
    ):
        diffs.append("%s: type %s != %s (%r vs %r)"
                     % (path, type(a).__name__, type(b).__name__, a, b))
        return diffs
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key not in a:
                diffs.append("%s.%s: missing in oracle (%r)" % (path, key, b[key]))
            elif key not in b:
                diffs.append("%s.%s: missing in production (%r)" % (path, key, a[key]))
            else:
                diffs.extend(deep_diff(a[key], b[key], "%s.%s" % (path, key)))
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append("%s: length %d != %d" % (path, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            diffs.extend(deep_diff(x, y, "%s[%d]" % (path, i)))
    elif a != b:
        diffs.append("%s: %r != %r" % (path, a, b))
    return diffs


# ---------------------------------------------------------------------------
# Production reference receipt (assembled from production modules with
# REAL git state; T007's assembly, not a golden file)
# ---------------------------------------------------------------------------

def build_production_receipt(case_dir: Path, case: dict):
    """Assemble the production receipt for one case. Returns
    (receipt, error_string).

    FIX-R5: this is now a thin delegation to
    ``instructionroot.cli.build_receipt_for`` — the *same* function
    the production CLI (``python -m instructionroot verify/inspect``)
    uses — with ``ancestor_stop`` set to the case dir so the ancestor
    walk cannot escape the fixture. The two paths used to be
    independent copies of the same assembly (discovery + import
    graph + trust + receipt), and they drifted: the CLI passed the
    *resolved* CWD to ``build_receipt``/``build_import_graph`` while
    this function passed the raw (lexical) CWD, so
    ``workspace.cwd`` (and the receipt hash) differed whenever the
    CWD went through a symlink/junction (V4 E08-5, F6). One shared
    assembly path makes that class of drift impossible. The case
    env (``{case}`` substituted) is set for the whole call, exactly
    as before; exceptions become ``(None, "production
    build_receipt failed: ...")`` as before.
    """
    from instructionroot.cli import build_receipt_for
    from instructionroot.resolver import UnsupportedProfileError

    cwd, home, repo_root, policy_arg, working, env = resolve_case_paths(
        case_dir, case)
    saved_env = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        try:
            receipt, _report = build_receipt_for(
                harness=case["harness"],
                cwd=cwd, home=home, repo_root=repo_root,
                policy=policy_arg,
                profile_version=case.get("profile_version"),
                working_files=working,
                ancestor_stop=str(case_dir),
            )
        except UnsupportedProfileError:
            # Must propagate, not be folded into the (None, err)
            # pair: the S0 fail-closed suite (FC-02/FC-03) and the
            # CLI map this to UNSUPPORTED_PROFILE (exit 40), while a
            # ValueError maps to INPUT_ERROR (exit 30). The old code
            # only wrapped build_receipt, so discovery errors
            # propagated the same way.
            raise
        except Exception as exc:  # production receipt build failed
            return None, "production build_receipt failed: %r" % (exc,)
        return receipt, None
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Resolver cases
# ---------------------------------------------------------------------------

def check_resolver_case(oracle: Path, case_dir: Path, tmpdir: Path, verbose=False):
    case = _load_json(case_dir / "case.json")
    expected = _load_json(case_dir / (case["case_id"] + ".expected.json"))
    case_id = case["case_id"]
    failures = []
    notes = []

    case_input = build_case_input(case_dir, case)
    receipt, explain, exit_code, deterministic = run_oracle_resolve(
        oracle, case_input, tmpdir)
    if receipt is None:
        return {"case_id": case_id, "passed": False,
                "failures": ["oracle produced no receipt (exit %s)" % exit_code],
                "notes": notes}
    if not deterministic:
        failures.append("receipt is not deterministic across two runs")
    verdict = receipt.get("verdict")
    want_exit = {"PASS": 0, "WARN": 10, "BLOCK": 20}.get(verdict)
    if want_exit is not None and exit_code != want_exit:
        failures.append("exit code %s != verdict %s (%s)"
                        % (exit_code, verdict, want_exit))

    # --- sources: set + order + fields (from receipt + explain) -----
    id_by_canonical = {
        s["canonical_path"]: s["source_id"] for s in receipt["sources"]
    }
    actual_pairs = [
        (s["discovery_rule"], _rel(s["canonical_path"], case_dir))
        for s in receipt["sources"]
    ]
    expected_pairs = [
        (e["discovery_rule"], e["relative_path"])
        for e in expected["expected_sources"]
    ]
    if sorted(actual_pairs) != sorted(expected_pairs):
        failures.append("source set mismatch: expected %r, got %r"
                        % (sorted(expected_pairs), sorted(actual_pairs)))
    if case["harness"] == "copilot-cli":
        order_ok = sorted(actual_pairs) == sorted(expected_pairs)
    else:
        order_ok = actual_pairs == expected_pairs
        if not order_ok:
            failures.append("source order mismatch: expected %r, got %r"
                            % (expected_pairs, actual_pairs))
    explain_by_canonical = {
        s["canonical_path"]: s for s in (explain or {}).get("sources", [])
    }
    for exp in expected["expected_sources"]:
        matches = [s for s in receipt["sources"]
                   if s["discovery_rule"] == exp["discovery_rule"]
                   and _rel(s["canonical_path"], case_dir) == exp["relative_path"]]
        if not matches:
            continue
        actual = matches[0]
        for field, key in (("scope", "scope"), ("phase", "phase")):
            if exp.get(key) is not None and actual[field] != exp[key]:
                failures.append(
                    "%s %s: %s expected %r, got %r"
                    % (exp["relative_path"], exp["discovery_rule"], field,
                       exp[key], actual[field]))
        if exp.get("precedence_kind") is not None and \
                actual["precedence"]["kind"] != exp["precedence_kind"]:
            failures.append(
                "%s %s: precedence_kind expected %r, got %r"
                % (exp["relative_path"], exp["discovery_rule"],
                   exp["precedence_kind"], actual["precedence"]["kind"]))
        if "also_discovered_by" in exp:
            actual_also = explain_by_canonical.get(
                actual["canonical_path"], {}).get("also_discovered_by", [])
            if sorted(actual_also) != sorted(exp["also_discovered_by"]):
                failures.append(
                    "%s %s: also_discovered_by expected %r, got %r"
                    % (exp["relative_path"], exp["discovery_rule"],
                       exp["also_discovered_by"], actual_also))
    if "expected_source_count" in expected and \
            expected["expected_source_count"] != len(receipt["sources"]):
        failures.append("source count expected %d, got %d"
                        % (expected["expected_source_count"],
                           len(receipt["sources"])))

    # --- not-applicable (explain sidecar) ---------------------------
    # Entries may carry a canonical path or only a raw path; both are
    # normalised to case-relative form (mirrors run_golden._norm).
    def _na_path(n):
        p = n.get("canonical_path") or n.get("raw_path")
        return _rel(p, case_dir) or p
    expected_na = sorted({
        (e["relative_path"], e["reason"])
        for e in expected.get("expected_not_applicable", [])
    })
    actual_na = sorted({
        (_na_path(n), n["reason"])
        for n in (explain or {}).get("considered_but_not_applicable", [])
    })
    if actual_na != expected_na:
        failures.append("not-applicable mismatch: expected %r, got %r"
                        % (expected_na, actual_na))

    # --- Claude import candidates (reason OK <-> WITHIN_*) ----------
    expected_imports = expected.get("expected_import_candidates", [])
    if expected_imports:
        actual_imports = sorted([
            (
                _rel(e["from"], case_dir),
                e["syntax"],
                e["depth"],
                _rel(e["canonical_target"], case_dir),
                e["allowed"],
                e["reason"],
            )
            for e in (explain or {}).get("edges", [])
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
        # Compare with OK accepted as either WITHIN_REPO or WITHIN_HOME
        # (T003's vocabulary has one allowed reason; T005 splits it).
        def _norm_reason(exp_reason, act_reason, allowed):
            if exp_reason == "OK" and allowed:
                return act_reason in ("WITHIN_REPO", "WITHIN_HOME")
            return exp_reason == act_reason
        mismatch = len(actual_imports) != len(expected_tuples)
        if not mismatch:
            for act, exp in zip(
                    sorted(actual_imports, key=lambda x: (x[0], x[1], x[2])),
                    sorted(expected_tuples, key=lambda x: (x[0], x[1], x[2]))):
                if act[:5] != exp[:5] or not _norm_reason(
                        exp[5], act[5], exp[4]):
                    mismatch = True
                    break
        if mismatch:
            failures.append(
                "import candidates mismatch: expected %r, got %r"
                % (expected_tuples, actual_imports))

    # --- full receipt vs production reference -----------------------
    prod, prod_err = build_production_receipt(case_dir, case)
    trust_ok = edge_ok = verdict_ok = hash_ok = True
    if prod_err is not None:
        failures.append(prod_err)
        trust_ok = edge_ok = verdict_ok = hash_ok = False
    else:
        diffs = deep_diff(receipt, prod)
        if diffs:
            failures.append("receipt != production reference (%d diffs): %s"
                            % (len(diffs), "; ".join(diffs[:8])))
            # Attribute the diff to the parity buckets.
            joined = "\n".join(diffs)
            if '"trust"' in joined or ".git" in joined:
                trust_ok = False
            if ".edges" in joined:
                edge_ok = False
            if ".verdict" in joined:
                verdict_ok = False
            if "receipt_hash" in joined:
                hash_ok = False
        if receipt.get("receipt_hash") != prod.get("receipt_hash"):
            hash_ok = False
            failures.append("receipt_hash != production receipt_hash")
        if receipt.get("verdict") != prod.get("verdict"):
            verdict_ok = False
            failures.append("verdict %r != production %r"
                            % (receipt.get("verdict"), prod.get("verdict")))

    # --- hash self-check: independent JCS recomputation -------------
    try:
        recomputed = receipt_hash_of(receipt)
    except Exception as exc:
        failures.append("independent JCS recomputation failed: %r" % (exc,))
        recomputed = None
        hash_ok = False
    if recomputed is not None and recomputed != receipt.get("receipt_hash"):
        hash_ok = False
        failures.append("receipt_hash %s != independent JCS hash %s"
                        % (receipt.get("receipt_hash"), recomputed))

    if verbose or failures:
        print("[%s] %s (%s)" % (
            "PASS" if not failures else "FAIL", case_id, case["harness"]))
        for failure in failures:
            print("       %s" % failure)
    return {
        "case_id": case_id, "passed": not failures, "failures": failures,
        "notes": notes, "trust_ok": trust_ok, "edge_ok": edge_ok,
        "verdict_ok": verdict_ok, "hash_ok": hash_ok,
    }


# ---------------------------------------------------------------------------
# Imports cases
# ---------------------------------------------------------------------------

def check_imports_case(oracle: Path, case_dir: Path, tmpdir: Path, verbose=False):
    case = _load_json(case_dir / "case.json")
    expected = _load_json(case_dir / (case["case_id"] + ".expected.json"))
    case_id = case["case_id"]
    failures = []

    case_input = build_case_input(case_dir, case)
    receipt, explain, exit_code, deterministic = run_oracle_resolve(
        oracle, case_input, tmpdir)
    if receipt is None:
        return {"case_id": case_id, "passed": False,
                "failures": ["oracle produced no receipt (exit %s)" % exit_code],
                "trust_ok": False, "edge_ok": False, "verdict_ok": False,
                "hash_ok": False}
    if not deterministic:
        failures.append("receipt is not deterministic across two runs")

    # --- edges: exact multiset (from explain: depth + both targets) --
    actual_edges = sorted([
        (
            _rel(e["from"], case_dir),
            e["syntax"],
            e["depth"],
            _rel_or_abs(e["canonical_target"], case_dir),
            _rel_or_abs(e["resolved_target"], case_dir),
            e["allowed"],
            e["reason"],
        )
        for e in (explain or {}).get("edges", [])
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
        failures.append("edge mismatch: expected %r, got %r"
                        % (expected_edges, actual_edges))
    if "expected_edge_count" in expected and \
            expected["expected_edge_count"] != len(actual_edges):
        failures.append("edge count expected %d, got %d"
                        % (expected["expected_edge_count"], len(actual_edges)))

    # --- verdict vs expected (synthetic trust) -----------------------
    verdict_ok = receipt.get("verdict") == expected.get("expected_verdict")
    if not verdict_ok:
        failures.append(
            "verdict mismatch: expected %r, got %r (expected uses "
            "synthetic trust; fixture files are committed so real git "
            "state should coincide — investigate if this fires)"
            % (expected.get("expected_verdict"), receipt.get("verdict")))

    # --- full receipt vs production reference -----------------------
    prod, prod_err = build_production_receipt(case_dir, case)
    trust_ok = True
    hash_ok = True
    if prod_err is not None:
        failures.append(prod_err)
        trust_ok = hash_ok = False
        verdict_ok = False
    else:
        diffs = deep_diff(receipt, prod)
        if diffs:
            failures.append("receipt != production reference (%d diffs): %s"
                            % (len(diffs), "; ".join(diffs[:8])))
            joined = "\n".join(diffs)
            if '"trust"' in joined or ".git" in joined:
                trust_ok = False
            if ".edges" in joined:
                edge_ok = False
            if ".verdict" in joined:
                verdict_ok = False
            if "receipt_hash" in joined:
                hash_ok = False
        if receipt.get("receipt_hash") != prod.get("receipt_hash"):
            hash_ok = False
            failures.append("receipt_hash != production receipt_hash")
        if receipt.get("verdict") != prod.get("verdict"):
            verdict_ok = False
            failures.append("verdict %r != production verdict %r"
                            % (receipt.get("verdict"), prod.get("verdict")))

    # --- hash self-check --------------------------------------------
    try:
        recomputed = receipt_hash_of(receipt)
    except Exception as exc:
        failures.append("independent JCS recomputation failed: %r" % (exc,))
        recomputed = None
        hash_ok = False
    if recomputed is not None and recomputed != receipt.get("receipt_hash"):
        hash_ok = False
        failures.append("receipt_hash %s != independent JCS hash %s"
                        % (receipt.get("receipt_hash"), recomputed))

    if verbose or failures:
        print("[%s] %s (%s)" % (
            "PASS" if not failures else "FAIL", case_id, case["harness"]))
        for failure in failures:
            print("       %s" % failure)
    return {
        "case_id": case_id, "passed": not failures, "failures": failures,
        "trust_ok": trust_ok, "edge_ok": edge_ok,
        "verdict_ok": verdict_ok, "hash_ok": hash_ok,
    }


# ---------------------------------------------------------------------------
# FS cases (oracle canonicalize probes + production cross-check)
# ---------------------------------------------------------------------------

def fs_probes(case_dir: Path):
    """(raw, expected) probes for one FS case. `raw` is case-relative
    unless absolute; expected fields are stated outright (canonical,
    resolved, exists, is_symlink, is_loop, is_broken_symlink)."""
    case_id = case_dir.name
    c = str(case_dir)
    probes = []
    if case_id == "basic":
        probes = [
            ("repo/AGENTS.md", (f"{c}/repo/AGENTS.md", f"{c}/repo/AGENTS.md", True, False, False, False)),
            ("repo/services/../AGENTS.md", (f"{c}/repo/AGENTS.md", f"{c}/repo/AGENTS.md", True, False, False, False)),
            ("repo//services///payments//AGENTS.md", (f"{c}/repo/services/payments/AGENTS.md", f"{c}/repo/services/payments/AGENTS.md", True, False, False, False)),
            ("~/.codex/AGENTS.md", (f"{c}/home/.codex/AGENTS.md", f"{c}/home/.codex/AGENTS.md", True, False, False, False)),
            ("repo/nope.md", (f"{c}/repo/nope.md", f"{c}/repo/nope.md", False, False, False, False)),
        ]
    elif case_id == "dotdot":
        probes = [
            ("repo/services/payments/../../AGENTS.md", (f"{c}/repo/AGENTS.md", f"{c}/repo/AGENTS.md", True, False, False, False)),
            ("repo/services/payments/../other/keep.txt", (f"{c}/repo/services/other/keep.txt", f"{c}/repo/services/other/keep.txt", True, False, False, False)),
        ]
    elif case_id == "symlink-inside":
        probes = [
            ("repo/link.md", (f"{c}/repo/link.md", f"{c}/repo/services/AGENTS.md", True, True, False, False)),
        ]
    elif case_id == "symlink-escape":
        probes = [
            ("repo/escape.md", (f"{c}/repo/escape.md", f"{c}/outside/Downloads/AGENTS.md", True, True, False, False)),
        ]
    elif case_id == "symlink-loop":
        probes = [
            ("repo/loop-a", (f"{c}/repo/loop-a", None, False, True, True, False)),
            ("repo/self-loop", (f"{c}/repo/self-loop", None, False, True, True, False)),
        ]
    elif case_id == "symlink-broken":
        probes = [
            ("repo/broken.md", (f"{c}/repo/broken.md", f"{c}/repo/does-not-exist.md", False, True, False, True)),
        ]
    elif case_id == "unicode":
        probes = [
            ("repo/ünïcode-✓/AGENTS-✓.md", (f"{c}/repo/ünïcode-✓/AGENTS-✓.md", f"{c}/repo/ünïcode-✓/AGENTS-✓.md", True, False, False, False)),
            ("repo/中文/说明.md", (f"{c}/repo/中文/说明.md", f"{c}/repo/中文/说明.md", True, False, False, False)),
        ]
    elif case_id == "missing":
        probes = [
            ("repo/nope.md", (f"{c}/repo/nope.md", f"{c}/repo/nope.md", False, False, False, False)),
        ]
    elif case_id == "separators":
        probes = [
            ("repo/services/payments/AGENTS.md/", (f"{c}/repo/services/payments/AGENTS.md", f"{c}/repo/services/payments/AGENTS.md", True, False, False, False)),
            ("repo//AGENTS.md", (f"{c}/repo/AGENTS.md", f"{c}/repo/AGENTS.md", True, False, False, False)),
        ]
    elif case_id == "deep-chain":
        probes = [
            ("repo/a/b/c/d/e/f/AGENTS.md", (f"{c}/repo/a/b/c/d/e/f/AGENTS.md", f"{c}/repo/a/b/c/d/e/f/AGENTS.md", True, False, False, False)),
            ("repo/a/b/../../AGENTS.md", (f"{c}/repo/AGENTS.md", f"{c}/repo/AGENTS.md", False, False, False, False)),
        ]
    elif case_id == "dir-symlink":
        probes = [
            ("repo/linkdir/AGENTS.md", (f"{c}/repo/linkdir/AGENTS.md", f"{c}/repo/services/AGENTS.md", True, True, False, False)),
            ("repo/loopdir-a/x", (f"{c}/repo/loopdir-a/x", None, False, True, True, False)),
        ]
    elif case_id == "windows":
        for item in _load_json(case_dir / "windows-paths.json")["cases"]:
            # Pure-string cases: canonical == expected; the shared
            # component-wise resolver yields "/"+expected as resolved
            # for drive letters, and expected-minus-one-slash for UNC
            # (bug-compatible with production canonicalize).
            expected = item["expected"]
            if expected.startswith("//"):
                resolved = expected[1:]
            else:
                resolved = "/" + expected
            probes.append((item["raw"], (expected, resolved, False, False, False, False)))
    return probes


def check_fs_case(oracle: Path, case_dir: Path, tmpdir: Path, verbose=False):
    from instructionroot.paths import canonicalize as prod_canonicalize

    case_id = case_dir.name
    failures = []
    probes = fs_probes(case_dir)
    if not probes:
        return {"case_id": case_id, "passed": True, "failures": [],
                "probes": 0}
    cwd = str(case_dir)  # probe raws are case-relative, not repo-relative
    home = str(case_dir / "home") if (case_dir / "home").exists() else str(case_dir)
    raws = [p[0] for p in probes]
    records = run_oracle_canonicalize(oracle, cwd, home, raws, tmpdir)
    for (raw, expected), rec in zip(probes, records):
        canon, resolved, exists, is_symlink, is_loop, is_broken = expected
        got = (
            rec.get("canonical_path"), rec.get("resolved_path"),
            rec.get("exists"), rec.get("is_symlink"),
            rec.get("is_loop"), rec.get("is_broken_symlink"),
        )
        if got != expected:
            failures.append(
                "%s %r: expected %r, got %r" % (case_id, raw, expected, got))
        # Production cross-check on the same input.
        try:
            prod = prod_canonicalize(raw, cwd=cwd, home=home)
            prod_got = (
                prod.canonical_path, prod.resolved_path, prod.exists,
                prod.is_symlink, prod.is_loop, prod.is_broken_symlink,
            )
            if prod_got != got:
                failures.append(
                    "%s %r: oracle %r != production %r"
                    % (case_id, raw, got, prod_got))
        except Exception as exc:
            failures.append("%s %r: production canonicalize raised %r"
                            % (case_id, raw, exc))
    if verbose or failures:
        print("[%s] fs/%s (%d probes)" % (
            "PASS" if not failures else "FAIL", case_id, len(probes)))
        for failure in failures:
            print("       %s" % failure)
    return {"case_id": case_id, "passed": not failures,
            "failures": failures, "probes": len(probes)}


# ---------------------------------------------------------------------------
# Git / trust scenarios (T004 semantics, built on the fly)
# ---------------------------------------------------------------------------

def _git(repo: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args, result.stderr))
    return result


def _git_head(repo: Path, rel: str):
    out = _git(repo, "log", "-1", "--format=%H", "--", rel)
    sha = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
    return sha if len(sha) == 40 else None


def check_git_scenarios(oracle: Path, tmpdir: Path, verbose=False):
    """Five scenarios in one temp repo; the Oracle receipt's git/trust
    fields are compared against hardcoded T004 expectations and
    against the production reference receipt."""
    failures = []
    scenarios = 0
    root = Path(tempfile.mkdtemp(prefix="oracle-git-", dir=str(tmpdir)))
    repo = root / "repo"
    home = root / "home"
    (repo / "services").mkdir(parents=True)
    home.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("# root\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init")
    head = _git_head(repo, "AGENTS.md")

    def run_codex(cwd):
        case_input = {
            "case_id": "git-scenario",
            "harness": "codex",
            "cwd": str(cwd),
            "home": str(home),
            "repo_root": str(repo),
            "policy": "default",
            "working_files": [],
            "env": {},
            "ancestor_stop": str(root),
        }
        receipt, _explain, _code, _det = run_oracle_resolve(
            oracle, case_input, tmpdir)
        return receipt

    def expect_source(receipt, rule, rel, git_expect, trust_expect, label):
        nonlocal scenarios
        scenarios += 1
        matches = [s for s in receipt["sources"]
                   if s["discovery_rule"] == rule
                   and s["canonical_path"] == str(repo / rel)]
        if not matches:
            failures.append("%s: source %s %s missing" % (label, rule, rel))
            return
        src = matches[0]
        got = (src["git"]["tracked"], src["git"]["modified"],
               src["git"]["head_commit"], src["trust"])
        want = (git_expect[0], git_expect[1], git_expect[2], trust_expect)
        if got != want:
            failures.append("%s: expected %r, got %r" % (label, want, got))

    # 1. Clean tracked tree.
    receipt = run_codex(repo)
    expect_source(receipt, "codex.repo-chain", "AGENTS.md",
                  (True, False, head), "GIT_TRACKED", "clean")
    # 2. Modified in the worktree.
    (repo / "AGENTS.md").write_text("# root modified\n", encoding="utf-8")
    receipt = run_codex(repo)
    expect_source(receipt, "codex.repo-chain", "AGENTS.md",
                  (True, True, head), "GIT_MODIFIED", "worktree-modified")
    # 3. Staged modification (still modified).
    _git(repo, "add", "AGENTS.md")
    receipt = run_codex(repo)
    expect_source(receipt, "codex.repo-chain", "AGENTS.md",
                  (True, True, head), "GIT_MODIFIED", "staged-modified")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "modify")
    head = _git_head(repo, "AGENTS.md")
    # 4. Untracked nested file (cwd = services so it is discovered).
    (repo / "services" / "AGENTS.md").write_text("# nested\n", encoding="utf-8")
    receipt = run_codex(repo / "services")
    expect_source(receipt, "codex.repo-chain", "services/AGENTS.md",
                  (False, False, None), "GIT_UNTRACKED", "untracked")
    # 5. Staged new file: tracked AND modified (T004 ruling).
    _git(repo, "add", "services/AGENTS.md")
    receipt = run_codex(repo / "services")
    expect_source(receipt, "codex.repo-chain", "services/AGENTS.md",
                  (True, True, None), "GIT_MODIFIED", "staged-new")
    # 6. Non-git workspace: repo_root null, no git repo anywhere.
    plain = root / "plain"
    plain_home = root / "plain-home"
    plain.mkdir()
    plain_home.mkdir()
    (plain / "AGENTS.md").write_text("# plain\n", encoding="utf-8")
    case_input = {
        "case_id": "git-scenario-nogit",
        "harness": "codex",
        "cwd": str(plain),
        "home": str(plain_home),
        "repo_root": None,
        "policy": "default",
        "working_files": [],
        "env": {},
        "ancestor_stop": str(root),
    }
    receipt, _e, _c, _d = run_oracle_resolve(oracle, case_input, tmpdir)
    scenarios += 1
    if receipt is None:
        failures.append("non-git: no receipt")
    else:
        src = receipt["sources"][0] if receipt["sources"] else None
        if src is None or src["git"]["repo"] is not None \
                or src["git"]["tracked"] is not False:
            failures.append("non-git: expected git.repo null + tracked "
                            "false, got %r" % (src["git"] if src else None,))
        # Production cross-check for the non-git case.
        case = {"case_id": "git-scenario-nogit", "harness": "codex",
                "cwd": "plain", "home": "plain-home", "repo_root": None,
                "policy": "default", "working_files": [], "env": {}}
        prod, prod_err = build_production_receipt(root, case)
        if prod_err is not None:
            failures.append("non-git: %s" % prod_err)
        else:
            diffs = deep_diff(receipt, prod)
            if diffs:
                failures.append("non-git: receipt != production (%s)"
                                % "; ".join(diffs[:6]))

    if verbose or failures:
        print("[%s] git/trust scenarios (%d)" % (
            "PASS" if not failures else "FAIL", scenarios))
        for failure in failures:
            print("       %s" % failure)
    return {"passed": not failures, "failures": failures,
            "scenarios": scenarios}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="P028 Oracle parity checker")
    parser.add_argument("--all", action="store_true",
                        help="run every section (default when no section given)")
    parser.add_argument("--resolver", action="store_true")
    parser.add_argument("--imports", action="store_true")
    parser.add_argument("--fs", action="store_true")
    parser.add_argument("--git", action="store_true")
    parser.add_argument("--cases", default=None,
                        help="comma-separated case ids (resolver/imports only)")
    parser.add_argument("--oracle", default=None,
                        help="oracle binary path (default: build release)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    sections = set()
    if args.all or not (args.resolver or args.imports or args.fs or args.git):
        sections = {"resolver", "imports", "fs", "git"}
    else:
        sections = {s for s in ("resolver", "imports", "fs", "git")
                    if getattr(args, s)}
    wanted = None
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",") if c.strip()}

    oracle = Path(args.oracle) if args.oracle else build_oracle()
    if not oracle.exists():
        print("oracle binary not found: %s" % oracle)
        return 2

    tmpdir = Path(tempfile.mkdtemp(prefix="compare-oracle-"))
    try:
        source_total = source_pass = 0
        trust_total = trust_pass = 0
        edge_total = edge_pass = 0
        verdict_total = verdict_pass = 0
        hash_total = hash_pass = 0
        fs_total = fs_pass = fs_probes_n = 0
        git_ok = True

        if "resolver" in sections:
            case_dirs = sorted(
                d for d in RESOLVER_DIR.iterdir()
                if d.is_dir() and (d / "case.json").exists())
            if wanted is not None:
                case_dirs = [d for d in case_dirs if d.name in wanted]
            for case_dir in case_dirs:
                result = check_resolver_case(
                    oracle, case_dir, tmpdir, verbose=args.verbose)
                source_total += 1
                source_pass += 1 if result["passed"] else 0
                trust_total += 1
                trust_pass += 1 if result.get("trust_ok") else 0
                edge_total += 1
                edge_pass += 1 if result.get("edge_ok") else 0
                verdict_total += 1
                verdict_pass += 1 if result.get("verdict_ok") else 0
                hash_total += 1
                hash_pass += 1 if result.get("hash_ok") else 0

        if "imports" in sections:
            case_dirs = sorted(
                d for d in IMPORTS_DIR.iterdir()
                if d.is_dir() and (d / "case.json").exists())
            if wanted is not None:
                case_dirs = [d for d in case_dirs if d.name in wanted]
            for case_dir in case_dirs:
                result = check_imports_case(
                    oracle, case_dir, tmpdir, verbose=args.verbose)
                trust_total += 1
                trust_pass += 1 if result.get("trust_ok") else 0
                edge_total += 1
                edge_pass += 1 if result.get("edge_ok") else 0
                verdict_total += 1
                verdict_pass += 1 if result.get("verdict_ok") else 0
                hash_total += 1
                hash_pass += 1 if result.get("hash_ok") else 0

        if "fs" in sections:
            case_dirs = sorted(
                d for d in FS_DIR.iterdir()
                if d.is_dir() and (d / "case.json").exists())
            if wanted is not None:
                case_dirs = [d for d in case_dirs if d.name in wanted]
            for case_dir in case_dirs:
                result = check_fs_case(
                    oracle, case_dir, tmpdir, verbose=args.verbose)
                fs_total += 1
                fs_pass += 1 if result["passed"] else 0
                fs_probes_n += result.get("probes", 0)

        if "git" in sections:
            result = check_git_scenarios(
                oracle, tmpdir, verbose=args.verbose)
            git_ok = result["passed"]

        def pct(passed, total):
            return 100.0 if total == 0 else 100.0 * passed / total

        print("resolver_cases=%d imports_cases=%d fs_cases=%d fs_probes=%d"
              % (source_total,
                 (edge_total - source_total) if "imports" in sections else 0,
                 fs_total, fs_probes_n))
        print("source_parity=%.1f%% trust_parity=%.1f%% edge_parity=%.1f%% "
              "verdict_parity=%.1f%% hash_parity=%.1f%%"
              % (pct(source_pass, source_total),
                 pct(trust_pass, trust_total),
                 pct(edge_pass, edge_total),
                 pct(verdict_pass, verdict_total),
                 pct(hash_pass, hash_total)))
        print("fs_parity=%.1f%% git_scenarios=%s"
              % (pct(fs_pass, fs_total), "PASS" if git_ok else "FAIL"))
        all_ok = (
            pct(source_pass, source_total) == 100.0
            and pct(trust_pass, trust_total) == 100.0
            and pct(edge_pass, edge_total) == 100.0
            and pct(verdict_pass, verdict_total) == 100.0
            and pct(hash_pass, hash_total) == 100.0
            and pct(fs_pass, fs_total) == 100.0
            and git_ok
        )
        return 0 if all_ok else 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
