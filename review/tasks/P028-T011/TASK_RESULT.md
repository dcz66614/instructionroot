# P028-T011 — Corpus expansion + Windows cases — TASK_RESULT

- TASK_ID: P028-T011
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-18
- Baseline: HEAD 633d6f6 (T007 S0 gate PASS); task-start pytest 239 passed, 2 skipped.
- **RESULT: PASS — windows corpus runner exit 0, RESULT=PASS.**
- **S0 gate still PASS (fixtures=60, parity 100%) — untouched and re-verified.**

## Verdict block (from `.venv/bin/python scripts/run_windows_corpus.py`, exit 0)

```text
receipt_cases=15 passed=15 failed=0
source_parity=15/15
trust_parity=15/15
edge_parity=15/15
verdict_parity=15/15
hash_parity=13/15
probes=10 passed=True
determinism=PASS distinct_hashes=1
RESULT=PASS
```

Hash parity is 13/15, not 15/15: the two shortfalls are the documented,
bounded known gap F6 (workspace.cwd only — see below). Source/trust/edge/
verdict parity is 15/15 with zero exceptions.

## What was built

| File / directory | What it is |
|---|---|
| `fixtures/windows/` (15 receipt cases + `build_windows_fixtures.py` + `manifest.json`) | New corpus. Layout follows `01_s0/fixtures/s0/`: `case.json` at each case root, `home/` / `repo/` / `outside/` beneath it, each case with its own real git repo where git state matters (fixed commit dates, reproducible HEADs). Generator is idempotent; nested `repo/` trees are gitignored and rebuilt, same rule as S0. |
| `fixtures/windows/expected/INDEX.json` | Hand-written expected index (NOT generated): 15 receipt cases + 1 probe set. Every expected value was hand-derived from the frozen contract and the code (paths/imports/trust/resolver), with per-case `reasoning`; no receipt_hash is ever written (hashes are compared production-vs-Oracle only). |
| `scripts/run_windows_corpus.py` | The corpus runner. Regenerates fixtures, checks every receipt case on production + Oracle (full receipt equality, hash parity, independent JCS recomputation, index check incl. edges-with-depth and not-applicable), checks the 10 pure-string probes on both `canonicalize` implementations, and runs a 10+10 determinism spot check. Reuses `compare_oracle` (`build_production_receipt`, `run_oracle_resolve`, `run_oracle_canonicalize`, `deep_diff`, `receipt_hash_of`) and mirrors the S0 gate's index-check helpers; it never reads or writes `01_s0/expected/` or `scripts/s0_gate.py`. Exit 0 iff everything passes. Writes `review/tasks/P028-T011/windows_corpus_summary.json`. |
| `05_tests/unit/test_windows_corpus.py` | 16 passed, 4 skipped. Pure-string probe assertions (10 spellings + drive-relative rejection) + index/manifest integrity + 4 explicit NOT_RUN skips (real junction / drive-letter / case-insensitive / UNC). |
| `.gitignore` | +3 lines: `fixtures/windows/*/repo/` (same embedded-repo rule as S0). |

## Case list (15 receipt cases; 7 PASS, 8 BLOCK, 0 WARN)

| Case | Harness | Expected outcome |
|---|---|---|
| win-case-variant | codex | `Agents.md` not discovered on Linux → 2 sources, PASS (F1) |
| win-case-both | codex | `AGENTS.md` + `AGENTS.MD` coexist; only exact-case found → PASS |
| win-junction-inside | codex | dir symlink → in-repo shared; 2 sources GIT_TRACKED, PASS (F6 gap) |
| win-junction-escape | codex | dir symlink → outside/Downloads; 1 source OUTSIDE_REPO, BLOCK (F6 gap) |
| win-junction-import-inside | claude-code | `@linked/also.md` through in-repo symlink → WITHIN_REPO, PASS |
| win-junction-import-escape | claude-code | `@linked/secret.md` through outside symlink → IMPORT_ESCAPE, BLOCK |
| win-unicode-chain | codex | `日本語/子目录` chain, committed → 3 sources, PASS |
| win-git-deleted-chain | codex | tracked chain file deleted → chain shrinks, PASS (F3) |
| win-git-deleted-import | claude-code | tracked-then-deleted import target → MISSING, BLOCK |
| win-git-case-rename | codex | case-only rename → new spelling undiscoverable, PASS |
| win-drive-import | claude-code | `@C:\shared\drive-note.md` → IMPORT_ESCAPE, BLOCK |
| win-unc-import | claude-code | natural UNC spelling → MISSING, BLOCK (F2) |
| win-drive-relative-import | claude-code | `@C:shared\note.md` → MISSING, BLOCK (F4) |
| win-tilde-user-import | claude-code | `@~other/shared.md` → UNRESOLVABLE, BLOCK |
| win-copilot-drive-ref | copilot-cli | `@C:\shared\drive-note.md` → IMPORT_ESCAPE, BLOCK |

Plus `win-probes`: 10 pure-string probes (lowercase drive, drive root, UNC
`..`/bare root, unicode drive path, drive-relative, mixed separators, `.`,
`..` above drive root, trailing separator) — 10/10 on both implementations.

Assertion counts: 21 source entries × 6 fields × 2 implementations = 252;
16 edge entries × 7 fields × 2 implementations = 224; 10 probes × 6 fields
× 2 implementations = 120.

## Parity table (production Python vs Rust Oracle)

| Bucket | Result |
|---|---|
| source (set + order + rule/scope/phase/precedence) | 15/15 |
| trust | 15/15 |
| edge (incl. depth, targets, allowed, reason) | 15/15 |
| verdict | 15/15 |
| receipt_hash | 13/15 — 2 known-gap F6 cases (below) |
| fs probes (canonical/resolved/exists/symlink/loop/broken) | 10/10 |
| determinism spot check (win-drive-import, 10 prod + 10 Oracle) | 1 distinct hash |

## NOT_RUN list (Linux cannot execute these; recorded per case in the index `windows` field, never faked as passes)

- Real NTFS junction resolution (reparse points, junction loops, junction to a drive root). Covered by: Linux dir-symlink analogues (same lexical/resolved + containment code path) + pure-string probes only.
- Real Windows drive-letter resolution against a Windows filesystem (existence, per-drive current directories). Covered by: pure-string normalisation probes only.
- Real case-insensitive filesystem matching (`Agents.md` found as `AGENTS.md`). Covered by: the Linux negative (exact-case matching pinned) + finding F1.
- Real UNC share access (network share existence/ACLs). Covered by: pure-string UNC probes + the import-path misparse case (F2, which happens before any filesystem access).
- Real Windows Git behaviour (core.ignorecase, case-only rename). Covered by: Linux git states (deleted/renamed) only.
- Real Windows UTF-16 / NFC handling. Covered by: the no-normalisation rule (contract Q3) pinned on Linux.

## Findings (resolver gaps — recorded, NOT patched, per the task constraints)

**F1 — No case-insensitive discovery mode.** Production probes the exact
filename `AGENTS.md` (and `CLAUDE.md`, etc.). On a case-insensitive Windows
filesystem the same probe would find `Agents.md`, so the Windows receipt for
`win-case-variant` would carry an extra (untracked) source and a different
verdict. There is no case-folding option anywhere in the resolver. Evidence:
`win-case-variant` (Linux: 2 sources PASS; Windows: 3rd source expected).
Severity: behaviour gap for Windows users; Linux behaviour is correct per
contract.

**F2 — UNC imports are misparsed to MISSING, not recognised as UNC.**
`parse_imports` collapses `\\` → `\` (backslash-escape removal), so the
natural UNC spelling `@\\server\share\note.md` becomes `\server\share\note.md`
(one leading backslash) before canonicalisation. That is not a Windows-style
spelling (the UNC detector needs two), so it is joined onto the importing
file's directory as a relative path and ends MISSING instead of
IMPORT_ESCAPE. The Oracle mirrors the collapse exactly (same edge, parity
holds), so this is a shared semantic gap, not a parity failure. Pure-string
UNC normalisation (`win-probes` P3/P4) is a separate code path and is
unaffected. Evidence: `win-unc-import`. Severity: a UNC import escapes
detection as an escape — it still BLOCKs (via MISSING), but for the wrong
reason, and an auditor reading the receipt would not see a UNC reference.

**F3 — A deleted chain file silently drops out of the chain (observation,
not a defect).** Deleting a tracked chain file removes it from discovery with
no receipt entry (unlike a missing import target, which IS reported as a
MISSING edge). A deleted file will not load, so silence is arguably correct,
but an auditor gets no signal that a previously-tracked instruction file is
gone. Evidence: `win-git-deleted-chain` (PASS, 2 sources) vs
`win-git-deleted-import` (BLOCK, MISSING edge).

**F4 — The drive-relative rejection is unreachable from the import /
canonicalise path.** `normalize_windows_path` rejects `C:foo`, but
`is_windows_style_path` requires a separator after the colon, so
`C:shared\note.md` is never detected as Windows-style: `lexical_canonical`
joins it onto the importing file's directory as a relative path (colon and
backslash as filename characters) and it ends MISSING, never UNRESOLVABLE.
The rejection itself is covered by unit tests on both implementations calling
`normalize_windows_path` directly. Evidence: `win-drive-relative-import`,
probe P6. Contrast `win-tilde-user-import` (`~user` IS rejected →
UNRESOLVABLE), the reachable fail-closed case.

**F5 — Drive-letter case is preserved, not folded.** `c:\repo\...` and
`C:\repo\...` normalise to different canonical strings (`c:/...` vs `C:/...`)
although they name the same Windows drive. Two spellings of one file would
get two canonical paths (and potentially two sources). Evidence: probe P1.
Severity: observation; Windows drive letters are case-insensitive.

**F6 — `workspace.cwd`: production records it lexically, the Oracle
resolved (known parity gap, bounded).** `resolver.discover_with_report`
canonicalises the caller-supplied CWD and builds the `ResolveContext` on the
RESOLVED cwd, so discovery is identical on both implementations — but
production's `build_receipt` records the LEXICAL cwd while the Oracle records
the RESOLVED cwd. Whenever the CWD contains a symlink component the two
receipts differ in exactly one field (`workspace.cwd`, hence the hash) and
nothing else. Grounded by direct inspection: `win-junction-inside` (both:
sources `repo/AGENTS.md` + `repo/shared/AGENTS.md`, PASS; only diff
`workspace.cwd`) and `win-junction-escape` (both: one source
`outside/Downloads/AGENTS.md`, OUTSIDE_REPO, BLOCK; only diff
`workspace.cwd`). The runner asserts the gap is exactly the documented diff
set (`$.workspace.cwd`, `$.receipt_hash`); any other diff still fails the
case. A corollary, also grounded: for the escape case the resolved CWD is
outside the repo, so `chain_dirs` returns `[cwd]` alone — the repo root file
is NOT in the chain, and the trust is OUTSIDE_REPO (not SYMLINK_ESCAPE,
because the discovered canonical path contains no symlink component).
Severity: real production↔Oracle divergence on symlinked CWDs, found by the
junction cases; receipt hashes for such workspaces are not reproducible
across implementations. No production or Oracle code was changed (forbidden
by the task); the gap is carried in the index as `known_parity_gap: F6`.

## Mistakes found and fixed during the run (fixture / expectation bugs, not production)

1. Escape-junction symlink depth: the generator linked `repo/linked` to
   `../../outside/Downloads`, which dangles from `repo/` (correct: `../outside/Downloads`).
   Both implementations rejected the dangling CWD (production `SnapshotError`,
   Oracle exit 30) — consistent fail-closed behaviour, fixture bug, fixed.
2. `win-case-variant` fixture accidentally contained `services/AGENTS.md`
   (from the shared tree helper) in addition to `services/Agents.md`; the
   generator now writes root + payments only, plus the variant file.
3. `win-copilot-drive-ref` hand-derivation bug: references resolve relative
   to the referencing file (`repo/.github/`), so the in-repo control must be
   spelled `@../shared/ok.md`, not `@shared/ok.md` (which resolves to
   `repo/.github/shared/ok.md` and is MISSING — both implementations agreed
   on that, my expectation was wrong). Fixed in fixture + index.
4. First-run junction expectations assumed the chain was built from the
   lexical CWD (`repo/linked/AGENTS.md`, SYMLINK_ESCAPE). Reading
   `resolver.py` (`cwd_resolved`) plus the actual receipts showed discovery
   runs on the resolved CWD; expectations were re-derived from that
   mechanism (F6), not copied from output.

## Regression (all green)

- Full pytest: **283 passed, 6 skipped** (task-start baseline 239/2; +28 from
  T008's `test_cli.py`, committed in parallel during this task; +16 passed /
  +4 skipped from T011's new test file).
- Cargo test: **26 + 5 passed, 0 failed.**
- `compare_oracle.py --all`: **5 parities 100%, fs 100%, git PASS**
  (resolver 20, imports 16, fs 12, probes 25).
- `scripts/s0_gate.py`: **RESULT=PASS** — `fixtures=60`,
  `production_oracle_parity=100%`, `receipt_hash_parity=100%`,
  `determinism=100/100`, `fail_closed=PASS`, `network_access=0`,
  `human_labels=0`. (Re-running the gate regenerated `review/S0_GATE.md` /
  `S0_LOG.txt` / `S0_ORACLE_SUMMARY.json` with count updates only.)

## What was NOT touched (per constraints)

`00_contract/*`, `02_src/*`, `03_oracle/*`, `01_s0/expected/*`,
`01_s0/fixtures/*`, `scripts/s0_gate.py`, `scripts/compare_oracle.py`,
`scripts/run_golden.py`, `scripts/build_s0_expected.py` — verified by
`git diff --stat` (empty). No production resolver/trust/import/receipt
semantics changed; no GitHub upload; no external messages; synthetic data
only; default zero network. The S0 gate stays exactly 60 fixtures.

## Handoff (for the coordinator)

- Corpus + runner are self-contained under `fixtures/windows/` and
  `scripts/run_windows_corpus.py`; rerun with
  `.venv/bin/python scripts/run_windows_corpus.py`.
- The two F6 cases are the only hash-parity exceptions, and the runner
  enforces that the diff is exactly `workspace.cwd` + hash.
- Findings F1/F2/F4/F6 are the substantive Windows gaps for the final
  review; F3/F5 are observations. None was patched (task constraint).
- The Windows runner work that remains genuinely NOT_RUN (real junction,
  real drive letters, real case-insensitive matching, real UNC, real
  Windows Git) still needs a Windows machine; this corpus is the
  Linux-executable specification of what that runner must check.
- Uncommitted working tree (commit decision is the coordinator's):
  `.gitignore` modified; new `fixtures/windows/`, `scripts/run_windows_corpus.py`,
  `05_tests/unit/test_windows_corpus.py`, `review/tasks/P028-T011/`.
  (Also present from parallel tasks, not T011: `web/`, T008's committed
  `test_cli.py`, `review/COORDINATOR_LOG.md`.)

## FIX-F6 closure (2026-11-18, P028-T011-FIX-F6)

**F6 CLOSED.** The Oracle's `workspace.cwd` now records the canonical
(lexical) path, matching production and the frozen contract
(`receipt_schema.json`: "Canonical absolute path of the working
directory"; T002 Q1: canonical = normalized lexical absolute path).
One receipt field changed in the Oracle only; no production, contract,
fixture, or S0 change.

| | Before (T011) | After (FIX-F6) |
|---|---|---|
| Windows corpus runner | exit 0, RESULT=PASS | exit 0, RESULT=PASS |
| receipt cases | 15/15 | 15/15 |
| source / trust / edge / verdict parity | 15/15 each | 15/15 each |
| **receipt_hash parity** | **13/15** (F6 gap) | **15/15** |
| probes | 10/10 | 10/10 |
| determinism spot check | PASS (1 hash) | PASS (1 hash) |

Direct check on the two junction cases (`win-junction-inside`,
`win-junction-escape`): `deep_diff` between Oracle and production
receipts is now **0 diffs** (was exactly `$.workspace.cwd` +
`$.receipt_hash`); `workspace.cwd`, `repo_root` and `home` all match
production exactly, and the hashes are equal. Discovery still runs on
the resolved CWD on both sides (the receipts' sources/trust/verdicts
are unchanged — e.g. the escape case is still BLOCK / OUTSIDE_REPO
with the single outside source).

Code change (`03_oracle/rust/src/receipt.rs`, `resolve_case` only):
`CanonicalPath.canonical_path` (lexical, `String`) is now kept as
`cwd_lexical` alongside the resolved `cwd` used for discovery, and the
receipt's `"cwd"` uses `cwd_lexical`. `repo_root` and `home` were
already identical on both sides (their paths contain no symlink
component in these cases) and were not changed. Discovery, trust,
import, and `canonicalize` logic untouched.

Runner change (`scripts/run_windows_corpus.py`): the F6 known-gap
carve-out is removed — any receipt diff or hash mismatch now fails the
case, buckets are strict, and the summary no longer carries a
`known_gaps` field. The `known_parity_gap: F6` records remain in
`fixtures/windows/expected/INDEX.json` as inert historical data (the
runner no longer reads them); fixture/expected values were not
touched, per the task constraints.

Regression (FIX-F6 re-run): full pytest **283 passed, 6 skipped**
(identical to the T011 baseline); cargo test **26 + 5 passed**;
`compare_oracle.py --all` **5 parities 100%, fs 100%, git PASS**;
S0 gate **RESULT=PASS** (fixtures=60, parity 100%, hash 100%,
determinism 100/100) — proving the S0 fixture hashes are unaffected,
as expected (no symlink in any S0 CWD). Note: the first S0 re-run in
this task reported RESULT=FAIL only because the gate's static network
grep flags the untracked `scripts/security_static_check.py` (a
parallel task's file, not in HEAD) for the token strings in its own
blocklist; with that file temporarily set aside the gate passes, and
the file was restored byte-identical (same SHA-256). That failure is
unrelated to FIX-F6.

Full record: `review/tasks/P028-T011-FIX-F6/TASK_RESULT.md`.
