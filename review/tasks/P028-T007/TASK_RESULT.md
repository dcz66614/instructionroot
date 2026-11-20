# P028-T007 — S0 Golden Corpus + Gate — TASK_RESULT

- TASK_ID: P028-T007
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-18
- Baseline: HEAD 5ae5b61 (FIX-C06); T001–T006 + FIX-C06 all PASS and committed.
- **RESULT: PASS — S0_GATE.md status=S0_PASS. T008 may proceed.**

## Verdict block (from `.venv/bin/python scripts/s0_gate.py`, exit 0)

```text
S0_GATE
fixtures=60
production_oracle_parity=100%
receipt_hash_parity=100%
determinism=100/100
fail_closed=PASS
network_access=0
human_labels=0
RESULT=PASS
```

## Handoff (for the coordinator)

- 60 fixtures: 20 normal / 20 boundary / 20 adversarial (resolver 20 + imports 16 + fs 12 + new s0 12).
- Source assertions: 99 entries × 6 fields (rule, path, scope, phase, precedence, trust) × 2 implementations = **1188** (required ≥ 180; either implementation alone gives 594).
- Edge assertions: 46 entries × 7 fields (from, syntax, depth, target, resolved target, allowed, reason) × 2 implementations = **644** (required ≥ 100).
- FS probe assertions: 25 probes × 6 fields × 2 implementations = 300.
- 5 parities, all 100% over 48 receipt cases: source 48/48, trust 48/48, edge 48/48, verdict 48/48, receipt-hash 48/48. FS parity 100% (12 cases, 25 probes). Git/trust scenarios 6/6.
- Determinism: codex-basic receipt hash `649d415f754c…` identical across 100 production runs + 100 Oracle runs; s0-git-tracked `cef656db9669…` identical across 25 + 25.
- Fail-closed suite 8/8 (FC-01–FC-08, production and Oracle agree on every error class; never PASS).
- network_access=0 (static grep over 02_src + 03_oracle/rust/src + scripts, 0 tokens, 0 `shell=True`, plus a runtime audit hook blocking any Python socket use during the determinism runs: 0 events). human_labels=0 (all four fixture manifests `synthetic: true`; no `human_label` marker anywhere in fixtures or the expected index).
- Known escape detection 15/15 (every case that expects an escape trust or a blocked edge carries it).
- 12 boundary scenarios (§9.1) 12/12; S01–S25 25/25 — with two honest carve-outs, both recorded in S0_GATE.md, neither faked as a pass:
  - S12/junction: `fs/windows` pure-string probes ran and passed; **real junction resolution is NOT_RUN on Linux** (T011, Windows runner).
  - S23/git deleted file: covered by unit test `test_deleted_tracked_file` (05_tests/unit/test_git.py) plus the missing-target mechanism in `s0-git-missing-import`.
- **SPEC-04 determination (T007): `considered_but_not_applicable` stays inside the DiscoveryReport (production `report.not_applicable`) and the Oracle explain sidecar; it does NOT enter the receipt** — the frozen receipt schema has no slot for it and no new enum value is invented. S16 (`copilot-applyto-nomatch`) is asserted by comparing the not-applicable lists in the gate, not by receipt sources.

## What was built

| File / directory | What it is |
|---|---|
| `scripts/s0_gate.py` | The S0 gate. Runs everything live (production + Oracle, no cached conclusions): inventory, golden stages, unified-index check (48 receipt cases), fs index check (12), git scenarios, determinism 100+100, fail-closed FC-01–FC-08, network proof, coverage, regression (pytest + cargo + compare_oracle --all). Writes all five review artifacts. Exit 0 iff PASS. |
| `scripts/build_s0_expected.py` | Generator for the unified expected index. Sources/edges transcribed from the frozen T003/T005 stage files; trust + verdict hand-derived in the `TRUST_VERDICT` table from the frozen contracts (with per-case reasoning comments); fs probes hand-transcribed from the T002 trees; s0 cases fully hand-written. No receipt_hash is ever written (hashes are compared production-vs-Oracle only). |
| `01_s0/expected/` (60 files + `INDEX.json`) | Unified expected index: one `<case-id>.expected.json` per fixture (receipt cases: sources with trust, edges with depth, verdict, not-applicable, forbidden trust; fs cases: canonicalize probes). |
| `01_s0/fixtures/s0/` (12 cases + `build_s0_fixtures.py` + `manifest.json`) | New fixtures. Each has its own **real git repository** (fixed commit dates, reproducible HEAD SHAs) — this closes the gap that the resolver/imports corpora have no nested `.git`, so tracked/modified/staged-new/renamed states were never committed fixtures before. Cases: s0-git-tracked, s0-git-modified, s0-git-modified-block, s0-git-untracked-block, s0-git-staged-new, s0-git-symlink-inside, s0-git-symlink-escape, s0-downloads-import, s0-git-missing-import, s0-git-unicode, s0-git-rename, s0-case-sensitive. All content is synthetic placeholder text; the Downloads file is a plain placeholder note, no malicious payload. |
| `review/S0_GATE.md` | Gate verdict (status=S0_PASS), metrics, recorded decisions. |
| `review/S0_LOG.txt` | Full gate run log (98 lines, all 10 sections). |
| `review/S0_ORACLE_SUMMARY.json` | Per-case parity table (48 receipt + 12 fs), determinism hashes, fail-closed results. |
| `review/S0_RECEIPT_HASHES.txt` | 250 receipt hashes (100+100 codex-basic, 25+25 s0-git-tracked); exactly 2 distinct values, one per fixture. |
| `review/S0_FIXTURE_MANIFEST.json` | 60 entries: layer, harness, §9.1/S01–S25 mapping, source/edge counts, fixture tree SHA-256, nested-repo git HEAD, expected-file SHA-256. |

## What was NOT touched (per DO_NOT_MODIFY)

`00_contract/*`, `02_src/*`, `03_oracle/*`, `.venv/`, `04_ui/*` — zero diffs
(`git status` confirms: only `01_s0/expected/`, `01_s0/fixtures/s0/`,
`scripts/build_s0_expected.py`, `scripts/s0_gate.py`, and the five
`review/S0_*` files are new; `review/COORDINATOR_LOG.md` was already
modified before T007 started and was not edited by this task).
No production code was changed to make anything green, no expected
value was changed to fit a production output, no failing case was
deleted or marked NOT_RUN (except the pre-existing, documented S12
real-junction NOT_RUN).

## Gate runs during this task (honest record)

- Run 1: 43/48 receipt cases. All 5 failures were on my side, not
  production defects — production and Oracle receipts were identical
  in all 48 cases throughout:
  1. Not-applicable path normalisation in the gate: the production
     `report.not_applicable` fallback `raw_path` (absolute) was not
     relativised (compare_oracle relativises both sides). Fixed in
     `s0_gate.py`.
  2. `s0-git-symlink-escape` was missing from the
     `FORBIDDEN_ESCAPE_CASES` set in `build_s0_expected.py`, so its
     (expected) SYMLINK_ESCAPE trust tripped my own forbidden-trust
     rule. Fixed in the generator and the index regenerated.
- Run 2: sections 1–7 all PASS; section 8 failed on a self-match —
  the network grep scanned `s0_gate.py` itself, whose token list is
  the data being searched for. Fixed by excluding the gate file from
  the static scan (the runtime audit hook still covers the gate
  process itself); other scripts were verified token-free first.
- Run 3: sections 1–10 all PASS, then a `ValueError` in report
  generation: `"100% (%d/%d cases)"` — `% (` is a format spec.
  Fixed to `100%%` (5 places); also added traceback printing to the
  gate's error handler and made the final block report NOT_RUN for
  determinism/fail-closed when those steps were never reached.
- Run 4 (after the `%%` fix in S0_GATE.md's own verdict block):
  **PASS, exit 0.** Re-run a second time to confirm: PASS, exit 0.

## Acceptance commands (run independently after the gate, all pass)

```text
$ .venv/bin/python -m pytest 05_tests/ -q
239 passed, 2 skipped in 1.20s

$ cargo test --manifest-path 03_oracle/rust/Cargo.toml
test result: ok. 26 passed; 0 failed
test result: ok. 5 passed; 0 failed

$ .venv/bin/python scripts/compare_oracle.py --all
resolver_cases=20 imports_cases=16 fs_cases=12 fs_probes=25
source_parity=100.0% trust_parity=100.0% edge_parity=100.0% verdict_parity=100.0% hash_parity=100.0%
fs_parity=100.0% git_scenarios=PASS

$ .venv/bin/python scripts/run_golden.py --stage resolver
cases=20 passed=20 failed=0
golden_source_order=100.0%  golden_source_set=100.0%

$ .venv/bin/python scripts/run_golden.py --stage imports
cases=16 passed=16 failed=0
golden_edge_parity=100.0%  golden_escape_detection=100.0%

$ .venv/bin/python scripts/s0_gate.py
GATE_EXIT=0, RESULT=PASS (block quoted above)
```

## Fail-closed suite (all run against production AND the Oracle)

| ID | Malformed input | Production | Oracle (exit) |
|---|---|---|---|
| FC-01 | case file is not valid JSON | INPUT_ERROR | INPUT_ERROR (30) |
| FC-02 | profile version mismatch (codex-2026-10) | UNSUPPORTED_PROFILE | UNSUPPORTED_PROFILE (40) |
| FC-03 | unknown harness (warp-drive) | UNSUPPORTED_PROFILE | UNSUPPORTED_PROFILE (40) |
| FC-04 | cwd does not exist | INPUT_ERROR | INPUT_ERROR (30) |
| FC-05 | policy has an unknown field | INPUT_ERROR | INPUT_ERROR (30) |
| FC-06 | policy field is not a bool | INPUT_ERROR | INPUT_ERROR (30) |
| FC-07 | repo_root points at a file, not a directory | INPUT_ERROR | INPUT_ERROR (30) |
| FC-08 | case input has no harness field | INPUT_ERROR | INPUT_ERROR (30) |

No case produced PASS on either side; production and Oracle agree on
the error class in all 8.

## Notes for the coordinator

1. **Nested git repos in the new fixtures.** Each `01_s0/fixtures/s0/*/repo`
   contains its own `.git`. The outer workdir git will see these as
   embedded repositories (untracked directory entries); `git add` will
   add the fixture files but not the nested `.git` contents. That is
   the intended shape — the nested HEAD SHAs are recorded in
   `S0_FIXTURE_MANIFEST.json` (`git_head`, all 12 set). If you prefer
   the fixtures committed differently, say so before T008; the
   generator (`build_s0_fixtures.py`) reproduces them deterministically.
2. **Known behaviour, not a defect:** Copilot custom-directory sources
   outside the repo (`copilot-custom-dirs`, `copilot-custom-dir`) are
   OUTSIDE_REPO / BLOCK because the frozen trust classifier has no
   custom-directory root. Production and Oracle agree exactly; the
   gate asserts the contract-derived classification. Whether T008
   should give custom dirs their own approved root is a design
   question for you, not something S0 may redesign by editing code.
3. **Resolver fixture `claude-import-depth4` is BLOCK as a whole**
   (it also contains `@missing.md`); the 4-hop chain itself is
   allowed (S13). Recorded in S0_GATE.md so the final review does not
   misread the verdict.
4. **Runtime:** the full gate takes ~15 s on this VM (plus the
   regression step's own compare_oracle run). Re-run any time with
   `.venv/bin/python scripts/s0_gate.py`.
