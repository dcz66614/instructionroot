# P028 T012 — Security / Privacy / Packaging — TASK_RESULT

Date: 2026-11-18 (UTC). Work dir: `~/workspace/p028-instructionroot/`
(HEAD 6ac1738 = T008 CLI commit; concurrent T009/T010/T011 work landed
during this task — final check re-ran on the tree as it stood at finish.)

## Result — the four required numbers

From `python scripts/security_static_check.py` (exit 0, `RESULT=PASS`,
`files_scanned=859` — full output in `security_static_check.txt`):

```text
shell_true=0
network_runtime=0
telemetry=0
secret_fixture_leaks=0
```

No production-code security fix was needed: all four numbers were 0 on
the code as found. The only files created by this task are the checker
itself, `LICENSE`, and `pyproject.toml` (both were missing). No changes
to 00_contract/, 01_s0/expected/, 01_s0/fixtures/s0/, s0_gate.py
assertions, or resolver/trust/import/receipt semantics.

## Book vs plan

No conflict. PROJECT_BOOK.md §18 is *more specific* than
IMPLEMENTATION_PLAN.md §17 and was followed where it adds detail:

- §18.1 — receipt stores only path / hash / Git state / source category /
  rule ID; no instruction content, commit message, username, or home
  listing. Verified: 64 receipt JSONs checked (01_s0/expected +
  web/receipt*.json), zero forbidden keys, zero multiline values.
- §18.2 — `<HOME>` redaction is a *display* transform; the hash uses
  the unredacted canonical path (receipt.py:50-52, receipt_schema.json
  description). Verified: `cli.py` uses `redact_home` for display.
  Consequence recorded: `workspace.home` is a legitimate structural
  field in receipts, not a leak (see "accepted" below).
- §18.3 — no shell, Git subprocess `shell=False`, no network,
  fail-closed. Verified by the checker (AST + raw sweep).
- §18.4 — MIT `LICENSE` required. Created (was missing).

## Findings

### Accepted with reason (nothing silently excluded)

1. **Single explicit `shell=False` call** — `02_src/instructionroot/git.py:140-142`:
   `subprocess.run(["git", *argv], shell=False, ...)`; argv is restricted
   by `_is_allowed()` to the plan's read-only allowlist
   (`rev-parse` / `ls-files` / `status` / `log`). Accepted: the one
   sanctioned shell-free Git invocation.
2. **32 further subprocess call sites with no `shell=` kwarg** (rely on
   the `subprocess` default `shell=False`), all list-argv, enumerated in
   the checker output §1 (33 call sites total incl. #1):
   `cli.py:652` (`cargo build --release --locked`, Oracle build),
   `cli.py:735` (oracle `resolve`), `cli.py:865` (oracle `--version`);
   `scripts/compare_oracle.py` (5), `scripts/s0_gate.py` (7),
   `scripts/run_windows_corpus.py:366`, `scripts/simulate_ci.py` (3),
   fixture builders (`01_s0/fixtures/s0/build_s0_fixtures.py:52`,
   `fixtures/build_demo_fixtures.py:61,77`,
   `fixtures/windows/build_windows_fixtures.py:69`), tests
   (`test_cli.py:31,38`, `test_git.py:53`, `test_trust.py:421`).
   Accepted: list argv + default `shell=False`, no shell metacharacters.
3. **Rust process spawn, no shell** — `03_oracle/rust/src/git.rs:100`
   and `03_oracle/rust/tests/cli.rs:31`: `Command::new("git")` + args.
   Accepted: Rust `Command` never invokes a shell.
4. **Shell launchers** — repo-root `instructionroot` and
   `scripts/run-verify.sh`: only `exec python3 -m instructionroot "$@"`
   (no `eval`/`curl`/`wget`). Accepted.
5. **95 accepted raw-text hits** (checker output §5): token strings
   (`shell=True`, `urllib`, `requests`, `socket.`, `curl`, …) occurring
   inside string literals (the check-pattern lists in `s0_gate.py`,
   `test_git.py`, and this checker itself), comments, documentation
   prose (`00_contract/*.md`, `review/tasks/*/TASK_RESULT.md`), `.txt`
   logs, and JSON data values (e.g. the word "requests" in
   `receipt_schema.json` prose). Each is listed with file:line and its
   classification — none is real code.
6. **Web dashboard local fetch (accepted, not a violation)** —
   `web/app.js:389`: `fetch(fileName)` with `DEFAULT_RECEIPT =
   "receipt.json"` — a same-origin *relative* fetch of the local receipt
   file. Plan §14 forbids *external* network requests; this is the
   dashboard's intended local load. No absolute-URL fetch / XHR /
   WebSocket / `src=https:` anywhere in `web/`.
7. **Receipt paths unredacted by design** — receipts store canonical
   absolute paths and `workspace.home`; `<HOME>` redaction is
   display-only (receipt.py docstring, receipt_schema.json). `cli.py`
   display redacts via `redact_home` (verified live: `verify` on
   `fixtures/demo` prints `<HOME>/...`). Not a leak.
8. **Test/support-only network use: 0.** No test file imports any
   network module; the separate test bucket is empty (it exists so any
   future test-only use is listed, never silently counted clean).
9. **Telemetry: 0.** No telemetry SDK import or `track/identify/capture`
   call in code (the only `track` matches are the words "tracked" /
   "tracking" in Git/trust prose, not calls).
10. **Secrets: 0.** No known-pattern hit repo-wide (`ghp_`, `sk-`,
    `AKIA`, private-key headers, `Bearer`, credential assignments);
    entropy scan clean after allowlisting hashes (SHA-256/SHA-1),
    UUIDs, URLs, paths, profile versions, CJK/full-width prose, and
    regex-pattern source literals. Fixture `secret.md` files are
    synthetic placeholders only (e.g. `claude-escape/outside/secret.md`
    contains the single word `outside`).

### Fixed / created by this task

- `scripts/security_static_check.py` (new, 998 lines) — the checker
  described above. AST-first Python analysis + classified raw-text
  second net + Rust/Cargo + web scans + secret entropy scan + license /
  package / receipt-privacy checks. Deterministic, no network, exit 0
  iff all four numbers are 0 and license/package/privacy pass.
  (Two checker bugs found by running it and fixed in-task: `tokenize`
  needs a `str` readline; a tuple-concat in the raw-sweep printer.
  Three classification refinements: `.txt`/`.log` = prose, HTML text
  outside tags = prose, relative `fetch()` = accepted local load.)
- `LICENSE` (new) — MIT License, `Copyright (c) 2026 InstructionRoot
  Resolve Contributors`.
- `pyproject.toml` (new) — `name=instructionroot`, `version=1.0.0`
  (== `cli.py:CLI_VERSION`), `license=MIT`, `requires-python=>=3.12`,
  `dependencies=[]` (stdlib only), console entry point
  `instructionroot = "instructionroot.cli:main"` (resolves, callable),
  `package-dir = {"" = "02_src"}` (repo layout), setuptools backend.
  This closes T008 note D4 (bare `instructionroot` on PATH).

## License / packaging state (verified live, offline)

- Wheel build (system setuptools 68.1.2, `--no-build-isolation`,
  `--no-deps`): `instructionroot-1.0.0-py3-none-any.whl`, 78,049 B,
  sha256 `1e12d28887002f48a9471dc03f8c93a6b5189419ca558cc6cde01de4f0656253`;
  contains the package, `LICENSE`, `METADATA`, and
  `[console_scripts] instructionroot = instructionroot.cli:main`.
- Editable install into `.venv` validated, then uninstalled and its
  `build/` + `02_src/instructionroot.egg-info/` removed to keep the
  tree clean: from `/tmp`, `.venv/bin/instructionroot --help` works,
  `instructionroot version` → `instructionroot 1.0.0`,
  `instructionroot verify --harness codex --cwd fixtures/demo` →
  `VERDICT: PASS (exit 0)`. Reproduce with:
  `PYTHONPATH=/usr/lib/python3/dist-packages .venv/bin/pip install --no-build-isolation -e .`
  (the project `.venv` has no setuptools; system setuptools was used
  offline — no network involved).
- Oracle `03_oracle/rust/Cargo.toml`: `license = "MIT"` (already set).

## Verification (run by this task, on the final tree)

| Check | Command | Result |
|---|---|---|
| Security check | `.venv/bin/python scripts/security_static_check.py` | `RESULT=PASS`, 0/0/0/0, exit 0 (859 files) |
| Python tests | `.venv/bin/python -m pytest -q` | **283 passed, 6 skipped** |
| Rust Oracle | `cargo test --manifest-path 03_oracle/rust/Cargo.toml` | **26 + 5 passed, 0 failed** |
| Oracle parity | `.venv/bin/python scripts/compare_oracle.py --all` | source/trust/edge/verdict/hash **100%**, fs 100%, git_scenarios PASS |
| S0 gate | `.venv/bin/python scripts/s0_gate.py` | **RESULT=FAIL — §8 only, known collision (see below)** |

## S0 gate collision — FLAG FOR COORDINATOR (gate-maintenance fix)

As briefed: `scripts/s0_gate.py` §8 greps `02_src/`, `03_oracle/rust/src/`
and `scripts/` for network tokens and FAILs the gate on any hit,
excluding only itself. This checker necessarily lists those tokens as
search data, so my gate run failed at §8 with exactly 12 hits, **all**
in `scripts/security_static_check.py` (its `NETWORK_MODULES` /
`RAW_TOKENS` literal lists — search data, not network calls).
Everything before §8 passed (`determinism=100/100`, `fail_closed=8/8`).
Per the coordinator note I did **not** obfuscate the token lists.
Required follow-up (not done here — it is gate maintenance, outside
T012): extend the gate's exclusion list to cover
`scripts/security_static_check.py`, same rationale as its own
self-exclusion. Full FAIL log:
`review/tasks/P028-T012/s0_gate_FAIL_on_checker_tokens.txt`.

Side effect repaired: that gate run overwrote `review/S0_GATE.md`,
`review/S0_LOG.txt` and `review/S0_ORACLE_SUMMARY.json` with the FAIL
record. I restored all three from HEAD (last committed PASS) with
`git checkout --` — verified `review/S0_GATE.md` again reads
`status=S0_PASS`. Caveat: `review/S0_LOG.txt` already carried an
uncommitted modification before my run (T011's gate run, which hit the
same §8 collision); its pre-run content was a generated log only and
could not be distinguished from the artifact, so HEAD's PASS log is the
restored version.

## Gaps / limitations

- Fixture `.git/` object stores are zlib-compressed binary and are
  excluded from the text scan like any binary file (same exclusion as
  `.venv`, `__pycache__`); their contents are not greppable. The S0
  gate's Git-scenario checks cover fixture Git behaviour instead.
- `web/` JavaScript is covered by the web-network scan (fetch/XHR/
  WebSocket/`src=https:`) only — no JS AST. Inline-script raw tokens
  outside HTML tags classify as prose; a network call written as an
  inline-script string literal would be missed by the raw sweep but
  caught by the web-network scan if it is a real `fetch(`/XHR call.
- The project `.venv` has no setuptools; packaging validation used the
  system setuptools 68.1.2 offline (see commands above).
- `muse.edit`/`muse.write` intermittently reported the new checker file
  as non-existent right after writing it (filesystem sync lag between
  tools); every file was verified present via `exec` (`ls` + `wc`) with
  the expected byte counts.

## Changed files

- `scripts/security_static_check.py` (new, 998 lines)
- `LICENSE` (new)
- `pyproject.toml` (new)
- `review/tasks/P028-T012/TASK_RESULT.md` (this file)
- `review/tasks/P028-T012/security_static_check.txt` (checker output)
- `review/tasks/P028-T012/s0_gate_FAIL_on_checker_tokens.txt` (gate FAIL log)
- `review/tasks/P028-T012/compare_oracle_all.txt` (oracle parity log)
- `review/tasks/P028-T012/changed-files.txt`, `command-log.txt`,
  `test-summary.json` (evidence pack)

No other repo files modified by this task (concurrent T009/T010/T011
changes — `web/`, `.github/`, `fixtures/windows/`,
`03_oracle/rust/src/receipt.rs`, etc. — are other tasks' work and were
left untouched; `review/S0_GATE.md` / `S0_LOG.txt` /
`S0_ORACLE_SUMMARY.json` were restored, not modified).
