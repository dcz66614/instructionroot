# P028-FIX-R4 — `sources[].git.repo` 未归一化（V3 唯一剩余缺陷）— TASK_RESULT

- TASK_ID: P028-FIX-R4
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-19
- Baseline: HEAD `32399d9` on branch `fix-r4` (FIX-R3 post-release state;
  freeze `535879b`, release `20699ea`); final-review R2 still HELD.
- **RESULT: FIX-R4 COMPLETE — V3 唯一剩余缺陷已修（`sources[].git.repo`
  在两条组装入口都归一化成 `C:/`）；全套回归绿色；重冻；Drive 已归档
  （见 §6）；V4 包已建（见 §7）。P1-02 本身仍 OPEN，直到 V4 包在 Sam 的
  PC 上跑完。**

## 1. Why FIX-R4 exists (the 2026-11-19 V3 Windows run)

V3 run evidence arrived from Sam's PC 2026-11-19 23:34–23:42 GMT
(RESULT=FAIL, exit 1, passed=1/4, parity each 1/4, distinct_hashes=2 —
new dirs `C:\p028-src-v3\` / `C:\p028-win-evidence-v3\`, V1/V2 preserved).
The failure narrowed completely: all 4 verdicts correct
(PASS/BLOCK/PASS/BLOCK), source/trust/edge all correct, class 2 fully
passes; V2's three root causes all confirmed fixed; pack §4 residuals
(`ancestor_chain`, `redact_home()`) caused no failures. The only
remaining defect, precisely localised by the main chat in source
before dispatch: `receipt.py:559` `"repo": git.repo` is the only path
field in the receipt NOT wrapped in `_normalize_receipt_path()`
(`raw_path` + `workspace.cwd/repo_root/home` all are) — Production
`C:\…` vs Oracle `C:/…`; class 2 passes precisely because its source
is outside the repo so `git.repo` is `None` on both sides.

## 2. What was fixed (branch `fix-r4-production`, merged into `fix-r4`)

Two commits, both pytest-verified before merge (worker reports in the
parent handoff; no separate worker-report files for FIX-R4):

- `ef5ddab`: `receipt.py::build_source_record` — `git.repo` normalised
  in both branches (GitState branch and dict branch, guarded by
  `"repo" in git_dict` so a missing field is still reported by the
  check below instead of silently added). + 5 regression tests
  (pytest 309 passed).
- `fb36200`: `receipt.py::_normalize_sources()` — dict-passthrough leak
  closed: dict sources handed straight to `build_receipt` get their
  git dict copied first, then `repo` normalised (caller dict never
  mutated; `None` still passes through as `None`; missing `repo`
  still errors at the validation above). + 1 regression test (dict
  source via `build_receipt`: backslash → `C:/`, hash equal to the
  slash version, `None` stays `None`, caller dict unmutated; negative
  control verified: stashing the fix makes the new test fail).
  pytest **310 passed / 6 skipped**.
- Audit conclusion: field-level, no second leak besides `git.repo`;
  Oracle side clean; `git.py`'s normpath source untouched.

### Merge (coordinator, branch `fix-r4`)

- Merged `fix-r4-production` into `fix-r4` (cut from `32399d9`) with
  **no conflicts** (merge commit `f897a31`). Merged diff:
  2 files, +153/−2 — `02_src/instructionroot/receipt.py` +24/−2,
  `05_tests/unit/test_receipt.py` +131. `git diff 32399d9 -- 02_src`
  confirms only `receipt.py` + the test file changed.
- Pack doc updates (in `fix-r4`, staged for freeze):
  `00_control/WIN_JUNCTION/CONSISTENCY_CHECK.md` gained new §5
  "FIX-R4 更新（2026-11-19）" — V3's single remaining defect
  `git.repo` fixed, both assembly entry points closed;
  `ancestor_chain` / `redact_home()` residuals unchanged, V3 proved
  they caused no failures. `WIN_JUNCTION_TASK.md` §4 gained a
  "V4 说明（FIX-R4，2026-11-19）" paragraph with the same class-2
  note and unchanged bar. Docs only, no code touched.

## 3. Re-freeze identity

- Freeze commit: `b2f9ceb2a24a61211304bd9af357c4c5d314935a`
  (branch `fix-r4-freeze`; message "P028 FIX-R4: re-freeze
  (sources[].git.repo C:/ normalisation, both assembly entry points;
  S0 refresh 310/43)"). It contains the merge + S0 evidence refresh
  + the two pack-doc edits; `07_release/` (FIX-R3 artifacts) deleted
  from the tree in the freeze commit, per the FIX-R2/FIX-R3 two-step
  pattern (source.zip is `git archive` of the freeze commit, so the
  freeze commit cannot contain the zip built from it).
- Release commit: `04195cf814f0182bddcf11b23d518ae48b0db6fb` (adds `07_release/`).
- Artifacts (`07_release/`):

| File | Size (bytes) | SHA-256 |
|---|---|---|
| `source.zip` | 951,147 | `1adcd3e3ad3a2532e0a334fe9bc86d3965655b549982e193bd6678b41ed3a735` |
| `dist.zip` | 580,497 | `0e19e3cf6682703ab388cfcc85de917ec45160754953a35b7a70f9019665056c` |
| `P028-instructionroot-bundle.zip` | 1,401,292 | `c3a5b53a5d992873e2ed8e76984201a81a2da593424aa57d812e76b77ac2f608` |
| `RELEASE_MANIFEST.json` | 3,943 | `d8b860280334ffbb912b6aacd1437541da49bcf0d0d2eb26d66cac8c00b3c6b5` |
| `FREEZE_REPORT.md` | 8,600 | `cd84d8811d1b1d7117f3f1e76d12f2d01aa87596e42f2a6aba4a59e46b5c4425` |
| `SHA256SUMS.txt` (outer, 6 entries) | 523 | `ae18966bbb8a961ca72e861b8a9a1e7a2303284650de7c884077f6d067423f02` |
| `p028-instructionroot-b2f9ceb.bundle` | 36,693,387 | `1bd8a57c2734be27f1210ad9fa86862b1ca01063e9d15224f76bfa9589b7dd96` |

- `dist.zip` members: wheel `instructionroot-1.0.0-py3-none-any.whl` (82,964 B,
  sha `c4b5bf6e2ab165c94526c835e0195cff6c88376034fc521f89b42e239f4b93eb`,
  built offline with system python3 `--no-build-isolation`; hash CHANGED
  from FIX-R3 (`a80f0096…`) — `receipt.py` changed in FIX-R4, as
  expected);
  `oracle/instructionroot-oracle` (1,178,272 B, sha
  `c4ddc0dee15bdcf4c0fe80ed7dcc057f3a40e5642e1967218fe09fbdf823b517`,
  rebuilt offline with `cargo build --release --locked --offline`; hash
  UNCHANGED from FIX-R3 — Oracle code unchanged in FIX-R4, as
  expected); `web/` static (README.md, app.js, index.html, receipt-block.json,
  receipt-pass.json, receipt.json, style.css).
- `source.zip` is `git archive` of the freeze commit (549 files —
  541 from the FIX-R3 freeze plus the 8 files of
  `review/tasks/P028-FIX-R3/` committed in the FIX-R3 post-release
  commit `32399d9`).
- Git bundle: refs HEAD + `refs/heads/fix-r4-freeze` → `04195cf` (release
  commit); `git bundle verify` OK; clean-clone checks PASS (freeze + release
  commits present, HEAD = release commit, status clean, fresh `git archive`
  byte-identical to source.zip, sha `1adcd3e3…`).

## 4. Acceptance battery (coordinator, personally re-run on the merged tree, 2026-11-19)

| Check | Command | Result |
|---|---|---|
| pytest (`.venv`, TMPDIR on persistent disk) | `.venv/bin/python -m pytest -q -p no:randomly` | **310 passed, 6 skipped** (7.32s) |
| cargo test | `cargo test --locked` (in `03_oracle/rust`) | **38 passed + 5 passed, 0 failed** |
| compare_oracle | `.venv/bin/python scripts/compare_oracle.py --all` | resolver 20, imports 16, fs 12, fs_probes 25; source/trust/edge/verdict/hash parity **100.0%**; fs_parity 100.0%; git_scenarios PASS |
| S0 gate | `.venv/bin/python scripts/s0_gate.py` | **RESULT=PASS** (fixtures=60, parity 100%, determinism 100/100, fail_closed PASS (8/8), network_access=0, human_labels=0) |
| Windows corpus | `.venv/bin/python scripts/run_windows_corpus.py` | **RESULT=PASS**: receipt_cases 15/15, parity 15/15, probes 10/10, determinism PASS |
| Security static check | `.venv/bin/python scripts/security_static_check.py` | **RESULT=PASS** (shell_true=0, network_runtime=0, telemetry=0, secret_fixture_leaks=0) |
| CI simulation (system python3) | `python3 scripts/simulate_ci.py` | **SIMULATION: PASS (2/2 cases)** |
| Dashboard smoke | `python3 -m http.server 8771 --directory web` + curl | HTTP **200** on `/`, `index.html`, `app.js`, `style.css`, `receipt.json`, `receipt-pass.json`, `receipt-block.json` (7/7) |
| `verify_release.py` | `.venv/bin/python scripts/verify_release.py` | **VERIFY_RELEASE: PASS (6/6 checks)** (final run on the final release dir: manifest 5 entries, zips clean, source.zip == freeze commit 549 files, bundle 7 members byte-identical, outer SHA256SUMS 6 entries, wheel install reproduces demo hash `efd5e4a02f41`) |
| Git bundle clone + reviewer checks | clone from bundle, `git archive` compare | **PASS** (see §3) |

- S0 evidence diff vs `32399d9` is only counts (pytest 304→310) + timing
  values + a temp-dir path in `S0_ORACLE_SUMMARY.json`;
  `S0_FIXTURE_MANIFEST.json` / `S0_RECEIPT_HASHES.txt` byte-identical.
- Battery-run notes (honest): the first `cargo test --locked` attempt ran
  from the repo root (no `Cargo.toml` there) — re-ran from
  `03_oracle/rust` per the tool's own error; the failed attempt is noted
  in `battery.log`. The dashboard-smoke driver first showed `000` for
  every path after `/` — root cause was my own URL bug (loop built
  `http://127.0.0.1:8771index.html`, a malformed port, curl exit 3;
  the server never saw those requests). Re-ran with correct
  `http://127.0.0.1:8771/<path>` URLs: 7/7 HTTP 200, confirmed in the
  server log. The `000` runs are kept in `battery.log` with the
  explanation, not deleted.
- No regressions against the FIX-R3 baselines: every number matches or
  improves by exactly the 6 new tests (310 vs 304); Oracle binary hash
  unchanged; demo hash `efd5e4a02f41` unchanged.

## 5. Carried items (not fixed in FIX-R4)

- P2-01 performance: 510-source verify p95 7.828 s vs 500 ms threshold (T014
  measurement, carried; demo verify p95 282.1 ms, normal path unaffected).
  No fix attempted.
- P2-03–P2-09: carried, recorded only (see R1 reply).
- P1-02: still OPEN — the V4 Windows runner pack is preparation plus the
  FIX-R4 code; the real NTFS junction run awaits Sam's PC.
- Residual — `ancestor_chain` with a Windows `stop` returns `[cwd]`:
  the chain elements are `/`-prefixed, so a `C:/…` stop never matches;
  identical on the Oracle side by the same algorithm, so left unchanged to
  preserve parity. If final review rules the stop must take effect on
  Windows, both sides must change together — never one side alone.
- Residual — `paths.py::redact_home()` is still `normpath` + `"/"` style
  and does not take effect on Windows; it only affects CLI display text,
  never receipts or hashes — out of FIX-R4 scope, left as is.
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
- `05_release_FIXR4_b2f9ceb`: `173nVYjUAjRaRl9nPFIYUzANcY8yYCMUw` (7 files)
- `04_review_FIXR4_b2f9ceb`: `1n6xKFuJWdtH6QtiV6NoJrnYuwNxQH3hm` (3 files)
- `03_evidence_FIXR4_b2f9ceb`: `1PBB5LEiVUhTCS3PCBf9GT7OpiRMXGc3-` (6 files)
- All files size+MD5 verified; full ID table in
  `review/tasks/P028-FIX-R4/drive-archive.json` (re-check with
  `review/tasks/P028-FIX-R4/drive-upload.py --verify-only`).

## 7. V4 dispatch pack (not sent)

`~/workspace/your_files/P028_WIN_JUNCTION_PACK_V4.zip` — **841,806 B, SHA-256
`8146241310ca4a93e6e5f592122d73196e6bb209b25bfc65caa5c5eabdd95547`** — 6 pack files
from the frozen tree + `P028-source-b2f9ceb.zip` (the freeze `source.zip`
renamed; inner SHA `1adcd3e3…`, identical to the frozen `source.zip`), with
`WIN_JUNCTION_TASK.md` §0 (and the matching identity lines
in `EVIDENCE_INDEX.md`, `WIN_JUNCTION_AGENT_PROMPT.md`,
`CONSISTENCY_CHECK.md`) filled in with the FIX-R4 freeze values in the
dispatch copy only (frozen tree untouched — `git status 00_control/` clean;
the in-tree §0 still carries FIX-R1 values). §0 values: freeze
`b2f9ceb2a24a61211304bd9af357c4c5d314935a`, release
`04195cf814f0182bddcf11b23d518ae48b0db6fb`, HEAD `04195cf` (release commit,
HEAD at pack time), source.zip 951,147 B / `1adcd3e3…`, dist.zip 580,497 B /
`0e19e3cf…`, Oracle 1,178,272 B / `c4ddc0de…`, bundle 36,693,387 B /
`1bd8a57c…`. Verified: inner source.zip SHA equals the frozen one; no stale
§0 values (the single remaining `0110fa8` is the historical P1-01 note,
kept identically in the V3 pack); `.ps1` starts `EF BB BF` (BOM); runner
uses `os.lstat` (line 123). Pack files differ from the frozen tree only by
the §0 substitutions (TASK 18 lines, AGENT_PROMPT 2, EVIDENCE 6,
CONSISTENCY 4, `.ps1`/runner 0).
NOT sent to Sam or anyone else.
