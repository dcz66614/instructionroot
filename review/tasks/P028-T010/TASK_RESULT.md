# P028-T010 — GitHub Action / Pre-commit — TASK_RESULT

- TASK_ID: P028-T010
- PROJECT_ID: P028 InstructionRoot Resolve
- Date: 2026-11-18
- Baseline: HEAD 6ac1738 (T008 CLI commit); S0 gate re-run by this task: **RESULT=PASS** (see §7 — with one caveat about a parallel task's file, §7.2).
- **RESULT: SUCCESS — Action + pre-commit hook authored; CI simulation PASS 2/2 (PASS exit 0, BLOCK exit 20); full suite green.**

## Verdict block

```text
simulate_ci.py:    config validation OK (YAML parses, uses: pinned 40-char SHA,
                   permissions contents: read only, pre-commit -> run-verify.sh)
                   case PASS  expected_exit=0  actual_exit=0  -> OK
                   case BLOCK expected_exit=20 actual_exit=20 -> OK
                   SIMULATION: PASS (2/2 cases), script exit 0
pytest:            283 passed, 6 skipped (was 267 + 2 at T008; +16 tests are
                   the parallel T011 windows-corpus tests, not this task's)
cargo test:        26 passed + 5 passed (unchanged from T008)
compare_oracle:    exit 0, source/trust/edge/verdict/hash parity 100%,
                   fs_parity 100%, git_scenarios PASS
s0_gate.py:        RESULT=PASS (fixtures=60, parity 100%, determinism 100/100,
                   fail_closed PASS, network_access=0, human_labels=0)
                   — in the real tree with the parallel T012 file held aside
                   (§7.2); with it present the gate fails on that file alone.
verify demo:       PASS, exit 0 (payments CWD, synthetic home)
verify demo-block: BLOCK, exit 20 (symlink escape)
malformed config:  exit 30 (fail-closed); missing config file: exit 0 (defaults)
```

## 1. What was built

Single shared entry point, so the Action and the pre-commit hook can never
drift apart — both run the same command:

```text
./scripts/run-verify.sh
  → $ROOT/instructionroot verify --harness <harness> --cwd <cwd>
      [--home <home>] [--policy <policy>] [--allow-warn]
```

New files (6):

| File | Purpose |
|---|---|
| `.github/workflows/instructionroot.yml` | The Action (name `instructionroot`) |
| `scripts/run-verify.sh` | Shared verify entry point (Action + hook) |
| `.instructionroot.json` | Repo config file (harness/cwd/allow_warn) |
| `.pre-commit-hooks.yaml` | Pre-commit hook definition |
| `.pre-commit-config.yaml` | Local self-check example (see §5) |
| `scripts/simulate_ci.py` | Local CI simulation + config validation |

No changes to `00_contract/`, `01_s0/expected/`, `01_s0/fixtures/s0/`,
`scripts/s0_gate.py`, or any production semantics. No GitHub upload, no
push, no external message (per task scope).

## 2. Workflow design

`.github/workflows/instructionroot.yml`:

- Triggers: `push` (branch `main`), `pull_request`, `workflow_dispatch`.
- `workflow_dispatch` inputs: `harness` (choice: `codex` / `claude-code` /
  `copilot-cli`, default `codex`) and `cwd` (string, default `.`). On
  push/PR the inputs are empty and the repo config file (or the
  `codex` / `.` defaults) applies.
- `permissions: contents: read` — the only permission; checkout runs with
  `persist-credentials: false`.
- Steps: (1) pinned `actions/checkout`; (2) `./scripts/run-verify.sh`
  with `INSTRUCTIONROOT_HARNESS` / `INSTRUCTIONROOT_CWD` from the dispatch
  inputs. A non-zero verify exit (BLOCK 20, WARN 10, INPUT_ERROR 30,
  UNSUPPORTED_PROFILE 40, INTERNAL_ERROR 50) fails the job — fail on BLOCK
  is the plan requirement; WARN also fails unless the repo config sets
  `"allow_warn": true` (book §8.8: "WARN 可配置").
- Runs from a plain checkout: the runner's system `python3` + the repo's
  own stdlib-only `./instructionroot` launcher. No `setup-python`, no
  `pip install`, no third-party tool install, no network fetch beyond the
  pinned checkout action itself. No artifact upload step exists, so no
  instruction contents leave the runner (book §18).

### Pin list

| `uses:` | Pinned SHA | Release |
|---|---|---|
| `actions/checkout` | `11bd71901bbe5b1630ceea73d27597364c9af683` | v4.2.2 |

- Only one `uses:` line exists in the workflow; it is pinned to a full
  40-char SHA (verified in `simulate_ci.py` by regex, and confirmed
  against the v4.2.1…v4.2.2 compare link / release notes via web search).
- No floating tags anywhere in the workflow.

### Harness configuration mechanism

Resolution order in `scripts/run-verify.sh` (first set wins):

1. Environment: `INSTRUCTIONROOT_HARNESS` / `_CWD` / `_HOME` / `_POLICY` /
   `_ALLOW_WARN` (empty values ignored) — this is how the workflow injects
   `workflow_dispatch` inputs.
2. Repo config file `.instructionroot.json` — in the caller's working
   directory if present there, else next to the script's repository root.
   Keys: `harness`, `cwd`, `home`, `policy`, `allow_warn`.
3. Defaults: `harness=codex`, `cwd=.`.

The default repo config (`.instructionroot.json`):

```json
{"version": 1, "harness": "codex", "cwd": ".", "allow_warn": false}
```

Config parsing is stdlib-`json` only; a malformed config fails closed
(exit 30, verified live). A missing config file falls back to defaults
(exit 0 on this repo). Unknown harness / bad policy are rejected by the
CLI itself (exits 40 / 30) — the script adds no validation of its own.

## 3. Pre-commit

`.pre-commit-hooks.yaml` — one hook:

```yaml
- id: instructionroot-verify
  name: instructionroot verify
  entry: scripts/run-verify.sh
  language: script
  pass_filenames: false
  always_run: true
```

`pass_filenames: false` + `always_run: true` because `verify` gates a
working directory, not individual changed files. It runs the identical
`scripts/run-verify.sh` as the Action, so the fail-on-BLOCK behavior
(and WARN handling) is the same.

`.pre-commit-config.yaml` is a `repo: local` self-check example so this
repository can run its own hook on itself. The book does **not** specify
a pre-commit config example (see §6); this file is provided as a local
example only, not as a book requirement.

## 4. CI simulation (`scripts/simulate_ci.py`)

Reproduces exactly the steps the workflow runs:

1. **Checkout-equivalent**: `git archive HEAD` into a temp dir (tracked
   files only, as `actions/checkout` would deliver) + an explicit overlay
   of the not-yet-committed T010 files (in real CI they would be
   committed; the overlay list is explicit so the simulation cannot
   silently depend on any other working-tree file).
2. **Verify step**: `./scripts/run-verify.sh` with the same environment
   the workflow sets (`INSTRUCTIONROOT_HARNESS=codex`,
   `INSTRUCTIONROOT_CWD=<synthetic repo>/services/payments`,
   plus `INSTRUCTIONROOT_HOME=<synthetic repo>/home` for the synthetic
   home — the workflow itself does not set HOME; the simulation does so
   the synthetic fixture, not the runner's real home, is the user scope).

Cases (T008 synthetic demo fixtures, placeholder text only):

- **PASS** — `fixtures/demo`, CWD `services/payments`: expected exit 0,
  actual exit 0, `VERDICT: PASS` found. Receipt hash in the temp copy:
  `ce7737a9…` (differs from the in-place run `efd5e4a0…` only because the
  receipt embeds absolute temp paths — expected, not a determinism break).
- **BLOCK** — `fixtures/demo-block`, CWD `services/payments` (symlink
  `services/payments/AGENTS.md -> ../../../outside/AGENTS.md`, copied
  with the sibling `fixtures/outside/` so the relative escape resolves):
  expected exit 20, actual exit 20, `VERDICT: BLOCK` found.

The script also validates the config before simulating: workflow YAML
parses (PyYAML 6.0.1), every `uses:` pinned to a 40-char SHA,
permissions exactly `{contents: read}`, and the workflow's only `run:`
step is `./scripts/run-verify.sh` (allowlist — no step can install,
fetch or upload anything). The pre-commit YAML parses and its entry
references the same `run-verify.sh`, which in turn invokes
`./instructionroot verify`. Final run: `SIMULATION: PASS (2/2 cases)`,
script exit 0.

## 5. Book-vs-plan check

- **No book-vs-plan conflict found.** Plan §15 is thin (name, command,
  5 security requirements, PASS/BLOCK synthetic acceptance); the book
  adds the CI flow (§7.3: PASS → continue, FAIL → block), the exit-code
  table (§8.8, incl. "WARN 可配置"), and the config-file shape (§14.2).
  All three were followed.
- **Two judgement calls recorded (book silent / ambiguous):**
  1. The book does not specify *how* the harness is configured for CI.
     Chosen: `workflow_dispatch` inputs override a repo config file
     `.instructionroot.json`, which overrides defaults. (Plan §15 only
     says "harness `<configured>`".)
  2. Book §14.2 shows a config with an **inline** `policy` object, but
     the T008 CLI's `--policy` takes a policy JSON **file**. This task's
     config therefore treats `policy` as a *path* to a policy file, not
     an inline object. No inline-policy support was added; the CLI
     contract was not changed.
  3. The book does not specify a `.pre-commit-config.yaml`; the file
     added is a local self-check example, not presented as a book
     requirement.

## 6. Gaps / limitations

1. **Not run on real GitHub Actions.** The workflow was validated
   locally only (YAML parse, pin check, and the `simulate_ci.py`
   checkout-equivalent). A real Actions run needs the repo on GitHub,
   which is a later step arranged by the coordinator. Risk is low: the
   workflow has exactly two steps and the second is the locally
   simulated script.
2. **Runner Python is assumed.** The workflow uses the `ubuntu-latest`
   runner's system `python3` (3.12 on current images) and `git`; no
   `setup-python` step was added deliberately (keeps the pin list to one
   action and avoids any install). If a future runner image drops
   `python3`, the job fails loudly at the verify step rather than
   silently passing.
3. **Pre-commit itself was not executed** (`pre-commit` is not installed
   in this VM and installing it is out of scope). The hook config was
   validated structurally (YAML parses, entry points at the same script,
   `language: script`, `pass_filenames: false`); the script it calls
   was executed directly in both cases.
4. **WARN fails CI by default.** This follows the CLI default and the
   fail-closed stance; repos that want WARN to pass must set
   `"allow_warn": true` in `.instructionroot.json`.

## 7. Regression evidence

| Check | Result |
|---|---|
| `python3 scripts/simulate_ci.py` | SIMULATION PASS 2/2, exit 0 (final run; also run twice before with same result) |
| `.venv/bin/pytest -q` | **283 passed, 6 skipped** in ~7.6s |
| `cargo test --manifest-path 03_oracle/rust/Cargo.toml` | 26 passed + 5 passed (cargo at `~/.cargo/bin`, not on default PATH) |
| `python3 scripts/compare_oracle.py --all` | exit 0; source/trust/edge/verdict/hash parity 100%, fs_parity 100%, git_scenarios PASS |
| `python3 scripts/run_golden.py --stage imports` (real tree) | 16/16, edge parity 100% |
| `python3 scripts/run_golden.py --stage resolver` (real tree) | 20/20, source order/set 100% |
| `python3 scripts/s0_gate.py` (with `.venv/bin` on PATH) | **RESULT=PASS** — fixtures=60, parity 100%, determinism 100/100, fail_closed PASS, network_access=0, human_labels=0 |
| `scripts/run-verify.sh` (repo root, defaults) | PASS, exit 0 |
| `INSTRUCTIONROOT_HARNESS=claude-code ... run-verify.sh` | PASS, exit 0 (env override works) |
| Malformed `.instructionroot.json` (`{"harness": 123}`) | exit 30, fail-closed |
| Missing config file | exit 0 (defaults apply) |

### 7.1 My own first gate run caught a real defect in my files

The first `s0_gate.py` re-run failed with 2 network-token hits in my own
`scripts/simulate_ci.py`: its denylist literally contained the words
`curl` / `wget`, which the gate's static grep (`scripts/*.py`) flags.
Fixed by replacing the denylist with an allowlist (the workflow's only
`run:` step must be exactly `./scripts/run-verify.sh`) and rewording the
workflow comment. No network-tool names now appear in any T010 file
(verified by grep against the gate's token list).

### 7.2 The full-tree gate currently fails — on a parallel task's file, not this task's

With all working-tree files present, `s0_gate.py` fails with 12
network-token hits, **all** in `scripts/security_static_check.py`
(the T012 static checker, created by a parallel agent while this task
ran; it legitimately lists the same tokens it greps for — the same
self-reference problem the gate itself exempts only its own file from).
To prove attribution, the gate was re-run in the real tree with that
one file temporarily moved aside (SHA-256 verified before and after;
file restored intact) and `.venv/bin` on PATH: **RESULT=PASS**
(see table above). A temp-copy isolation attempt was abandoned as
evidence because the copy lost nested `.git` dirs and failed the
imports golden stage 15/16 — an artifact of the copy, since the same
stage passes 16/16 in the real tree. **Follow-up for the coordinator:
T012's `security_static_check.py` needs the same treatment as the
gate's own token list (exemption or token-free spelling), or the S0
gate will keep failing while that file exists.** This task did not
modify that file.

Note: the gate must be run with `.venv/bin` on PATH — with system
`python3` it fails at `No module named pytest` (pytest lives in the
venv). That is an environment quirk, not a T010 issue.

### 7.3 Pre-existing / parallel-work files (not mine, not touched)

- `.gitignore` and `review/COORDINATOR_LOG.md` were already modified
  before this task started (the `.gitignore` diff is T011's
  `fixtures/windows/*/repo/` rule).
- `review/S0_GATE.md`, `review/S0_LOG.txt`,
  `review/S0_ORACLE_SUMMARY.json` were regenerated by this task's gate
  re-runs (pytest 267→283, tmp-path churn in the oracle summary) — the
  normal gate output, same as T008 did.
- Untracked parallel-work files present throughout: `web/`,
  `fixtures/windows/`, `scripts/run_windows_corpus.py`,
  `05_tests/unit/test_windows_corpus.py`,
  `review/tasks/P028-T009/`, `review/tasks/P028-T011/`,
  `scripts/security_static_check.py`.

## 8. Changed files (this task)

```text
.github/workflows/instructionroot.yml   (new)
.instructionroot.json                   (new)
.pre-commit-hooks.yaml                  (new)
.pre-commit-config.yaml                 (new)
scripts/run-verify.sh                   (new, executable)
scripts/simulate_ci.py                  (new, executable)
review/tasks/P028-T010/TASK_RESULT.md   (new, this file)
review/tasks/P028-T010/changed-files.txt
review/tasks/P028-T010/command-log.txt
review/tasks/P028-T010/test-summary.json
review/S0_GATE.md, review/S0_LOG.txt, review/S0_ORACLE_SUMMARY.json
                                        (regenerated by gate re-runs)
```
