# P028-T008 — CLI / Policy / Exit Codes — TASK_RESULT

- TASK_ID: P028-T008
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-18
- Baseline: HEAD 633d6f6 (T007 S0 PASS commit); S0 gate re-run by this task: **RESULT=PASS** (see §7).
- **RESULT: SUCCESS — CLI complete, all acceptance commands pass, full suite green.**

## Verdict block

```text
pytest:            267 passed, 2 skipped (was 239 + 2 at S0; +28 new CLI tests)
cargo test:        26 passed + 5 passed (unchanged)
compare_oracle:    exit 0, source/trust/edge/verdict/hash parity 100%,
                   fs_parity 100%, git_scenarios PASS
s0_gate.py:        RESULT=PASS (fixtures=60, parity 100%, determinism 100/100,
                   fail_closed PASS, network_access=0, human_labels=0)
verify demo:       PASS, exit 0, receipt_hash efd5e4a0… (payments CWD, synthetic home)
verify demo-block: BLOCK, exit 20, receipt_hash aeb13c64… (symlink escape)
oracle parity:     PARITY on both demo fixtures (5/5 buckets, identical hashes)
malformed input:   exit 30 (missing CWD, bad policy JSON, unknown/non-bool policy field)
unknown harness:   exit 40 (unknown id, unknown profile version)
```

## 1. What was built

The CLI is a thin shell over the frozen production modules — it
**reuses** the resolver / trust / import / receipt machinery and
adds no resolution semantics of its own:

- `02_src/instructionroot/cli.py` (new, ~700 lines) — argparse CLI,
  receipt assembly (`build_receipt_for`, mirroring
  `scripts/compare_oracle.py::build_production_receipt` exactly:
  same import-escape trust override, same git/trust calls), policy
  loading, four formatters, Oracle runner.
- `02_src/instructionroot/__main__.py` (new) —
  `PYTHONPATH=02_src python -m instructionroot …`.
- `instructionroot` (new, executable, repo root) — launcher script
  setting `PYTHONPATH=02_src` and exec'ing the module. No install
  step, no pyproject change (packaging is T012/T013's; see §6).
- `05_tests/unit/test_cli.py` (new, 28 tests) — end-to-end through
  the launcher on synthetic tmp git repos.
- `fixtures/build_demo_fixtures.py` (new) + `fixtures/outside/AGENTS.md`
  (new, committed) — deterministic generator for the demo fixtures
  (fixed commit dates → deterministic HEADs, see §4).
- `.gitignore` — `fixtures/demo/` + `fixtures/demo-block/` ignored
  whole-dir (same embedded-repo reason as the S0 corpus, §4).

Commands (all with `--help` at top level and per subcommand):

```text
instructionroot inspect [--harness --cwd --home --repo-root --policy
                         --profile-version --working-file --strict
                         --format terminal|json|md|html --output]
instructionroot verify  [same inputs + --allow-warn]
instructionroot export  [same inputs + --format json,md,html,terminal --output]
instructionroot profile list [--format terminal|json]
instructionroot oracle  [same inputs as inspect]
instructionroot version
```

Formats: `terminal` (PROJECT_BOOK.md §7.1/§19.2 shape, home redacted
as `<HOME>` for display only — the receipt hash always uses the
unredacted canonical path), `json` (the receipt dict, pretty-printed,
sorted keys), `md` (Markdown report), `html` (standalone static HTML,
no external references).

Policy: `--policy FILE` loads a JSON object with the 13 frozen
`policy_schema.json` v1 fields (flat, or wrapped as
`{"values": {...}}` / `{"policy": {...}}`); omitted fields take the
frozen defaults. Unknown fields or non-bool values → INPUT_ERROR
(exit 30) via `receipt.validate_policy`, before any discovery runs.
`--strict` sets `treat_warn_as_block=true` on top.

Exit codes (PROJECT_BOOK.md §8.8 / receipt_schema.json):
PASS 0, WARN 10, BLOCK 20, INPUT_ERROR 30, UNSUPPORTED_PROFILE 40,
INTERNAL_ERROR 50. `verify` exits with the verdict's code
(`--allow-warn` makes WARN exit 0). `inspect` / `export` /
`profile list` / `oracle` exit 0 whenever they produce their output,
whatever the verdict — they report, only `verify` gates (see §5,
decision D1). All error paths exit non-zero and never emit a PASS.

`oracle` builds the release Oracle binary with
`cargo build --release --locked` when it is missing, runs
`oracle resolve <case.json> --explain …` on the same harness / CWD /
home / merged-policy input (env passthrough of the three discovery
vars only), and reports per-bucket parity (sources, trust, edges,
verdict, receipt_hash). A mismatch is INTERNAL_ERROR (50). The
full-corpus check stays with `scripts/compare_oracle.py --all`.

`export` default output is `<cwd>/.instructionroot/receipt.<ext>`
(the PROJECT_BOOK.md §7.1 receipt location). `--output` naming an
existing directory writes `receipt.<ext>` inside it; otherwise it is
a file stem (single format = exact path).

No production resolver / trust / import / receipt semantics were
changed. No files under `00_contract/`, `01_s0/expected/`,
`01_s0/fixtures/s0/` were touched, and the S0 gate script's
assertions were not modified. No network, no LLM, no instruction
content is ever printed (paths, hashes, Git state, trust, rule ids
only). Zero real humans, synthetic data only.

## 2. Acceptance commands (run live, this task)

All from the work directory (`~/workspace/p028-instructionroot`).
Full log: `review/tasks/P028-T008/command-log.txt`.

| Command | Result |
|---|---|
| `./instructionroot --help` | exit 0; lists all 6 subcommands |
| `./instructionroot profile list` | exit 0; codex `codex-2026-11`, claude-code `claude-code-2026-11`, copilot-cli `copilot-cli-2026-11`, with source URLs + rules_hashes |
| `./instructionroot version` | exit 0; `instructionroot 1.0.0`, python 3.12.3, 3 profile versions, `instructionroot-oracle 0.1.0` |
| `./instructionroot verify --harness codex --cwd fixtures/demo` (spec command, real home) | **PASS, exit 0**; 1 source (repo-root AGENTS.md, GIT_TRACKED); receipt_hash `93b9bf33…` |
| `./instructionroot verify --harness codex --cwd fixtures/demo/services/payments --home fixtures/demo/home` | **PASS, exit 0**; 4 sources (user + repo-chain ×3, all GIT_TRACKED); receipt_hash `efd5e4a0…` |
| `./instructionroot inspect … --format json` (same CWD/home) | exit 0; receipt parses, `verify_receipt()` true, hash recomputes identically |
| `./instructionroot verify --harness codex --cwd fixtures/demo-block/services/payments --home fixtures/demo-block/home` | **BLOCK, exit 20**; `SYMLINK_ESCAPE` on `services/payments/AGENTS.md`; receipt_hash `aeb13c64…` |
| `./instructionroot oracle --harness codex --cwd fixtures/demo/services/payments --home fixtures/demo/home` | exit 0; **RESULT: PARITY**; identical receipt_hash `efd5e4a0…`; production verdict PASS / oracle PASS |
| `./instructionroot oracle … --cwd fixtures/demo-block/services/payments …` | exit 0; **RESULT: PARITY**; identical receipt_hash `aeb13c64…`; BLOCK / BLOCK |
| `./instructionroot export … --format json,md,html` (demo) | exit 0; wrote `.instructionroot/receipt.{json,md,html}` (removed after check to keep the fixture clean) |
| WARN case (tmp repo, untracked nested AGENTS.md, default policy) | **WARN, exit 10**; `--allow-warn` → exit 0; `--strict` → exit 20; policy `{"block_repo_untracked": true}` → exit 20 |
| Claude import escape (tmp repo, `CLAUDE.md` `@../outside/shared.md`) | **BLOCK, exit 20** |
| `./instructionroot verify --harness bogus …` | **exit 40**, stderr `UNSUPPORTED_PROFILE: unknown harness: 'bogus'`, no PASS on stdout |
| `--profile-version codex-1999-01` | **exit 40** `UNSUPPORTED_PROFILE` |
| `--cwd /nonexistent-xyz` | **exit 30** `INPUT_ERROR` |
| policy `{"block_repo_untracked": "yes"}` (non-bool) | **exit 30** `INPUT_ERROR: policy field … must be a bool` |
| policy `{"unknown_field_xyz": true}` | **exit 30** `INPUT_ERROR: unknown policy field(s)` |
| policy `{not json` / `[]` / missing file | **exit 30** `INPUT_ERROR` |
| `--help` on `verify`, `inspect`, `export`, `oracle`, `profile list` | exit 0 each |

## 3. Verification (run live, this task)

- Full pytest: **267 passed, 2 skipped in 6.10s**
  (`.venv/bin/python -m pytest 05_tests/ -q`; 239 pre-existing + 28 new CLI tests).
- Cargo test: **26 passed + 5 passed, 0 failed**
  (`cargo test --manifest-path 03_oracle/rust/Cargo.toml`).
- `compare_oracle.py --all`: **exit 0** —
  `resolver_cases=20 imports_cases=16 fs_cases=12 fs_probes=25`;
  `source_parity=100.0% trust_parity=100.0% edge_parity=100.0%
  verdict_parity=100.0% hash_parity=100.0%`; `fs_parity=100.0%
  git_scenarios=PASS`.
- `scripts/s0_gate.py`: **RESULT=PASS** (exit 0) — fixtures=60,
  production_oracle_parity=100%, receipt_hash_parity=100%,
  determinism=100/100, fail_closed=PASS, network_access=0,
  human_labels=0. The gate regenerated its own evidence files
  (`review/S0_GATE.md`, `S0_LOG.txt`, `S0_ORACLE_SUMMARY.json`);
  the only material change is the pytest count 239 → 267.
  `review/COORDINATOR_LOG.md` was also modified during this window
  by the coordinator (07:19 GMT entry, not by this task); left as-is.
- Determinism: `inspect --format json` twice on the demo → identical
  `receipt_hash` (also covered by `test_inspect_deterministic_hash`).

## 4. Demo fixtures

`fixtures/demo/` (PASS) and `fixtures/demo-block/` (BLOCK) are real
git repos (verify needs real Git state), so they hit the same
embedded-repo problem as the S0 corpus (FIX-S0-SETUP): `git add`
would store only empty gitlinks. Fix, same as S0: the dirs are
git-ignored whole-dir and `fixtures/build_demo_fixtures.py`
rebuilds them deterministically (fixed author/committer dates
`2026-11-18T07:00:00+00:00`, relative symlink for the escape).
Verified idempotent: two consecutive runs give the same HEADs —
demo `38aebc4a674005b67423373622de8af163e83787`, demo-block
`abf817656b0db836b30d43fa998844f5bb0ce520` — and the same verdicts.
`fixtures/outside/AGENTS.md` (the escape target) is a plain file
committed to the outer repo. `fixtures/windows/` embedded-repo
warnings in `git add --dry-run` belong to T011's concurrent work,
not this task; left alone.

Note: the demo home lives *inside* the demo repo, so its
`.codex/AGENTS.md` classifies GIT_TRACKED (repo-first, per the
trust classifier), not USER_SCOPE — a property of the fixture
layout, not a CLI defect. The tmp-repo CLI tests use a home
outside the repo and do show USER_SCOPE.

## 5. Spec / plan conflicts and decisions (book wins per task brief)

- **D1 — `inspect`/`export` exit code on BLOCK (plan silent, book
  §8.8 decisive).** IMPLEMENTATION_PLAN.md §13 lists commands and
  formats but no exit-code rule for `inspect`/`export`. PROJECT_BOOK.md
  §8.8 is titled "Verify Exit Codes" (FR-08) and §7.3/§8.8 describe
  `verify` as the gate ("fail on BLOCK"). Followed the book: only
  `verify` gates; `inspect`/`export`/`oracle` exit 0 on a produced
  result whatever the verdict. If the coordinator wants `inspect`
  to gate too, it is a one-line change in `cmd_inspect`.
- **D2 — Book §14.2 vs SPEC-02 (default `block_repo_untracked`).**
  The book's §14.2 example policy shows `block_repo_untracked: true`
  while §7.1's demo shows untracked as WARN. The frozen contract
  (SPEC-02, policy_schema.json) resolves this: default `false`
  (WARN). The CLI uses the contract default; the example value is
  reachable via `--policy` / `--strict`. No new decision made here.
- **D3 — Import depth 5 (book/plan) vs 4 (contract SPEC-01).**
  Carried, not re-decided: the CLI reuses `imports.py`, which
  implements the official-doc depth of 4 hops. The CLI adds no
  depth handling of its own.
- **D4 — `instructionroot` on PATH.** There is no `pyproject.toml`
  / console-script install in the repo (packaging is T012/T013).
  Delivered the repo-root `./instructionroot` launcher plus
  `python -m instructionroot`; a bare `instructionroot` on PATH
  needs T012/T013 packaging or a PATH export. Not faked as
  installed.
- **D5 — Receipt has no slot for `considered_but_not_applicable`.**
  Carried SPEC-04/T007: the list is shown in terminal/md/html as a
  clearly-marked diagnostic section ("not in the receipt"), never
  injected into the receipt JSON.

## 6. Gaps / observations (no resolver patch made — recorded, not fixed)

- **G1 — Git-state display for non-repo files.** `get_git_state`
  returns `tracked=False` for a file in no repository, which the
  first terminal draft rendered as "untracked" (wrongly implying a
  repo exists). Fixed display-side only in the CLI (`no-repo`
  label when `git.repo is None`); receipt data untouched.
- **G2 — Copilot custom-dirs outside the repo → OUTSIDE_REPO /
  BLOCK.** Carried S0 decision (coordinator ruling in S0_GATE.md):
  the trust classifier has no custom-directory root. The CLI does
  not work around it.
- **G3 — Claude's upward walk reads real ancestors.** `claude-code`
  discovery walks above the fixture CWD to the filesystem root, so
  a `CLAUDE.md`/`AGENTS.md` in a real ancestor (e.g. the user's
  home when the CWD is under it) is legitimately discovered. That
  is the profile's documented behaviour, not a CLI bug — but it
  means Claude demo runs are machine-dependent unless the CWD is
  isolated; the CLI tests use codex for determinism and pass
  `ancestor_stop` only through the internal `build_receipt_for`
  API, not a CLI flag.
- **G4 — No gap found in the resolver.** The CLI needed no resolver
  behaviour that was missing; nothing was patched in production
  modules (only two new files, `cli.py` + `__main__.py`, were added
  under `02_src/`).

## 7. Changed files

```text
02_src/instructionroot/cli.py            (new)
02_src/instructionroot/__main__.py       (new)
instructionroot                          (new, executable launcher)
05_tests/unit/test_cli.py                (new, 28 tests)
fixtures/build_demo_fixtures.py         (new)
fixtures/outside/AGENTS.md              (new, committed plain file)
.gitignore                               (fixtures/demo/, fixtures/demo-block/)
review/S0_GATE.md, review/S0_LOG.txt, review/S0_ORACLE_SUMMARY.json
                                         (regenerated by the S0 gate re-run;
                                          only pytest count 239 -> 267)
review/tasks/P028-T008/TASK_RESULT.md    (this file)
review/tasks/P028-T008/command-log.txt   (final verification log)
review/tasks/P028-T008/test-summary.json
review/tasks/P028-T008/changed-files.txt
```

Forbidden paths untouched: `00_contract/` (frozen), `01_s0/expected/`,
`01_s0/fixtures/s0/` (S0 corpus), `scripts/s0_gate.py` assertions.
No GitHub upload, no external messages. No commit made by this task
(commit is the coordinator's call; the working tree contains only
the files above plus T011's concurrent `fixtures/windows/*` and
`scripts/run_windows_corpus.py`).
