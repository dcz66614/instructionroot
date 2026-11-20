# P028 FIX-R2 — Runner-pack worker report (WIN-JUNCTION pack fixes + spec sync)

- Worker: Pack (WIN-JUNCTION runner pack + spec §13.1)
- Commit: `fc3fd62e7d9534124dadc384ab1b867d5d44ee8f`
  (on branch `fix-r2-pack`, merged into `fix-r2-merged` as the first FIX-R2 commit)
- Date: 2026-11-19 18:35 GMT
- Scope: 8 files, +46/−30 (see below)

## What changed

### Runner pack (`00_control/WIN_JUNCTION/`, 6 of the 8 files)

- `run_win_junction.py:119`: `os.stat` → `os.lstat` in the reparse-tag
  preflight. `os.stat` follows the junction, so the tag read `0x0`;
  `os.lstat` reads the link itself. (Root cause of the 2026-11-19
  Windows-run preflight misread; the run's RESULT=FAIL itself was the
  drive-letter bug, not this — see below.)
- `build_win_junction_fixtures.ps1`: now UTF-8 **with BOM**. As UTF-8
  no-BOM, PowerShell 5.1 threw a ParserError; pwsh 7 ran it. The BOM
  makes the stock PS 5.1 path work.
- `WIN_JUNCTION_TASK.md` / `WIN_JUNCTION_AGENT_PROMPT.md` /
  `CONSISTENCY_CHECK.md` / `EVIDENCE_INDEX.md`: stale claims replaced
  with 2026-11-19 measured facts from Sam's PC — `link.exe`/`cl.exe`
  ARE present (MSVC 14.44.35207; the "PC has no C++ components" claim
  was wrong, the real blocker was the missing Rust toolchain),
  rustup 1.100.0 installed with Sam's approval (`--no-modify-path`,
  tools in `C:\p028-tools\`), PATH python 3.11.15 vs native 3.14.4,
  `mklink /J` needs no elevation, git does not index junction targets,
  Python `os.path.islink(junction)` = False vs Rust `is_symlink()` =
  True (OQ-5 measured split).
- `WIN_JUNCTION_TASK.md` §0 freeze table deliberately UNTOUCHED (still
  FIX-R1 values `0110fa8` / source.zip `fdcd98af…`); new freeze values
  are filled in only in the dispatch copy at pack time (FIX-R1
  precedent — the frozen tree must not claim values that do not exist
  yet at freeze time).

### Spec sync (`00_contract/`)

- `PROJECT_BOOK.md` §13.1 (+9 lines) and `PROJECT_BOOK.docx` (58,385 →
  59,198 bytes): Windows drive-letter resolution + reparse-tag junction
  rule (`0xA0000003`/`0xA000000C`); Linux unchanged; UNC stays
  string-only. The docx was edited by run-level replacement, format
  preserved (verified `unzip -t` clean at the time by the worker).

## Background: what the 2026-11-19 Windows run showed (why FIX-R2 exists)

Windows run evidence arrived from Sam's PC ~18:24 GMT 2026-11-19:
RESULT=FAIL, 4/4 junction classes, parity 0/4. Root cause is NOT
junctions: both Production (`paths.py`) and Oracle (`paths.rs`)
rebuilt absolute paths as `"/" + "/".join(parts)`, so `C:\…` became
`/C:/…`, which does not exist on Windows. Verified in source
(`paths.py` docstring: real junction/drive-letter filesystem
resolution deliberately left empty for T011, never implemented).
Decisive control: class 3/4 cwds are plain dirs, same error.
Junctions themselves all passed (`mklink /J` no admin needed,
fsutil `0xa0000003`, git did not index linked dirs).

## Not done (carried)

- The lstat fix and the BOM'd `.ps1` have NOT been run on real Windows
  yet — V2 (this freeze's pack) is their first real-Windows run.
- P1-02 itself is still OPEN until the V2 run on Sam's PC passes.
