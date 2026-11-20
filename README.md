# InstructionRoot Resolve

**Instruction-chain preflight for coding-agent harnesses: given a harness, a working
directory, and the local filesystem/Git snapshot, determine exactly which instruction
files the harness would load, why each one loads, and whether any of them crosses a
trust boundary — then seal the answer in a deterministic receipt.**

> **First-screen answers**
>
> | Question | Answer |
> |---|---|
> | **What does it verify?** | Which instruction files a harness would discover for a CWD, in what order, with what scope/phase/precedence, each file's canonical path, SHA-256, Git state, import edges, and trust classification — sealed in a deterministic receipt that an independent Rust Oracle can recompute. |
> | **What does it not verify?** | Whether instruction *content* is safe or malicious; whether a real agent binary actually follows its documentation; who authored an untracked file; remote/organisation policy; anything that happens after the snapshot (runtime reads). See [What it does not prove](#what-it-does-not-prove) and [Known limitations](#known-limitations). |
> | **Supported harnesses?** | `codex` (OpenAI Codex CLI), `claude-code` (Anthropic Claude Code), `copilot-cli` (GitHub Copilot CLI) — frozen profiles, see [Harness profiles](#harness-profiles). |
> | **10-second demo?** | [Yes — copy-paste below](#10-second-demo). `fixtures/demo` → `PASS`, `fixtures/demo-block` → `BLOCK` (symlink escape). |
> | **Install?** | Stdlib-only Python ≥ 3.12: `pip install` from the built wheel, or `./instructionroot` with no install step. See [Install](#install). |
> | **CI?** | GitHub Action (`.github/workflows/instructionroot.yml`) + pre-commit hook, both running `scripts/run-verify.sh`; they fail on `BLOCK` (exit 20) and on `WARN` (exit 10) unless `allow_warn` is set. See [CI](#ci-github-action--pre-commit). |
> | **Receipt example?** | [Yes — real receipt from the demo run](#receipt-example). |
> | **Limitations?** | [Yes — ten recorded limitations, none softened](#known-limitations). |

---

## No LLM. No network.

- **No LLM is involved in any determination.** Discovery, trust classification, import
  edges, and the receipt are computed by deterministic local code (Python production
  implementation, cross-checked by an independent Rust Oracle). No model is called,
  no prompt is sent anywhere.
- **Zero network access at runtime.** The tool reads only the local filesystem and
  local Git metadata (read-only Git commands: `rev-parse`, `ls-files`, `status`,
  `log` — all with `shell=False`; no `fetch`/`pull`/`push`). It never uploads
  instruction contents, repository contents, or anything else. Evidence:
  `scripts/security_static_check.py` → `RESULT=PASS`
  (`shell_true=0`, `network_runtime=0`, `telemetry=0`, `secret_fixture_leaks=0`);
  the S0 gate records `network_access=0` and `human_labels=0`.
- **Synthetic data only.** Every fixture in this repository is synthetic placeholder
  text (e.g. `# Synthetic demo repo instructions (placeholder only).`). No real
  user workspace, no real malicious payload, no real humans are involved in any
  verification.

## 10-second demo

No install needed — the repo-root launcher runs the production CLI directly
(requires `python3` ≥ 3.12 and a `git` binary on `PATH`):

```sh
# PASS: four tracked sources, repo root → CWD chain, nothing escapes
./instructionroot verify --harness codex --cwd fixtures/demo/services/payments --home fixtures/demo/home
# BLOCK: the payments AGENTS.md is a symlink escaping the repo
./instructionroot verify --harness codex --cwd fixtures/demo-block/services/payments --home fixtures/demo-block/home
```

Real output (run 2026-11-18; absolute paths are the machine the demo ran on —
yours will differ, verdicts and receipt hashes will not):

```text
$ ./instructionroot verify --harness codex --cwd fixtures/demo/services/payments --home fixtures/demo/home
InstructionRoot Resolve 1.0.0
Harness: codex (codex-2026-11)
CWD:     /home/hatch/workspace/p028-instructionroot/fixtures/demo/services/payments
Repo:    /home/hatch/workspace/p028-instructionroot/fixtures/demo

VERDICT: PASS (exit 0)
sources=4 blocked=0 warnings=0

1  <HOME>/.codex/AGENTS.md
   GIT_TRACKED / user / startup / tracked
   discovered_by: codex.user
   sha256: 0a97c865d792
2  /home/hatch/workspace/p028-instructionroot/fixtures/demo/AGENTS.md
   GIT_TRACKED / project / startup / tracked
   discovered_by: codex.repo-chain
   sha256: 15fea277c488
3  /home/hatch/workspace/p028-instructionroot/fixtures/demo/services/AGENTS.md
   GIT_TRACKED / project / startup / tracked
   discovered_by: codex.repo-chain
   sha256: 58ac069b35f4
4  /home/hatch/workspace/p028-instructionroot/fixtures/demo/services/payments/AGENTS.md
   GIT_TRACKED / project / startup / tracked
   discovered_by: codex.repo-chain
   sha256: a236caf43109

receipt_hash: efd5e4a02f41935b71e97cb40979fe9d48050e506001bfb0d47d7af81d3b9f90
```

```text
$ ./instructionroot verify --harness codex --cwd fixtures/demo-block/services/payments --home fixtures/demo-block/home
InstructionRoot Resolve 1.0.0
Harness: codex (codex-2026-11)
CWD:     /home/hatch/workspace/p028-instructionroot/fixtures/demo-block/services/payments
Repo:    /home/hatch/workspace/p028-instructionroot/fixtures/demo-block

VERDICT: BLOCK (exit 20)
sources=4 blocked=1 warnings=0

1  <HOME>/.codex/AGENTS.md
   GIT_TRACKED / user / startup / tracked
   discovered_by: codex.user
   sha256: 9b0b0f60c90d
2  /home/hatch/workspace/p028-instructionroot/fixtures/demo-block/AGENTS.md
   GIT_TRACKED / project / startup / tracked
   discovered_by: codex.repo-chain
   sha256: 957cc2968932
3  /home/hatch/workspace/p028-instructionroot/fixtures/demo-block/services/AGENTS.md
   GIT_TRACKED / project / startup / tracked
   discovered_by: codex.repo-chain
   sha256: 32d1e6497a63
4  /home/hatch/workspace/p028-instructionroot/fixtures/demo-block/services/payments/AGENTS.md
   SYMLINK_ESCAPE / project / startup / no-repo
   discovered_by: codex.repo-chain
   sha256: 853797948eb0

receipt_hash: aeb13c64e6c46988a2b80429c9927ba590bd62d1db43f3a62dfce94f95741d8a
```

Why the demo-block case blocks: `fixtures/demo-block/services/payments/AGENTS.md` is a
symlink (`AGENTS.md -> ../../../outside/AGENTS.md`) whose resolved target,
`fixtures/outside/AGENTS.md`, sits outside the demo-block repository — a
`SYMLINK_ESCAPE`. The demo fixtures are self-contained Git repositories, so the
user-scope file (`fixtures/demo/home/.codex/AGENTS.md`) shows as `GIT_TRACKED`
here; in real use a `~/.codex/AGENTS.md` outside any repository is classified
`USER_SCOPE` instead.

Try the other harnesses on the same fixtures (`claude-code`, `copilot-cli`) and
`inspect` / `export` for the full chain and receipt files:

```sh
./instructionroot inspect --harness claude-code --cwd fixtures/demo/services/payments --home fixtures/demo/home --format json
./instructionroot profile list
./instructionroot version
```

Note what the other harnesses do on these exact fixtures (observed
2026-11-18): `copilot-cli` on the demo fixture reports `PASS` with 3 sources,
while `claude-code` reports `BLOCK` with 4 sources — its upward discovery
walks to the filesystem root and finds a real `/home/hatch/AGENTS.md` sitting
above the repository (`OUTSIDE_REPO`, `claude-code.agents-fallback`). That is
limitation 7 happening live: the same command gives a different verdict on a
different machine unless the CWD is isolated.

## Install

Requirements: Python ≥ 3.12 (`requires-python = ">=3.12"` in `pyproject.toml`),
stdlib only — **no third-party dependencies**. A `git` binary on `PATH` is needed
for Git provenance (read-only commands only).

### Option A — install from the built wheel (verified offline)

```sh
python3 -m pip wheel . --no-deps --no-build-isolation -w dist
python3 -m venv /tmp/ir-venv
/tmp/ir-venv/bin/pip install --no-index --no-deps dist/instructionroot-1.0.0-py3-none-any.whl
/tmp/ir-venv/bin/instructionroot version
```

Observed 2026-11-18 (system Python 3.12.3, setuptools 68.1.2): the wheel builds
as `instructionroot-1.0.0-py3-none-any.whl` (78,049 bytes,
SHA-256 `6ce8eae6148bc21814a9a0ff8201b20e8a144a223d272c235220c6080ffa33ae`) and
installs offline with `--no-index --no-deps`. The installed console entry
reproduces the demo exactly — same verdicts, same receipt hashes
(`efd5e4a0…` for the demo, `aeb13c64…` for demo-block).

### Option B — `pip install .` (verified, with one precondition)

```sh
python3 -m venv --system-site-packages /tmp/ir-venv   # or any venv with setuptools >= 61 importable
/tmp/ir-venv/bin/pip install --no-index --no-deps --no-build-isolation .
/tmp/ir-venv/bin/instructionroot verify --harness codex --cwd fixtures/demo-block/services/payments --home fixtures/demo-block/home
# VERDICT: BLOCK (exit 20), receipt_hash: aeb13c64e6c46988a2b80429c9927ba590bd62d1db43f3a62dfce94f95741d8a
```

Precondition, observed honestly: the build backend is `setuptools>=61`
(`pyproject.toml`). A bare venv with no setuptools fails `pip install .
--no-build-isolation` with `ModuleNotFoundError: No module named 'setuptools'`.
With setuptools available (as in the command above) the install succeeds
offline. With build isolation left on (the pip default), pip would fetch the
build backend from the network — use `--no-build-isolation` for a fully
offline install.

### Option C — no install: the repo-root launcher

```sh
./instructionroot --help
./instructionroot verify --harness codex --cwd fixtures/demo/services/payments --home fixtures/demo/home
```

`./instructionroot` is a small shell launcher that sets `PYTHONPATH` to
`02_src/` and runs the production CLI from the checkout. It is the same entry
the GitHub Action and the pre-commit hook use. Once installed, the
`instructionroot` console script (`instructionroot.cli:main`) replaces it —
no `PYTHONPATH` export is needed.

Installed `instructionroot version` output (observed):

```text
instructionroot 1.0.0
python 3.12.3
profile codex codex-2026-11
profile claude-code claude-code-2026-11
profile copilot-cli copilot-cli-2026-11
oracle: not built (run `instructionroot oracle` once to build)
```

(The `oracle: not built` line appears for a fresh install; running
`instructionroot oracle` once builds the Rust Oracle. From a checkout the
launcher reports `instructionroot-oracle 0.1.0` instead.)

## CLI

```text
instructionroot inspect   show the effective instruction chain + receipt
instructionroot verify    gate: exit non-zero on BLOCK (and WARN by default)
instructionroot export    write the receipt to files
instructionroot profile   harness profile commands (list)
instructionroot oracle    run the Rust Oracle on the same input and check parity
instructionroot version   print versions (CLI, Python, profiles, Oracle)
```

Output formats for `inspect` / `verify` / `export`: `terminal` (default),
`json`, `md`, `html`.

### Exit codes — only `verify` gates

| Exit code | Verdict | Meaning |
|---|---|---|
| 0 | `PASS` | Chain is clean under the active policy. |
| 10 | `WARN` | Warnings only (e.g. untracked in-repo source under the default policy). `--allow-warn` makes it exit 0. |
| 20 | `BLOCK` | A source crosses a trust boundary (outside repo, symlink/import escape, missing reference, depth exceeded). |
| 30 | `INPUT_ERROR` | Bad input: missing CWD, malformed config/policy, invalid JSON. Fails closed. |
| 40 | `UNSUPPORTED_PROFILE` | Unknown harness or a `--profile-version` that does not match the frozen version. |
| 50 | `INTERNAL_ERROR` | Unexpected internal failure. |

**Only `verify` gates on exit code.** `inspect`, `export`, and `oracle` exit 0
whenever they successfully produce their output, whatever the verdict — this is
a deliberate design decision (T008 D1), not a bug: inspecting a `BLOCK` chain
is a legitimate read operation. Observed: `inspect` on the demo-block fixture
exits 0 while reporting `verdict: BLOCK`. If you want a gate, use `verify`.

Default policy (13 frozen `policy_schema` v1 fields; see
`00_contract/policy_schema.json`): user scope allowed, repo tracked allowed,
untracked in-repo sources are `WARN` (`block_repo_untracked=false`), modified
in-repo sources allowed (`block_repo_modified=false`), outside-repo / symlink
escape / import escape / missing reference all `BLOCK`, unspecified precedence
warns. Override with `--policy <policy.json>` or `--strict` (treats `WARN` as
`BLOCK`).

## Harness profiles

Profiles are frozen in `00_contract/profile_contract.json` (frozen 2026-11-18;
official sources fetched 2026-11-18). The JSON is the machine-readable
authority; `06_docs/PROFILES.md` is its human-readable rendering — if the two
ever disagree, the JSON wins. Each profile carries a `rules_hash`
(`sha256:…`) over its rules, so a profile cannot change silently.

| Harness | Profile version | Official source (copied verbatim from the frozen contract) |
|---|---|---|
| `codex` — OpenAI Codex CLI | `codex-2026-11` | https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide (also: https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference) |
| `claude-code` — Anthropic Claude Code | `claude-code-2026-11` | https://docs.anthropic.com/zh-CN/docs/claude-code/memory (also: https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference) |
| `copilot-cli` — GitHub Copilot CLI | `copilot-cli-2026-11` | https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions (also: https://docs.github.com/en/copilot/concepts/prompting-and-context/custom-instructions and https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference) |

Rules are only modelled from what the official documentation actually says.
Anything the documentation does not define is marked `UNVERIFIED` and never
guessed; precedence the documentation does not define is reported as
`UNSPECIFIED`, never invented. Examples of `UNVERIFIED` items (see
`06_docs/PROFILES.md` for the full list): Codex has no documented `@`-import
mechanism, so `AGENTS.md` `@…` text produces no edges for `codex`; the Codex
size cap has no documented value, so no limit is enforced; `AGENTS.override.md`
fallback-selection semantics are undefined.

```text
$ ./instructionroot profile list
InstructionRoot profiles (frozen contract):

codex  codex-2026-11
  OpenAI Codex CLI
  source: https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide
  rules_hash: sha256:a0a03c1cdd77f8d9110ccbc77dae937e30e288a2609e6b04b60d26d15af5dc23

claude-code  claude-code-2026-11
  Anthropic Claude Code
  source: https://docs.anthropic.com/zh-CN/docs/claude-code/memory
  rules_hash: sha256:7f1d074dc0bb8dde1eace4c01498f8899b8ef58aa47f71c32c649768104f6058

copilot-cli  copilot-cli-2026-11
  GitHub Copilot CLI
  source: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions
  rules_hash: sha256:76a5f6c8fbd7fc4ff910bf5f471ecb9291ab2a575d871f93338fb1b298c73d0e
```

## Receipt example

Real receipt from the demo `PASS` run (`inspect --format json`), shortened to
one full source plus the remaining source IDs; paths redacted as `<HOME>` for
display (the stored receipt contains absolute paths; the hash is computed over
the canonical receipt, so redaction here is display-only and the hash below is
the real one):

```json
{
  "receipt_version": 1,
  "profile": {
    "id": "codex",
    "version": "codex-2026-11",
    "rules_hash": "sha256:a0a03c1cdd77f8d9110ccbc77dae937e30e288a2609e6b04b60d26d15af5dc23"
  },
  "workspace": {
    "cwd": "<HOME>/workspace/p028-instructionroot/fixtures/demo/services/payments",
    "home": "<HOME>/workspace/p028-instructionroot/fixtures/demo/home",
    "repo_root": "<HOME>/workspace/p028-instructionroot/fixtures/demo"
  },
  "verdict": "PASS",
  "sources": [
    {
      "source_id": "src-0001",
      "raw_path": "~/.codex/AGENTS.md",
      "canonical_path": "<HOME>/workspace/p028-instructionroot/fixtures/demo/home/.codex/AGENTS.md",
      "resolved_path": "<HOME>/workspace/p028-instructionroot/fixtures/demo/home/.codex/AGENTS.md",
      "scope": "user",
      "phase": "startup",
      "discovery_rule": "codex.user",
      "precedence": {
        "kind": "ORDERED",
        "detail": "First in the chain: global instructions are injected before repo instructions."
      },
      "sha256": "0a97c865d7925c3004b94f265463ee7e65cf18d3ac6885e291d9fe793bb24197",
      "git": {
        "repo": "<HOME>/workspace/p028-instructionroot/fixtures/demo",
        "tracked": true,
        "modified": false,
        "head_commit": "38aebc4a674005b67423373622de8af163e83787"
      },
      "trust": "GIT_TRACKED"
    },
    { "source_id": "src-0002", "raw_path": "<HOME>/…/fixtures/demo/AGENTS.md",
      "scope": "project", "phase": "startup", "discovery_rule": "codex.repo-chain",
      "trust": "GIT_TRACKED", "sha256": "15fea277c488…" },
    { "source_id": "src-0003", "raw_path": "<HOME>/…/fixtures/demo/services/AGENTS.md",
      "scope": "project", "phase": "startup", "discovery_rule": "codex.repo-chain",
      "trust": "GIT_TRACKED", "sha256": "58ac069b35f4…" },
    { "source_id": "src-0004", "raw_path": "<HOME>/…/fixtures/demo/services/payments/AGENTS.md",
      "scope": "project", "phase": "startup", "discovery_rule": "codex.repo-chain",
      "trust": "GIT_TRACKED", "sha256": "a236caf43109…" }
  ],
  "edges": [],
  "receipt_hash": "efd5e4a02f41935b71e97cb40979fe9d48050e506001bfb0d47d7af81d3b9f90"
}
```

Trust values (9, per the frozen receipt schema): `GIT_TRACKED`,
`GIT_MODIFIED`, `GIT_UNTRACKED`, `USER_SCOPE`, `OUTSIDE_REPO`,
`SYMLINK_ESCAPE`, `IMPORT_ESCAPE`, `MISSING`, `NOT_OBSERVED`. The receipt hash
is a SHA-256 over the canonical (RFC 8785 JCS) receipt, so the same input
always produces the same hash — the production implementation and the Rust
Oracle agree on it bit-for-bit (see [S0 evidence](#s0-evidence)). Receipts are
**unsigned** SHA-256 hashes; there is no Sigstore/SLSA signature (limitation 9
below).

## CI: GitHub Action + pre-commit

Both integrations run the same entry point, `scripts/run-verify.sh`, so they
cannot drift apart. The script resolves settings in order: environment
variables (`INSTRUCTIONROOT_HARNESS` / `_CWD` / `_HOME` / `_POLICY` /
`_ALLOW_WARN`) → repo config `.instructionroot.json` → defaults
(`harness=codex`, `cwd=.`). A malformed config fails closed (exit 30); a
missing config falls back to defaults.

**GitHub Action** — `.github/workflows/instructionroot.yml` (runs on push to
`main`, pull requests, and `workflow_dispatch` with `harness`/`cwd` inputs).
Security properties: only a pinned `actions/checkout` action is used
(`actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683`, v4.2.2 — full
40-char commit SHA, no floating tags); permissions are read-only
(`contents: read`, `persist-credentials: false`); no instruction contents are
uploaded (the job produces no artifacts); no third-party tools are installed
(the verify step uses the runner's system `python3` and the repo's own
stdlib-only CLI). The job fails whenever `verify` exits non-zero — `BLOCK`
(20), `WARN` (10), `INPUT_ERROR` (30), `UNSUPPORTED_PROFILE` (40),
`INTERNAL_ERROR` (50).

**Pre-commit hook** — `.pre-commit-hooks.yaml` exposes hook id
`instructionroot-verify` (`entry: scripts/run-verify.sh`, `pass_filenames:
false`, `always_run: true` — the gate checks a working directory, not
individual changed files). It fails the commit on `BLOCK` and on `WARN` unless
`"allow_warn": true` is set in the config. The repo's own
`.pre-commit-config.yaml` wires this hook locally as a self-check example.

CI simulation (T010, `scripts/simulate_ci.py`): **PASS 2/2** — the `PASS`
fixture yields exit 0 and the `BLOCK` fixture yields exit 20, exactly as
configured.

**Honest note — the shipped config passes vacuously on this repository.**
The default config (`.instructionroot.json`: `{"allow_warn": false, "cwd":
".", "harness": "codex", "version": 1}`) verifies this repo's own root, and
this repo has no `AGENTS.md` at its root, so the shipped workflow is a
per-repo template, not a gate over this repo's own instruction files:

```text
$ ./instructionroot verify --harness codex --cwd .
InstructionRoot Resolve 1.0.0
Harness: codex (codex-2026-11)
CWD:     <HOME>/workspace/p028-instructionroot
Repo:    <HOME>/workspace/p028-instructionroot

VERDICT: PASS (exit 0)
sources=0 blocked=0 warnings=0


receipt_hash: 3a8f11ada86d615155ac6182effb4963ac5c85dbed397602e0d2a8fa9a1e7c49
```

`PASS` with `sources=0` means "nothing was found to check", not "everything
was checked". Point the config at a real working directory (or a fixture such
as `fixtures/demo/services/payments`) to get a meaningful gate.

## Dashboard

`web/` is a static HTML dashboard (no build step, no server, no external
requests — the only fetch is a relative fetch of a local receipt file):

```sh
python -m http.server 8765 --directory web
# then open http://127.0.0.1:8765/
```

It shows the verdict header, source tree, effective chain, trust badges,
import graph, why panel, raw JSON, and an export button — all rendered from
the same `receipt.sources` / `receipt.edges` arrays, so the tree, the chain,
and the graph cannot disagree. `web/receipt.json` is the sample `PASS` receipt
from the demo; `web/receipt-block.json` is the sample `BLOCK` receipt
(`src-0004`, `SYMLINK_ESCAPE`); use the "BLOCK demo" button (or
`?receipt=receipt-block.json`) to view it. Opening `index.html` directly from
disk blocks the local receipt fetch in most browsers — use the static server
above.

## What it does not prove

(From PROJECT_BOOK §6.2 — the honest boundary, repeated here because
misunderstanding it is the main misuse risk.)

1. It **cannot prove a real agent binary follows its documentation.** The
   profiles model published discovery rules; a binary could behave
   differently. This tool proves "under the frozen, citable rules, these
   sources would be discovered" — nothing more.
2. It **cannot prove instruction content is safe or benign.** It never reads
   content for a safety judgement; a `PASS` receipt says nothing about what
   the instructions tell the agent to do.
3. It **cannot prove who created a file.** For an untracked file it can only
   prove "currently not Git-tracked" — never an author.
4. It **cannot prove remote organisation policy.** Unobserved remote policy is
   recorded as `NOT_OBSERVED`, never guessed.
5. It **cannot invent precedence** where the official documentation defines
   none — those cases are reported `UNSPECIFIED`.
6. It **cannot guarantee what the agent reads at runtime.** The receipt is a
   preflight snapshot of the filesystem at scan time; files read or changed
   mid-run are a different problem.
7. It **cannot prevent a user from bypassing the gate.** `verify` provides a
   blocking exit code; whether it actually runs before the agent starts
   depends on how the user or CI wires it in.

## Known limitations

Each of these is a recorded coordinator/worker decision or finding. None of
them is fixed, and none is softened here.

1. **Load, not safety.** The tool proves *which* instruction files load and
   *why* — not that their content is safe, and not that real agent binaries
   follow the documentation. (See also [What it does not prove](#what-it-does-not-prove).)
2. **Claude `@` import max depth is 4 hops** (SPEC-01, resolved in the
   FIX-R1 spec sync), per the official documentation: a chain of 4 imports
   passes, a 5th hop is enumerated with
   `allowed=false, reason="DEPTH_EXCEEDED"` and blocks. The spec book
   (§15.2 S13/S14) and the implementation plan (§3.3, §10.3) now agree
   ("≤ 4"; depth 4 PASS, depth 5 BLOCK); the earlier "≤ 5" text was a spec
   defect, fixed in the FIX-R1 spec sync. The implementation follows the
   official doc (depth 4), as before.
3. **`considered_but_not_applicable` is diagnostic only.** Paths that were
   considered but do not apply (e.g. a Copilot `applyTo` pattern that matches
   nothing) live in the discovery report (`report.not_applicable`) and the
   Oracle explain sidecar. They are **never in the receipt** — the frozen
   receipt schema has no slot for them and no new enum value is invented
   (SPEC-04).
4. **Copilot custom instruction dirs outside the repo classify
   `OUTSIDE_REPO` / `BLOCK`.** The trust classifier has no custom-directory
   trust root, so files under `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` that sit
   outside the repository are blocked even though the user configured the
   directory. Production and Oracle agree; this is recorded behaviour, not a
   redesign.
5. **Windows behaviour on Linux is string-only.** Real junction resolution,
   drive-letter handling, case-insensitive-filesystem behaviour, and UNC-share
   behaviour are `NOT_RUN` on Linux — only pure-string probes run here. There
   is **no case-insensitive discovery mode**: on a case-insensitive filesystem
   `Agents.md` would be found, on Linux it is not (F1). UNC imports degrade to
   `MISSING`, not `IMPORT_ESCAPE` (F2). Drive-relative spellings such as
   `@C:shared\note.md` are unreachable (F4). Drive-letter case is not folded
   (F1/F2/F4/F5). A deleted chain file silently drops out of the chain instead
   of being reported (F3). The Windows corpus (`fixtures/windows/`, 15 receipt
   cases) passes 15/15 on Linux with these behaviours pinned as expectations —
   it documents what the Linux implementation does, it does not prove Windows
   behaviour.
6. **T003 parser gap: `"@path"` is still parsed as an import.** A
   double-quoted `"@foo.md"` — the quote *before* the `@` — is parsed as an
   import of `foo.md` (verified live). Only `@"quoted.md"` (quote *after* the
   `@`) is excluded, along with code spans and fenced code blocks. Both
   implementations (production and Oracle) agree on the gap, so parity is
   unaffected — but the gap itself is real and undisclosed nowhere else.
7. **Claude upward discovery walks to the filesystem root.** Ancestor
   `CLAUDE.md` files are concatenated from the filesystem root downward to the
   CWD, so real ancestor files above the repository can be discovered. The
   result is machine-dependent unless the CWD is isolated (e.g. a container or
   a fixture home).
8. **Only `verify` gates on exit code.** `inspect`, `export`, and `oracle`
   exit 0 on any produced result, whatever the verdict (T008 D1). A script
   that gates on `inspect`'s exit code gates on nothing.
9. **Receipts are unsigned SHA-256.** There is no Sigstore/SLSA signature and
   no key management; a receipt proves the content hashed to that value, not
   who produced it.
10. **S12 real junction resolution is `NOT_RUN` on Linux.** Filesystem
    junction probes in the S0 corpus are pure-string only; real junction
    resolution awaits a Windows runner (T011). It is not faked as a pass.

## S0 evidence

The S0 gate (`scripts/s0_gate.py`, `review/S0_GATE.md`) is **PASS**. All numbers
below were measured live by the gate and re-verified for this README
(2026-11-18; see `review/tasks/P028-T013/TASK_RESULT.md` for the
command-by-command table):

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

| Measure | Result | Source |
|---|---|---|
| Golden fixtures | 60 (normal 20 / boundary 20 / adversarial 20) | `review/S0_GATE.md` |
| Production ↔ Oracle parity | 100% — source, trust, edge, verdict, receipt-hash (48/48 cases each) | `scripts/compare_oracle.py --all` (exit 0) |
| Determinism | 100/100 identical receipt hashes (`codex-basic`), 25/25 (`s0-git-tracked`) | S0 gate |
| Fail-closed | PASS 8/8 (malformed input fails closed) | S0 gate |
| Known escape detection | 15/15 | S0 gate |
| Source assertions | 99 entries × 6 fields × 2 implementations = 1188 (required ≥ 180) | S0 gate |
| Edge assertions | 46 entries × 7 fields × 2 implementations = 644 (required ≥ 100) | S0 gate |
| Python tests | **283 passed, 6 skipped** (`python -m pytest -q`, 7.22 s) | this task's run |
| Rust Oracle tests | **26 passed + 5 passed** (`cargo test`, 0 failed) | this task's run |
| Windows corpus | **15/15** receipt cases; source/trust/edge/verdict/hash parity 15/15; 10 pure-string probes 10/10 | `scripts/run_windows_corpus.py` (exit 0) |
| Network access | 0 | S0 gate |
| Human labels | 0 | S0 gate |

## Repository layout

```text
README.md                      this file (T013)
LICENSE                        MIT (T012)
pyproject.toml                 packaging: stdlib-only, console script `instructionroot`
instructionroot                repo-root launcher (no install needed)
00_contract/                   frozen contracts: profile_contract.json, receipt_schema.json,
                               policy_schema.json, PROJECT_BOOK.md, IMPLEMENTATION_PLAN.md
01_s0/                         S0 golden corpus (fixtures, expected, oracle, logs)
02_src/instructionroot/        production Python implementation
03_oracle/rust/                independent Rust Oracle (no shared code with production)
05_tests/                      unit / integration / golden / oracle tests
06_docs/                       PROFILES.md (human-readable profile contract)
fixtures/                      demo (PASS), demo-block (BLOCK), outside, windows
web/                           static HTML dashboard (T009)
.github/workflows/             instructionroot.yml — the CI gate (T010)
scripts/                       s0_gate.py, compare_oracle.py, run_windows_corpus.py,
                               security_static_check.py, run-verify.sh, simulate_ci.py
review/                        S0_GATE.md, TASK_RESULTs, and per-task evidence
```

## License

MIT — see [LICENSE](LICENSE). Third-party profile documentation is referenced
by URL and necessary fact only; no large copyrighted text is reproduced.

## Further reading

- `06_docs/PROFILES.md` — the full human-readable profile contract, including
  every `UNVERIFIED` item per harness.
- `00_contract/profile_contract.json` — the frozen, machine-readable profile
  contract (the authority if the docs disagree).
- `00_contract/receipt_schema.json` — the frozen receipt schema (v1).
- `00_contract/PROJECT_BOOK.md` — the product book: goals, honest boundary
  (§6), workflows (§7), and the full reference list (§22).
- `review/S0_GATE.md` — the S0 gate verdict and metrics.
- `review/tasks/P028-T013/TASK_RESULT.md` — this README's verification table:
  every command run, every number's source, and the book-vs-plan conflicts
  found while writing it.
