# P028-FIX-R1 — Fix R1 blockers (P1-01, P1-03, P2-02) + Windows runner pack (P1-02 prep) — TASK_RESULT

- TASK_ID: P028-FIX-R1
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-18
- Baseline: HEAD 6fa67b7 (R1 freeze lineage); final-review R1 = FINAL_VERDICT: FAIL (P0=0, P1=3, P2=9), full reply at ~/workspace/P028_FINAL_REVIEW_R1.md
- **RESULT: FIX-R1 COMPLETE — P1-01 CLOSED (verified from two clean paths), P1-03 CLOSED (Git bundle archived), P2-02 CLOSED (specs synced depth 4), P1-02 runner pack PREPARED (not executed, not closed — needs Sam's PC). Re-frozen; full battery green; Drive archived.**

## What was fixed

### P1-01 — S0 fixtures reproducible from any clean directory (CLOSED)
- `01_s0/fixtures/imports/claude-symlink-escape/repo/shared/link.md`: absolute symlink → relative `../../outside/secret.md` (root cause: the fixture generator built the link with an absolute path).
- `01_s0/fixtures/imports/build_imports_fixtures.py`, `01_s0/fixtures/resolver/build_resolver_fixtures.py`, `01_s0/fixtures/s0/build_s0_fixtures.py`: generators now use `os.path.relpath` for symlinks and `_fill_empty_dirs()` so re-running a generator reproduces the committed tree byte-for-byte.
- 42 `.gitkeep` placeholder files added so `git archive` carries the snapshot-required empty dirs (imports home 15, resolver home 13 + cwd 2, s0 home 12). `.gitkeep` is not an instruction file; discovery semantics unchanged, S0 still 60/60.
- `scripts/s0_gate.py`: new setup step 0b `ensure_fixture_dirs()` (rebuilds cwd/home/repo_root dirs from case.json, directories only) and step 0c `ensure_git_workspace()` (on a clean extraction with no `.git`: `git init + add -A + commit` with fixed author/date/message; no-op when `.git` exists, so a real checkout is unaffected).
- Two findings beyond the reviewer's count, both found empirically: (a) a clean extraction with no `.git` failed 32/48 receipt cases on trust (`GIT_TRACKED` expected vs `GIT_UNTRACKED` actual) — step 0c closes this; (b) the s0 layer's 12 empty homes also needed placeholders (42 total, not 30).
- Receipt-hash note: receipt hashes still differ across extraction paths by design (the frozen receipt schema embeds absolute `canonical_path`); the two clean paths produced the SAME self-built git HEAD (`6da546a2…`) and identical receipts except the absolute paths. R1 already ruled cross-workspace hash differences are not an implementation inconsistency. Changing this would require changing the frozen receipt contract — out of scope, not done.

### P1-03 — Git identity chain (CLOSED)
- New release includes `07_release/p028-instructionroot-<freeze7>.bundle` (Git bundle, ref `fix-r1`) containing the freeze commit, the release commit, and HEAD. Verified by cloning from the bundle into a temp dir and running the reviewer's checks: `git cat-file -e <freeze>^{commit}`, `git cat-file -e <release>^{commit}`, `git rev-parse HEAD`, `git status --porcelain` (empty), and regenerating `git archive` from the freeze commit and comparing it byte-for-byte with `source.zip` (see §5).

### P2-02 / SPEC-01 — Claude depth 4/5 spec contradiction (CLOSED)
- `00_contract/PROJECT_BOOK.md` §3.2, §15.2 (S13 depth 4 PASS / S14 depth 5 BLOCK); `00_contract/IMPLEMENTATION_PLAN.md` §3.3, §10.3; both DOCX files (run-level replacement, format preserved, `unzip -t` clean); `00_contract/profile_contract.json` (SPEC-01 marked RESOLVED in FIX-R1); `06_docs/PROFILES.md`; `01_s0/fixtures/README.md`; `README.md` Known limitations. Implementation untouched (`MAX_IMPORT_DEPTH = 4` in both Python and Rust, already correct). One production comment updated: `02_src/instructionroot/profiles/claude.py:46-48` docstring now says the defect was fixed in FIX-R1 (comment only, no behaviour change).
- Full-repo grep re-check: no remaining "depth 5 / ≤5 / depth 6 BLOCK" as a rule; remaining "depth 5" hits are the correct new statements (S14 depth 5 BLOCK, etc.).

### P1-02 — Real Windows NTFS junction (PREPARED, NOT CLOSED)
- New pack `00_control/WIN_JUNCTION/` (6 files, 1068 lines): `WIN_JUNCTION_TASK.md` (authoritative task spec, 4 junction classes, verdict/parity criteria, fail-closed rules, 9 open questions OQ-1–OQ-9), `WIN_JUNCTION_AGENT_PROMPT.md` (copy-paste prompt for the agent on Sam's PC), `EVIDENCE_INDEX.md` (evidence template, `C:\p028-win-evidence\`), `CONSISTENCY_CHECK.md` (self-check list), `build_win_junction_fixtures.ps1` (generates the 4 junction fixtures on the PC), `run_win_junction.py` (Windows-only runner: pre-checks → cargo native Oracle build → 4 classes via `check_receipt_case` → 10+10 determinism spot check → per-case receipts + summary JSON; exit 0 only if 4/4 pass AND five parities 4/4 AND determinism PASS).
- Feasibility verified on this VM: `dist.zip`'s Oracle is a Linux ELF and MUST NOT be used on Windows; this VM cannot cross-compile (no `x86_64-pc-windows-gnu` target, no MinGW linker; `rustup target add` NOT run); the only arranged path is a native `cargo build --release --locked` on Sam's PC (rust-toolchain.toml pins 1.100.0). Biggest unverified risk, recorded in the pack: the PC's VS Build Tools 2022 has no C++ components, so whether Rust's default MSVC link step finds `link.exe` is untested — the pack does NOT claim a C++ workload is needed (P025 lesson); on build failure the agent stops and preserves evidence.
- Open product question recorded as OQ-5: whether Rust's `is_symlink()` gate and Python's link check treat an NTFS junction (reparse tag `0xa0000003`, vs symlink `0xa000000c`) as a link — untested on Windows; any mismatch is recorded as a failure/product finding, never papered over.
- The pack's `WIN_JUNCTION_TASK.md` §0 SHA table still lists the R1 freeze values (30700bd / source.zip ec76dbe0…); it already instructs the dispatcher to update the table before dispatch. The dispatcher MUST fill in the new FIX-R1 freeze values (see §5) when building the dispatch ZIP for Sam's PC. The frozen copy is intentionally left as-is because the new source.zip SHA cannot be known before the freeze that produces it.

## Branches merged (coordinator)

- `fix-r1-p101` (P1-01): `6fa67b7 → abbd4ff → 02b078f → e358347` (clean chain).
- `fix-r1-spec` (P2-02): `91f894c`.
- `fix-r1-winpack` (P1-02 pack): tip `2ddf568` = P1-01 content (identical to `e358347`, verified empty diff) + 6 pack files.
- Merge: new branch `fix-r1` from `2ddf568`, merged `fix-r1-spec` (clean, no conflicts), plus the claude.py docstring fix → tip `1c4239a`.
- Shared-worktree note: the three parallel workers occasionally committed onto each other's branches (a `git checkout` race in one worktree). Verified and untangled by the coordinator before merging: `git diff d38faf0 91f894c` empty (spec cherry-pick byte-identical); `git diff 6d264f4 02b078f` empty (P1-01 content identical); `git diff e358347 2ddf568` = exactly the 6 pack files. No work lost; no file content duplicated or dropped.

## 1. Verification summary (all run by the coordinator on the merged tree, 2026-11-18)

Full log: `review/tasks/P028-FIX-R1/battery.log` (+ this file).

| Check | Command | Result |
|---|---|---|
| pytest | `.venv/bin/python -m pytest -q` (TMPDIR on persistent disk) | **283 passed, 6 skipped in 7.90 s** (exit 0) |
| cargo test | `cargo test --manifest-path 03_oracle/rust/Cargo.toml` | **26 passed + 5 passed, 0 failed** (exit 0) |
| compare_oracle --all | `.venv/bin/python scripts/compare_oracle.py --all` | exit 0; resolver 20, imports 16, fs 12, fs_probes 25; source/trust/edge/verdict/hash parity **100.0%**; fs_parity 100.0%; git_scenarios PASS |
| S0 gate | `.venv/bin/python scripts/s0_gate.py` | exit 0, **RESULT=PASS** (fixtures=60, parity 100%, determinism 100/100, fail_closed 8/8, network_access=0, human_labels=0) |
| Windows corpus | `.venv/bin/python scripts/run_windows_corpus.py` | exit 0, **RESULT=PASS**: receipt_cases **15/15**, parity **15/15**, probes 10/10, determinism PASS |
| Security check | `.venv/bin/python scripts/security_static_check.py` | exit 0, **RESULT=PASS**: shell_true=0, network_runtime=0, telemetry=0, secret_fixture_leaks=0 |
| CI simulation (system python3) | `python3 scripts/simulate_ci.py` | exit 0, **SIMULATION: PASS (2/2 cases)** |
| Dashboard smoke | `python3 -m http.server 8767 --directory web` + curl | HTTP **200** on `/`, `index.html`, `app.js`, `style.css`, `receipt.json`, `receipt-pass.json`, `receipt-block.json` (7/7) |

No regressions against the R1 baselines: every number matches (283/6, 26+5, 5×100%, S0 PASS, 15/15, 4×0, 2/2, 7/7).

## 2. Two-path clean-room reproduction of the MERGED tree (coordinator, re-run after merge, on the freeze archive)

Source archive: `07_release/source.zip` from the freeze commit `0110fa8` (SHA-256 `fdcd98af…`, 866,129 B, 865 entries). Extracted with `/tmp/extract_p028_zip.py` (the P1-01 worker's extractor: stock Info-ZIP `unzip` mangles UTF-8 filenames, stock Python `zipfile.extractall` flattens symlinks — both verified traps; the archive bytes themselves are correct). Extraction verified first: the claude-symlink-escape link reads `../../outside/secret.md` (relative), 42 `.gitkeep` files present.

| | Path A: `~/workspace/r20-verification/p028-fixr1-a` | Path B: `~/workspace/r20-verification/p028-fixr1-b` |
|---|---|---|
| S0 verdict | RESULT=PASS (exit 0) | RESULT=PASS (exit 0) |
| fixtures / receipt | 60, receipt 48/48 | 60, receipt 48/48 |
| five parities | 100% | 100% |
| determinism / fail-closed | 100/100, 8/8 | 100/100, 8/8 |
| gate self-built git HEAD | `ab485d5a19a013398d2cbb9fc8c9b82c628ba008` | `ab485d5a19a013398d2cbb9fc8c9b82c628ba008` (**identical**) |
| S0 fixture manifest | byte-identical to B | byte-identical to A |

Logs saved under `review/tasks/P028-FIX-R1/`: `cleanroom-A-S0_LOG.txt`, `cleanroom-B-S0_LOG.txt`, `cleanroom-A/B-S0_GATE.md`, `cleanroom-B-run.log`. (Path A's stdout run log was lost when the VM restarted at ~10:01 GMT mid-way through the B run; the A gate artifacts `S0_LOG.txt`/`S0_GATE.md` are intact and were copied. Path B's first attempt was interrupted by that same restart and was re-run cleanly afterwards; its second run found the `.git` created by the interrupted first run and left it untouched, per step-0c design — the HEAD still matched A's exactly.)

Environment note (not a product defect): the first two-path attempt used `/tmp` paths and failed at the gate's `cargo test` step with `ld terminated with signal 7 [Bus error]` — /tmp (512 MB tmpfs) was 100% full (two 171 MB stale clean dirs from the P1-01 worker + a 145 MB fresh cargo target). After clearing /tmp and moving the extractions to persistent disk, both paths passed. The reviewer runs the clean-room check on a normal disk, not this VM's tmpfs.

## 3. Tool versions

| Tool | Version |
|---|---|
| Python (system + .venv) | 3.12.3 |
| pytest (.venv) | 9.2.0 |
| Rust / Cargo | 1.100.0 |
| git | 2.43.0 |
| Oracle binary | `instructionroot-oracle 0.1.0` (rebuilt offline, hash unchanged `60247a20…`) |

## 4. Performance — P2-01 carried, not re-measured

No performance work was done in FIX-R1 (no production code changed except a comment). The T014 numbers stand: 510-source case p95 7.828 s vs 500 ms threshold (P2); demo verify p95 282.1 ms, normal path unaffected. R1 agreed P2-01 stays P2.

## 5. Release freeze (local only — no Drive, no GitHub)

Built under `07_release/` from the freeze commit
(`0110fa8fbeac497a98801d14e5308d454ec52e31`).
`scripts/verify_release.py` run: **VERIFY_RELEASE: PASS (6/6 checks
passed), exit 0** — manifest entries (5 checked); zips unzip (2);
source.zip == freeze-commit tree (525 files, all hashes match);
bundle members byte-identical (except the documented `SHA256SUMS.txt`
inner/outer difference); outer `SHA256SUMS.txt` covers the release dir
(6 entries); wheel installs offline in a temp venv and reproduces
the demo verify hash `efd5e4a0…` (installed == repo launcher).

| Artifact | Size | SHA-256 |
|---|---|---|
| `source.zip` | 866,129 | `fdcd98af548557a213cb1a5853804d04e1ed7b7302814363adada2ac4120acf8` |
| `dist.zip` | 570,918 | `a780fba55a1bdcbfbe923a5dd0a8684cc00f321a66a2c5ac3af0ae5744cd204f` |
| `P028-instructionroot-bundle.zip` | 1,310,701 | `6da5dc0315c6b41de89e0c1bac77a6a265a5bc52e8e8a945186076c95be39913` |
| `RELEASE_MANIFEST.json` | 3,601 | `3d8f59cef59a3eb72a942ad046563c9c38326c005be19d0c9cdea72ceff07730` |
| `FREEZE_REPORT.md` | 7,356 | `c3cf9b87599c5b4bcecdce6ad361a7ece282e2c8416995ca424f1adf14a3ec05` |
| `SHA256SUMS.txt` (outer, 6 entries) | 583 | `a2de1baefda65d533672dcc14f9044e0ac8eef8605711f133617062bcec8bdba` |
| `p028-instructionroot-0110fa8.bundle` (Git bundle, P1-03) | 4,851,843 | `15281b8481a3759a9342353cde3978a36d75a63a260135f3945116a57b3937fb` |
| `README.md` (repo root, in bundle) | 30,680 | `c2e7b8e9158fc7dbdf73866c27b217e0aa6ca26fbafb5a63320dacce54d27864` |
| `LICENSE` (repo root, in bundle) | 1,093 | `8302a1dde65e110f9cecf741db1967f06181e75499423227b58c4fc311992605` |

- Freeze commit: **`0110fa8fbeac497a98801d14e5308d454ec52e31`**
- Release commit (adds `07_release/` artifacts):
  **`12b8d6129933d760818556099a32fdb7732e226a`**
- Post-release commit (adds the Git bundle file, the updated
  `SHA256SUMS.txt`, and the final version of this report): its hash
  is recorded in the coordinator's final report to the parent agent
  (it cannot be recorded here — self-reference: this file is part
  of that commit).
- Two-step freeze (why two commits): `source.zip` is `git archive` of
  the freeze commit, so the freeze commit cannot itself contain the
  zip built from it. The freeze commit holds all FIX-R1 work except the
  release artifacts; the release commit adds `07_release/` on top.
  `verify_release.py` proves `source.zip` == the freeze-commit tree.
- `source.zip`: `git archive` of the freeze commit (865 entries: 525
  files + 340 directory entries).
- `dist.zip`: wheel `instructionroot-1.0.0-py3-none-any.whl` (78,062 B,
  SHA-256 `ab7f8472bdfa8dda6e2d3df43c8b75946addf8272876fb31105e23bdd6b8982d`;
  built offline, system python3, `--no-build-isolation`), the static
  dashboard (`web/`), and the release Oracle binary
  `instructionroot-oracle 0.1.0` (1,162,032 bytes, SHA-256
  `60247a20a3dd83479ca255fc0a993ad4ee8ea42880899c7ce79d317fdea2bf6b`;
  rebuilt offline with `cargo build --release --locked --offline`,
  no crates fetched; hash unchanged from R1 — no Oracle code changed).
- Bundle: `P028-instructionroot-bundle.zip` = source.zip + dist.zip +
  SHA256SUMS.txt + RELEASE_MANIFEST.json + FREEZE_REPORT.md +
  README.md + LICENSE.
- `SHA256SUMS.txt` (outer copy) lists every file in `07_release/`
  except itself (6 entries: the five above + the Git bundle file);
  the copy inside the bundle omits the bundle's own entry and the Git
  bundle file's entry (both postdate it — self-reference is
  impossible) and every line it contains matches the outer copy.
  Documented in `FREEZE_REPORT.md`.
- `RELEASE_MANIFEST.json` lists source.zip, dist.zip,
  FREEZE_REPORT.md, README.md, LICENSE with size + SHA-256, plus the
  freeze commit, tool versions (§3), test counts (§1), S0 verdict and
  the performance numbers (§4). It does not list itself,
  `SHA256SUMS.txt`, the bundle zip, or the Git bundle file
  (self/circular reference — documented in the manifest's `notes`);
  those are covered by `SHA256SUMS.txt` / `FREEZE_REPORT.md` / this
  report.
- `FREEZE_REPORT.md`: freeze commit, artifact inventory, full
  verification table, FIX-R1 change list, carried known limitations.
- Git bundle (P1-03): `p028-instructionroot-0110fa8.bundle`, refs
  `HEAD` + `refs/heads/fix-r1` → `12b8d61` (the release commit),
  complete history, `git bundle verify` OK. The coordinator verified
  it by cloning into a fresh dir
  (`~/workspace/r20-verification/bundle-clone`) and running the
  reviewer's checks there:
  `git cat-file -e 0110fa8…^{commit}` OK,
  `git cat-file -e 12b8d61…^{commit}` OK,
  `git rev-parse HEAD` = `12b8d6129933d760818556099a32fdb7732e226a`,
  `git status --porcelain` empty,
  fresh `git archive --format=zip 0110fa8…` SHA-256 =
  `fdcd98af548557a213cb1a5853804d04e1ed7b7302814363adada2ac4120acf8` —
  identical to `source.zip`. (First bundle attempt recorded only
  `refs/heads/fix-r1`; cloning it left HEAD unresolvable. The bundle
  was recreated with `HEAD` + `fix-r1` refs before the post-release
  commit — the bundle file was not yet committed anywhere, so no
  history was rewritten.)

## 7. Drive archive (coordinator, 2026-11-18 ~10:05 GMT)

Root folder `P028-instructionroot` (`1QQ44A3krBc3pfvpWlu6bPmDpjqb7EZWD`).
New subfolders (all files verified size + MD5 against local copies;
full ID table in `review/tasks/P028-FIX-R1/drive-archive.json`):

| Folder | ID | Files | Verified |
|---|---|---|---|
| `05_release_FIXR1_0110fa8` | `1f92vk30XVXz683Qs-RhN61ZtyYBVkBPx` | source.zip, dist.zip, bundle zip, SHA256SUMS.txt, RELEASE_MANIFEST.json, FREEZE_REPORT.md, Git bundle (7) | 7/7 |
| `04_review_FIXR1_0110fa8` | `1mA_E-Ri7tQZ3T2gMqJKh2LhCHmQoyOix` | S0_GATE.md, S0_LOG.txt, S0_ORACLE_SUMMARY.json, S0_FIXTURE_MANIFEST.json, S0_RECEIPT_HASHES.txt (5) | 5/5 |
| `03_evidence_FIXR1_0110fa8` | `1EfuK0TBkMdDLSXUZKho5JFXBkpMPO1Fx` | TASK_RESULT.md, battery.log, cleanroom-A/B S0_LOG.txt, cleanroom-A/B S0_GATE.md, cleanroom-B-run.log (7) | 7/7 |

**19/19 files verified (size + MD5).** Upload script:
`review/tasks/P028-FIX-R1/drive-upload.py` (run it with
`--verify-only` to re-check without re-uploading). One CLI quirk
found and fixed during the run: `files get` without an explicit
`fields` param returns no `size`/`md5Checksum` — verification must
request `fields=id,name,size,md5Checksum,mimeType`.

Root spec files updated in place to the FIX-R1 versions (depth 4),
verified size + MD5 (the establishment specs zip was left untouched
as the historical bundle):

| File | Drive ID | Size | MD5 (new) |
|---|---|---|---|
| `PROJECT_BOOK.md` | `1nGISmXoWChr8ThqeLteXUx-wYaYO7dw8` | 37,909 | `893cc2116e5b…` |
| `PROJECT_BOOK.docx` | `1tMsXBNdwuzMwQZ16DVHJLmUX_W4kVyz8` | 58,385 | `38a2b3e6a30a…` |
| `IMPLEMENTATION_PLAN.md` | `1KVM-PhN8eD0J4dwGHg8Pcf-fKqAWzDPm` | 26,310 | `50dadf317050…` |
| `IMPLEMENTATION_PLAN.docx` | `1iOlJm7OKOA6dIzWIX3-BomTXlBL07QKt` | 51,332 | `ee5e0ebf2ba6…` |

Note: the Drive copy of this TASK_RESULT.md is updated again after
this §7 is committed, so its Drive MD5 matches the final committed
version (see the coordinator's final commit).

## 8. What was NOT done (per task constraints)

- No real Windows junction run (P1-02 pack prepared only; execution awaits Sam's PC).
- No P2 scope expansion (P2-01, P2-03–P2-09 carried, recorded only).
- No final-review R2 submission (parent submits). No GitHub upload, no external messages.
- No production/Oracle semantic changes (one comment-only docstring edit in `claude.py`).
