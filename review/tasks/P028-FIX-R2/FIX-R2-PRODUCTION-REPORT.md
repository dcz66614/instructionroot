# P028 FIX-R2 — Production worker report (Windows drive-letter resolution, Python side)

- Worker: Production (paths.py)
- Commit: `5d909df206a2f1ee1592867729cfec930436b429` (on branch `fix-r2-production`, merged into `fix-r2-merged` as the second FIX-R2 commit; parent `fc3fd62`, child `de60187`)
- Date: 2026-11-19 18:36 GMT
- Scope: `02_src/instructionroot/paths.py` (+323/−37), `05_tests/unit/test_paths.py` (+300)

## What changed

`paths.py` gains a Windows drive-letter branch in `canonicalize()`:

- New helpers: `_RealFS`, `_normalize_windows_readlink_target()`,
  `_split_windows_components()`, `_is_link()`, `_resolve_components()`,
  `_resolve_windows_drive()`; `canonicalize()` gains `fs=` / `os_name=`
  injection points so the Windows branch is unit-testable on Linux.
- Drive-absolute lexical paths (`C:/…` / `C:\…`) resolve against the drive
  root on a Windows host: `..` stops at the drive root, the resolved path
  is rebuilt as `C:/` + components (never `"/" + "/".join(parts)` — that
  was the 2026-11-19 Windows-run root cause: `"/C:/…"` does not exist on
  Windows, so all 4 junction classes failed at cwd validation with
  INPUT_ERROR, before any junction was even examined).
- Link test on the Windows branch is the unified reparse-tag rule:
  `os.path.islink()` returns False for NTFS junctions, so it must not be
  used here; reparse tags `0xA0000003` (junction) and `0xA000000C`
  (symlink) both count as links. Elsewhere the link test is unchanged.
- Readlink targets are normalised (backslash → `/`, `\\?\` prefix
  stripped, `\\?\UNC\…` → `//server/share/…`) before splitting.
- Linux behaviour unchanged: `/C:/…` stays an ordinary path under root.

## Tests

`05_tests/unit/test_paths.py` gains `FakeWindowsFS` and 9 new tests:
drive-root resolution, `..` stops at drive root, junction followed via
reparse tag, verbatim-prefix normalisation, absolute target switches
drive, symlink loop fail-closed, broken junction not fabricated,
non-link reparse tag not followed, Linux drive-letter resolution
unchanged. Full battery after merge: pytest 292 passed / 6 skipped
(was 283 in FIX-R1; +9 = these tests).

## Not done (carried)

- `ancestor_chain` in `profiles/_common.py` is NOT drive-aware (see
  TASK_RESULT.md §6): on Windows `os.path.normpath("C:/a/b")` yields
  backslashes, splitting on `/` gives the degenerate chain
  `["/", "/C:\\a\\b"]`. Only affects verdicts when an ancestor directory
  itself holds an instruction file; fixture environments are clean.
- No real-Windows run of this code in this round (V2 pack on Sam's PC).
