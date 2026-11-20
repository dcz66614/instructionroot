# P028-FIX-R2 — Fix the Windows drive-letter root cause (P1-02) + runner-pack defects — TASK_RESULT

- TASK_ID: P028-FIX-R2
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-19
- Baseline: HEAD `de60187` on branch `fix-r2-merged` (merge chain:
  `6b0979d` FIX-R1 §0 update → `fc3fd62` pack → `5d909df` Production →
  `de60187` Oracle); final-review R1 = FINAL_VERDICT: FAIL (P0=0, P1=3,
  P2=9); FIX-R1 closed P1-01/P1-03/P2-02, P1-02 prepared only.
- **RESULT: FIX-R2 COMPLETE — Windows drive-letter resolution fixed on
  both sides (Production + Oracle), runner-pack defects fixed
  (lstat preflight, BOM fixtures, measured env facts), spec §13.1
  synced. Re-frozen; full battery green; Drive archived (see §7).
  P1-02 itself stays OPEN until the V2 pack runs on Sam's PC.**

## Why FIX-R2 exists (the 2026-11-19 Windows run)

Windows run evidence arrived from Sam's PC ~18:24 GMT 2026-11-19
(RESULT=FAIL, 4/4 junction classes, parity 0/4). Root cause is NOT
junctions: both Production (`02_src/instructionroot/paths.py`) and
Oracle (`03_oracle/rust/src/paths.rs`) rebuilt absolute paths as
`"/" + "/".join(parts)`, so `C:\…` became `/C:/…`, which does not
exist on Windows. Verified in source (`paths.py` docstring: real
junction/drive-letter filesystem resolution deliberately left empty
for T011, never implemented). Decisive control: class 3/4 cwds are
plain dirs, same error. Junctions themselves all passed (`mklink /J`
no admin needed, fsutil `0xa0000003`, git did not index linked dirs).
OQ-5 measured: Python `os.path.islink(junction)` = False, Rust
`is_symlink()` = True — parity likely still fails after the drive fix
unless aligned (FIX-R2 aligns it via the reparse-tag rule).

## What was fixed (three workers, three commits)

### Production — `5d909df` (details: `FIX-R2-PRODUCTION-REPORT.md`)

`02_src/instructionroot/paths.py` (+323/−37) gains a Windows
drive-letter branch in `canonicalize()`: drive-absolute paths
(`C:/…` / `C:\…`) resolve against the drive root on a Windows host,
`..` stops at the drive root, resolved path rebuilt as `C:/` +
components; link test is the unified reparse-tag rule
(`0xA0000003` junction / `0xA000000C` symlink — `os.path.islink()`
returns False for junctions and must not be used here); readlink
targets normalised (backslash → `/`, `\\?\` stripped,
`\\?\UNC\…` → `//server/share/…`). Linux behaviour unchanged.
`05_tests/unit/test_paths.py` (+300): `FakeWindowsFS` + 9 new tests.

### Oracle — `de60187` (details: `FIX-R2-ORACLE-REPORT.md`)

`03_oracle/rust/src/paths.rs` (+789): the same drive-letter branch on
the Rust side (`cfg!(windows)`): drive root is the root, `..` stops
at the drive root, `C:/` + components rebuild, native FS calls;
`is_link_metadata()` (`file_type().is_symlink()` as the reparse-tag
proxy; std exposes no exact tag, no new deps); target normalisation
identical to Production; absolute drive targets switch drive, UNC
targets switch root to the share, root-relative targets reset to the
same drive root; drive-letter cwd/home absolute only on a Windows
host. `WinFs` trait + fake FS: 9 new tests. Linux behaviour
byte-identical.

### Runner pack + spec — `fc3fd62` (details: `FIX-R2-PACK-REPORT.md`)

- `00_control/WIN_JUNCTION/run_win_junction.py:119`: `os.stat` →
  `os.lstat` (stat follows the junction, tag read `0x0`).
- `build_win_junction_fixtures.ps1`: UTF-8 with BOM (PS 5.1
  ParserError fix).
- Pack docs: stale claims replaced with 2026-11-19 measured facts
  (`link.exe`/`cl.exe` present, MSVC 14.44.35207; rustup 1.100.0
  installed; PATH python 3.11.15 vs native 3.14.4; `mklink /J` needs
  no elevation; git ignores junction targets; OQ-5 split measured).
- `00_contract/PROJECT_BOOK.md` §13.1 (+9) and `PROJECT_BOOK.docx`
  (58,385 → 59,198 bytes): Windows drive-letter + reparse-tag rules.
- `WIN_JUNCTION_TASK.md` §0 freeze table left at FIX-R1 values
  (filled in only in the V2 dispatch copy — FIX-R1 precedent).

## 1. Verification summary (freeze worker re-run on the merged tree, 2026-11-19)

Full log: `review/tasks/P028-FIX-R2/battery.log`.

| Check | Command | Result |
|---|---|---|
| pytest | `.venv/bin/python -m pytest -q` (TMPDIR on persistent disk) | **292 passed, 6 skipped in 8.71 s** (exit 0; was 283 in FIX-R1, +9 = Production tests) |
| cargo test | `cargo test --manifest-path 03_oracle/rust/Cargo.toml` | **35 passed + 5 passed, 0 failed** (exit 0; was 26+5, +9 = Oracle tests) |
| compare_oracle --all | `.venv/bin/python scripts/compare_oracle.py --all` | exit 0; resolver 20, imports 16, fs 12, fs_probes 25; source/trust/edge/verdict/hash parity **100.0%**; fs_parity 100.0%; git_scenarios PASS |
| S0 gate | `.venv/bin/python scripts/s0_gate.py` | exit 0, **RESULT=PASS** (fixtures=60, parity 100%, determinism 100/100, fail_closed PASS, network_access=0, human_labels=0) |
| Windows corpus | `.venv/bin/python scripts/run_windows_corpus.py` | exit 0, **RESULT=PASS**: receipt_cases **15/15**, parity **15/15**, probes 10/10, determinism PASS |
| Security check | `.venv/bin/python scripts/security_static_check.py` | exit 0, **RESULT=PASS**: shell_true=0, network_runtime=0, telemetry=0, secret_fixture_leaks=0 (see battery.log correction note: first run FAILed only on the freeze worker's own battery-driver script, which was moved out of the repo; no product file involved) |
| CI simulation (system python3) | `python3 scripts/simulate_ci.py` | exit 0, **SIMULATION: PASS (2/2 cases)** |
| Dashboard smoke | `python3 -m http.server 8767 --directory web` + curl | HTTP **200** on `/`, `index.html`, `app.js`, `style.css`, `receipt.json`, `receipt-pass.json`, `receipt-block.json` (7/7; see battery.log correction note: first run had a missing-slash URL bug in the driver script) |

No regressions against the FIX-R1 baselines: every number matches or
improves by exactly the 9+9 new tests. The S0 refresh changed only the
pytest/cargo counts in `review/S0_GATE.md` / `S0_LOG.txt` and a temp-dir
path in `S0_ORACLE_SUMMARY.json` (timing/path-only diffs, still PASS);
`S0_FIXTURE_MANIFEST.json` and `S0_RECEIPT_HASHES.txt` are byte-identical
to FIX-R1.

## 2. Tool versions

| Tool | Version |
|---|---|
| Python (system + .venv) | 3.12.3 |
| pytest (.venv) | 9.2.0 |
| Rust / Cargo | 1.100.0 |
| git | 2.43.0 |

## 3. Performance — P2-01 carried, not re-measured

No performance work was done in FIX-R2. The T014 numbers stand:
510-source case p95 7.828 s vs 500 ms threshold (P2); demo verify p95
282.1 ms, normal path unaffected.

## 4. Release freeze (local only — no Drive, no GitHub)

Built under `07_release/` from the freeze commit
(`d3847b9c0886ff2e98d6ac2c37a1b046c0e50635`).
`scripts/verify_release.py` run: **VERIFY_RELEASE: PASS (6/6 checks
passed), exit 0**.

| Artifact | Size | SHA-256 |
|---|---|---|
| `source.zip` | 912,438 | `524cbe750ed1825898d35273ce4f8e74b7049c985b8858c2c6e2e96c91b7b168` |
| `dist.zip` | 573,910 | `e393d67ec829cedd5481a7959f66780aa1ef690f208cf433be85c153b8296cb7` |
| `P028-instructionroot-bundle.zip` | 1,357,619 | `3b5032b1f9ccb9e9aab696bb016b0049939a0bde7a0d5d06efd87ce3bfc76022` |
| `RELEASE_MANIFEST.json` | 3,844 | `bc911ac0791965c11779a7f86d3b9322a30d89e40133a9d148a8105b7f9041e1` |
| `FREEZE_REPORT.md` | 8,072 | `5be813ebb893a9252ff6a8340e3f54c2f0c25916cf8f3c2124dd4230371ba806` |
| `SHA256SUMS.txt` (outer, 6 entries) | 523 | `2ac861942faa5f8e2c454126e09e3a48ed50a961eda87e35d611c45375ea2c46` |
| `p028-instructionroot-d3847b9.bundle` (Git bundle, P1-03) | 11,897,570 | `4249cbf5b7dab4eed621291d1a409457b344d4ef0e5d0d1428841ede9729800b` |

- Freeze commit: **`d3847b9c0886ff2e98d6ac2c37a1b046c0e50635`**
- Release commit (adds `07_release/` artifacts):
  **`c2fd640c1be890c31e2ee1c307675a2c2b38856c`**
- Post-release commit (adds the Git bundle file, the updated
  `SHA256SUMS.txt`, and the final version of this report):
  **`acaf77396c361bada70e73ae94bc7bd0bb0f7e92`**
  (Drive-archive commit: see §5.)
- Two-step freeze (why two commits): `source.zip` is `git archive` of
  the freeze commit, so the freeze commit cannot itself contain the
  zip built from it. The freeze commit holds all FIX-R2 work except
  the release artifacts (and, unlike FIX-R1, it also removes the
  FIX-R1 `07_release/` artifacts from the tree — they are descendants
  of the FIX-R1 release in this branch's history, so the freeze commit
  deletes them; the release commit adds the rebuilt FIX-R2 set).
  `verify_release.py` proves `source.zip` == the freeze-commit tree.
- `dist.zip`: wheel `instructionroot-1.0.0-py3-none-any.whl` (built
  offline, system python3, `--no-build-isolation`), the static
  dashboard (`web/`), and the release Oracle binary rebuilt offline
  with `cargo build --release --locked --offline` (see
  `FREEZE_REPORT.md` for sizes/hashes).
- Bundle: `P028-instructionroot-bundle.zip` = source.zip + dist.zip +
  SHA256SUMS.txt + RELEASE_MANIFEST.json + FREEZE_REPORT.md +
  README.md + LICENSE.
- `SHA256SUMS.txt` (outer copy) lists every file in `07_release/`
  except itself (7 entries: the six above + the Git bundle file);
  the copy inside the bundle omits the bundle's own entry and the Git
  bundle file's entry (both postdate it — self-reference is
  impossible) and every line it contains matches the outer copy.
- Git bundle (P1-03): `p028-instructionroot-d3847b9.bundle`, refs
  `HEAD` + `refs/heads/fix-r2-freeze` → `c2fd640` (the release commit), complete
  history, `git bundle verify` OK. Verified by cloning from the
  bundle into a fresh dir and running the reviewer's checks
  (`git cat-file -e <freeze>^{commit}`,
  `git cat-file -e <release>^{commit}`, `git rev-parse HEAD`,
  `git status --porcelain` empty, fresh `git archive` of the freeze
  commit byte-identical to `source.zip`).

## 5. Drive archive (freeze worker, 2026-11-19 ~19:00 GMT)

Root folder `P028-instructionroot` (`1QQ44A3krBc3pfvpWlu6bPmDpjqb7EZWD`).
New subfolders (all files verified size + MD5 against local copies;
full ID table in `review/tasks/P028-FIX-R2/drive-archive.json`):

| Folder | ID | Files | Verified |
|---|---|---|---|
| `05_release_FIXR2_d3847b9` | `1wyfire6fOi834OdjVTR2zhx9LHfhnVhO` | source.zip, dist.zip, bundle zip, SHA256SUMS.txt, RELEASE_MANIFEST.json, FREEZE_REPORT.md, Git bundle (7) | 7/7 |
| `04_review_FIXR2_d3847b9` | `1CFempGkbARDdh96ovzxNJaPpwwmSgytp` | FIX-R2-PRODUCTION-REPORT.md, FIX-R2-ORACLE-REPORT.md, FIX-R2-PACK-REPORT.md, TASK_RESULT.md, battery.log, verify_release.log (6) | 6/6 |
| `03_evidence_FIXR2_d3847b9` | `1q4g2BAvvo-eMAOIpOmUTzQmkXJwbsOd9` | S0_GATE.md, S0_LOG.txt, S0_ORACLE_SUMMARY.json, S0_FIXTURE_MANIFEST.json, S0_RECEIPT_HASHES.txt, windows_corpus.log (6) | 6/6 |

**19/19 files verified (size + MD5).** Upload script:
`review/tasks/P028-FIX-R2/drive-upload.py` (run it with
`--verify-only` to re-check without re-uploading). Folder mapping
differs from FIX-R1 by design (see task): this round `04_review`
holds the worker reports + freeze report + acceptance logs, and
`03_evidence` holds the S0 gate products + Windows corpus log;
FIX-R1 had them the other way round.

Note: the Drive copy of this TASK_RESULT.md was re-uploaded after
this §5 was committed, so its Drive MD5 matches the final committed
version (see the freeze worker's final report to the parent agent).
FIX-R1 folders and files were not touched; no root spec files were
updated in this round (no spec content change needed beyond the
§13.1 sync already in the frozen tree).

## 6. What was NOT done / carried residuals

- **P1-02 still OPEN**: the real Windows NTFS junction run awaits the
  V2 pack on Sam's PC. The FIX-R2 code has never run on real Windows.
- **NEW residual — `ancestor_chain` not drive-aware (FIX-R2 did not
  fix, V2 run arbitrates)**: Python `profiles/_common.py:201`
  `ancestor_chain` does `os.path.normpath(cwd)` then splits on `/`;
  on Windows `normpath("C:/a/b")` yields backslashes, so the chain is
  the degenerate `["/", "/C:\\a\\b"]`. Rust `profiles.rs:220`
  `ancestor_chain` splits the POSIX-normalised path and yields
  `["/", "/C:", "/C:/a", "/C:/a/b"]`. The two sides probe different
  ancestor-directory sets. Verified in source by the freeze worker
  (both functions read). It affects a verdict only when an ancestor
  directory itself holds an instruction file; fixture environments
  are clean. If the V2 discovery parity fails, check here first.
  Recorded in the V2 pack's `CONSISTENCY_CHECK.md` as a known
  residual.
- **Runner-pack residuals**: the lstat fix and the BOM'd `.ps1` have
  not been run on real Windows yet (V2 is their first real-Windows
  run); OQ-5's Python/Rust junction-as-link split is aligned by the
  reparse-tag rule in code but unproven on a real junction until V2.
- P2-01 performance carried (see §3); P2-03–P2-09 carried.
- No final-review R2 submission (parent submits). No GitHub upload,
  no external messages.

## 7. V2 dispatch pack (not sent)

`~/workspace/your_files/P028_WIN_JUNCTION_PACK_V2.zip` — 6 pack files
from the frozen tree + `P028-source-d3847b9.zip` (the freeze
`source.zip` renamed), with `WIN_JUNCTION_TASK.md` §0 filled in with
the FIX-R2 freeze values in the dispatch copy only (frozen tree
untouched) and the known-residual note appended to the dispatch
copy's `CONSISTENCY_CHECK.md`. SHA-256 / size recorded in the
coordinator's final report. NOT sent to Sam or anyone else.
