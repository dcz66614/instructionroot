"""Deterministic receipt builder for P028 InstructionRoot Resolve (T005).

Two parts:

1. **A dedicated RFC 8785 JSON Canonicalization Scheme (JCS)
   canonicalizer** (:func:`canonical_json`), implemented from
   scratch in this module. It is deliberately *not* a reuse of
   :meth:`instructionroot.snapshot.FilesystemSnapshot.to_canonical_json`
   (coordinator ruling Q2: that helper is internal to the snapshot;
   the receipt needs its own JCS implementation, and the Rust
   Oracle will implement JCS independently — parity is the point).
   It is also *not* ``json.dumps(sort_keys=True)``: JCS differs
   from that in two places that matter for parity — object keys
   sort by **UTF-16 code unit** order (not Python's code-point
   order, so a non-BMP key sorts *before* ``\\uffff``), and
   numbers serialize by **ECMAScript Number::toString** semantics
   (``1e30`` not ``1e+30`` as a float literal, ``100.0`` as
   ``100``, ``-0.0`` as ``0``).

   JCS rules implemented here (RFC 8785 §3.2):

   * objects: keys sorted by UTF-16 code-unit order, no whitespace,
     ``":"`` and ``","`` separators only;
   * strings: only ``"``, ``\\`` and U+0000–U+001F are escaped
     (``\\b \\t \\n \\f \\r`` short forms, other controls as
     ``\\u00xx`` lowercase hex); all other characters — including
     non-ASCII — are emitted as-is (UTF-8 on encoding). A lone
     surrogate is emitted as ``\\udXXX``; a valid surrogate pair
     is emitted as the single astral character, matching
     ECMAScript string semantics;
   * numbers: integers in the safe range serialize as decimal
     digits; anything else goes through the ECMAScript
     ``Number::toString`` algorithm over the *shortest round-trip*
     decimal digits (``repr`` in CPython gives those digits);
     ``-0`` serializes as ``0``; ``NaN`` / infinities are rejected
     (not valid JSON — fail-closed, never emitted as ``null``);
   * arrays keep order; ``true`` / ``false`` / ``null`` as usual;
   * only ``str`` keys are accepted; ``set`` and other types are
     rejected (a set has no order — canonicalizing one would be a
     lie). Tuples are accepted as arrays (callers' convenience).

2. **The receipt builder** (:func:`build_receipt`): assembles the
   frozen receipt (``00_contract/receipt_schema.json`` v1) from
   discovery sources + import edges, derives the verdict from the
   policy (``00_contract/policy_schema.json``), and sets
   ``receipt_hash = SHA-256(canonical_json(receipt))`` with the
   ``receipt_hash`` field itself excluded. No wall-clock timestamp,
   duration, username or file contents ever enter a receipt — the
   builder takes no such input, so a receipt cannot leak them.
   Canonical paths are stored **unredacted** (the schema's
   ``<HOME>`` redaction is a display transform; the hash always
   uses the unredacted path).

Verdict derivation (:func:`derive_verdict`, policy_schema.json
``verdict_derivation`` — PASS / WARN / BLOCK only; the error
verdicts are caller-signalled, not derived):

* BLOCK — a source whose trust is OUTSIDE_REPO / SYMLINK_ESCAPE /
  IMPORT_ESCAPE / MISSING while the corresponding ``block_*``
  field is true; any edge with ``allowed=false`` while
  ``block_import_escape`` or ``block_missing_reference`` is true;
  a user / managed / tracked source while its ``allow_*`` field
  is false; or ``treat_warn_as_block=true`` with a WARN condition
  present.
* WARN — a GIT_UNTRACKED in-repo source while
  ``block_repo_untracked`` is false; a GIT_MODIFIED source while
  ``block_repo_modified`` is false; a source with precedence kind
  UNSPECIFIED while ``warn_on_unspecified_precedence`` is true.
* PASS — no BLOCK and no WARN condition applies.
* Trust NOT_OBSERVED is fail-closed → BLOCK (T004: "downstream
  verdict code must treat NOT_OBSERVED as fail-closed (never a
  silent PASS)"; no policy field governs it, so it blocks
  unconditionally — recorded in TASK_RESULT.md for the
  coordinator / T008 to confirm).

Policy never changes which files were discovered; it only changes
the verdict. Unknown policy fields and non-bool values raise
``ValueError`` (the caller's INPUT_ERROR), never a silent PASS.
"""

from __future__ import annotations

import hashlib
import math
import re
from decimal import Decimal

from instructionroot.paths import is_windows_style_path, normalize_windows_path
from instructionroot.resolver import DEFAULT_POLICY, UnsupportedProfileError

__all__ = [
    "DEFAULT_POLICY",
    "EXIT_CODES",
    "PROFILE_VERSIONS",
    "RECEIPT_VERSION",
    "TRUST_ENUM",
    "VERDICT_ENUM",
    "build_receipt",
    "build_source_record",
    "canonical_json",
    "canonical_json_bytes",
    "derive_verdict",
    "exit_code_for_verdict",
    "receipt_hash_for",
    "validate_policy",
    "verify_receipt",
]

#: Receipt schema version (frozen, receipt_schema.json).
RECEIPT_VERSION = 1

#: Policy schema version (frozen, policy_schema.json).
POLICY_SCHEMA_VERSION = 1

#: Frozen profile id -> version (profile_contract.json).
PROFILE_VERSIONS: dict[str, str] = {
    "codex": "codex-2026-11",
    "claude-code": "claude-code-2026-11",
    "copilot-cli": "copilot-cli-2026-11",
}

#: Frozen profile id -> rules_hash (profile_contract.json).
PROFILE_RULES_HASHES: dict[str, str] = {
    "codex": (
        "sha256:a0a03c1cdd77f8d9110ccbc77dae937e30e288a2609e6b04b60d26d15af5dc23"
    ),
    "claude-code": (
        "sha256:7f1d074dc0bb8dde1eace4c01498f8899b8ef58aa47f71c32c649768104f6058"
    ),
    "copilot-cli": (
        "sha256:76a5f6c8fbd7fc4ff910bf5f471ecb9291ab2a575d871f93338fb1b298c73d0e"
    ),
}

#: Frozen verdict enum (receipt_schema.json).
VERDICT_ENUM: tuple[str, ...] = (
    "PASS",
    "WARN",
    "BLOCK",
    "INPUT_ERROR",
    "UNSUPPORTED_PROFILE",
    "INTERNAL_ERROR",
)

#: Frozen trust enum (receipt_schema.json).
TRUST_ENUM: tuple[str, ...] = (
    "GIT_TRACKED",
    "GIT_MODIFIED",
    "GIT_UNTRACKED",
    "USER_SCOPE",
    "OUTSIDE_REPO",
    "SYMLINK_ESCAPE",
    "IMPORT_ESCAPE",
    "MISSING",
    "NOT_OBSERVED",
)

#: Exit codes (PROJECT_BOOK.md §8.8 / receipt_schema.json).
EXIT_CODES: dict[str, int] = {
    "PASS": 0,
    "WARN": 10,
    "BLOCK": 20,
    "INPUT_ERROR": 30,
    "UNSUPPORTED_PROFILE": 40,
    "INTERNAL_ERROR": 50,
}

#: Receipt source required fields (receipt_schema.json ``source``).
_SOURCE_REQUIRED: frozenset[str] = frozenset({
    "source_id",
    "raw_path",
    "canonical_path",
    "resolved_path",
    "scope",
    "phase",
    "discovery_rule",
    "precedence",
    "sha256",
    "git",
    "trust",
})

#: Receipt source allowed fields (required + optional).
_SOURCE_ALLOWED: frozenset[str] = _SOURCE_REQUIRED | frozenset({
    "symlink_target",
    "is_symlink",
})

#: Receipt edge required fields (receipt_schema.json ``edge``).
_EDGE_REQUIRED: frozenset[str] = frozenset({
    "edge_id",
    "from",
    "syntax",
    "to",
    "allowed",
    "reason",
})

#: Receipt edge allowed fields (required + optional).
_EDGE_ALLOWED: frozenset[str] = _EDGE_REQUIRED | frozenset({"resolved_target"})

#: Receipt git object required fields.
_GIT_REQUIRED: frozenset[str] = frozenset({
    "repo",
    "tracked",
    "modified",
    "head_commit",
})

_SOURCE_ID_RE = re.compile(r"^src-[0-9]{4}$")
_EDGE_ID_RE = re.compile(r"^edge-[0-9]{4}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRECEDENCE_KINDS: frozenset[str] = frozenset({
    "ORDERED",
    "BEFORE",
    "AFTER",
    "COMBINE_UNORDERED",
    "UNSPECIFIED",
})


# ---------------------------------------------------------------------------
# RFC 8785 JCS canonicalization
# ---------------------------------------------------------------------------

def _utf16_key(key: str) -> bytes:
    """Sort key for an object key: its UTF-16 code units (big-endian).

    Python's default ``str`` order is by code *point*; JCS sorts by
    UTF-16 code *unit*, so e.g. U+10000 (``\\ud800\\udc00``) sorts
    before U+FFFF (``\\uffff``). ``surrogatepass`` keeps lone
    surrogates encodable so they sort deterministically too.
    """
    return key.encode("utf-16-be", "surrogatepass")


def _escape_string(value: str) -> str:
    """Escape one string per RFC 8785 §3.2.2.3 (no surrounding quotes)."""
    out: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
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
        elif 0xD800 <= code <= 0xDBFF:
            # High surrogate: pair with a following low surrogate
            # (one astral character, emitted as-is) or escape lone.
            if i + 1 < n and 0xDC00 <= ord(value[i + 1]) <= 0xDFFF:
                out.append(ch)
                out.append(value[i + 1])
                i += 1
            else:
                out.append("\\u%04x" % code)
        elif 0xDC00 <= code <= 0xDFFF:
            # Lone low surrogate (a preceding high one was already
            # consumed above as a pair).
            out.append("\\u%04x" % code)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _format_float(value: float) -> str:
    """Serialize a float per ECMAScript Number::toString (RFC 8785 §3.2.2.4).

    Uses the shortest round-trip decimal digits (``repr``) and then
    applies the ECMAScript placement rules over ``(digits, n)``
    where value = 0.digits × 10**n.
    """
    if value == 0.0:
        return "0"  # -0 serializes as 0 (RFC 8785)
    if math.isnan(value) or math.isinf(value):
        raise ValueError("non-finite number cannot be canonicalized: %r" % value)
    sign = "-" if value < 0 else ""
    dec = Decimal(repr(abs(value)))
    digits_tuple, exponent = dec.as_tuple().digits, dec.as_tuple().exponent
    digits = "".join(str(d) for d in digits_tuple)
    # Strip trailing zeros (repr's shortest form never needs them,
    # but Decimal('100.0') carries them): each stripped zero raises
    # the exponent by one, keeping value = int(digits) × 10**exponent.
    stripped = digits.rstrip("0")
    if stripped:
        exponent += len(digits) - len(stripped)
        digits = stripped
    else:  # value was 0 — handled above; unreachable, kept for safety
        return "0"
    k = len(digits)
    n = exponent + k  # decimal-point position: value = 0.digits × 10**n
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    # Scientific notation: exponent is n-1, always signed, no padding.
    exp = n - 1
    if k == 1:
        mantissa = digits
    else:
        mantissa = digits[0] + "." + digits[1:]
    return sign + mantissa + "e%+d" % exp


def _format_number(value) -> str:
    """Serialize an int/float per RFC 8785 §3.2.2.4."""
    if isinstance(value, bool):
        raise TypeError("bool is not a number for canonicalization")
    if isinstance(value, int):
        # Safe integers serialize as plain decimal digits. Outside
        # the safe range the JCS input is a double (JSON numbers
        # parse as IEEE-754 doubles), so convert first — this is
        # the JCS-faithful rounding, not exact bignum output.
        if -(2 ** 53) < value < 2 ** 53:
            return str(value)
        return _format_float(float(value))
    if isinstance(value, float):
        return _format_float(value)
    raise TypeError(
        "number must be int or float, not %s" % type(value).__name__
    )


def _canonicalize(value) -> str:
    """Recursive JCS serialization of one JSON value."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return '"' + _escape_string(value) + '"'
    if isinstance(value, (int, float)):
        return _format_number(value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in value:
            if not isinstance(key, str):
                raise TypeError(
                    "object keys must be str, not %s" % type(key).__name__
                )
        for key in sorted(value.keys(), key=_utf16_key):
            parts.append(
                '"' + _escape_string(key) + '":' + _canonicalize(value[key])
            )
        return "{" + ",".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonicalize(item) for item in value) + "]"
    raise TypeError(
        "value of type %s cannot be canonicalized as JSON"
        % type(value).__name__
    )


def canonical_json(value) -> str:
    """Return the RFC 8785 canonical JSON string for *value*.

    Deterministic: same value → same string, regardless of dict
    insertion order. Raises ``TypeError`` / ``ValueError`` for
    non-JSON values (non-str keys, sets, NaN/inf) — fail-closed.
    """
    return _canonicalize(value)


def canonical_json_bytes(value) -> bytes:
    """Return :func:`canonical_json` encoded as UTF-8 bytes."""
    return canonical_json(value).encode("utf-8")


def receipt_hash_for(receipt: dict) -> str:
    """SHA-256 (lowercase hex) of the canonical receipt JSON.

    The ``receipt_hash`` field itself is excluded from the hash
    (receipt_schema.json ``receipt_hash_definition``); every other
    field is covered. A stored ``receipt_hash`` value is ignored,
    never trusted.
    """
    if not isinstance(receipt, dict):
        raise TypeError("receipt must be a dict")
    without_hash = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    return hashlib.sha256(canonical_json_bytes(without_hash)).hexdigest()


def verify_receipt(receipt: dict) -> bool:
    """Return True when *receipt*'s stored hash matches its content."""
    if not isinstance(receipt, dict):
        return False
    stored = receipt.get("receipt_hash")
    if not isinstance(stored, str) or not _SHA256_RE.match(stored):
        return False
    try:
        return receipt_hash_for(receipt) == stored
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def validate_policy(policy) -> dict:
    """Merge a caller policy over the frozen defaults, rejecting bad input.

    ``None`` → defaults. Unknown fields or non-bool values raise
    ``ValueError`` (the caller's INPUT_ERROR).
    """
    if policy is None:
        return dict(DEFAULT_POLICY)
    if not isinstance(policy, dict):
        raise ValueError("policy must be a dict or None")
    unknown = sorted(set(policy) - set(DEFAULT_POLICY))
    if unknown:
        raise ValueError("unknown policy field(s): %s" % ", ".join(unknown))
    merged = dict(DEFAULT_POLICY)
    for key, value in policy.items():
        if not isinstance(value, bool):
            raise ValueError("policy field %r must be a bool" % key)
        merged[key] = value
    return merged


def derive_verdict(sources, edges, policy=None) -> str:
    """Derive PASS / WARN / BLOCK from receipt sources + edges + policy.

    *sources* are receipt-shaped source dicts (``trust`` and
    ``precedence.kind`` / ``scope`` are read); *edges* are
    receipt-shaped edge dicts (``allowed`` is read). See the module
    docstring for the rule table. The error verdicts are never
    derived here — a caller that hit an input / profile / internal
    error passes its verdict explicitly to :func:`build_receipt`.
    """
    merged = validate_policy(policy)
    block = False
    warn = False

    for src in sources:
        trust = src.get("trust")
        scope = src.get("scope")
        precedence = src.get("precedence") or {}
        kind = precedence.get("kind") if isinstance(precedence, dict) else None
        if trust == "NOT_OBSERVED":
            block = True  # fail-closed: unobserved state never passes
        elif trust == "MISSING":
            if merged["block_missing_reference"]:
                block = True
        elif trust == "OUTSIDE_REPO":
            if merged["block_outside_repo"]:
                block = True
        elif trust == "SYMLINK_ESCAPE":
            if merged["block_symlink_escape"]:
                block = True
        elif trust == "IMPORT_ESCAPE":
            if merged["block_import_escape"]:
                block = True
        elif trust == "GIT_UNTRACKED":
            if merged["block_repo_untracked"]:
                block = True
            else:
                warn = True
        elif trust == "GIT_MODIFIED":
            if merged["block_repo_modified"]:
                block = True
            else:
                warn = True
        if scope == "user" and not merged["allow_user_scope"]:
            block = True
        if scope == "managed" and not merged["allow_managed_scope"]:
            block = True
        if trust == "GIT_TRACKED" and not merged["allow_repo_tracked"]:
            block = True
        if kind == "UNSPECIFIED" and merged["warn_on_unspecified_precedence"]:
            warn = True

    for edge in edges:
        if edge.get("allowed") is False:
            if merged["block_import_escape"] or merged["block_missing_reference"]:
                block = True

    if block:
        return "BLOCK"
    if warn:
        return "BLOCK" if merged["treat_warn_as_block"] else "WARN"
    return "PASS"


def exit_code_for_verdict(verdict: str) -> int:
    """Return the frozen exit code for *verdict* (receipt_schema.json)."""
    try:
        return EXIT_CODES[verdict]
    except KeyError:
        raise ValueError("unknown verdict: %r" % verdict) from None


# ---------------------------------------------------------------------------
# Receipt assembly
# ---------------------------------------------------------------------------

def _normalize_receipt_path(value: str | None) -> str | None:
    """Unify a receipt path's spelling to ``C:/`` form (FIX-R3 D).

    Windows-style spellings (drive letter / UNC) are normalised
    with :func:`instructionroot.paths.normalize_windows_path`; any
    other spelling — POSIX paths, relative paths, ``~`` paths — is
    returned unchanged, so ``raw_path`` keeps its contract meaning
    ("path as discovered", which may be relative or contain ``~``)
    and only the separator spelling is unified. This is what makes
    production receipts hash-equal to the Oracle's: the Oracle
    builds its discovery strings with ``/`` joins while production
    discovery strings come from native ``os.path.join`` (``\\`` on
    Windows). ``None`` passes through (``repo_root`` / ``home``).
    A non-string value is returned unchanged so the caller's
    validation still reports it (never silently dropped here).
    """
    if value is None or not isinstance(value, str):
        return value
    if not is_windows_style_path(value):
        return value
    return normalize_windows_path(value)


def build_source_record(candidate, *, git, trust: str, source_id: str | None = None) -> dict:
    """Build a receipt-shaped source dict from a T003 candidate.

    *candidate* is a :class:`SourceCandidate`; *git* is a dict (or
    ``GitState``) with ``repo`` / ``tracked`` / ``modified`` /
    ``head_commit``; *trust* is a frozen trust-enum value (T004).
    ``source_id`` defaults to ``None`` — pass the discovery-order
    id (``src-NNNN``) from the caller, or let :func:`build_receipt`
    assign ids in list order by leaving it unset here and in the
    record (see :func:`build_receipt`'s id assignment).

    Canonical paths are stored unredacted (the hash always uses
    the unredacted path; ``<HOME>`` redaction is display-only).
    ``raw_path`` keeps the discovered path but with its spelling
    unified to ``C:/`` form (FIX-R3 D, see
    :func:`_normalize_receipt_path`). ``git.repo`` is unified the
    same way (FIX-R4): on Windows production discovery yields a
    backslash repo while the Oracle yields ``C:/`` spelling, and
    the spelling difference alone broke receipt-hash parity.
    """
    if trust not in TRUST_ENUM:
        raise ValueError("unknown trust value: %r" % trust)
    if hasattr(git, "repo"):  # GitState
        git_dict = {
            "repo": _normalize_receipt_path(git.repo),
            "tracked": bool(git.tracked),
            "modified": bool(git.modified),
            "head_commit": git.head_commit,
        }
    else:
        git_dict = dict(git)
        # Same field, same fix as the GitState branch above (FIX-R4):
        # a dict caller can pass an un-normalised backslash repo.
        # Guarded by "repo" in git_dict so a missing field is still
        # reported by the check below instead of silently added.
        if "repo" in git_dict:
            git_dict["repo"] = _normalize_receipt_path(git_dict["repo"])
    missing_git = _GIT_REQUIRED - set(git_dict)
    if missing_git:
        raise ValueError("git record missing field(s): %s" % ", ".join(sorted(missing_git)))
    if candidate.resolved_path is None:
        raise ValueError(
            "source %s has no resolved path (symlink loop / unresolvable); "
            "it cannot be a receipt source" % candidate.canonical_path
        )
    record: dict = {
        "raw_path": _normalize_receipt_path(candidate.raw_path),
        "canonical_path": candidate.canonical_path,
        "resolved_path": candidate.resolved_path,
        "scope": candidate.scope,
        "phase": candidate.phase,
        "discovery_rule": candidate.discovery_rule,
        "precedence": candidate.precedence.to_dict(),
        "sha256": candidate.sha256,
        "git": git_dict,
        "trust": trust,
        "symlink_target": candidate.symlink_target,
        "is_symlink": bool(candidate.is_symlink),
    }
    if source_id is not None:
        record["source_id"] = source_id
    return record


def _normalize_sources(sources) -> list[dict]:
    """Validate receipt source dicts; assign ids in order when absent."""
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    for index, src in enumerate(sources):
        if not isinstance(src, dict):
            raise ValueError("source %d must be a dict" % index)
        unknown = sorted(set(src) - _SOURCE_ALLOWED)
        if unknown:
            raise ValueError(
                "source %d has unknown field(s): %s" % (index, ", ".join(unknown))
            )
        missing = sorted(_SOURCE_REQUIRED - set(src) - {"source_id"})
        if missing:
            raise ValueError(
                "source %d missing required field(s): %s" % (index, ", ".join(missing))
            )
        record = dict(src)
        # FIX-R3 D: unify the source's raw-path spelling at receipt
        # assembly (idempotent with build_source_record above, so
        # dict-passed sources get the same treatment).
        record["raw_path"] = _normalize_receipt_path(record.get("raw_path"))
        source_id = record.get("source_id")
        if source_id is None:
            source_id = "src-%04d" % (index + 1)
            record["source_id"] = source_id
        if not isinstance(source_id, str) or not _SOURCE_ID_RE.match(source_id):
            raise ValueError("source %d has invalid source_id: %r" % (index, source_id))
        if source_id in seen_ids:
            raise ValueError("duplicate source_id: %s" % source_id)
        seen_ids.add(source_id)
        if record.get("scope") not in ("managed", "user", "project", "nested"):
            raise ValueError("source %s has invalid scope: %r" % (source_id, record.get("scope")))
        if record.get("phase") not in ("startup", "on_demand"):
            raise ValueError("source %s has invalid phase: %r" % (source_id, record.get("phase")))
        if record.get("trust") not in TRUST_ENUM:
            raise ValueError("source %s has invalid trust: %r" % (source_id, record.get("trust")))
        precedence = record.get("precedence")
        if not isinstance(precedence, dict) or precedence.get("kind") not in _PRECEDENCE_KINDS:
            raise ValueError("source %s has invalid precedence: %r" % (source_id, precedence))
        sha = record.get("sha256")
        if sha is not None and (not isinstance(sha, str) or not _SHA256_RE.match(sha)):
            raise ValueError("source %s has invalid sha256: %r" % (source_id, sha))
        git = record.get("git")
        if not isinstance(git, dict) or _GIT_REQUIRED - set(git):
            raise ValueError("source %s has invalid git record" % source_id)
        if not isinstance(git.get("tracked"), bool) or not isinstance(git.get("modified"), bool):
            raise ValueError("source %s git tracked/modified must be bool" % source_id)
        # FIX-R4 (dict passthrough): the same git.repo spelling
        # unification as build_source_record, for dict sources handed
        # straight to build_receipt. Copy first: record is a shallow
        # copy of the caller's dict, so mutating record["git"] in
        # place would mutate the caller's git dict. Placed after the
        # git validation above, so a missing "repo" still errors
        # there (never silently added) and None (class 2) passes
        # through via _normalize_receipt_path.
        git = dict(record["git"])
        git["repo"] = _normalize_receipt_path(git.get("repo"))
        record["git"] = git
        normalized.append(record)
    return normalized


def _normalize_edges(edges, *, known_source_ids: set[str]) -> list[dict]:
    """Validate receipt edge dicts (or ImportEdge objects); assign ids when absent."""
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    for index, edge in enumerate(edges):
        if hasattr(edge, "to_dict") and not isinstance(edge, dict):
            edge = edge.to_dict()
        if not isinstance(edge, dict):
            raise ValueError("edge %d must be a dict or ImportEdge" % index)
        unknown = sorted(set(edge) - _EDGE_ALLOWED)
        if unknown:
            raise ValueError(
                "edge %d has unknown field(s): %s" % (index, ", ".join(unknown))
            )
        missing = sorted(_EDGE_REQUIRED - set(edge) - {"edge_id"})
        if missing:
            raise ValueError(
                "edge %d missing required field(s): %s" % (index, ", ".join(missing))
            )
        record = dict(edge)
        edge_id = record.get("edge_id")
        if edge_id is None:
            edge_id = "edge-%04d" % (index + 1)
            record["edge_id"] = edge_id
        if not isinstance(edge_id, str) or not _EDGE_ID_RE.match(edge_id):
            raise ValueError("edge %d has invalid edge_id: %r" % (index, edge_id))
        if edge_id in seen_ids:
            raise ValueError("duplicate edge_id: %s" % edge_id)
        seen_ids.add(edge_id)
        # ``from`` is the importer's source_id when it is a
        # discovered source, else its canonical path (contract gap
        # — see imports.py): either way it must be a non-empty str.
        if not isinstance(record.get("from"), str) or record.get("from") == "":
            raise ValueError("edge %s has empty from" % edge_id)
        to = record.get("to")
        if to is not None and to not in known_source_ids:
            raise ValueError("edge %s references unknown target source: %r" % (edge_id, to))
        if not isinstance(record.get("allowed"), bool):
            raise ValueError("edge %s allowed must be bool" % edge_id)
        if not isinstance(record.get("syntax"), str) or record.get("syntax") == "":
            raise ValueError("edge %s has invalid syntax" % edge_id)
        if not isinstance(record.get("reason"), str) or record.get("reason") == "":
            raise ValueError("edge %s has invalid reason" % edge_id)
        if "resolved_target" not in record:
            record["resolved_target"] = None
        normalized.append(record)
    return normalized


def build_receipt(
    *,
    profile: str,
    profile_version: str | None = None,
    rules_hash: str | None = None,
    cwd: str,
    repo_root: str | None,
    home: str | None = None,
    sources=(),
    edges=(),
    policy=None,
    verdict: str | None = None,
    include_policy: bool = True,
) -> dict:
    """Build a frozen receipt dict (v1) with its ``receipt_hash``.

    * ``profile`` — one of ``codex`` / ``claude-code`` /
      ``copilot-cli``; ``profile_version`` must be the frozen
      version for that id (mismatch raises
      :class:`UnsupportedProfileError` — the receipt verdict
      ``UNSUPPORTED_PROFILE``). ``rules_hash`` defaults to the
      frozen profile rules hash.
    * ``cwd`` / ``repo_root`` / ``home`` — canonical absolute
      workspace paths (``repo_root`` None for a non-git workspace).
    * ``sources`` — receipt-shaped source dicts (see
      :func:`build_source_record`); ids are assigned in list order
      when absent. ``edges`` — receipt-shaped edge dicts or
      :class:`ImportEdge` objects; ids likewise.
    * ``policy`` — a policy dict (defaults applied) or None;
      included in the receipt as ``policy`` when
      ``include_policy`` is true.
    * ``verdict`` — when None, derived by :func:`derive_verdict`;
      otherwise the caller's explicit verdict (used for the error
      verdicts, which are never derived from sources).

    Raises ``ValueError`` for malformed sources/edges/policy and
    ``UnsupportedProfileError`` for an unknown id/version. Never
    returns a receipt with a PASS verdict on invalid input.
    """
    if profile not in PROFILE_VERSIONS:
        raise UnsupportedProfileError("unknown harness: %r" % profile)
    frozen_version = PROFILE_VERSIONS[profile]
    if profile_version is not None and profile_version != frozen_version:
        raise UnsupportedProfileError(
            "profile version %r does not match frozen %r for harness %r"
            % (profile_version, frozen_version, profile)
        )
    if not isinstance(cwd, str) or cwd == "" or "\x00" in cwd:
        raise ValueError("cwd must be a non-empty path string")
    if repo_root is not None and (not isinstance(repo_root, str) or repo_root == ""):
        raise ValueError("repo_root must be a string or None")
    if home is not None and (not isinstance(home, str) or home == ""):
        raise ValueError("home must be a string or None")
    if verdict is not None and verdict not in VERDICT_ENUM:
        raise ValueError("unknown verdict: %r" % verdict)

    merged_policy = validate_policy(policy)
    norm_sources = _normalize_sources(sources)
    known_ids = {s["source_id"] for s in norm_sources}
    norm_edges = _normalize_edges(edges, known_source_ids=known_ids)
    final_verdict = verdict if verdict is not None else derive_verdict(
        norm_sources, norm_edges, merged_policy
    )

    profile_obj: dict = {"id": profile, "version": frozen_version}
    profile_obj["rules_hash"] = (
        rules_hash if rules_hash is not None else PROFILE_RULES_HASHES[profile]
    )
    # FIX-R3 D: workspace paths are "canonical absolute paths" per
    # the frozen schema, so a Windows spelling arriving here (the
    # compare_oracle runner passes raw ``str(case_dir / ...)``
    # strings) is unified to ``C:/`` form at assembly; POSIX
    # spellings pass through unchanged.
    workspace: dict = {
        "cwd": _normalize_receipt_path(cwd),
        "repo_root": _normalize_receipt_path(repo_root),
    }
    if home is not None:
        workspace["home"] = _normalize_receipt_path(home)

    receipt: dict = {
        "receipt_version": RECEIPT_VERSION,
        "profile": profile_obj,
        "workspace": workspace,
        "sources": norm_sources,
        "edges": norm_edges,
        "verdict": final_verdict,
    }
    if include_policy:
        receipt["policy"] = {
            "policy_schema_version": POLICY_SCHEMA_VERSION,
            "values": merged_policy,
        }
    receipt["receipt_hash"] = receipt_hash_for(receipt)
    return receipt
