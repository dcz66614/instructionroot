# P028-T011 handoff

- **Result:** PASS. Windows corpus runner exit 0 (`scripts/run_windows_corpus.py`).
- **Corpus:** `fixtures/windows/` — 15 receipt cases (7 PASS / 8 BLOCK) + 10 pure-string probes, with hand-written expected index `fixtures/windows/expected/INDEX.json` (per-case reasoning included).
- **Parity:** source 15/15, trust 15/15, edge 15/15, verdict 15/15, hash 13/15, probes 10/10, determinism spot check 10+10 one hash.
- **Known gap F6 (bounded):** `win-junction-inside` + `win-junction-escape` differ production↔Oracle only in `workspace.cwd` (lexical vs resolved) + hash; the runner asserts the diff is exactly that set. Root cause is in `build_receipt`'s lexical cwd vs discovery's resolved cwd — recorded, not patched.
- **Other findings:** F1 (no case-insensitive discovery), F2 (UNC imports misparse to MISSING), F3 (deleted chain file silent), F4 (drive-relative rejection unreachable), F5 (drive-letter case not folded). Details in TASK_RESULT.md.
- **NOT_RUN (needs a Windows runner):** real junction, real drive letters, real case-insensitive matching, real UNC, real Windows Git, Windows UTF-16/NFC.
- **Regression:** pytest 283 passed / 6 skipped, cargo 26+5, compare_oracle --all 5×100%, S0 gate RESULT=PASS (fixtures=60).
- **Untouched:** `00_contract/`, `02_src/`, `03_oracle/`, `01_s0/expected/`, `scripts/s0_gate.py` (verified by git diff).
- **Rerun:** `.venv/bin/python scripts/run_windows_corpus.py`
