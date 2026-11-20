"""Unit tests for P028 T011 — Windows corpus (fixtures/windows/).

Covers the pure-string Windows spellings in the T011 probe set
(``win-probes``) against the frozen contract, plus the structural
integrity of the Windows expected index (``fixtures/windows/expected/
INDEX.json``) and its fixture manifest. The receipt cases themselves
are checked end-to-end (production + Oracle) by
``scripts/run_windows_corpus.py``, not here.

Honesty rule (same as T002's S12 precedent): real junction /
drive-letter / UNC resolution and real case-insensitive filesystem
matching cannot be verified on this Linux host. Those behaviours are
explicitly ``skip`` (NOT_RUN) here and in the corpus runner; only
pure-string normalisation is asserted. Nothing about Windows is
faked as passing.
"""

import json
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_src"))

from instructionroot.paths import (  # noqa: E402
    canonicalize,
    is_windows_style_path,
    normalize_windows_path,
)

WINDOWS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "windows"


# ---------------------------------------------------------------------------
# Pure-string probes (hand-derived from the contract; mirrors win-probes)
# ---------------------------------------------------------------------------

def test_win_probe_lowercase_drive_letter_preserved():
    # Drive letters are NOT folded: 'c:' stays 'c:' (finding F5).
    assert normalize_windows_path("c:\\repo\\AGENTS.md") == "c:/repo/AGENTS.md"


def test_win_probe_drive_root():
    assert normalize_windows_path("C:\\") == "C:/"


def test_win_probe_unc_dotdot_never_above_share():
    assert normalize_windows_path(
        "\\\\server\\share\\repo\\..\\AGENTS.md") == "//server/share/AGENTS.md"


def test_win_probe_bare_unc_root():
    assert normalize_windows_path("\\\\server\\share") == "//server/share"


def test_win_probe_unicode_drive_path():
    assert normalize_windows_path(
        "C:\\Ünïcode\\日本語\\AGENTS.md") == "C:/Ünïcode/日本語/AGENTS.md"


def test_win_probe_mixed_separators():
    assert normalize_windows_path(
        "D:/mixed\\separators/AGENTS.md") == "D:/mixed/separators/AGENTS.md"


def test_win_probe_dot_component():
    assert normalize_windows_path(
        "C:\\repo\\.\\AGENTS.md") == "C:/repo/AGENTS.md"


def test_win_probe_dotdot_never_above_drive_root():
    assert normalize_windows_path(
        "C:\\repo\\..\\..\\outside\\AGENTS.md") == "C:/outside/AGENTS.md"


def test_win_probe_trailing_separator_removed():
    assert normalize_windows_path("C:\\repo\\services\\") == "C:/repo/services"


def test_win_probe_drive_relative_rejected_by_normalize():
    # normalize_windows_path itself rejects drive-relative spellings.
    with pytest.raises(ValueError, match="drive-relative"):
        normalize_windows_path("C:foo\\bar")


def test_win_probe_drive_relative_not_detected_as_windows_style():
    # ... but canonicalize never reaches that rejection: the detector
    # requires a separator after the colon, so 'C:foo\\bar' is joined
    # onto cwd as a relative path (finding F4, cf.
    # win-drive-relative-import). The backslash is a filename
    # character on Linux.
    assert not is_windows_style_path("C:foo\\bar")
    got = canonicalize("C:foo\\bar", cwd="/tmp/win-probe", home="/tmp/win-probe")
    assert got.canonical_path == "/tmp/win-probe/C:foo\\bar"
    assert got.resolved_path == "/tmp/win-probe/C:foo\\bar"
    assert got.exists is False


@pytest.mark.skip(reason="NOT_RUN on Linux: real junction resolution needs "
                         "a Windows runner (T011 records it, never fakes it)")
def test_win_real_junction_resolution():
    raise AssertionError("unreachable")


@pytest.mark.skip(reason="NOT_RUN on Linux: real drive-letter resolution "
                         "needs a Windows filesystem (T011 records it, "
                         "never fakes it)")
def test_win_real_drive_letter_resolution():
    raise AssertionError("unreachable")


@pytest.mark.skip(reason="NOT_RUN on Linux: real case-insensitive "
                         "filesystem matching needs a Windows filesystem "
                         "(T011 records it, never fakes it)")
def test_win_real_case_insensitive_matching():
    raise AssertionError("unreachable")


@pytest.mark.skip(reason="NOT_RUN on Linux: real UNC share access needs a "
                         "Windows network share (T011 records it, never "
                         "fakes it)")
def test_win_real_unc_share_access():
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Index / manifest integrity (no generated repo/ trees needed)
# ---------------------------------------------------------------------------

def _load_index() -> dict:
    return json.loads((WINDOWS_DIR / "expected" / "INDEX.json").read_text())


def test_win_index_has_15_receipt_cases_and_10_probes():
    index = _load_index()
    receipt = [c for c in index["cases"] if c["kind"] == "receipt"]
    probes = [c for c in index["cases"] if c["kind"] == "fs"]
    assert len(receipt) == 15
    assert len(probes) == 1
    assert len(probes[0]["expected_probes"]) == 10


def test_win_index_receipt_cases_have_case_json_and_expected_fields():
    index = _load_index()
    for case in index["cases"]:
        if case["kind"] != "receipt":
            continue
        case_dir = WINDOWS_DIR / case["case_id"]
        assert (case_dir / "case.json").exists(), case["case_id"]
        assert case["expected_verdict"] in ("PASS", "WARN", "BLOCK")
        assert case["expected_sources"], case["case_id"]
        assert case["expected_source_count"] == len(case["expected_sources"])
        assert "reasoning" in case and case["reasoning"], case["case_id"]
        assert "windows" in case and "NOT_RUN" in case["windows"], case["case_id"]
        for src in case["expected_sources"]:
            assert src["trust"] not in ("NOT_OBSERVED",), case["case_id"]


def test_win_index_known_gaps_are_bounded():
    # A known parity gap must name its finding and the exact diff set;
    # anything else is a free-form excuse and is rejected here.
    index = _load_index()
    gaps = [c for c in index["cases"] if "known_parity_gap" in c]
    assert {c["case_id"] for c in gaps} == {
        "win-junction-inside", "win-junction-escape"}
    for case in gaps:
        gap = case["known_parity_gap"]
        assert gap["id"] == "F6"
        assert set(gap["only_diffs"]) == {"$.workspace.cwd", "$.receipt_hash"}


def test_win_manifest_lists_the_receipt_cases():
    manifest = json.loads((WINDOWS_DIR / "manifest.json").read_text())
    assert manifest["synthetic"] is True
    index = _load_index()
    receipt_ids = sorted(
        c["case_id"] for c in index["cases"] if c["kind"] == "receipt")
    assert [c["case_id"] for c in manifest["cases"]] == receipt_ids


def test_win_probe_expectations_match_normalize():
    # Every non-{corpus} probe canonical form is reproduced by the
    # pure-string normaliser (the {corpus} probe is covered by
    # test_win_probe_drive_relative_not_detected_as_windows_style).
    index = _load_index()
    probes = [c for c in index["cases"] if c["kind"] == "fs"][0]
    for probe in probes["expected_probes"]:
        if "{corpus}" in probe["canonical"]:
            continue
        assert normalize_windows_path(probe["raw"]) == probe["canonical"], probe["raw"]
