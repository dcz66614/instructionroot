# P028 FIX-S0-TREEHASH — Task Result

Date: 2026-11-18 (GMT). Work dir: `~/workspace/p028-instructionroot/` (git HEAD `5ae5b61`).
One change only, in `scripts/s0_gate.py`, function `_tree_hash`.

## 1. Defect (as confirmed by the coordinator)

Two consecutive S0 gate runs produced different `fixture_tree_sha256` values on
12/12 s0 fixtures while all 12 `git_head` values were stable. Root cause: the
skip rule in `_tree_hash` only excluded a top-level `.git`
(`rel == ".git" or rel.startswith(".git/")`), so nested `repo/.git/index` —
which embeds filesystem stat data (mtime/ctime/inode) that changes on every
fixture regeneration — was hashed. No content changed; only the index stat
bytes moved.

## 2. Exact code change (`scripts/s0_gate.py`, `_tree_hash`, ~line 969)

Before:

```python
        rel = path.relative_to(case_dir).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
```

After:

```python
        rel = path.relative_to(case_dir).as_posix()
        if ".git" in path.relative_to(case_dir).parts:
            continue
```

Any file whose relative path contains a `.git` component at any depth is now
skipped. All other hashing is unchanged: sorted walk, per-file sha256,
`rel:hash` lines fed to the digest. No other function, threshold, expected
value, gate assertion, or output format was touched. `02_src/`, `03_oracle/`,
`01_s0/expected/`, the frozen contract, and fixture content were not touched.

## 3. Gate runs (two consecutive, `.venv/bin/python scripts/s0_gate.py`)

Both runs exited 0 with the exact block:

```
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

## 4. Two-run manifest comparison (`review/S0_FIXTURE_MANIFEST.json`)

The manifest was copied aside between the two runs
(`/tmp/fix-s0-treehash/manifest_run1.json`, `manifest_run2.json`).

- `fixture_tree_sha256`: **60/60 identical** between runs (0 mismatches).
- `git_head`: **60/60 identical** between runs (12 non-null, 48 null).
- Whole file: **byte-identical** — SHA-256
  `7e7feed9779a265de1135bcddedb499984f444aeba40dcb30b2137319c0bbc48`
  for both runs.
- Timestamp fields: **none** — a scan of the manifest for
  time/date/stamp/generated/created keys found no timestamp field, so there
  is nothing timestamp-like that differs.

The defect is fixed: the 12 s0 fixtures that previously differed on every
re-run are now stable.

## 5. Nested HEAD check (regenerated repos vs manifest `git_head`)

`git -C 01_s0/fixtures/s0/<case>/repo rev-parse HEAD` compared byte-identical
against the manifest value for all 12 nested repos: **12/12**.

| case_id | git_head |
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

## 6. Full verification (independent re-runs after the two gate runs)

- pytest: **239 passed, 2 skipped** (1.56 s) — as expected.
- cargo test: **26 passed** (lib/bin suite) + **5 passed** (second suite),
  0 failed — as expected.
- `compare_oracle.py --all`: source/trust/edge/verdict/hash parity
  **100.0% × 5**, fs_parity **100.0%**, git_scenarios **PASS**;
  resolver_cases=20, imports_cases=16, fs_cases=12, fs_probes=25 — as expected.
- (The two gate runs themselves also ran all three internally with the same
  numbers: pytest 239 passed / 2 skipped, cargo 26 + 5, compare_oracle 5×100%.)

## 7. Working-tree scope check (`git status --short`)

Tracked modifications are only the pre-existing `.gitignore` (FIX-S0-SETUP)
and `review/COORDINATOR_LOG.md` (pre-existing modified). `scripts/s0_gate.py`
is untracked in this repo state (as are the other S0 work products:
`01_s0/expected/`, `01_s0/fixtures/s0/`, `review/S0_*.json/md/txt`,
`review/tasks/P028-T007*/`, `scripts/build_s0_expected.py`) — that untracked
state predates this task; this task's only file edit is the two-line change
in `scripts/s0_gate.py` above. No changes exist outside `scripts/s0_gate.py`
and the `review/` outputs.

## Conclusion

FIX-S0-TREEHASH complete. The S0 manifest's `fixture_tree_sha256` is now
stable across gate re-runs (60/60, whole file byte-identical), nested HEADs
still verify 12/12, and the full gate + pytest + cargo + oracle verification
passes with the expected numbers.
