# P028 S0 Gate — PASS

status=S0_PASS
date: 2026-11-18 (gate run; see S0_LOG.txt for the full log)
baseline: HEAD 5ae5b61 (FIX-C06); production and Oracle code untouched by T007

## Verdict block

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

## Metrics (all measured live by scripts/s0_gate.py)

- fixtures: 60
- layers: normal 20 / boundary 20 / adversarial 20
- human_labels: 0
- golden_resolver: 20/20 (source order+set 100%)
- golden_imports: 16/16 (edge parity 100%, escape 100%)
- source_assertions: 99 entries x 6 fields x 2 implementations = 1188 (required >= 180)
- edge_assertions: 46 entries x 7 fields x 2 implementations = 644 (required >= 100)
- fs_probe_assertions: 25 probes x 6 fields x 2 implementations = 300
- source_parity: 100% (48/48 cases)
- trust_parity: 100% (48/48 cases)
- edge_parity: 100% (48/48 cases)
- verdict_parity: 100% (48/48 cases)
- receipt_hash_parity: 100% (48/48 cases)
- production_oracle_parity: 100%
- determinism: 100/100 (codex-basic) + 25/25 (s0-git-tracked)
- fail_closed: PASS (8/8)
- network_access: 0
- known_escape_detection: 15/15
- boundary_scenarios_9_1: 12/12 (junction: pure-string probes only; real resolution NOT_RUN)
- s01_s25: 25/25 (S12 NOT_RUN real resolution; S23 via unit test + missing-target mechanism)
- pytest: 323 passed, 6 skipped in 10.35s
- cargo_test: test result: ok. 39 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s; test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.08s
- compare_oracle_all: exit 0, 5 parities 100%

## Decisions recorded by this gate

- **SPEC-01** (coordinator ruling, carried): Claude `@` import maximum depth is 4 hops per the official doc; S13 = depth 4 PASS, S14 = depth 5 BLOCK. The resolver fixture `claude-import-depth4` is BLOCK as a whole because it also contains `@missing.md` (a MISSING edge); the 4-hop chain itself is allowed.
- **SPEC-02** (contract default): `block_repo_untracked=false` -> untracked in-repo sources are WARN; the BLOCK variant is covered by `s0-git-untracked-block` with an explicit policy.
- **SPEC-04** (T007 determination): `considered_but_not_applicable` stays inside the DiscoveryReport (production `report.not_applicable`) and the Oracle explain sidecar; it does NOT enter the receipt -- the frozen receipt schema has no slot for it and no new enum value is invented. S16 (`copilot-applyto-nomatch`) is asserted by comparing the not-applicable lists, not by receipt sources.
- **C-05** (coordinator ruling, carried): the import-approval root is repo + cwd + home + additional-dirs, as implemented.
- **C-06 / FIX-C06** (carried): precedence detail strings follow the frozen contract verbatim on both sides.
- **Copilot custom-dirs outside the repo** (`copilot-custom-dirs`, `copilot-custom-dir`): the trust classifier has no custom-directory root, so files under `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` outside the repo are OUTSIDE_REPO / BLOCK. Production and Oracle agree; this is recorded as known behaviour for the coordinator / T008, not an S0 defect -- the gate asserts parity and the contract-derived classification, it does not redesign the classifier.
- **S12 / junction**: `fs/windows` pure-string probes ran and passed; real junction resolution is NOT_RUN on Linux (T011, Windows runner). Not faked as a pass.
- **S23 / git deleted file**: covered by the unit test `test_deleted_tracked_file` (05_tests/unit/test_git.py) plus the missing-target mechanism in `s0-git-missing-import`.

## Evidence files

- `review/S0_LOG.txt` — full gate run log
- `review/S0_ORACLE_SUMMARY.json` — per-case parity table
- `review/S0_RECEIPT_HASHES.txt` — 100 production + 100 Oracle receipt hashes (codex-basic) + 25 + 25 (s0-git-tracked)
- `review/S0_FIXTURE_MANIFEST.json` — 60 fixtures with layer, scenario mapping, source/edge counts, tree hash, git HEAD
- `01_s0/expected/` — unified expected index (60 files)
- `01_s0/fixtures/s0/` — 12 new fixtures + generator
