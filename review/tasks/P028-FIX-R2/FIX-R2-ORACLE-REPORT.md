# P028 FIX-R2 — Oracle worker report (Windows drive-letter branch, Rust side)

- Worker: Oracle (paths.rs)
- Commit: `de601873425b9036d48916f39c4143bd787d8cc7` (on branch `fix-r2-oracle`, merged tip of `fix-r2-merged`)
- Date: 2026-11-19 18:40 GMT
- Scope: `03_oracle/rust/src/paths.rs` (+789 lines, single file)

## What changed

- Drive-absolute lexical paths (`C:/…`) resolve against the real FS on a
  Windows host (`cfg!(windows)`): drive root is the root, `..` stops at
  the drive root, resolved path rebuilt as `C:/` + components,
  exists/is_file/is_dir from native FS calls. Linux behaviour
  byte-identical (`/C:/…` preserved; the existing
  `windows_drive_resolves_like_python` behaviour untouched).
- Unified link rule via `is_link_metadata()`: `file_type().is_symlink()`
  as the reparse-tag proxy on Windows (junction `0xA0000003` / symlink
  `0xA000000C`; std exposes no exact tag, no new deps); residual
  documented, fixture set verified to contain no other reparse type.
- Readlink targets normalised (backslash → `/`, `\\?\` prefix stripped,
  `\\?\UNC\…` → `//server/share/…`) before splitting; chain and
  symlink_target record the NORMALISED target, never the raw value.
  Absolute drive targets switch drive; UNC targets switch root to the
  share; root-relative targets reset to the same drive root.
- Drive-letter cwd/home are absolute only on a Windows host, so relative
  imports resolve against a drive base_dir and `~` against a drive home
  there; on Linux still rejected exactly as before.
- Windows branch unit-testable on Linux via the `WinFs` trait + fake FS:
  9 new tests (drive root, `..` stops at root, junction follow, target
  normalisation, drive switch, UNC switch, loop fail-closed, broken
  symlink, drive cwd/home host rule). Full battery after merge:
  cargo test 35 passed + 5 passed (was 26 + 5 in FIX-R1; +9 = these tests).

## Not done (carried)

- `ancestor_chain` in `profiles.rs` is NOT drive-aware (see TASK_RESULT.md
  §6): it splits on `/` and yields `["/", "/C:", "/C:/a", …]` for a
  drive cwd, while the Python side yields the degenerate
  `["/", "/C:\\a\\b"]`. The two sides probe different ancestor sets.
  Only affects verdicts when an ancestor directory itself holds an
  instruction file; fixture environments are clean.
- No real-Windows run of this code in this round (V2 pack on Sam's PC).
