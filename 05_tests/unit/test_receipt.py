"""Unit tests for P028 T005 — RFC 8785 JCS canonicalization + receipt builder.

JCS tests pin the two places where JCS differs from naive
``json.dumps(sort_keys=True)`` (key order by UTF-16 code unit,
numbers by ECMAScript semantics), plus the RFC 8785 example
vector, string escaping (including lone surrogates and astral
pairs), nested structures, and rejection of non-JSON values.

Receipt tests pin: hash determinism (same input twice, key-order
independence, content sensitivity), the frozen receipt shape,
profile-version validation, source/edge validation (fail-closed),
and verdict derivation under the default and varied policies
(policy_schema.json ``verdict_derivation``).

All data is synthetic; no filesystem, network or wall-clock use
except tmp_path trees for the SourceCandidate conversion test.
"""

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_src"))

from instructionroot.git import GitState  # noqa: E402
from instructionroot.profiles._common import Precedence, SourceCandidate  # noqa: E402
from instructionroot.receipt import (  # noqa: E402
    DEFAULT_POLICY,
    EXIT_CODES,
    PROFILE_VERSIONS,
    build_receipt,
    build_source_record,
    canonical_json,
    canonical_json_bytes,
    derive_verdict,
    exit_code_for_verdict,
    receipt_hash_for,
    validate_policy,
    verify_receipt,
)
from instructionroot.resolver import (  # noqa: E402
    DEFAULT_POLICY as RESOLVER_DEFAULT_POLICY,
    UnsupportedProfileError,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


# ---------------------------------------------------------------------------
# JCS: objects / key order
# ---------------------------------------------------------------------------

def test_jcs_keys_sorted_and_no_whitespace():
    assert canonical_json({"b": 1, "a": {"d": 4, "c": 3}}) == \
        '{"a":{"c":3,"d":4},"b":1}'
    assert canonical_json({}) == "{}"
    assert canonical_json([]) == "[]"
    assert canonical_json({"a": [1, {"z": 2, "y": 3}]}) == \
        '{"a":[1,{"y":3,"z":2}]}'


def test_jcs_key_order_is_utf16_code_unit_not_code_point():
    # U+10000 is U+D800 U+DC00 in UTF-16: its first code unit
    # 0xD800 sorts BEFORE U+FFFF (0xFFFF). Python code-point order
    # would put U+FFFF first — that is the sort_keys=True trap.
    value = {"\uffff": 1, "\U00010000": 2}
    assert canonical_json(value) == '{"\U00010000":2,"\uffff":1}'
    assert list(json.loads(canonical_json(value)).keys()) == \
        ["\U00010000", "\uffff"]
    # ASCII vs astral: 'a' (0x0061) sorts before any astral key.
    assert canonical_json({"\U0001f600": 1, "a": 2}) == '{"a":2,"\U0001f600":1}'
    # Lone surrogates sort by their code unit too.
    assert canonical_json({"\ud800": 1, "a": 2}) == '{"a":2,"\\ud800":1}'


def test_jcs_unicode_keys_and_values_verbatim():
    assert canonical_json({"中文": "说明✓"}) == '{"中文":"说明✓"}'
    assert canonical_json({"é": "ünïcode"}) == '{"é":"ünïcode"}'


def test_jcs_string_escaping():
    assert canonical_json({"s": 'a"b\\c'}) == '{"s":"a\\"b\\\\c"}'
    assert canonical_json({"s": "a\nb\tc\rd\be\ff"}) == \
        '{"s":"a\\nb\\tc\\rd\\be\\ff"}'
    assert canonical_json({"s": "\x00\x01\x1f"}) == '{"s":"\\u0000\\u0001\\u001f"}'
    # DEL and non-ASCII are NOT escaped.
    assert canonical_json({"s": "\x7f"}) == '{"s":"\x7f"}'
    assert canonical_json({"s": "😀"}) == '{"s":"😀"}'
    # Lone surrogates escape; a valid pair becomes the astral char.
    assert canonical_json(json.loads('{"s":"\\ud800"}')) == '{"s":"\\ud800"}'
    assert canonical_json(json.loads('{"s":"\\udc00"}')) == '{"s":"\\udc00"}'
    assert canonical_json(json.loads('{"s":"\\ud83d\\ude00"}')) == '{"s":"😀"}'


def test_jcs_numbers_ecmascript():
    # RFC 8785 §3.2.2.4 example vector (Appendix B style).
    assert canonical_json(
        {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3,
                     0.000000000000000000000000001]}
    ) == '{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'
    assert canonical_json({"a": 1e16}) == '{"a":10000000000000000}'
    assert canonical_json({"a": 1e21}) == '{"a":1e+21}'
    assert canonical_json({"a": 1e20}) == '{"a":100000000000000000000}'
    assert canonical_json({"a": 100.0}) == '{"a":100}'
    assert canonical_json({"a": 0.000001}) == '{"a":0.000001}'
    assert canonical_json({"a": 0.0000001}) == '{"a":1e-7}'
    assert canonical_json({"a": 1.5e-7}) == '{"a":1.5e-7}'
    assert canonical_json({"a": -0.0}) == '{"a":0}'
    assert canonical_json({"a": 0.1}) == '{"a":0.1}'
    assert canonical_json({"a": 123.456}) == '{"a":123.456}'
    assert canonical_json({"a": 5e-324}) == '{"a":5e-324}'
    assert canonical_json({"a": -1.5}) == '{"a":-1.5}'
    assert canonical_json({"a": 123456789}) == '{"a":123456789}'


def test_jcs_numbers_ints_and_safe_range():
    assert canonical_json({"a": 0}) == '{"a":0}'
    assert canonical_json({"a": -7}) == '{"a":-7}'
    assert canonical_json({"a": 2 ** 53 - 1}) == '{"a":9007199254740991}'
    # Outside the safe-integer range the JCS input is a double:
    # 2**53+1 rounds to 2**53 — JCS-faithful, not exact bignum.
    assert canonical_json({"a": 2 ** 53 + 1}) == '{"a":9007199254740992}'
    assert canonical_json({"a": 10 ** 30}) == '{"a":1e+30}'


def test_jcs_scalars_and_nesting():
    assert canonical_json(None) == "null"
    assert canonical_json(True) == "true"
    assert canonical_json(False) == "false"
    assert canonical_json("x") == '"x"'
    assert canonical_json([1, "a", None, True, {"k": [2]}]) == \
        '[1,"a",null,true,{"k":[2]}]'
    assert canonical_json((1, 2)) == "[1,2]"  # tuple as array
    assert canonical_json({"a": {"b": {"c": {"d": []}}}}) == \
        '{"a":{"b":{"c":{"d":[]}}}}'


def test_jcs_rejects_non_json():
    with pytest.raises(ValueError):
        canonical_json({"a": math.nan})
    with pytest.raises(ValueError):
        canonical_json({"a": math.inf})
    with pytest.raises(ValueError):
        canonical_json({"a": -math.inf})
    with pytest.raises(TypeError):
        canonical_json({1: "x"})  # non-str key
    with pytest.raises(TypeError):
        canonical_json({"a": {1, 2}})  # set: no order, fail-closed
    with pytest.raises(TypeError):
        canonical_json(b"bytes")
    with pytest.raises(TypeError):
        canonical_json(object())


def test_jcs_bytes_is_utf8_of_string():
    value = {"key": "中文😀"}
    assert canonical_json_bytes(value) == canonical_json(value).encode("utf-8")
    assert hashlib.sha256(canonical_json_bytes(value)).hexdigest() == \
        hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def test_jcs_differs_from_sort_keys_dumps_where_it_must():
    # sort_keys=True sorts by code point: U+FFFF before U+10000.
    naive = json.dumps({"\uffff": 1, "\U00010000": 2},
                       sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    assert naive == '{"￿":1,"𐀀":2}'
    assert canonical_json({"\uffff": 1, "\U00010000": 2}) != naive
    # And naive float formatting differs from ECMAScript.
    assert json.dumps({"a": 1e16}, separators=(",", ":")) == '{"a":1e+16}'
    assert canonical_json({"a": 1e16}) == '{"a":10000000000000000}'


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def test_default_policy_matches_contract_and_resolver():
    contract_path = Path(__file__).resolve().parents[2] / "00_contract" / "policy_schema.json"
    with open(contract_path, encoding="utf-8") as fh:
        contract = json.load(fh)
    assert DEFAULT_POLICY == contract["default_policy"]
    assert DEFAULT_POLICY == RESOLVER_DEFAULT_POLICY
    assert validate_policy(None) == DEFAULT_POLICY
    assert validate_policy({"block_repo_untracked": True})["block_repo_untracked"] is True
    assert validate_policy({"block_repo_untracked": True})["allow_user_scope"] is True


def test_validate_policy_rejects_bad_input():
    with pytest.raises(ValueError):
        validate_policy({"no_such_field": True})
    with pytest.raises(ValueError):
        validate_policy({"allow_user_scope": "yes"})
    with pytest.raises(ValueError):
        validate_policy(["allow_user_scope"])


# ---------------------------------------------------------------------------
# Receipt fixtures
# ---------------------------------------------------------------------------

def _git(*, repo="/w/repo", tracked=True, modified=False, head_commit=SHA_A):
    return {"repo": repo, "tracked": tracked, "modified": modified,
            "head_commit": head_commit}


def _source(source_id="src-0001", trust="GIT_TRACKED", scope="project",
            phase="startup", rule="codex.repo-chain", kind="ORDERED",
            canonical="/w/repo/AGENTS.md", **overrides):
    src = {
        "source_id": source_id,
        "raw_path": "repo/AGENTS.md",
        "canonical_path": canonical,
        "resolved_path": canonical,
        "scope": scope,
        "phase": phase,
        "discovery_rule": rule,
        "precedence": {"kind": kind},
        "sha256": SHA_A,
        "git": _git(),
        "trust": trust,
    }
    src.update(overrides)
    return src


def _edge(edge_id="edge-0001", from_id="src-0001", syntax="@shared/a.md",
          to=None, resolved="/w/repo/shared/a.md", allowed=True,
          reason="WITHIN_REPO"):
    return {
        "edge_id": edge_id,
        "from": from_id,
        "syntax": syntax,
        "to": to,
        "resolved_target": resolved,
        "allowed": allowed,
        "reason": reason,
    }


def _receipt_kwargs(**overrides):
    kwargs = {
        "profile": "codex",
        "cwd": "/w/repo/services",
        "repo_root": "/w/repo",
        "home": "/w/home",
        "sources": [_source()],
        "edges": [],
    }
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# build_receipt: shape + hash
# ---------------------------------------------------------------------------

def test_build_receipt_shape_and_hash():
    receipt = build_receipt(**_receipt_kwargs())
    assert receipt["receipt_version"] == 1
    assert receipt["profile"] == {
        "id": "codex",
        "version": "codex-2026-11",
        "rules_hash":
        "sha256:a0a03c1cdd77f8d9110ccbc77dae937e30e288a2609e6b04b60d26d15af5dc23",
    }
    assert receipt["workspace"] == {
        "cwd": "/w/repo/services",
        "repo_root": "/w/repo",
        "home": "/w/home",
    }
    assert receipt["verdict"] == "PASS"
    assert receipt["policy"]["policy_schema_version"] == 1
    assert receipt["policy"]["values"] == DEFAULT_POLICY
    assert len(receipt["receipt_hash"]) == 64
    assert receipt["receipt_hash"] == receipt_hash_for(receipt)
    assert verify_receipt(receipt) is True
    # No volatile fields anywhere in the receipt.
    assert "timestamp" not in json.dumps(receipt)
    assert "duration" not in json.dumps(receipt)
    assert "username" not in json.dumps(receipt)


def test_build_receipt_hash_deterministic_same_input_twice():
    first = build_receipt(**_receipt_kwargs())
    second = build_receipt(**_receipt_kwargs())
    assert first["receipt_hash"] == second["receipt_hash"]
    assert first == second


def test_build_receipt_hash_key_order_independent():
    kwargs = _receipt_kwargs()
    # Rebuild the same source dict with a different insertion order.
    src = _source()
    reordered = dict(reversed(list(src.items())))
    kwargs["sources"] = [reordered]
    assert build_receipt(**kwargs)["receipt_hash"] == \
        build_receipt(**_receipt_kwargs())["receipt_hash"]


def test_build_receipt_hash_changes_when_content_changes():
    base = build_receipt(**_receipt_kwargs())["receipt_hash"]
    changed = build_receipt(**_receipt_kwargs(
        sources=[_source(trust="GIT_UNTRACKED")]))["receipt_hash"]
    assert changed != base
    changed_edge = build_receipt(**_receipt_kwargs(
        edges=[_edge(allowed=False, reason="MISSING")]))["receipt_hash"]
    assert changed_edge != base


def test_build_receipt_hash_deterministic_100_runs():
    hashes = {
        build_receipt(**_receipt_kwargs())["receipt_hash"] for _ in range(100)
    }
    assert len(hashes) == 1


def test_verify_receipt_rejects_tampering():
    receipt = build_receipt(**_receipt_kwargs())
    assert verify_receipt(receipt) is True
    tampered = dict(receipt)
    tampered["verdict"] = "BLOCK"
    assert verify_receipt(tampered) is False
    tampered_hash = dict(receipt)
    tampered_hash["receipt_hash"] = "0" * 64
    assert verify_receipt(tampered_hash) is False
    assert verify_receipt({"receipt_hash": "xyz"}) is False
    assert verify_receipt("not a dict") is False


def test_receipt_hash_excludes_receipt_hash_field():
    receipt = build_receipt(**_receipt_kwargs())
    without = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    assert receipt_hash_for(receipt) == receipt_hash_for(without)
    assert receipt_hash_for(receipt) == hashlib.sha256(
        canonical_json_bytes(without)).hexdigest()


def test_build_receipt_assigns_ids_in_order():
    receipt = build_receipt(**_receipt_kwargs(
        sources=[{k: v for k, v in _source().items() if k != "source_id"},
                 {k: v for k, v in _source(
                     canonical="/w/repo/services/AGENTS.md").items()
                  if k != "source_id"}],
        edges=[{k: v for k, v in _edge().items() if k != "edge_id"}],
    ))
    assert [s["source_id"] for s in receipt["sources"]] == ["src-0001", "src-0002"]
    assert [e["edge_id"] for e in receipt["edges"]] == ["edge-0001"]


def test_build_receipt_without_policy_block():
    receipt = build_receipt(**_receipt_kwargs(), include_policy=False)
    assert "policy" not in receipt
    assert verify_receipt(receipt) is True


def test_build_receipt_profile_validation():
    with pytest.raises(UnsupportedProfileError):
        build_receipt(**_receipt_kwargs(profile="vim"))
    with pytest.raises(UnsupportedProfileError):
        build_receipt(**_receipt_kwargs(profile_version="codex-1999-01"))
    with pytest.raises(UnsupportedProfileError):
        build_receipt(**_receipt_kwargs(
            profile="claude-code", profile_version="codex-2026-11"))
    # Each frozen id/version pair is accepted.
    for profile, version in PROFILE_VERSIONS.items():
        receipt = build_receipt(**_receipt_kwargs(
            profile=profile, profile_version=version, sources=[], edges=[]))
        assert receipt["profile"]["version"] == version
        assert receipt["verdict"] == "PASS"  # empty chain, no conditions


def test_build_receipt_rejects_bad_sources_and_edges():
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(sources=[_source(trust="EVIL")]))
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(sources=[_source(scope="repo")]))
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(
            sources=[_source(), _source()]))  # duplicate src-0001
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(
            sources=[{k: v for k, v in _source().items()
                      if k != "sha256"}]))  # required field missing
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(
            sources=[_source(extra_field="nope")]))  # unknown field
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(
            edges=[_edge(to="src-9999")]))  # unknown target
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(
            edges=[_edge(allowed="yes")]))  # allowed must be bool
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(policy={"bogus": True}))
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(verdict="MAYBE"))
    with pytest.raises(ValueError):
        build_receipt(**_receipt_kwargs(cwd=""))


def test_build_receipt_explicit_error_verdicts():
    for verdict in ("INPUT_ERROR", "UNSUPPORTED_PROFILE", "INTERNAL_ERROR"):
        receipt = build_receipt(**_receipt_kwargs(verdict=verdict))
        assert receipt["verdict"] == verdict
        assert verify_receipt(receipt) is True


def test_exit_codes():
    assert EXIT_CODES == {
        "PASS": 0, "WARN": 10, "BLOCK": 20,
        "INPUT_ERROR": 30, "UNSUPPORTED_PROFILE": 40, "INTERNAL_ERROR": 50,
    }
    for verdict, code in EXIT_CODES.items():
        assert exit_code_for_verdict(verdict) == code
    with pytest.raises(ValueError):
        exit_code_for_verdict("MAYBE")


# ---------------------------------------------------------------------------
# build_source_record
# ---------------------------------------------------------------------------

def test_build_source_record_from_candidate(tmp_path):
    candidate = SourceCandidate(
        raw_path="repo/AGENTS.md",
        canonical_path="/w/repo/AGENTS.md",
        resolved_path="/w/repo/AGENTS.md",
        scope="project",
        phase="startup",
        discovery_rule="codex.repo-chain",
        precedence=Precedence(kind="ORDERED", detail="root-to-leaf"),
        sha256=SHA_A,
        is_symlink=False,
        symlink_target=None,
    )
    record = build_source_record(
        candidate, git=_git(), trust="GIT_TRACKED", source_id="src-0001")
    assert record["source_id"] == "src-0001"
    assert record["precedence"] == {"kind": "ORDERED", "detail": "root-to-leaf"}
    assert record["git"] == _git()
    assert record["trust"] == "GIT_TRACKED"
    assert record["symlink_target"] is None
    assert record["is_symlink"] is False
    # The record is accepted by the receipt builder as-is.
    receipt = build_receipt(**_receipt_kwargs(sources=[record]))
    assert receipt["sources"][0]["source_id"] == "src-0001"
    assert receipt["verdict"] == "PASS"


def test_build_source_record_rejects_bad_trust_and_missing_resolved(tmp_path):
    candidate = SourceCandidate(
        raw_path="repo/AGENTS.md",
        canonical_path="/w/repo/AGENTS.md",
        resolved_path="/w/repo/AGENTS.md",
        scope="project",
        phase="startup",
        discovery_rule="codex.repo-chain",
        precedence=Precedence(kind="ORDERED"),
        sha256=SHA_A,
    )
    with pytest.raises(ValueError):
        build_source_record(candidate, git=_git(), trust="EVIL")
    looped = SourceCandidate(
        raw_path="repo/loop.md",
        canonical_path="/w/repo/loop.md",
        resolved_path=None,  # symlink loop: no resolved path
        scope="project",
        phase="startup",
        discovery_rule="codex.repo-chain",
        precedence=Precedence(kind="ORDERED"),
        sha256=None,
    )
    with pytest.raises(ValueError):
        build_source_record(looped, git=_git(), trust="NOT_OBSERVED")


# ---------------------------------------------------------------------------
# derive_verdict
# ---------------------------------------------------------------------------

def test_derive_verdict_pass_empty_and_clean():
    assert derive_verdict([], []) == "PASS"
    assert derive_verdict([_source()], []) == "PASS"
    assert derive_verdict([_source()], [_edge()]) == "PASS"


def test_derive_verdict_warn_untracked_and_modified():
    assert derive_verdict([_source(trust="GIT_UNTRACKED")], []) == "WARN"
    assert derive_verdict([_source(trust="GIT_MODIFIED")], []) == "WARN"
    assert derive_verdict(
        [_source(trust="GIT_UNTRACKED")], [],
        {"block_repo_untracked": True}) == "BLOCK"
    assert derive_verdict(
        [_source(trust="GIT_MODIFIED")], [],
        {"block_repo_modified": True}) == "BLOCK"


def test_derive_verdict_block_outside_symlink_import_escape():
    assert derive_verdict([_source(trust="OUTSIDE_REPO")], []) == "BLOCK"
    assert derive_verdict([_source(trust="SYMLINK_ESCAPE")], []) == "BLOCK"
    assert derive_verdict([_source(trust="IMPORT_ESCAPE")], []) == "BLOCK"
    assert derive_verdict(
        [_source(trust="OUTSIDE_REPO")], [],
        {"block_outside_repo": False}) == "PASS"
    assert derive_verdict(
        [_source(trust="SYMLINK_ESCAPE")], [],
        {"block_symlink_escape": False}) == "PASS"


def test_derive_verdict_block_missing_and_not_observed():
    assert derive_verdict([_source(trust="MISSING")], []) == "BLOCK"
    assert derive_verdict(
        [_source(trust="MISSING")], [],
        {"block_missing_reference": False}) == "PASS"
    # NOT_OBSERVED is fail-closed: no policy field can pass it.
    assert derive_verdict([_source(trust="NOT_OBSERVED")], []) == "BLOCK"
    assert derive_verdict(
        [_source(trust="NOT_OBSERVED")], [],
        {"block_missing_reference": False,
         "block_outside_repo": False}) == "BLOCK"


def test_derive_verdict_block_disallowed_edge():
    assert derive_verdict(
        [_source()], [_edge(allowed=False, reason="MISSING")]) == "BLOCK"
    assert derive_verdict(
        [_source()], [_edge(allowed=False, reason="IMPORT_ESCAPE")]) == "BLOCK"
    assert derive_verdict(
        [_source()], [_edge(allowed=False, reason="DEPTH_EXCEEDED")]) == "BLOCK"
    # Both edge-blocking flags off: a disallowed edge alone does not block.
    assert derive_verdict(
        [_source()], [_edge(allowed=False, reason="MISSING")],
        {"block_import_escape": False,
         "block_missing_reference": False}) == "PASS"


def test_derive_verdict_warn_unspecified_precedence():
    assert derive_verdict(
        [_source(kind="UNSPECIFIED")], []) == "WARN"
    assert derive_verdict(
        [_source(kind="UNSPECIFIED")], [],
        {"warn_on_unspecified_precedence": False}) == "PASS"
    assert derive_verdict(
        [_source(kind="COMBINE_UNORDERED")], []) == "PASS"


def test_derive_verdict_allow_flags_block():
    assert derive_verdict(
        [_source(scope="user", trust="USER_SCOPE")], [],
        {"allow_user_scope": False}) == "BLOCK"
    assert derive_verdict(
        [_source(scope="managed", trust="USER_SCOPE")], [],
        {"allow_managed_scope": False}) == "BLOCK"
    assert derive_verdict(
        [_source()], [], {"allow_repo_tracked": False}) == "BLOCK"


def test_derive_verdict_treat_warn_as_block():
    assert derive_verdict(
        [_source(trust="GIT_UNTRACKED")], [],
        {"treat_warn_as_block": True}) == "BLOCK"
    assert derive_verdict(
        [_source()], [], {"treat_warn_as_block": True}) == "PASS"


def test_derive_verdict_block_beats_warn():
    assert derive_verdict(
        [_source(trust="GIT_UNTRACKED"), _source(
            source_id="src-0002", trust="OUTSIDE_REPO",
            canonical="/w/outside/AGENTS.md")], []) == "BLOCK"


def test_malformed_input_never_passes():
    # A malformed import must not produce PASS: a MISSING edge under
    # the default policy blocks, and a bad policy raises instead.
    assert derive_verdict(
        [_source()], [_edge(allowed=False, reason="MISSING")]) == "BLOCK"
    with pytest.raises(ValueError):
        derive_verdict([_source()], [], {"bogus": True})


# ---------------------------------------------------------------------------
# FIX-R3 D: receipt spelling unification (V2 class 2)
#
# Production stored workspace.cwd/home/repo_root and sources[].raw_path
# as raw backslash strings (the compare_oracle runner passes raw
# str(case_dir / ...) strings); the Oracle stores C:/ spellings.
# Same semantics, different receipt_hash. build_receipt now unifies
# Windows spellings to C:/ form at assembly; POSIX spellings and
# relative / "~" raw_paths keep their contract meaning untouched.
# ---------------------------------------------------------------------------

def test_fixr3_d_workspace_windows_spellings_unified():
    receipt = build_receipt(**_receipt_kwargs(
        cwd="C:\\p028-src-v2\\case1\\repo",
        repo_root="C:\\p028-src-v2\\case1\\repo",
        home="C:\\Users\\Du",
    ))
    assert receipt["workspace"] == {
        "cwd": "C:/p028-src-v2/case1/repo",
        "repo_root": "C:/p028-src-v2/case1/repo",
        "home": "C:/Users/Du",
    }


def test_fixr3_d_workspace_spelling_unification_is_hash_stable():
    # The same receipt built from backslash vs slash spellings must
    # hash identically — that is the class-2 parity failure.
    backslash = build_receipt(**_receipt_kwargs(
        cwd="C:\\p028-src-v2\\case1\\repo",
        repo_root="C:\\p028-src-v2\\case1\\repo",
        home="C:\\Users\\Du",
        sources=[_source(raw_path="C:\\p028-src-v2\\case1\\repo\\AGENTS.md",
                         canonical="C:/p028-src-v2/case1/repo/AGENTS.md")],
    ))
    slash = build_receipt(**_receipt_kwargs(
        cwd="C:/p028-src-v2/case1/repo",
        repo_root="C:/p028-src-v2/case1/repo",
        home="C:/Users/Du",
        sources=[_source(raw_path="C:/p028-src-v2/case1/repo/AGENTS.md",
                         canonical="C:/p028-src-v2/case1/repo/AGENTS.md")],
    ))
    assert backslash["receipt_hash"] == slash["receipt_hash"]
    assert backslash["sources"][0]["raw_path"] == (
        "C:/p028-src-v2/case1/repo/AGENTS.md")


def test_fixr3_d_raw_path_relative_and_tilde_untouched():
    # Contract: raw_path is "as discovered" — it may be relative or
    # contain "~". Only the separator spelling of Windows-style
    # absolute paths is unified; these keep their meaning.
    receipt = build_receipt(**_receipt_kwargs(
        sources=[_source(raw_path="repo/AGENTS.md")]))
    assert receipt["sources"][0]["raw_path"] == "repo/AGENTS.md"
    receipt = build_receipt(**_receipt_kwargs(
        sources=[_source(raw_path="~/AGENTS.md")]))
    assert receipt["sources"][0]["raw_path"] == "~/AGENTS.md"
    # POSIX workspace spellings pass through unchanged.
    receipt = build_receipt(**_receipt_kwargs())
    assert receipt["workspace"] == {
        "cwd": "/w/repo/services", "repo_root": "/w/repo",
        "home": "/w/home"}

# ---------------------------------------------------------------------------
# FIX-R4: sources[].git.repo spelling unification (V3 classes 1/3/4)
#
# V3 Windows re-run: all 4 verdicts correct, but classes 1/3/4 failed
# receipt-hash parity on this one field — production stored
# ``C:\p028-src-v3\...\repo`` (native os.path.join) while the Oracle
# stored ``C:/p028-src-v3/.../repo``. It was the only receipt path
# field not wrapped in _normalize_receipt_path. Class 2 passed
# precisely because its source is outside the repo, so git.repo is
# None on both sides. build_source_record now unifies git.repo to
# C:/ form on both the GitState and the dict input branches.
# ---------------------------------------------------------------------------

def _fixr4_candidate():
    return SourceCandidate(
        raw_path="repo/AGENTS.md",
        canonical_path="/w/repo/AGENTS.md",
        resolved_path="/w/repo/AGENTS.md",
        scope="project",
        phase="startup",
        discovery_rule="codex.repo-chain",
        precedence=Precedence(kind="ORDERED", detail="root-to-leaf"),
        sha256=SHA_A,
        is_symlink=False,
        symlink_target=None,
    )


def test_fixr4_git_repo_backslash_unified_to_slash():
    # (a) The V3 case verbatim: a Windows backslash repo from a
    # GitState (the production path — cli.py / compare_oracle.py /
    # run_golden.py all pass GitState) comes out C:/ form.
    git = GitState(repo="C:\\p028-src-v3\\case1\\repo", tracked=True,
                   modified=False, head_commit=SHA_A)
    record = build_source_record(
        _fixr4_candidate(), git=git, trust="GIT_TRACKED")
    assert record["git"]["repo"] == "C:/p028-src-v3/case1/repo"
    assert record["git"]["tracked"] is True
    assert record["git"]["head_commit"] == SHA_A


def test_fixr4_git_repo_dict_branch_unified():
    # Same field, same fix on the dict input branch: the docstring
    # promises git may be a dict, and the existing candidate test
    # calls it that way, so a dict caller must not reintroduce the
    # backslash spelling.
    record = build_source_record(
        _fixr4_candidate(),
        git=_git(repo="C:\\p028-src-v3\\case1\\repo"),
        trust="GIT_TRACKED")
    assert record["git"]["repo"] == "C:/p028-src-v3/case1/repo"


def test_fixr4_git_repo_none_passthrough():
    # (b) The class-2 case: source outside the repo, git.repo is
    # None on both sides — it must stay None, not become "" or raise.
    git = GitState(repo=None, tracked=False, modified=False,
                   head_commit=None)
    record = build_source_record(
        _fixr4_candidate(), git=git, trust="GIT_UNTRACKED")
    assert record["git"]["repo"] is None
    record = build_source_record(
        _fixr4_candidate(),
        git=_git(repo=None, tracked=False, head_commit=None),
        trust="GIT_UNTRACKED")
    assert record["git"]["repo"] is None


def test_fixr4_git_repo_posix_and_slash_spelling_unchanged():
    # (c) Linux behaviour unchanged: a POSIX repo passes through
    # verbatim, and an already-C:/ repo is not re-spelled.
    git = GitState(repo="/w/repo", tracked=True, modified=False,
                   head_commit=SHA_A)
    record = build_source_record(
        _fixr4_candidate(), git=git, trust="GIT_TRACKED")
    assert record["git"]["repo"] == "/w/repo"
    git = GitState(repo="C:/p028-src-v3/case1/repo", tracked=True,
                   modified=False, head_commit=SHA_A)
    record = build_source_record(
        _fixr4_candidate(), git=git, trust="GIT_TRACKED")
    assert record["git"]["repo"] == "C:/p028-src-v3/case1/repo"


def test_fixr4_git_repo_spelling_is_hash_stable():
    # The V3 failure mode, pinned at the hash: the same receipt
    # built from a backslash-repo record vs a slash-repo record
    # must hash identically, or parity fails again.
    backslash = build_source_record(
        _fixr4_candidate(),
        git=GitState(repo="C:\\p028-src-v3\\case1\\repo", tracked=True,
                     modified=False, head_commit=SHA_A),
        trust="GIT_TRACKED", source_id="src-0001")
    slash = build_source_record(
        _fixr4_candidate(),
        git=GitState(repo="C:/p028-src-v3/case1/repo", tracked=True,
                     modified=False, head_commit=SHA_A),
        trust="GIT_TRACKED", source_id="src-0001")
    assert backslash["git"] == slash["git"]
    receipt_backslash = build_receipt(
        **_receipt_kwargs(sources=[backslash]))
    receipt_slash = build_receipt(**_receipt_kwargs(sources=[slash]))
    assert receipt_backslash["receipt_hash"] == receipt_slash["receipt_hash"]


def test_fixr4_dict_source_git_repo_unified_in_build_receipt():
    # FIX-R4 follow-up (dict passthrough): the audit found the same
    # field leaking a second way — _normalize_sources passed a dict
    # source's git.repo through verbatim, so a caller handing a dict
    # source straight to build_receipt (bypassing
    # build_source_record) got a backslash repo in the receipt. The
    # three production callers all go through build_source_record,
    # so this was latent, but receipt assembly must be closed for
    # every entry point.
    backslash = _source(git=_git(repo="C:\\p028-src-v3\\case1\\repo"))
    slash = _source(git=_git(repo="C:/p028-src-v3/case1/repo"))
    receipt_backslash = build_receipt(
        **_receipt_kwargs(sources=[backslash]))
    receipt_slash = build_receipt(**_receipt_kwargs(sources=[slash]))
    assert receipt_backslash["sources"][0]["git"]["repo"] == \
        "C:/p028-src-v3/case1/repo"
    assert receipt_backslash["receipt_hash"] == receipt_slash["receipt_hash"]
    # The caller's dict must not be mutated: record is a shallow
    # copy, so the fix copies the git dict before normalizing.
    assert backslash["git"]["repo"] == "C:\\p028-src-v3\\case1\\repo"
    # None (class 2: source outside the repo) still passes through.
    receipt = build_receipt(**_receipt_kwargs(sources=[_source(
        git=_git(repo=None, tracked=False, head_commit=None),
        trust="GIT_UNTRACKED")]))
    assert receipt["sources"][0]["git"]["repo"] is None
