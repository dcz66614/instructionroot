# P028 InstructionRoot Resolve｜实施计划
> IMPLEMENTATION_PLAN.md  
> 版本：1.0.0  
> 项目 ID：P028  
> slug：`instructionroot`  
> 总工作量：88 Agent·小时  
> S0：T001–T007，共 72 小时；S0 失败立即停止  
> 零真人参与：强制  
> 许可：MIT

---

## 0. 执行总则

### 0.1 项目目标

在 88 Agent·小时内交付一个本地、确定性、跨 harness 的 instruction-chain preflight 工具：

> 给定 harness + CWD + 本地文件系统/Git 快照，计算该 harness 按公开规则会发现的 instruction sources，并生成 provenance/trust receipt。

MVP 不判断 instruction 内容是否恶意，不调用 LLM，不执行 instruction，不联网。

### 0.2 强制门禁

```text
T001 → T002 → T003 → T004 → T005 → T006 → T007
                                      │
                                      ▼
                                  S0 GATE
                                PASS / FAIL
                                  │
                         PASS ─────┴─────> T008–T014
                         FAIL ────────────> STOP
```

任何人不得因为“代码已经差不多”绕过 S0。

### 0.3 任务状态

每个任务：

```text
WAITING
READY
RUNNING
SUCCESS
RETRYABLE_ERROR
FATAL_ERROR
POLICY_BLOCKED
```

任务只有在：

- 输入明确；
- 输出路径明确；
- 禁止修改范围明确；
- 验收命令明确；
- 证据明确；

时才可进入 READY。

### 0.4 会话隔离

每个 TASK_ID：

- 新建独立 Agent 会话；
- 由 Muse 传入任务包；
- 不依赖上一 Agent 的聊天记忆；
- 先验收再合并；
- 构建者与 Oracle/审查者尽量使用不同模型/会话。

---

# 1. 工作区与交接结构

## 1.1 推荐工作区

```text
P028-instructionroot/
├── 00_contract/
│   ├── PROJECT_BOOK.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── profile_contract.json
│   └── receipt_schema.json
├── 01_s0/
│   ├── fixtures/
│   ├── expected/
│   ├── oracle/
│   └── logs/
├── 02_src/
│   └── instructionroot/
├── 03_oracle/
│   └── rust/
├── 04_ui/
├── 05_tests/
├── 06_docs/
├── 07_release/
└── review/
    ├── REVIEW_INDEX.md
    ├── REVIEW_PACK_01.md
    ├── S0_GATE.md
    └── HANDOFF.md
```

## 1.2 文件 ownership

| 文件/目录 | Owner |
|---|---|
| `00_contract/*` | Muse/架构任务；施工 Agent 只能在明确 TASK_ID 下修改 |
| `02_src/instructionroot/paths.py` | T002 |
| `02_src/instructionroot/snapshot.py` | T002 |
| `02_src/instructionroot/profiles/*` | T003 |
| `02_src/instructionroot/resolver.py` | T003 |
| `02_src/instructionroot/git.py` | T004 |
| `02_src/instructionroot/trust.py` | T004 |
| `02_src/instructionroot/imports.py` | T005 |
| `02_src/instructionroot/receipt.py` | T005/T008 |
| `03_oracle/rust/*` | T006 |
| `01_s0/*` | T001/T006/T007 |
| `04_ui/*` | T009 |
| `.github/workflows/*` | T010 |
| `README.md` / docs | T013 |
| `LICENSE` | T012/T013 |

---

# 2. 技术契约

## 2.1 Python Production Contract

最低：

```text
Python >= 3.12
推荐开发锁定：Python 3.14.x
```

原因：

- `pathlib` API 足够；
- `tomllib` 不需要；
- MVP 配置采用 JSON；
- 避免 YAML parser 依赖；
- Windows/Linux 均可。

核心依赖：

```text
stdlib first
```

不允许为核心解析器引入：

- LLM SDK；
- 网络客户端；
- GitHub API SDK；
- 浏览器自动化；
- shell framework。

## 2.2 Rust Oracle Contract

- stable Rust；
- T001 记录实际版本；
- `rust-toolchain.toml` 锁定；
- 只读 filesystem；
- `serde_json`；
- `sha2`；
- 不依赖 production Python。

## 2.3 Git Contract

只允许：

```text
git rev-parse --show-toplevel
git ls-files --error-unmatch -- <path>
git status --porcelain=v1 -- <path>
git log -1 --format=%H -- <path>
```

禁止：

```text
git fetch
git pull
git push
git checkout
git reset
git clean
```

所有 subprocess：

```python
subprocess.run(args, shell=False, ...)
```

禁止：

```python
shell=True
os.system(...)
```

---

# 3. Harness Profile Contract

## 3.1 Profile 必须版本化

```json
{
  "id": "codex",
  "version": "codex-2026-11",
  "source_url": "https://developers.openai.com/...",
  "rules_hash": "sha256:..."
}
```

Profile 一旦用于 release receipt，不允许静默修改。

## 3.2 Codex profile

依据公开文档建模：

- user/global scope：`~/.codex`
- project scope：repo root → CWD
- root-to-leaf order；
- later/more-specific guidance overrides earlier；
- `AGENTS.override.md` 作为可配置 fallback；
- size cap/其他运行时限制必须记录为 profile metadata。

注意：

> “profile 模型”不是“真实 Codex runtime trace”。

## 3.3 Claude Code profile

建模：

- `~/.claude/CLAUDE.md`
- 从 CWD 向上发现 `CLAUDE.md`；
- nested files 可在访问子树时按需发现；
- `@path` import；
- import depth ≤ 4；
- `CLAUDE.local.md` 的实际支持状态必须以 T001 当前官方文档为准，不能引用旧文档猜测。

## 3.4 Copilot CLI profile

建模：

- `$HOME/.copilot/copilot-instructions.md`
- `$HOME/.copilot/instructions/**/*.instructions.md`
- repo `.github/copilot-instructions.md`
- repo `.github/instructions/**/*.instructions.md`
- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`
- `applyTo`
- `/instructions` 可观察发现集合。

特别规则：

> Copilot CLI 的多源组合没有统一 general precedence；receipt 必须记录 `COMBINE_UNORDERED` 或 profile 文档允许的具体 precedence，不得擅自生成“第一优先级”。

---

# 4. 统一 Receipt Contract

## 4.1 Receipt 顶层

```json
{
  "receipt_version": 1,
  "profile": {},
  "workspace": {},
  "sources": [],
  "edges": [],
  "verdict": "PASS",
  "receipt_hash": "sha256:..."
}
```

## 4.2 Source

```json
{
  "source_id": "src-0001",
  "raw_path": "~/...",
  "canonical_path": "<HOME>/...",
  "resolved_path": "<HOME>/...",
  "scope": "user",
  "phase": "startup",
  "discovery_rule": "codex.user",
  "precedence": {
    "kind": "before",
    "relative_to": ["src-0002"]
  },
  "sha256": "...",
  "git": {
    "repo": null,
    "tracked": false,
    "modified": false,
    "head_commit": null
  },
  "trust": "USER_SCOPE"
}
```

## 4.3 Edge

```json
{
  "edge_id": "edge-0001",
  "from": "src-0002",
  "syntax": "@../shared/rules.md",
  "to": "src-0003",
  "allowed": true,
  "reason": "WITHIN_REPO"
}
```

## 4.4 Verdict

固定：

```text
PASS
WARN
BLOCK
INPUT_ERROR
UNSUPPORTED_PROFILE
INTERNAL_ERROR
```

---

# 5. 任务依赖图

```text
T001
 │
 ├──► T002
 │      │
 │      ├──► T003
 │      │      │
 │      │      └────┐
 │      │           │
 │      └──► T004 ──┼──► T005
 │                   │      │
 │                   └──────┼──► T006
 │                          │
 └──────────────────────────┴──► T007
                                   │
                              S0 GATE
                                   │
              ┌────────────────────┼───────────────────┐
              ▼                    ▼                   ▼
             T008                 T011                T012
              │                    │                   │
              ├────► T009         │                   ├──► T013
              ├────► T010         │                   │
              └────────────────────┴───────────────────┴──► T014
```

---

# 6. TASK T001 — 问题/契约冻结 + Harness Profiles

**工时：8h**  
**阶段：S0**  
**依赖：无**

## 6.1 目标

冻结：

- 3 个 harness；
- profile schema；
- trust enum；
- receipt schema；
- policy schema；
- S0 golden case 格式。

## 6.2 输入

- PROJECT_BOOK.md；
- 官方 Codex docs；
- 官方 Claude docs；
- 官方 VS Code/GitHub docs。

## 6.3 输出

```text
00_contract/profile_contract.json
00_contract/receipt_schema.json
00_contract/policy_schema.json
docs/PROFILES.md
01_s0/fixtures/README.md
```

## 6.4 禁止修改

- `02_src/*`
- `03_oracle/*`
- UI

## 6.5 验收

```bash
python -m json.tool 00_contract/profile_contract.json
python -m json.tool 00_contract/receipt_schema.json
python -m json.tool 00_contract/policy_schema.json
```

必须输出：

```text
T001 PASS
profiles=3
receipt_schema_version=1
policy_schema_version=1
```

## 6.6 失败回退

若官方规则无法明确：

- 不猜；
- profile 标 `UNVERIFIED`；
- 若核心 discovery rule 无法确定，T001 FAIL；
- 不进入 T002。

---

# 7. TASK T002 — Filesystem Snapshot + Canonical Path

**工时：12h**  
**阶段：S0**  
**依赖：T001**

## 7.1 目标

实现：

```text
snapshot.py
paths.py
```

支持：

- cwd；
- home；
- repo root；
- absolute/relative；
- symlink；
- junction；
- Windows drive；
- missing path；
- loop；
- Unicode。

## 7.2 原子任务

1. `Path.resolve()` wrapper；
2. lexical vs resolved path 双记录；
3. root containment；
4. symlink escape；
5. Windows junction；
6. stable path serialization；
7. fixture builder。

## 7.3 输出

```text
02_src/instructionroot/paths.py
02_src/instructionroot/snapshot.py
05_tests/unit/test_paths.py
01_s0/fixtures/fs/
```

## 7.4 验收

```bash
python -m pytest 05_tests/unit/test_paths.py -q
```

门槛：

- ≥ 30 tests；
- 0 fail；
- Linux pass；
- Windows runner若可用必须 pass；
- 不可用平台明确 NOT_RUN，不伪造。

---

# 8. TASK T003 — Harness Resolution Engine

**工时：12h**  
**阶段：S0**  
**依赖：T001、T002**

## 8.1 目标

实现：

```text
profiles/codex.py
profiles/claude.py
profiles/copilot.py
resolver.py
```

## 8.2 原子任务

### T003-A

Profile interface：

```python
discover(snapshot, cwd, policy) -> list[SourceCandidate]
```

### T003-B

Codex：

- user;
- repo root;
- nested;
- order；
- override fallback。

### T003-C

Claude：

- upward discovery；
- nested on-demand；
- import candidate；
- depth counter。

### T003-D

Copilot：

- user;
- repo;
- path-specific；
- `applyTo`;
- combine semantics。

### T003-E

Unknown precedence

任何 profile 未定义：

```text
precedence.kind = UNSPECIFIED
```

不得自动排序。

## 8.3 验收

```bash
python -m pytest 05_tests/unit/test_resolver.py -q
python scripts/run_golden.py --stage resolver
```

门槛：

```text
golden_source_order=100%
golden_source_set=100%
```

---

# 9. TASK T004 — Git Provenance + Trust Classifier

**工时：10h**  
**阶段：S0**  
**依赖：T002**

## 9.1 目标

实现：

```text
git.py
provenance.py
trust.py
```

## 9.2 只读 Git

允许：

```text
rev-parse
ls-files
status
log
```

禁止所有 mutation/network commands。

## 9.3 Trust algorithm

输入：

```text
resolved_path
repo_root
git_state
policy
```

输出：

```text
trust
reason_code
```

## 9.4 reason code

```text
R001 WITHIN_REPO_TRACKED
R002 WITHIN_REPO_MODIFIED
R003 WITHIN_REPO_UNTRACKED
R004 USER_SCOPE
R005 OUTSIDE_REPO
R006 SYMLINK_ESCAPE
R007 IMPORT_ESCAPE
R008 MISSING
R009 NOT_OBSERVED
R010 UNSPECIFIED_PRECEDENCE
```

## 9.5 验收

```bash
python -m pytest 05_tests/unit/test_git.py 05_tests/unit/test_trust.py -q
```

门槛：

- tracked/untracked/modified 100%；
- outside repo 100%；
- escape 100%；
- git mutation calls = 0。

---

# 10. TASK T005 — Import Graph + Escape Detection

**工时：10h**  
**阶段：S0**  
**依赖：T003、T004**

## 10.1 目标

实现：

```text
imports.py
```

只解析 profile-contract 明确声明的 syntax。

## 10.2 安全要求

禁止：

- 执行 import；
- 读取 arbitrary network URL；
- follow shell commands；
- follow Markdown link as executable instruction unless profile says so。

## 10.3 Claude

测试：

```text
depth 0
depth 1
...
depth 4
depth 5 → BLOCK
```

## 10.4 Copilot

测试：

- repo-relative reference；
- allowed custom instruction dir；
- absolute path → BLOCK；
- `~/` reference → BLOCK。

## 10.5 验收

```bash
python -m pytest 05_tests/unit/test_imports.py -q
python scripts/run_golden.py --stage imports
```

门槛：

```text
edge_parity=100%
escape_detection=100%
```

---

# 11. TASK T006 — Rust Independent Oracle

**工时：10h**  
**阶段：S0**  
**依赖：T001、T003、T004、T005**

## 11.1 目标

实现：

```text
03_oracle/rust/
```

Oracle 不 import Python。

## 11.2 独立实现

必须独立实现：

- path normalization；
- harness resolution；
- trust classification；
- import edges；
- canonical receipt；
- SHA-256。

## 11.3 禁止

Oracle 不得：

- 执行 production CLI；
- 读取 production JSON answer；
- import Python；
- 调用网络；
- 复用 production rule table。

## 11.4 验收

```bash
cargo test --manifest-path 03_oracle/rust/Cargo.toml
python scripts/compare_oracle.py --all
```

门槛：

```text
source_parity=100%
trust_parity=100%
edge_parity=100%
verdict_parity=100%
hash_parity=100%
```

---

# 12. TASK T007 — S0 Golden Corpus + Gate

**工时：10h**  
**阶段：S0**  
**依赖：T001–T006**

## 12.1 目标

建立正式 S0 gate。

## 12.2 Golden corpus

至少：

```text
60 workspaces
180+ source assertions
100+ edge assertions
```

分层：

```text
20 normal
20 boundary
20 adversarial synthetic
```

## 12.3 adversarial synthetic

只模拟：

- Downloads source；
- untracked source；
- modified source；
- symlink escape；
- import escape；
- missing file；
- ambiguous precedence。

不包含真实恶意 payload。

## 12.4 Gate 命令

```bash
python scripts/s0_gate.py
```

必须输出：

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

## 12.5 Gate 证据

生成：

```text
review/S0_GATE.md
review/S0_LOG.txt
review/S0_ORACLE_SUMMARY.json
```

## 12.6 S0 FAIL

如果：

```text
RESULT=FAIL
```

立即：

```text
review/S0_GATE.md
status=S0_FAIL
```

并停止 T008–T014。

---

# 13. TASK T008 — CLI / Policy / Exit Codes

**工时：4h**  
**阶段：Post-S0**  
**依赖：S0 PASS**

## 13.1 命令

```text
instructionroot inspect
instructionroot verify
instructionroot export
instructionroot profile list
instructionroot oracle
instructionroot version
```

## 13.2 输出

```text
terminal
json
md
html
```

## 13.3 验收

```bash
instructionroot --help
instructionroot profile list
instructionroot verify --harness codex --cwd fixtures/demo
```

---

# 14. TASK T009 — Static HTML Dashboard

**工时：4h**  
**阶段：Post-S0**  
**依赖：T008**

## 14.1 目标

无 build server：

```text
web/index.html
web/app.js
web/style.css
```

输入：

```text
receipt.json
```

## 14.2 页面

必须有：

1. Verdict header；
2. source tree；
3. effective chain；
4. trust badges；
5. import graph；
6. why panel；
7. raw JSON；
8. export button。

## 14.3 验收

```bash
python -m http.server 8765 --directory web
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

检查：

- 不请求外网；
- receipt 可加载；
- BLOCK source 明显；
- 图与列表一致。

---

# 15. TASK T010 — GitHub Action / Pre-commit

**工时：2h**  
**阶段：Post-S0**  
**依赖：T008**

## 15.1 Action

```yaml
name: instructionroot
```

执行：

```text
instructionroot verify --harness <configured>
```

## 15.2 安全要求

Action：

- 不上传 instruction contents；
- 不安装随机第三方工具；
- 使用 pinned action versions；
- 只读 repository；
- fail on BLOCK。

## 15.3 验收

Synthetic repository：

```text
PASS fixture → CI success
BLOCK fixture → CI failure
```

---

# 16. TASK T011 — Corpus 扩充 + Windows cases

**工时：2h**  
**阶段：Post-S0**  
**依赖：T007**

补充：

- Windows drive；
- junction；
- case behavior；
- UNC-like path；
- Unicode；
- deleted/renamed Git file。

输出：

```text
fixtures/windows/
```

---

# 17. TASK T012 — Security / Privacy / Packaging

**工时：1h**  
**阶段：Post-S0**  
**依赖：T008**

检查：

- `shell=True` 搜索；
- network imports；
- telemetry；
- secrets in receipt；
- license；
- package metadata。

命令：

```bash
python scripts/security_static_check.py
```

必须：

```text
shell_true=0
network_runtime=0
telemetry=0
secret_fixture_leaks=0
```

---

# 18. TASK T013 — README / Examples / MIT

**工时：1h**  
**阶段：Post-S0**  
**依赖：T009、T010**

README 必须在首屏回答：

```text
What does it verify?
What does it not verify?
Supported harnesses?
10-second demo?
Install?
CI?
Receipt example?
Limitations?
```

必须包含：

```text
MIT
```

以及：

- 官方 profile URLs；
- known limitations；
- no-LLM statement；
- zero-network statement；
- S0 evidence。

---

# 19. TASK T014 — Integration / Performance / Release

**工时：2h**  
**阶段：Post-S0**  
**依赖：T008–T013**

## 19.1 Integration

```bash
python -m pytest -q
cargo test --manifest-path 03_oracle/rust/Cargo.toml
python scripts/compare_oracle.py --all
```

## 19.2 Determinism

同一 fixture 连续 100 次：

```text
receipt_hash same
```

## 19.3 Performance

Synthetic large case：

```text
500 candidates
100 edges
10 git roots
```

门槛：

```text
p95 <= 500ms
```

若超标：

- 记录；
- 不扩大 scope；
- 若不影响正常 CLI，则 P2。

## 19.4 Release

生成：

```text
P028-instructionroot-release.zip
SHA256SUMS.txt
RELEASE_MANIFEST.json
```

---

# 20. 测试策略

## 20.1 Unit

覆盖：

- path;
- git;
- profiles;
- trust;
- imports;
- receipt canonicalization。

## 20.2 Golden

每个 fixture：

```text
input
expected sources
expected edges
expected verdict
expected receipt hash
```

## 20.3 Oracle

生产实现与 Oracle 必须交叉复核。

## 20.4 Property tests

至少：

1. path normalization idempotent；
2. receipt serialization idempotent；
3. source ordering stable；
4. adding irrelevant file doesn't change receipt；
5. changing source bytes changes source hash；
6. moving outside repo changes trust；
7. symlink target escape cannot become PASS。

## 20.5 Negative tests

必须包含：

```text
missing CWD
non-git repo
broken symlink
symlink loop
invalid JSON
unknown harness
unknown profile version
invalid applyTo
import depth overflow
path traversal
permission denied
```

---

# 21. 验收标准

## 21.1 S0 acceptance

必须全部：

- 3 profiles；
- 60 fixtures；
- 100% production/Oracle parity；
- 100/100 deterministic reruns；
- 100% known escape detection；
- malformed input fail-closed；
- no network；
- no human labels。

## 21.2 MVP acceptance

在 S0 通过后，再要求：

- CLI 可运行；
- HTML 可打开；
- GitHub Action 可阻断；
- README 可从零安装；
- MIT；
- release hash；
- source manifest；
- no unverified feature described as PASS。

---

# 22. Risk Register

| 风险 | 等级 | 处理 |
|---|---|---|
| harness 文档变更 | P1 | profile version + source URL + revalidation |
| 官方 precedence 未定义 | P0 | 不猜，输出 UNSPECIFIED |
| symlink/junction 差异 | P1 | OS-specific fixtures |
| Git 命令差异 | P1 | capture version + fallback |
| home path privacy | P1 | redact display |
| Oracle 与 production 同 bug | P0 | different language + separate implementation |
| import syntax 误判 | P1 | profile-specific only |
| 用户误解为 content security | P0 | UI/README repeated boundary |
| UI 超 scope | P2 | static only |
| 性能不足 | P2 | profile/candidate cache |
| remote org policy 不可见 | P1 | NOT_OBSERVED |
| 文件在扫描后变化 | P1 | snapshot timestamp/hash; no runtime guarantee |

---

# 23. 模型工种分配建议

不指定模型名称、额度或账号；Muse 只从自己已经实测可用的免费模型清单中选择。

| 工种 | 建议任务 |
|---|---|
| Python implementation | T002–T005、T008 |
| Rust independent engineer | T006 |
| QA/golden | T007、T011、T014 |
| UI | T009 |
| CI/release | T010、T012、T014 |
| Documentation | T013 |
| Security reviewer | T004/T005/T012 |
| Independent Oracle reviewer | T006/T007 |

Builder 与 reviewer 尽量不同模型/不同新会话。

---

# 24. 每个任务的标准 TASK_ID 包

Muse 派工必须使用：

```text
TASK_ID: P028-T00X
PROJECT_ID: P028
GOAL:
INPUTS:
OUTPUTS:
MUST_READ:
DO_NOT_MODIFY:
COMMANDS:
EXPECTED_EVIDENCE:
DONE_WHEN:
FAILURE_STOP:
HANDOFF:
```

示例：

```text
TASK_ID: P028-T006
PROJECT_ID: P028

GOAL:
Implement an independent Rust Oracle for source discovery,
trust classification, import edges, and canonical receipt hash.

INPUTS:
- 00_contract/profile_contract.json
- 00_contract/receipt_schema.json
- 01_s0/fixtures/

OUTPUTS:
- 03_oracle/rust/**
- review/T006_EVIDENCE.md

MUST_READ:
- profile contract
- receipt schema
- T005 handoff

DO_NOT_MODIFY:
- 02_src/**
- 01_s0/expected/**

COMMANDS:
cargo test --manifest-path 03_oracle/rust/Cargo.toml
python scripts/compare_oracle.py --all

EXPECTED_EVIDENCE:
- test log
- parity summary
- oracle binary version
- changed file list

DONE_WHEN:
source/trust/edge/verdict/hash parity = 100%

FAILURE_STOP:
Any parity < 100%; do not alter expected outputs to match production.

HANDOFF:
review/T006_EVIDENCE.md
```

---

# 25. 集成顺序

严格：

```text
T001 contract
  ↓
T002 path/snapshot
  ↓
T003 profiles/resolver
  ↓
T004 git/trust
  ↓
T005 imports/receipt
  ↓
T006 Oracle
  ↓
T007 S0 gate
  ↓
T008 CLI
  ├── T009 UI
  ├── T010 CI
  └── T011 corpus
       ↓
T012 security
       ↓
T013 docs
       ↓
T014 release
```

不允许：

- UI 先于 S0；
- CI 先于 CLI contract；
- 修改 Oracle expected output 来“修绿”；
- builder 自己决定新 profile；
- 在 T014 才第一次运行 Oracle。

---

# 26. 证据包

## 26.1 每任务

```text
review/tasks/P028-T00X/
├── TASK_RESULT.md
├── changed-files.txt
├── command-log.txt
├── test-summary.json
└── handoff.md
```

## 26.2 S0

```text
review/
├── S0_GATE.md
├── S0_LOG.txt
├── S0_ORACLE_SUMMARY.json
├── S0_RECEIPT_HASHES.txt
└── S0_FIXTURE_MANIFEST.json
```

## 26.3 最终

```text
REVIEW_INDEX.md
REVIEW_PACK_01.md
REVIEW_PACK_02.md
REVIEW_PACK_03.md
RELEASE_MANIFEST.json
SHA256SUMS.txt
```

---

# 27. Release Manifest

必须包含：

```json
{
  "project_id": "P028",
  "version": "1.0.0",
  "license": "MIT",
  "source_sha256": "...",
  "oracle_sha256": "...",
  "fixture_manifest_sha256": "...",
  "profile_versions": {
    "codex": "codex-2026-11",
    "claude-code": "claude-code-2026-11",
    "copilot-cli": "copilot-cli-2026-11"
  },
  "s0": {
    "status": "PASS",
    "fixtures": 60,
    "oracle_parity": 1.0,
    "determinism_runs": 100
  }
}
```

---

# 28. 交付清单

必须存在：

```text
[ ] PROJECT_BOOK.md
[ ] IMPLEMENTATION_PLAN.md
[ ] README.md
[ ] LICENSE
[ ] pyproject.toml
[ ] src/**
[ ] oracle/**
[ ] tests/**
[ ] fixtures/**
[ ] web/**
[ ] .github/workflows/**
[ ] docs/PROFILES.md
[ ] docs/RECEIPT_SCHEMA.md
[ ] docs/LIMITATIONS.md
[ ] REVIEW_INDEX.md
[ ] REVIEW_PACK_XX.md
[ ] S0_GATE.md
[ ] RELEASE_MANIFEST.json
[ ] SHA256SUMS.txt
```

---

# 29. 真实运行边界

本计划书没有执行任何项目源码，因此：

```text
BUILD: NOT_VERIFIED
TEST: NOT_VERIFIED
S0: NOT_RUN
PERFORMANCE: NOT_RUN
WINDOWS: NOT_RUN
RELEASE: NOT_READY
```

这些状态必须保持，直到 Muse 在 VM 中提供真实日志。

---

# 30. 最终完成定义

只有同时满足以下条件，才允许标记项目“施工完成”：

1. S0 PASS；
2. T008–T014 完成；
3. 全量测试通过；
4. Rust Oracle 独立通过；
5. 100 次 deterministic rerun；
6. GitHub Action synthetic PASS/BLOCK 双向验证；
7. README 与实际行为一致；
8. LICENSE 为 MIT；
9. release manifest 与发布包 hash 一致；
10. 没有未披露的“计划中但实际未实现”功能；
11. 所有 known limitations 已写入；
12. 完整 source + tests + fixtures + evidence 可供独立终审。

**施工完成 ≠ 最终验收通过。**

最终验收仍由 ChatGPT 在同一立项对话中依据真实交付证据独立完成。

---

## 附录 A：关键官方来源

- Codex `AGENTS.md`: https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide
- Claude Code memory: https://docs.anthropic.com/zh-CN/docs/claude-code/memory
- VS Code custom instructions: https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference
- GitHub Copilot custom instructions: https://docs.github.com/en/copilot/concepts/prompting-and-context/custom-instructions
- GitHub Copilot CLI instructions: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions
- Forever Security incident: https://forever.security/blog/hijacking-ai-agents-via-downloads-folder/
- BleepingComputer incident coverage: https://www.bleepingcomputer.com/news/security/ai-coding-agents-hijacked-using-agentsmd-file-in-downloads-folder/
- agentdrift: https://github.com/kriskimmerle/agentdrift
- agentsmd: https://github.com/kriskimmerle/agentsmd
- instruction-files: https://github.com/btakita/instruction-files
- agent-security-skill: https://github.com/olanokhin/agent-security-skill
- Python pathlib: https://docs.python.org/3/library/pathlib.html
- Python subprocess: https://docs.python.org/3/library/subprocess.html
- RFC 8785: https://www.rfc-editor.org/rfc/rfc8785.html

## 附录 B：禁止复制的内容

不得把以下项目直接换名：

- `agentdrift` 的 20 条安全规则；
- `agentsmd` 的内容扫描规则；
- `instruction-files` 的文档质量规则；
- `agent-security-skill` 的 OWASP checklist；
- vendor UI 的 `/memory` 或 `/instructions` 功能。

本项目只实现：

> **harness resolution + provenance + trust boundary + deterministic receipt。**

