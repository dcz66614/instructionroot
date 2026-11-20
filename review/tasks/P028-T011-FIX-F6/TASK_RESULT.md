# P028-T011-FIX-F6 — Oracle `workspace.cwd` must be the canonical (lexical) path — TASK_RESULT

- TASK_ID: P028-T011-FIX-F6
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-18
- Baseline: HEAD 6ac1738 (T008 commit); T011 Windows corpus files present but uncommitted.
- **RESULT: PASS — F6 CLOSED. Windows corpus runner exit 0, hash parity 15/15, S0 gate RESULT=PASS.**

## Verdict block

Windows corpus runner (`.venv/bin/python scripts/run_windows_corpus.py`, exit 0):

```text
receipt_cases=15 passed=15 failed=0
source_parity=15/15
trust_parity=15/15
edge_parity=15/15
verdict_parity=15/15
hash_parity=15/15
probes=10 passed=True
determinism=PASS distinct_hashes=1
RESULT=PASS
```

Before (T011): same numbers except `hash_parity=13/15`, the two
shortfalls being the F6 cases `win-junction-inside` and
`win-junction-escape`. After: **15/15 in every bucket, no
special-casing.**

## The gap (contract reading — settled by the coordinator, not re-decided)

Frozen `receipt_schema.json` defines `workspace.cwd` as "Canonical
absolute path of the working directory". T002 Q1 defines canonical =
normalized lexical absolute path and resolved = symlink-resolved
absolute path, both fields kept. Production passes the lexical path
(`scripts/compare_oracle.py` `resolve_case_paths`: `str(case_dir /
rel)`) to `build_receipt`, so production was correct. The Oracle built
`workspace.cwd` from `cwd_canon.resolved_path`, so whenever the CWD
contained a symlink component the two receipts differed in exactly
`$.workspace.cwd` + `$.receipt_hash` (hash parity 13/15, all other
buckets 15/15).

## Exact code change (Oracle-side only)

File: `03_oracle/rust/src/receipt.rs`, function `resolve_case` — one
receipt field only. The Oracle's `canonicalize` struct was verified
first (`03_oracle/rust/src/paths.rs`, `CanonicalPath`): field
`canonical_path: String` (lexical) and `resolved_path:
Option<String>` (symlink-resolved) — the same semantics as
production's `CanonicalPath` (fs parity 100%).

```diff
     let cwd = cwd_canon.resolved_path.clone().ok_or_else(|| {
         OracleError::InputError(format!("cwd does not resolve: {cwd_raw}"))
     })?;
+    // FIX-F6: the receipt's workspace.cwd is the canonical (lexical)
+    // path per the frozen receipt schema ("Canonical absolute path of
+    // the working directory", T002 Q1: canonical = normalized lexical
+    // absolute path). Discovery keeps running on the resolved `cwd`
+    // below — only the receipt field uses the lexical path.
+    let cwd_lexical = cwd_canon.canonical_path.clone();
```

```diff
         "workspace": {
-            "cwd": cwd,
+            "cwd": cwd_lexical,
             "repo_root": repo_root,
             "home": home,
         },
```

`cwd` (resolved) is unchanged and still feeds discovery
(`ResolveContext`, working-file and env-dir resolution) exactly as
before. `repo_root` and `home` in the Oracle receipt were not changed:
they already matched production (their paths contain no symlink
component in the junction cases), re-verified below. Discovery, trust,
import, and `canonicalize` logic untouched.

## Runner change

File: `scripts/run_windows_corpus.py` — the F6 known-gap carve-out is
removed:

- `check_receipt_case` (a): any `deep_diff` between Oracle and
  production receipts, and any `receipt_hash` mismatch, now fails the
  case unconditionally. The `known_parity_gap` lookup, the
  `known_gap_hit` computation, and the `gap.get("id")` result field are
  gone.
- Buckets: strict on `parity_clean` only (`effective_clean` removed);
  any receipt diff fails every bucket.
- Per-case status: no more `PASS+KNOWN-GAP` status.
- Determinism comment: the stale "(junction chain cases are NOT used
  here: their hashes differ by the F6 gap)" note removed.
- Summary JSON: the `known_gaps` list and per-case `known_gap` field
  removed.

The `known_parity_gap: F6` records remain in
`fixtures/windows/expected/INDEX.json` as inert historical data — the
runner no longer reads that key. Fixture content and expected values
were not touched, per the constraints.

## Verification — before/after parity numbers

| Check | Before (T011) | After (FIX-F6) |
|---|---|---|
| Windows corpus runner exit / RESULT | 0 / PASS | 0 / PASS |
| receipt cases passed | 15/15 | 15/15 |
| source parity | 15/15 | 15/15 |
| trust parity | 15/15 | 15/15 |
| edge parity | 15/15 | 15/15 |
| verdict parity | 15/15 | 15/15 |
| **hash parity** | **13/15** | **15/15** |
| probes (win-probes) | 10/10 | 10/10 |
| determinism spot check (win-drive-import, 10+10) | PASS, 1 hash | PASS, 1 hash |

Direct per-case check on the two former gap cases (independent
`deep_diff` of Oracle vs production receipts, absolute case paths):

- `win-junction-inside`: `deep_diff_count= 0`, diffs `[]`, hash equal,
  deterministic. Oracle workspace `cwd` =
  `…/win-junction-inside/repo/linked` (lexical), `repo_root` =
  `…/win-junction-inside/repo`, `home` =
  `…/win-junction-inside/home` — identical to production.
- `win-junction-escape`: `deep_diff_count= 0`, diffs `[]`, hash equal,
  deterministic. Oracle workspace `cwd` =
  `…/win-junction-escape/repo/linked`, `repo_root` and `home`
  identical to production.

So the full receipt diff is empty on both junction cases, and
`repo_root`/`home` agree exactly. Discovery still runs on the resolved
CWD: the receipts' sources/trust/verdicts are unchanged (the escape
case is still BLOCK / OUTSIDE_REPO with the single outside source; the
inside case still PASS with `repo/AGENTS.md` + `repo/shared/AGENTS.md`),
and the runner's index checks pass on both implementations.

## Regression (all green)

- Full pytest: **283 passed, 6 skipped** — identical to the T011
  baseline (239/2 at T011 start + T008's `test_cli.py` + T011's new
  test file).
- Cargo test (Oracle Rust): **26 passed (unit) + 5 passed (CLI
  integration), 0 failed.**
- `scripts/compare_oracle.py --all`: **resolver 20, imports 16, fs
  12, fs probes 25; source/trust/edge/verdict/hash parity 100.0%,
  fs parity 100.0%, git scenarios PASS.**
- `scripts/s0_gate.py`: **RESULT=PASS** — `fixtures=60`,
  `production_oracle_parity=100%`, `receipt_hash_parity=100%`,
  `determinism=100/100`, `fail_closed=PASS`, `network_access=0`,
  `human_labels=0`. This proves the S0 fixture hashes are unaffected
  by the change, as expected (no symlink in any S0 CWD).

### S0 gate note — one FAIL observed, diagnosed, not caused by FIX-F6

The first S0 re-run in this task reported `RESULT=FAIL` with
`GATE FAILURE: network tokens found in production/Oracle code: 12`.
All 12 tokens are in the untracked
`scripts/security_static_check.py` — a parallel task's file, not in
HEAD, never touched by this task — which the gate's static grep scans
and which lists those token strings in its own blocklist (it flags
itself). My changed files contain none of the tokens, and the
committed HEAD `review/S0_LOG.txt` already shows `RESULT=PASS`.
Diagnostic proof: with that file temporarily moved aside (SHA-256
`134b14fb…` before and after, restored byte-identical), the gate
re-run gives `RESULT=PASS` with the numbers above. The failure is a
pre-existing working-tree artifact of parallel work, unrelated to
FIX-F6; the file was left exactly as found. (The gate re-runs
regenerated `review/S0_GATE.md` / `S0_LOG.txt` /
`S0_ORACLE_SUMMARY.json`, which were already modified in the working
tree from T011's gate re-run.)

## What was NOT touched (per constraints)

- `02_src/` (production) — no change; verified by `git diff`
  (only `03_oracle/rust/src/receipt.rs` modified among tracked
  files, besides the S0 gate outputs above).
- `00_contract/` (frozen) — untouched.
- `01_s0/expected/`, `scripts/s0_gate.py` and its assertions —
  untouched.
- Fixture content / expected values (`fixtures/windows/`, including
  the `known_parity_gap` index records) — untouched.
- Oracle discovery, trust, import, and `canonicalize` logic —
  untouched; one receipt field only.
- No GitHub upload; no external messages.

## Files changed by this task

| File | Change |
|---|---|
| `03_oracle/rust/src/receipt.rs` | `workspace.cwd` now `cwd_canon.canonical_path` (lexical); +5 lines, 1 line changed |
| `scripts/run_windows_corpus.py` | F6 known-gap carve-out removed (strict parity, no `known_gaps` in summary) |
| `review/tasks/P028-T011/TASK_RESULT.md` | "FIX-F6 closure" section appended (this file's summary) |
| `review/tasks/P028-T011/windows_corpus_summary.json` | Regenerated by the runner (hash 15/15, no `known_gaps` key) |
| `review/S0_GATE.md`, `review/S0_LOG.txt`, `review/S0_ORACLE_SUMMARY.json` | Regenerated by the S0 gate re-runs (PASS, count updates only) |
| `review/tasks/P028-T011-FIX-F6/TASK_RESULT.md` | This file |

## Handoff (for the coordinator)

- F6 is closed with full hash parity 15/15 and zero diffs on both
  junction cases; the runner now enforces strict parity with no
  carve-outs anywhere.
- S0 is unaffected (100% hash parity on all 60 fixtures).
- Remaining known Windows findings from T011 (F1, F2, F4 — plus
  observations F3, F5) are untouched by this fix and still open as
  recorded in `review/tasks/P028-T011/TASK_RESULT.md`.
- Uncommitted working tree (commit decision is the coordinator's):
  this task's changes above, on top of the pre-existing uncommitted
  T011 files and parallel-task files (`web/`, `LICENSE`,
  `pyproject.toml`, `scripts/security_static_check.py`,
  `review/tasks/P028-T010/`, etc.).
