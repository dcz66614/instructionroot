# P028 T009 — Static HTML Dashboard — TASK_RESULT

- Task: P028 T009 (static HTML dashboard, no build server)
- Date: 2026-11-18 (GMT)
- Work dir: `~/workspace/p028-instructionroot/` (HEAD 6ac1738 = T008 CLI commit; no commit made by this task)
- Status: **DONE — all acceptance checks pass, with the headless-browser caveat below.**

## What was built

New files under `web/` (7 files, 29,514 bytes total):

| File | Size | Role |
|---|---|---|
| `web/index.html` | 3,040 B | Page shell, all 8 required elements |
| `web/app.js` | 18,560 B | Rendering + receipt loading + export, local only |
| `web/style.css` | 6,208 B | All styling, local; BLOCK styling in red |
| `web/README.md` | 1,706 B | How to serve and view, sample receipts, scope note |
| `web/receipt.json` | 5,185 B | Sample PASS receipt (default view) |
| `web/receipt-pass.json` | 5,185 B | Same PASS receipt, explicitly named (byte-identical to `receipt.json`, sha256 `fc261c7f…`) |
| `web/receipt-block.json` | 5,202 B | Sample BLOCK receipt |

Sample receipts were generated with the T008 CLI (no hand-writing):

- PASS: `./instructionroot export --harness codex --cwd fixtures/demo/services/payments --home fixtures/demo/home --format json` → verdict PASS, 4 sources, 0 edges, receipt_hash `efd5e4a02f41…` (full: `efd5e4a02f41935b71e97cb40979fe9d48050e506001bfb0d47d7af81d3b9f90`).
- BLOCK: same command with `--cwd fixtures/demo-block/services/payments --home fixtures/demo-block/home` → verdict BLOCK, 4 sources, 0 edges, receipt_hash `aeb13c64e6c4…`. Blocked source: `src-0004`, trust `SYMLINK_ESCAPE` — `services/payments/AGENTS.md` is a symlink to `fixtures/outside/AGENTS.md`, outside the repo.

## The 8 required elements (all present in `index.html`, one occurrence each)

1. Verdict header — `#verdict-header` / `#verdict-value` (+ profile, source/edge counts).
2. Source tree — `#source-tree`, grouped HOME / REPO / OUTSIDE per PROJECT_BOOK §10.1.
3. Effective chain — `#effective-chain`, one card per source in discovery order (scope, phase, discovery rule, precedence, SHA-256, Git status).
4. Trust badges — `#trust-badges`, one badge per trust value present, with counts; blocking values styled red.
5. Import graph — `#import-graph`, chain nodes in order with arrows, then import edges.
6. Why panel — `#why-panel`, filled on click: why discovered / why this trust / why blocked / related import edges / content hash.
7. Raw JSON — `#raw-json`, pretty-printed receipt (via `textContent`, never `innerHTML`).
8. Export button — `#export-button`, downloads the currently displayed receipt as `receipt-<verdict>.json` (Blob, local only).

Extras (within scope, no new semantics): PASS/BLOCK/receipt.json switcher buttons, “Open local receipt” file picker, `?receipt=<name>.json` query param (plain file name only), home path displayed as `<HOME>` (display-only redaction; receipt and hash untouched).

## Graph/list agreement (single source of truth)

The tree, the chain, and the graph are all rendered in `app.js` from the same
`receipt.sources` array (in discovery order) and `receipt.edges` — there is no
second hand-written copy of the source list. Each rendered node carries
`data-source-id`; clicking a source in any view highlights it in the other two
and fills the Why panel. Verified by the headless check below (tree/chain/graph
id sequences identical for both receipts).

## BLOCK prominence

- Red banner `#block-banner` (“BLOCKED — do not run this harness in this workspace.” + the blocking source id/path/trust) shown only when verdict is BLOCK.
- Blocked sources get `.blocked` (red background/border) + a red `BLOCK` tag in the tree, chain, and graph, and the verdict header turns red with a red bottom border.
- Why panel for a blocked source states the blocking trust value and policy reason.

## Book-vs-plan conflicts / divergences (recorded, not silently picked)

1. **Location: plan §1.1 / §28 lists the UI under `04_ui/`; the task brief (and PROJECT_BOOK §13 layout) names `web/`.** Followed the task brief: files live in `web/`. `04_ui/` in this repo is an empty directory and was left untouched.
2. **Layout: plan §14 lists the 8 elements; PROJECT_BOOK §10.1 is more specific** (three-column layout: left source tree, middle effective chain, right Why; §10.2 directed-graph view). Followed the book: three-column grid (collapses to one column under 900px), chain nodes drawn top-to-bottom with arrows, import edges drawn beneath the chain.
3. **Demo content: PROJECT_BOOK §10.3 describes a demo mode with a `repo/CLAUDE.md` importing `~/Downloads/…`.** That exact workspace does not exist as a fixture; the task brief instead specifies the CLI-generated demo/demo-block receipts. Followed the task brief: the two CLI-generated receipts are the samples, and the import-graph code handles edges generically (including `to === null` targets) even though both sample receipts have 0 edges.
4. No other book-vs-plan conflict affecting T009 was found.

## Verification (all run by this task)

### HTTP serving — all 200

`python -m http.server 8765 --directory web`, fetched over HTTP:

| File | Status | Size |
|---|---|---|
| `index.html` | 200 | 3,040 B |
| `app.js` | 200 | 18,560 B |
| `style.css` | 200 | 6,208 B |
| `receipt.json` | 200 | 5,185 B |
| `receipt-pass.json` | 200 | 5,185 B |
| `receipt-block.json` | 200 | 5,202 B |
| `README.md` | 200 | 1,706 B |

### Zero external requests

`grep -rInE "https?://|//cdn|fonts.googleapis|google-analytics|cdn.jsdelivr|unpkg.com" web/` → **0 matches** except one line in `web/README.md` (`http://127.0.0.1:8765/` — the local-server instruction, not a fetched resource). A broader `grep -rIn "http" web/` finds only that README line plus the words `python -m http.server 8765` in the README and in an `app.js` error message (plain text, never fetched). The page's only fetch is `fetch(fileName)` with a relative local file name (`receipt.json` by default); there are no `<link>`/`<script>`/`<img>` references to anything outside this folder, no fonts, no analytics. `node --check web/app.js` passes.

### Headless DOM check (no real browser in this VM)

No Chromium/Firefox headless binary is installed in this VM, so the page was
**not** opened in a real browser. Instead it was checked with a Node harness
(`/tmp/p028t009/check.mjs`, kept in /tmp as scratch): a minimal DOM shim
(`getElementById`, `createElement`, `appendChild`, `textContent`,
`classList`, attributes, events, a local-file `fetch`) loads the real
`app.js`, lets its real `fetch("receipt.json")` run, then calls the real
`renderAll()` for both receipts and inspects the resulting DOM. Results:

- **PASS receipt:** verdict header `PASS` (expected `PASS`); BLOCK banner hidden; tree = chain = graph = `[src-0001, src-0002, src-0003, src-0004]` (agreement: true); blocked sources in DOM: none; clicking `src-0004` fills the Why panel with `src-0004` + `GIT_TRACKED`; raw JSON contains the receipt hash.
- **BLOCK receipt:** verdict header `BLOCK` (expected `BLOCK`); BLOCK banner **visible**, text `src-0004 …/fixtures/demo-block/services/payments/AGENTS.md (SYMLINK_ESCAPE)`; tree = chain = graph = `[src-0001, src-0002, src-0003, src-0004]` (agreement: true); blocked sources: `[src-0004]`, and `src-0004` carries the `blocked` class in the DOM; clicking `src-0004` fills the Why panel with `src-0004` + `SYMLINK_ESCAPE`; raw JSON contains the receipt hash.
- Export-button click: no throw.

**Gap:** visual rendering (colours, layout, banner appearance) was verified only
through the DOM state and CSS classes, not by a screenshot in a real browser.
A real-browser open (`python -m http.server 8765 --directory web`, then
`http://127.0.0.1:8765/`) is still the recommended final eyeball check; nothing
in the code depends on browser-only behaviour beyond standard DOM/fetch/Blob.

### Regression suites — all PASS

| Check | Result |
|---|---|
| `pytest` (`.venv`, full suite) | **283 passed, 6 skipped** in ~6.5 s |
| `cargo test` (Rust Oracle, `~/.cargo/bin/cargo`) | **31 passed, 0 failed** (26 + 5 across the two test binaries) |
| `scripts/compare_oracle.py --all` | exit 0; source/trust/edge/verdict/hash parity **100.0%**; fs_parity 100.0%; git_scenarios PASS (resolver 20, imports 16, fs 12, fs_probes 25) |
| `scripts/s0_gate.py` (re-run) | **RESULT=PASS** — fixtures=60, production/oracle parity 100%, receipt_hash parity 100%, determinism 100/100, fail_closed PASS, network_access 0, human_labels 0 |

Note: the pytest count rose from 267 (recorded in the committed S0 gate) to 283
because the working tree now also contains a parallel task's T011 Windows-corpus
tests (`05_tests/unit/test_windows_corpus.py` etc., not written by this task).
The S0 re-run therefore refreshed `review/S0_GATE.md` / `review/S0_LOG.txt` /
`review/S0_ORACLE_SUMMARY.json` with the new counts and timings only; the gate
result is unchanged (PASS). The `.gitignore` change in the working tree is also
T011's, not this task's. This task touched nothing outside `web/` except those
S0 log regenerations; it did not touch `00_contract/`, `01_s0/expected/`,
`01_s0/fixtures/s0/`, `scripts/s0_gate.py`, or any production resolver/trust/
import/receipt code. No GitHub upload, no external messages.

## Files changed by this task

- Added: `web/index.html`, `web/app.js`, `web/style.css`, `web/README.md`, `web/receipt.json`, `web/receipt-pass.json`, `web/receipt-block.json`
- Regenerated by the S0 gate re-run (counts/timings only): `review/S0_GATE.md`, `review/S0_LOG.txt`, `review/S0_ORACLE_SUMMARY.json`
- Not committed (no commit was requested).
