# P028-FIX-R3 — Fix the three V2 Windows path-normalisation root causes (A, B, C) + receipt spelling (D) — TASK_RESULT

- TASK_ID: P028-FIX-R3
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-19
- Baseline: HEAD `d234994` on branch `fix-r3` (FIX-R2 post-freeze state);
  final-review R1 = FINAL_VERDICT: FAIL (P0=0, P1=3, P2=9); FIX-R1 closed
  P1-01/P1-03/P2-02; FIX-R2 fixed the drive-letter branch on both sides and
  the runner-pack defects. R2 still HELD.
- **RESULT: FIX-R3 COMPLETE — all three V2 root causes fixed (relative-import
  join re-normalisation; four `normpath` + hardcoded `/` helpers in one pass;
  Oracle `git.rs` `abspath()` drive-aware) plus the receipt-spelling split
  unified to `C:/` on both sides; pack known-residual note corrected;
  re-frozen; full battery green; Drive archived (see §6); V3 pack built
  (see §7). P1-02 itself stays OPEN until the V3 pack runs on Sam's PC.**

## 1. Why FIX-R3 exists (the 2026-11-19 V2 Windows run)

V2 run evidence arrived from Sam's PC 2026-11-19 22:43–22:52 GMT
(RESULT=FAIL, exit 1, 4/4 classes, five parities 0/4, distinct_hashes=2 —
new dirs `C:\p028-src-v2\` / `C:\p028-win-evidence-v2\`, V1 preserved).
The failure narrowed completely: receipts are now produced, junction
semantics work (Oracle fully correct; Production cwd junction correct),
each side is deterministic (Production 10 runs 1 hash, Oracle 10 runs
another hash) — the sides disagree. Three root causes, all reproduced
with evidence (E08-6):

- **A. Production: relative import + cwd join not re-normalised.**
  `lexical_canonical()` only normalises when `raw` itself is Windows
  spelling; import passes a relative reference (`shared/ok.md`), joined
  with cwd via `os.path.join` into all-backslash `C:\...\shared\ok.md`,
  never re-normalised → drive regex `^[A-Za-z]:/` misses → POSIX fallback
  → `/C:\...` → `IMPORT_ESCAPE`. Control: `canonicalize` eating an
  absolute path directly is correct for every spelling.
- **B. Production: a family of `normpath` + hardcoded `/` helpers, 4 places,
  same defect.** `os.path.normpath()` yields backslashes on Windows, then
  `"/"` is used for `startswith`/`split` — always fails on Windows.
  Measured: `chain_dirs` (`['…\repo\shared']` vs `['…\repo','…\repo\shared']`
  — class 1's main cause), `is_within_root` (False vs True),
  `relative_posix` (None vs `'AGENTS.md'`), `ancestor_chain`
  (`['…\repo']` vs full chain). The pack's "known residual" predicted
  ONLY `ancestor_chain` — the actual area is much larger.
- **C. Oracle: `git.rs` `abspath()` only treats `/`-prefixed as absolute.**
  `C:/…` gets cwd prefixed → `relative_to_repo()` = None → `git.repo=null` /
  `tracked=false` → all `GIT_UNTRACKED` → `WARN`. git itself excluded
  (same spawn method runs `git rev-parse` / `git ls-files` exit 0).
- **D. Spelling split (class 2's only difference):** `workspace.cwd/home/
  repo_root` and `sources[].raw_path` — Production stores raw backslash
  strings, Oracle stores normalised forward-slash strings; semantics
  identical but `receipt_hash` differs. Class 2 was already semantically
  fully correct.

## 2. What was fixed (two workers, two worktrees, merged without conflicts)

Work split into two git worktrees (avoids the FIX-R2 shared-worktree
HEAD-switching incident): `~/workspace/p028-fixr3-production/` (branch
`fix-r3-production`) and `~/workspace/p028-fixr3-oracle/` (branch
`fix-r3-oracle`), both from `d234994`.

### Production — `7c0dab9` (merge `5dbaa31`; details: `FIX-R3-PRODUCTION-REPORT.md`)

- **A** (`02_src/instructionroot/paths.py`): `lexical_canonical()` re-normalises
  join/`~` expansion results when Windows spelling; new `_is_absolute_path()`
  so Windows-style cwd/home count as absolute on any host (needed for Linux
  fake-FS `os_name="nt"` tests).
- **B** (`paths.py::is_within_root` + `profiles/_common.py`: `chain_dirs`,
  `relative_posix`, `ancestor_chain`): new shared `_normalize_for_comparison()`
  (normalise Windows spelling to `C:/` first, then compare; POSIX path
  unchanged, Linux byte-identical; drive root `C:/` treated like `/`).
  Measured results match V2 expectations: `chain_dirs →
  ['C:/repo','C:/repo/shared']`, `is_within_root → True`, `relative_posix →
  'AGENTS.md'`, `ancestor_chain` (no stop) → `['/','/C:','/C:/repo','/C:/repo/shared']`
  — same algorithm as Oracle's, outputs identical.
- **D** (`02_src/instructionroot/receipt.py`): new `_normalize_receipt_path()`
  at receipt assembly: `workspace.cwd/home/repo_root` + `sources[].raw_path` →
  `C:/`; contract checked — workspace fields are "Canonical absolute path"
  (normalisation is compliance, not a semantic change); `raw_path` is "Path as
  discovered (may contain ~ or be relative)" — only separator spelling unified,
  relative/`~` paths kept verbatim; `CanonicalPath.raw_path` untouched;
  backslash vs forward-slash versions of the same receipt now hash identically
  (regression test asserts).
- Spec sync (minimal): `00_contract/PROJECT_BOOK.md` §13.1 +1 line;
  `paths.py` docstring +1 sentence.
- Tests +236 lines, 12 new FIX-R3 regression tests (fake Windows FS +
  `os_name="nt"`); before/after control: stashing the three source fixes makes
  11/12 fail (the one passing is D's "relative/`~` kept verbatim" guard, which
  should pass).
- Residuals NOT fixed (out of scope): `ancestor_chain` with a Windows `stop`
  returns `[cwd]` (byte-identical algorithm to Oracle, kept for parity — if
  review wants stop to work on Windows, both sides must change together, never
  one side alone); `paths.py` `redact_home()` still `normpath` + `"/"` (CLI
  display text only, not in receipt/hash, untouched).
- One flaky `test_cli.py::test_version` failure in random-order runs —
  pre-existing order dependency (test needs the Oracle binary to exist; a fresh
  worktree has no binary yet; deterministic order `-p no:randomly` passes;
  unrelated to the change; passes in isolation before/after stash).
- `review/S0_RECEIPT_HASHES.txt` 504-line diff is only worktree-path differences
  (hashes embed absolute workspace paths).

### Oracle — `bda88f6` (merge `0706d57`; details: `FIX-R3-ORACLE-REPORT.md`)

- **C** (`03_oracle/rust/src/git.rs`): new `normalise_spelling()` (Windows
  drive/UNC spelling → normalised `C:/…` or `//server/share/…`, rest via
  `normpath_posix`; pure string, host-independent — deliberately NOT
  `Path::is_absolute()`, because on Linux it still judges `C:/…` relative and
  the unit tests run on Linux); `abspath()` first checks `is_windows_style_path`
  (`C:/…` and `C:\…` both recognised as absolute, no longer cwd-prefixed —
  eliminates V2's `C:\p028-tools/C:/…`); `..` truncates at drive root; bare
  drive-relative `C:foo` still goes via cwd (as before); relative joins
  normalise a backslash cwd to `C:/…` first and strip backslashes from the
  result. Also fixed the same rule in `find_repo_root()` (git's top-level output
  kept `C:/…`, else `relative_to_repo` splitting on `/` never matches),
  `relative_to_repo()` and `get_git_state()` repo spelling (receipt `git.repo`
  no longer carries backslashes); `nearest_existing_dir()` got a bare
  drive-root `C:` → `C:/` guard. Spawn logic (allowlist, 4 git commands) untouched.
- **D** (`03_oracle/rust/src/receipt.rs`, +87 lines): read the contract first —
  `receipt_schema.json` + Production `paths.py` both require `raw_path` to keep
  "caller verbatim" at discovery ("Path as discovered", may contain `~` or be
  relative), so NOT changed at discovery; only at receipt assembly, new
  `receipt_raw_path()`: Windows-style spelling → normalised `C:/…`, everything
  else (`~/…`, relative, POSIX) verbatim; `sources[].raw_path` assembly calls
  it. Audit: `workspace.cwd/home/repo_root` on Windows were already `C:/…`
  (from `canonicalize`'s canonical/resolved paths) — no rewrite (rewriting
  would only mask a `canonicalize` bug); Oracle-internally-built `raw_path`s
  (chain/ancestor/list_dir joins) were already `C:/…`; the only verbatim leak
  was caller-supplied `managed_path` — receipt-layer normalisation covers it.
  `canonicalize` subcommand + explain sidecar `raw_path` stay verbatim (not in
  receipt hash, outside this freeze's contract).
- Full `starts_with('/')` audit (grep, itemised): `git.rs:145` fixed;
  `paths.rs:79` `normpath_posix` internal — not changed; `paths.rs:158`
  `is_absolute_on_host` — not changed (has drive branch, deliberately
  host-gated; Linux drive cwd/home still refused, locked by fixture
  `drive_cwd_home_absolute_only_on_windows_host`); `paths.rs:375`
  `target.is_absolute()` — not changed (Linux bug-compat for `/C:/…`
  deliberately kept; Windows takes the other branch); `paths.rs:609`,
  `paths.rs:789`, `paths.rs:946` — not input-path absolute judgements;
  `profiles.rs:1123` `copilot_syntactic_block` — already drive-aware
  (`ref[1] == ':'`).
- Tests: `cargo test --locked`: **43 passed, 0 failed** — unit 38 (baseline 35,
  +3 new: `abspath_recognises_drive_spellings`, `relpath_drive_spellings`,
  `receipt_raw_path_spelling`) + CLI integration 5. Windows corpus
  `scripts/run_windows_corpus.py`: **15/15 full parity** (source/trust/edge/
  verdict/hash each 15/15, probes 10/10, determinism PASS distinct_hashes=1,
  RESULT=PASS), same as pre-fix baseline — Linux behaviour unchanged.
  `cargo fmt`/`clippy` not installed (toolchain 1.100.0 lacks them), not
  installed by worker; code hand-written to repo style.
- Notable check: `run_windows_corpus.py` rewrote
  `review/tasks/P028-T011/windows_corpus_summary.json` with 15 changed receipt
  hashes — worker re-ran against a clean tree (stash) and got the **identical
  15 new hashes** (e.g. `bfccf714…`): cause is the runner's `tempfile.mkdtemp`
  random temp dir entering receipt hashes, unrelated to the change; meaningful
  signal is 15/15 parity + RESULT=PASS on both runs. File reverted, not committed.
- Still unverified: real Windows end-to-end (only the V3 pack run on Sam's PC
  can prove it); `nearest_existing_dir`'s real-`git rev-parse` path can't take
  drive-letter input on Linux.

### Merge + pack docs (coordinator, branch `fix-r3`)

- Merged both branches into `fix-r3` with no conflicts (merge commits
  `5dbaa31` Production, `0706d57` Oracle; HEAD `0706d57`). Merged diff:
  13 files, +852/−300 — paths.py +72, _common.py +42, receipt.py +45,
  git.rs +129, receipt.rs +87, PROJECT_BOOK.md +1, test_paths.py +109,
  test_receipt.py +63, test_resolver.py +64, plus 4 S0 evidence files
  (regenerated).
- Pack doc updates (in `fix-r3`, staged for freeze):
  `00_control/WIN_JUNCTION/CONSISTENCY_CHECK.md` gained new §4 "已知残差
  （FIX-R3 更新，2026-11-19）" — states honestly that FIX-R2's dispatch copy
  predicted only `ancestor_chain`, V2 proved all four B sites broken (class
  1's main cause is `chain_dirs`), FIX-R3 fixed all four in one pass, V2 class
  2 was already semantically correct (only spelling), V3's bar unchanged
  (4/4 + parity 4/4 + determinism PASS, no relaxation), residuals:
  `ancestor_chain` + Windows `stop` → `[cwd]` (parity-consistent,
  unmodified) and `redact_home()` still `normpath` + `"/"` (CLI display only,
  unmodified). `WIN_JUNCTION_TASK.md` §4 gained a "V3 说明（FIX-R3，
  2026-11-19）" paragraph with the same class-2 note and unchanged bar.

## 3. Re-freeze identity

- Freeze commit: `535879b2823d0fe5b579b6da6bd16b780c39645c`
  (branch `fix-r3-freeze`; message "P028 FIX-R3: re-freeze (relative-import
  renormalisation; four normpath helpers; Oracle git abspath drive-aware;
  receipt C:/ spelling; S0 refresh 304/43)"). It contains the two merges +
  S0 evidence refresh + the two pack-doc edits; `07_release/` (FIX-R2
  artifacts) deleted from the tree in the freeze commit, per the FIX-R2
  two-step pattern (source.zip is `git archive` of the freeze commit, so the
  freeze commit cannot contain the zip built from it).
- Release commit: `20699ea373718389e03aff544d92768be109ab65` (adds `07_release/`).
- Artifacts (`07_release/`):

| File | Size (bytes) | SHA-256 |
|---|---|---|
| `source.zip` | 927,693 | `20bede49ea152395d9837a3392ea4c66389798d32f71a2f442e546e751ab45c5` |
| `dist.zip` | 580,075 | `65ca4f79b74e3de5ce9e463a76dfa7daf8a56fed2956684a85643214975e9f68` |
| `P028-instructionroot-bundle.zip` | 1,379,781 | `6638b308277e7bebfd27302f7ab2c27097877580be9eb62d5c1e7c2fcc3eae04` |
| `RELEASE_MANIFEST.json` | 4,028 | `ecda232214bc21f18f22d90fd143a76417d7dfa0f391916b6870501caed6f2ea` |
| `FREEZE_REPORT.md` | 9,185 | `b707b05da4da4faa7cde4df64cce2ee63095f0d4f15f68c15aa501eae0fd07a0` |
| `SHA256SUMS.txt` (outer, 6 entries) | 523 | `fb065215f278199e44357963065bdc404e4f479b1d337d3b05535cb585a66d2d` |
| `p028-instructionroot-535879b.bundle` | 25,904,846 | `ba648275e741e52895dbf6953491e851e7b1ba2b40a69122759cc9d03d02c2e8` |

- `dist.zip` members: wheel `instructionroot-1.0.0-py3-none-any.whl` (82,544 B,
  sha `a80f00962c18af5b56966c0872e5848b6469ceeb8eb199babd27adb946fea3ba`,
  built offline with system python3 `--no-build-isolation`);
  `oracle/instructionroot-oracle` (1,178,272 B, sha
  `c4ddc0dee15bdcf4c0fe80ed7dcc057f3a40e5642e1967218fe09fbdf823b517`,
  rebuilt offline with `cargo build --release --locked --offline`; hash
  CHANGED from FIX-R2 (`032932ec…`) — Oracle code changed in FIX-R3, as
  expected); `web/` static (README.md, app.js, index.html, receipt-block.json,
  receipt-pass.json, receipt.json, style.css).
- `source.zip` is `git archive` of the freeze commit (541 files).
- Git bundle: refs HEAD + `refs/heads/fix-r3-freeze` → `20699ea` (release
  commit); `git bundle verify` OK; clean-clone checks PASS (freeze + release
  commits present, HEAD = release commit, status clean, fresh `git archive`
  byte-identical to source.zip, sha `20bede49…`).

## 4. Acceptance battery (coordinator, personally re-run on the merged tree, 2026-11-19)

| Check | Command | Result |
|---|---|---|
| pytest (`.venv`, TMPDIR on persistent disk) | `.venv/bin/python -m pytest -q -p no:randomly` | **304 passed, 6 skipped** (8.78s) |
| cargo test | `cargo test --locked` | **38 passed + 5 passed, 0 failed** |
| compare_oracle | `.venv/bin/python scripts/compare_oracle.py --all` | resolver 20, imports 16, fs 12, fs_probes 25; source/trust/edge/verdict/hash parity **100.0%**; fs_parity 100.0%; git_scenarios PASS |
| S0 gate | `.venv/bin/python scripts/s0_gate.py` | **RESULT=PASS** (fixtures=60, parity 100%, determinism 100/100, fail_closed 8/8, network_access=0, human_labels=0) |
| Windows corpus | `.venv/bin/python scripts/run_windows_corpus.py` | **RESULT=PASS**: receipt_cases 15/15, parity 15/15, probes 10/10, determinism PASS |
| Security static check | `.venv/bin/python scripts/security_static_check.py` | **RESULT=PASS** (shell_true=0, network_runtime=0, telemetry=0, secret_fixture_leaks=0) |
| CI simulation (system python3) | `python3 scripts/simulate_ci.py` | **SIMULATION: PASS (2/2 cases)** |
| Dashboard smoke | `python3 -m http.server 8767 --directory web` + curl | HTTP **200** on `/`, `index.html`, `app.js`, `style.css`, `receipt.json`, `receipt-pass.json`, `receipt-block.json` (7/7) |
| `verify_release.py` | `.venv/bin/python scripts/verify_release.py` | **VERIFY_RELEASE: PASS (6/6 checks)** (final run on the final release dir: manifest 5 entries, zips clean, source.zip == freeze commit 541 files, bundle 7 members byte-identical, outer SHA256SUMS 6 entries, wheel install reproduces demo hash `efd5e4a02f41`) |
| Git bundle clone + reviewer checks | clone from bundle, `git archive` compare | **PASS** (see §3) |

- S0 evidence diff vs `d234994` is only counts (pytest 292→304, cargo 35→38)
  + a temp-dir path; `S0_RECEIPT_HASHES.txt` byte-identical to `d234994`.
- Battery-run notes (honest): the S0 re-run changed only timing values in
  `review/S0_GATE.md` / `S0_LOG.txt` / `S0_ORACLE_SUMMARY.json` (pytest 7.73s→
  8.50s, cargo 0.08s→0.11s) — restored with `git checkout` to keep the frozen
  tree intact. The CI-sim first attempt used `.venv/bin/python` (no PyYAML) —
  re-ran with system python3 per the FIX-R2 precedent; the failed attempt is
  noted in `battery.log`. The dashboard-smoke driver once self-killed via
  `pkill -f "http.server 8767"` matching its own shell (known AGENTS.md
  lesson); the 7/7 results printed before the kill and are in `battery.log`.
- No regressions against the FIX-R2 baselines: every number matches or improves
  by exactly the 12+3 new tests.

## 5. Carried items (not fixed in FIX-R3)

- P2-01 performance: 510-source verify p95 7.828 s vs 500 ms threshold (T014
  measurement, carried; demo verify p95 282.1 ms, normal path unaffected).
  No fix attempted.
- P2-03–P2-09: carried, recorded only (see R1 reply).
- P1-02: still OPEN — the V3 Windows runner pack is preparation plus the
  FIX-R3 code; the real NTFS junction run awaits Sam's PC.
- Residual — `ancestor_chain` with a Windows `stop` returns `[cwd]`:
  the chain elements are `/`-prefixed, so a `C:/…` stop never matches;
  identical on the Oracle side by the same algorithm, so left unchanged to
  preserve parity. If final review rules the stop must take effect on
  Windows, both sides must change together — never one side alone.
- Residual — `paths.py::redact_home()` is still `normpath` + `"/"` style
  and does not take effect on Windows; it only affects CLI display text,
  never receipts or hashes — out of FIX-R3 scope, left as is.
- Known limitations (unchanged from README §Known limitations): SPEC-04
  `considered_but_not_applicable` diagnostic-only; Copilot custom dirs
  outside the repo → `OUTSIDE_REPO`/`BLOCK`; Windows behaviour on Linux
  string-only (S12 real junction `NOT_RUN`); T003 `"@path"` parser gap;
  Claude upward discovery to filesystem root; only `verify` gates; receipts
  unsigned SHA-256.
- No final-review R2 submission (parent submits). No GitHub upload, no
  external messages.

## 6. Drive archive

- P028 root: `1QQ44A3krBc3pfvpWlu6bPmDpjqb7EZWD` ("agent project auto" /
  P028-instructionroot).
- `05_release_FIXR3_535879b`: `1xrM14l6cFWhPrhOLXO55VYD6prq2_NV9` (7 files)
- `04_review_FIXR3_535879b`: `1LMGgH3ZRvHJpGSfASGyg_MRE0UnpfOvY` (5 files)
- `03_evidence_FIXR3_535879b`: `1GVWVTsmKLa7gtvhYimJC0QgNgUChFW5A` (6 files)
- All files size+MD5 verified; full ID table in
  `review/tasks/P028-FIX-R3/drive-archive.json` (re-check with
  `review/tasks/P028-FIX-R3/drive-upload.py --verify-only`).

## 7. V3 dispatch pack (not sent)

`~/workspace/your_files/P028_WIN_JUNCTION_PACK_V3.zip` — 6 pack files
from the frozen tree + `P028-source-535879b.zip` (the freeze `source.zip`
renamed), with `WIN_JUNCTION_TASK.md` §0 (and the matching identity lines
in `EVIDENCE_INDEX.md`, `WIN_JUNCTION_AGENT_PROMPT.md`,
`CONSISTENCY_CHECK.md`) filled in with the FIX-R3 freeze values in the
dispatch copy only (frozen tree untouched; the in-tree §0 still carries
FIX-R1 values). SHA-256 / size recorded in the coordinator's final report.
NOT sent to Sam or anyone else.
