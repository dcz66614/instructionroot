# InstructionRoot Resolve — static dashboard (T009)

Open it with a local static server (opening `index.html` directly from
disk blocks the local receipt fetch in most browsers):

```sh
python -m http.server 8765 --directory web
# then open http://127.0.0.1:8765/
```

Files:

- `index.html` — page shell with all 8 required elements: verdict header,
  source tree, effective chain, trust badges, import graph, why panel,
  raw JSON, export button.
- `app.js` — renders everything from the loaded receipt. The tree, the
  chain, and the graph all read the same `receipt.sources` /
  `receipt.edges` arrays, so they cannot disagree. No external requests:
  the only fetch is a relative fetch of a local receipt file.
- `style.css` — all styling, local. No fonts, no CDN.
- `receipt.json` — sample PASS receipt (default view), generated with
  `./instructionroot export --harness codex --cwd fixtures/demo/services/payments --home fixtures/demo/home --format json`.
- `receipt-pass.json` — same PASS receipt, kept under an explicit name.
- `receipt-block.json` — sample BLOCK receipt (src-0004,
  `SYMLINK_ESCAPE`: `services/payments/AGENTS.md` is a symlink to a file
  outside the repo), generated the same way from
  `fixtures/demo-block/services/payments`. Use the “BLOCK demo” button
  (or `?receipt=receipt-block.json`) to view it.

Other receipts: use “Open local receipt” to load any receipt JSON file
from disk, or `?receipt=<name>.json` for a file in this folder.

Scope: this page shows *which* instruction files a harness would load,
where they came from, and whether they cross a trust boundary. It does
not judge instruction content, call a model, or execute instructions.
