# P028 FIX-GATE-EXCL — S0 gate §8 excludes scripts/security_static_check.py

Date: 2026-11-18 ~07:58–08:05 GMT. Base: HEAD ba4e9e4 (T012 commit).
Scope: one file changed — `scripts/s0_gate.py` only. No change to `02_src/`,
`03_oracle/`, `00_contract/`, `01_s0/expected/`, fixtures, or any gate
assertion/threshold. The checker file stayed in place for every run
(never moved aside).

## Problem

`check_network()` (§8) statically greps `02_src/`, `03_oracle/rust/src/`
and `scripts/` for network tokens and FAILs the whole gate on any hit.
It already excluded itself (`scripts/s0_gate.py`) because its own token
list is data, not a network call. The T012 security checker
`scripts/security_static_check.py` necessarily contains the same token
strings as its search data, so the gate failed with exactly 12 hits,
all in that file, while §1–§7 all passed.

## Fix (exact diff — `git diff scripts/s0_gate.py`)

```diff
@@ -853,13 +853,20 @@ def check_network() -> dict:
     log("== 8. network_access=0 (static grep + runtime audit hook) ==")
     hits = []
     gate_file = Path(__file__).resolve()
+    # scripts/security_static_check.py necessarily contains the same
+    # network token strings as its search data (its token/pattern
+    # lists), not as network calls -- same rationale as the gate's own
+    # self-exclusion. The runtime audit hook still covers actual
+    # socket use during the gate.
+    excluded = {gate_file,
+                (WORKDIR / "scripts" / "security_static_check.py").resolve()}
     for root in (WORKDIR / "02_src", WORKDIR / "03_oracle" / "rust" / "src",
                  WORKDIR / "scripts"):
         for path in sorted(root.rglob("*")):
             # The gate's own token list is data (the strings being
             # searched for), not a network call; the runtime audit hook
             # covers the gate process itself instead.
-            if path.resolve() == gate_file:
+            if path.resolve() in excluded:
                 continue
             if path.is_file() and path.suffix in (".py", ".rs", ".toml"):
                 text = path.read_text(encoding="utf-8", errors="replace")
@@ -870,7 +877,7 @@ def check_network() -> dict:
     for root in (WORKDIR / "02_src", WORKDIR / "03_oracle" / "rust" / "src",
                  WORKDIR / "scripts"):
         for path in sorted(root.rglob("*")):
-            if path.resolve() == gate_file:
+            if path.resolve() in excluded:
                 continue
             if path.is_file() and path.suffix in (".py", ".rs"):
                 if "shell=True" in path.read_text(encoding="utf-8", errors="replace"):
```

Notes on the change:

- Same mechanism as the existing exclusion (`path.resolve()` comparison),
  now as a two-member `excluded` set applied identically to both scans
  (network-token scan and `shell=True` scan). The second scan needed the
  same exclusion too: the checker also contains literal `"shell=True"`
  strings as check-pattern data (docstrings / print strings), so the
  substring scan would have flagged it as well.
- Nothing else weakened: same `NETWORK_TOKENS` list, same three roots,
  same failure behaviour for every other file.

## Gate result (clean re-run, checker present)

`.venv/bin/python scripts/s0_gate.py` — exit 0, exact block:

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

Gate internals (from the same run's log): golden 20/20 + 16/16
(source order/set/edge parity/escape detection all 100.0%); unified
index 48/48 passed, source_ok/trust_ok/edge_ok/verdict_ok/hash_ok all
48/48; fs 12/12 (25 probes); git scenarios 6 PASS; determinism 100/100
(codex-basic 100 runs + s0-git-tracked 25 runs, one hash each);
fail-closed 8/8; known_escape_detection 15/15; coverage 12/12 scenarios
+ 25/25 S01–S25.

## Probe test (exclusion is narrow — the check still catches real tokens)

- Created `scripts/_probe_socket.py` containing a literal
  `import socket` (plus `socket.socket()` use).
- Re-ran the gate: exit 1, `RESULT=FAIL`, with
  `network token: scripts/_probe_socket.py: import socket` and
  `network token: scripts/_probe_socket.py: socket.`
  (`GATE FAILURE: network tokens found in production/Oracle code: 2`).
- Deleted the probe file (verified gone; `git status` shows only
  `scripts/s0_gate.py` modified under `scripts/`), re-ran the gate:
  exit 0, `RESULT=PASS` with the exact block above.

## Full verification numbers

| Check | Result |
|---|---|
| S0 gate (`.venv/bin/python scripts/s0_gate.py`) | exit 0, `RESULT=PASS` (block above) |
| Probe file with `import socket` | gate exit 1, `RESULT=FAIL`, 2 hits on the probe file; deleted, gate PASS again |
| Security checker (`python3 scripts/security_static_check.py`) | exit 0, `shell_true=0`, `network_runtime=0`, `telemetry=0`, `secret_fixture_leaks=0`, `RESULT=PASS` (files_scanned=859) |
| pytest (standalone, `05_tests/ -q`) | 283 passed, 6 skipped |
| cargo test (standalone) | 26 passed + 5 passed (2 suites, 0 failed) |
| `compare_oracle.py --all` (standalone) | resolver 20, imports 16, fs 12, fs_probes 25; source/trust/edge/verdict/hash parity all 100.0%; fs_parity 100.0%; git_scenarios PASS |
| Windows corpus runner (`.venv/bin/python scripts/run_windows_corpus.py`) | exit 0, `RESULT=PASS`; receipt cases 15/15, source/trust/edge/verdict/hash parity all 15/15; probes 10/10; determinism 1 hash |

(Gate §10 re-ran pytest / cargo test / `compare_oracle --all` inside the
gate as well, with identical numbers: pytest 283 passed, 6 skipped;
cargo 26 + 5; compare 5×100%, fs 100%, git PASS.)

## Working-tree note

`git status` after the work: only `scripts/s0_gate.py` is an intentional
change. `review/S0_GATE.md`, `review/S0_LOG.txt` and
`review/S0_ORACLE_SUMMARY.json` were regenerated by the clean PASS gate
runs (previously they held the T012-collision FAIL state; the summary
diff is only a `/tmp/s0-gate-*` tmpdir name inside the FC-01 detail
string). `review/COORDINATOR_LOG.md` gained one line during this task
from the coordinator's own concurrent T012 PASS entry, not from this
work. No commit made — commit is the coordinator's call.
