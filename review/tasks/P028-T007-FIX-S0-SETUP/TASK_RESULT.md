# P028 FIX-S0-SETUP — Task Result

Date: 2026-11-18. Work dir: `~/workspace/p028-instructionroot/` (HEAD 5ae5b61).
Goal: make the S0 gate reproducible from a fresh checkout (nested fixture
git repos cannot be stored in git).

## What changed (two files only)

1. **`.gitignore`** — added one pattern (plus comment):
   `01_s0/fixtures/s0/*/repo/`
2. **`scripts/s0_gate.py`** — new setup step 0 `regenerate_s0_fixtures()`,
   called at the very start of `main()` before section 1 corpus inventory.
   It runs `01_s0/fixtures/s0/build_s0_fixtures.py` via subprocess with
   `sys.executable` (the repo venv python when invoked as
   `.venv/bin/python scripts/s0_gate.py`), unconditionally. On a non-zero
   generator exit (or a missing generator file) it raises `GateFailure`,
   so the gate writes `RESULT=FAIL` and exits non-zero — it never runs on
   stale/missing fixtures. No gate assertion, threshold, expected value,
   or output format was changed (only the module docstring gained a
   section-0 line).

Nothing else was touched: `02_src/`, `03_oracle/`, `01_s0/expected/`,
the frozen contract, and all fixture content/expected values are
untouched. (`review/COORDINATOR_LOG.md` shows as modified in
`git status`, but that modification predates this task — it was already
`M` before any change here.)

## Why the pattern is `.../repo/`, not `.../repo/.git`

The literal `01_s0/fixtures/s0/*/repo/.git` pattern was tried first:
`git check-ignore` matched 12/12, but `git add --dry-run
01_s0/fixtures/s0/` still emitted 12 `warning: adding embedded git
repository` lines. Verified in a scratch repo that git 2.43 treats any
directory containing a `.git` dir as an embedded repo (gitlink)
regardless of `.git` ignore rules (patterns `.../.git`, `.../.git/`,
`.../.git/*`, `.../.git/**` all still warn). Ignoring the whole `repo/`
dir is the only ignore-based fix. It still matches all 12 `.../repo/.git`
paths on `git check-ignore` (via the ignored parent dir), and the
generator rebuilds `repo/` working-tree files deterministically, so
nothing is lost. The `.gitignore` comment records this reasoning.

## Git-ignore check (after the change)

- `git check-ignore -v` on each of the 12 `01_s0/fixtures/s0/*/repo/.git`
  paths: **12/12 ignored** (`.gitignore:18:01_s0/fixtures/s0/*/repo/`).
- `git add --dry-run 01_s0/fixtures/s0/`: **zero** `embedded`/`gitlink`
  lines (previously 12 warnings). Only real files are listed
  (generator, `manifest.json`, `case.json`, `home/`, `outside/`).
- `git status --ignored --short 01_s0/fixtures/s0/`: **12 `!!` entries**,
  one `repo/` dir per case; plain `git status --short` shows no
  untracked/gitlink entries for the 12 `.git` dirs
  (`?? 01_s0/fixtures/s0/` is the untracked fixture tree itself).

## Fresh-checkout simulation

Deleted all 12 nested `.git` dirs (`rm -rf
01_s0/fixtures/s0/*/repo/.git`, 0 remaining), then ran
`.venv/bin/python scripts/s0_gate.py` — **exit 0** with the exact block:

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

The gate log starts with `== 0. fixture setup: regenerate S0 fixtures ==`
followed by `s0 cases=12`.

## HEAD comparison (vs pre-run `review/S0_FIXTURE_MANIFEST.json`)

All 12 nested HEADs are byte-identical after regeneration — **0/12
mismatches**:

| case | HEAD |
|---|---|
| s0-case-sensitive | bc966c84355bf4479b31c952bdd7dcfc5d48558b |
| s0-downloads-import | 40d13ab004ccf1a087fb9e4417174f60db9551dc |
| s0-git-missing-import | e7d03d7447f568a272d6ef19baa96eb9adf6dd6d |
| s0-git-modified | 557a7bfb71f5942a3736fd4564fd1695a3de4bb4 |
| s0-git-modified-block | 834d8f36f2794691dbf695755ce0526b213f693c |
| s0-git-rename | b049e5ad05c2a1c5815658ad66d549fdd10b2f7a |
| s0-git-staged-new | d97eab82fafaffa9a5f7f59c4d8f7e7d29d1e462 |
| s0-git-symlink-escape | 9aed0a9fb5be578725a24b4e57b2731291a4158c |
| s0-git-symlink-inside | 2c8f3914af2f0f7d9ba5bd6c34057258790e5d2b |
| s0-git-tracked | 810474a999c0af35dd3b4b3392c2f1f749df5b87 |
| s0-git-unicode | d0b7e8b891bfafaa51dc55a3318863bab9d8005c |
| s0-git-untracked-block | d5693e9bc6d1348d614363ae551eebfe16ba0d37 |

The manifest was NOT edited to match — the gate rewrote it itself, and
its HEADs match the pre-run baseline. A final gate re-run (clean state)
also exited 0 with the same verdict block, and the manifest it wrote is
self-consistent (recomputed tree hashes match it 12/12, HEADs match
baseline 12/12).

## Tree-hash caveat (found during verification, needs coordinator awareness)

The manifest's `fixture_tree_sha256` values for the 12 s0 cases do NOT
match the pre-run manifest — but this is a property of the manifest's
hash definition, not a fixture-content change:

- The gate's `_tree_hash` only skips a top-level `.git`; it **includes**
  `repo/.git/**` contents.
- Across two consecutive generator runs, non-`.git` fixture bytes are
  identical in **0/12** changed cases, while `repo/.git/index` changes
  in **12/12** (the git index embeds filesystem stat data —
  mtime/ctime/inode — so it differs on every rebuild despite fixed
  commit dates). Object files and reflog are stable; only `index` moves.
- Consequence: `_tree_hash` changes on **every** regeneration, so no
  regenerated tree can ever reproduce the recorded tree hashes. HEADs
  (12/12 identical) plus the gate PASS are the stable identity proof.
- No action taken here (out of scope: changing `_tree_hash` would alter
  gate output semantics). Follow-up option for the coordinator: exclude
  nested `repo/.git` from `_tree_hash` if stable tree hashes are wanted.

## Full verification numbers (independent re-runs, after the fix)

- pytest: **239 passed, 2 skipped** (`05_tests/ -q`, 1.30s)
- cargo test: **26 passed** + **5 passed** (0 failed)
- `compare_oracle.py --all`: resolver 20, imports 16, fs 12, fs probes 25;
  source/trust/edge/verdict/hash parity **100.0% x5**; fs parity
  **100.0%**; git_scenarios **PASS**
- S0 gate (from deleted `.git` state): **exit 0, RESULT=PASS**
  (block quoted above); final clean-state re-run: same, exit 0.
