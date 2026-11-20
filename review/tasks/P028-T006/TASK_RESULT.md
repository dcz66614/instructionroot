# P028-T006 TASK_RESULT — 独立 Rust Oracle

- **任务**: P028-T006，构建独立 Rust Oracle（path normalization、harness
  resolution、trust classification、import edges、canonical receipt
  RFC 8785 JCS、SHA-256），与 Python 生产实现完全独立。
- **完成时间**: 2026-11-18（UTC）
- **工作目录**: `~/workspace/p028-instructionroot/`（git main；
  本任务开始时 HEAD 为 `9e1fdb5`，期间 T005 以 `ec98b7c` 提交，
  Oracle 按协调员补充口径与 T005 的可执行代码对齐，见 §5）
- **状态**: ✅ 完成。`cargo test` 31/31 通过；
  `compare_oracle.py --all` 5 项 parity 均为 100%，fs 100%，
  git 场景 PASS，退出码 0。

## 1. 改动文件清单

新增（未提交；提交由协调员做）：

| 文件 | 说明 |
| --- | --- |
| `03_oracle/rust/Cargo.toml` | 包 `instructionroot-oracle` 0.1.0，edition 2021，依赖 serde_json 1.0.154、sha2 0.10.9 |
| `03_oracle/rust/Cargo.lock` | 依赖锁定（4,873 B，随构建生成） |
| `03_oracle/rust/rust-toolchain.toml` | `channel = "1.100.0"` |
| `03_oracle/rust/README.md` | 输入格式、子命令、退出码、对齐口径 |
| `03_oracle/rust/src/main.rs` | CLI：`resolve` / `canonicalize` / `--version` |
| `03_oracle/rust/src/paths.rs` | 词法 canonical 化、component-wise symlink 解析（hop 上限 40）、Windows 拼写、SHA-256 |
| `03_oracle/rust/src/git.rs` | 仅 4 条 allowlisted git 命令，30s 超时 |
| `03_oracle/rust/src/trust.rs` | R001–R010 分类（§13.4 first-match-wins）、13 字段 Policy、verdict 推导 |
| `03_oracle/rust/src/jcs.rs` | RFC 8785 JCS 从零实现（UTF-16 码元键排序、ECMAScript 数字）+ SHA-256 |
| `03_oracle/rust/src/textscan.rs` | frontmatter 子集、applyTo、fnmatchcase glob、`@` 引用扫描 |
| `03_oracle/rust/src/profiles.rs` | 三 profile discovery、统一 import 图（T005 口径） |
| `03_oracle/rust/src/receipt.rs` | receipt 组装、hash、explain sidecar |
| `03_oracle/rust/tests/cli.rs` | 5 个 CLI 端到端集成测试（真实 git 仓库） |
| `scripts/compare_oracle.py` | parity 对比脚本（供 T007 的 S0 门禁复用），见 §3 |

未改动：`00_contract/*`（冻结）、`02_src/*`（只读；为解语义歧义读
过 T003/T004/T005 代码，未复制逻辑、未调用 Python、未读生产
receipt 当 ground truth）、`04_ui/*`、`01_s0/fixtures/*`、
`01_s0/expected/*`、`.venv/`、T005 的任何文件。
`review/COORDINATOR_LOG.md` 的修改不是本任务所做（任务开始前
已是 modified 状态，属协调员的补充口径写入）。

**提交注意**：`03_oracle/rust/target/` 为构建产物（debug +
release，含 Oracle 二进制），仓库 `.gitignore` 的 `/target/`
只覆盖根目录，未覆盖此处；提交时请排除 `target/`（或补一条
`03_oracle/rust/target/` 到 `.gitignore`），只提交源码 +
`Cargo.lock`。

## 2. 验收命令输出

### 工具链

```text
rustc 1.100.0 (0ef1bc386 2026-11-09)
cargo 1.100.0 (3acc79c0c 2026-11-05)
```

crates.io 拉取：成功（经 egress 代理）。`cargo fetch` 拉到
serde_json 1.0.154 + sha2 0.10.9，`Cargo.lock` 已生成并随
Oracle 一起放在工作目录。未伪造 Oracle、未用 Python 冒充。

### `cargo test --manifest-path 03_oracle/rust/Cargo.toml`

```text
running 26 tests
test result: ok. 26 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
running 5 tests
test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

26 个单元测试 + 5 个集成测试，全部通过。6 条 dead-code 警告
（bin crate 内未被二进制入口直接使用的 pub 项，如
`TRUST_PRIORITY`、`trust_priority_index`、`CanonicalPath::valid`），
无害，已在 `03_oracle/rust/README.md` 记录。

### `.venv/bin/python scripts/compare_oracle.py --all`（退出码 0）

```text
resolver_cases=20 imports_cases=15 fs_cases=12 fs_probes=25
source_parity=100.0% trust_parity=100.0% edge_parity=100.0% verdict_parity=100.0% hash_parity=100.0%
fs_parity=100.0% git_scenarios=PASS
```

### 生产 golden 自检（确认对比基准本身是绿的）

```text
.venv/bin/python scripts/run_golden.py --stage resolver
cases=20 passed=20 failed=0
golden_source_order=100.0%
golden_source_set=100.0%
.venv/bin/python scripts/run_golden.py --stage imports
cases=15 passed=15 failed=0
golden_edge_parity=100.0%
golden_escape_detection=100.0%
```

## 3. compare_oracle.py 的对比口径

- **resolver（20）**：source set + order（copilot 只比 set）、
  scope/phase/precedence_kind/also_discovered_by、not-applicable
  （取自 Oracle `--explain` sidecar）、Claude import candidates
  （reason 映射 `OK` ↔ `WITHIN_REPO`/`WITHIN_HOME`）、整份 receipt
  与生产参考逐字段比对、hash 三重校验。
- **imports（15）**：edge 多重集（from/syntax/depth/canonical
  target/resolved target/allowed/reason，取自 explain）、verdict
  对 `expected_verdict`（合成 trust；fixture 文件均已提交，真实
  git 状态与合成口径一致）、整份 receipt 与生产参考比对、hash。
- **fs（12，25 probes）**：`oracle canonicalize` 探测，期望值在
  脚本内硬编码写明；另与生产 `paths.canonicalize` 逐字段交叉核对
  （含 windows-paths.json 的 4 个纯字符串用例；真实 Windows
  解析仍为 NOT_RUN）。
- **git/trust（6 场景，临时仓库现建）**：clean / worktree 修改 /
  暂存修改 / untracked / 暂存新文件（tracked+modified）/ 非 git
  工作区；核对 receipt 的 git（tracked/modified/head_commit）与
  trust 字段；非 git 场景另与生产 receipt 全量比对。
- **生产参考 receipt**：由脚本用生产模块现场组装
  （`discover_with_report` + 真实 git 状态 + `classify_trust` +
  `build_import_graph` + `build_receipt`，含 import-escape 的
  trust 覆盖），不是 golden 文件。
- **hash parity**：三重——Oracle 自带 hash、脚本内独立 RFC 8785
  JCS（按 RFC 文本另写，stdlib only，不 import 生产 receipt 模块）
  重算、生产参考 receipt_hash，三者一致才算通过。

## 4. 本轮修复的两个单元测试失败（均已绿）

1. `jcs::tests::key_sort_is_utf16_code_units`：根因是测试字面量
   错误——原先手写的 U+E000 字面字符在编辑中丢失，变成空字符串
   key（空串在任何排序下都排第一，掩盖了测试意图），比较器本身
   正确。已改为显式 `\u{e000}` / `\u{10000}` 转义。
2. `textscan::tests::imports_skip_code_and_quotes`：测试期望错误——
   按 CQ-4，`"@quoted/c.md"`（引号在 @ 之前）**会被**解析；已按
   当前行为修正期望，并补 `@"path"` 排除用例。

## 5. 协调员补充口径对齐（CQ-1～CQ-10，逐条确认）

| # | 口径 | Oracle 状态 |
| --- | --- | --- |
| CQ-1 | Copilot 相对引用按**文件相对**解析（U-09 仍 UNVERIFIED） | ✅ 已改：相对引用按文件相对解析，无深度上限，允许目标继续 BFS 展开；集成测试 `resolve_copilot_relative_expands_and_absolute_blocks` 覆盖（`.github/` 下的 `@../shared/ok.md` 展开，`@/etc/nope.md` BLOCK） |
| CQ-2 | edge `from`：depth≥2 导入者无 source_id，用其 canonical path；`to` 是 source 则写 id，否则 null | ✅ 已改（`receipt.rs`）；集成测试断言 depth-2 edge 的 `from` 为 canonical path |
| CQ-3 | Claude import 批准根 = repo + home；home 内目标 WITHIN_HOME、允许 | ⚠️ 见契约问题 C-05：Oracle 按 **T005 可执行代码**取 repo + cwd + home + additional-dirs；两读法在全部 35 个现有金样本上等价（cwd 总在 repo 内、无 additional dirs），compare 全绿。措辞差异需协调员确认 |
| CQ-4 | `"@path"` 仍被解析，只有 `@"path"` 被排除；不修 | ✅ 扫描器原样保留；单元测试已按此修正 |
| CQ-5 | 用户级 copilot-instructions.md 的 `@` 按文件名展开 | ✅ 已改：expandable = rule ∈ {user, repo-wide, agents, claude, custom-dirs} 且 basename ∈ {copilot-instructions.md, AGENTS.md, CLAUDE.md} |
| CQ-6 | `.claude/CLAUDE.md` 的 `@` 不展开（fail-closed） | ✅ 已对齐为 T005 的 `/.claude/` 子串判定 |
| CQ-7 | Copilot code-span/引号排除复用 T003 解析器 | ✅ 共享 `parse_imports` |
| CQ-8 | `considered_but_not_applicable` 在 DiscoveryReport，不进 receipt | ✅ 已改：receipt 不含该字段（也不含 `also_discovered_by`，生产 `build_receipt` 会拒收未知字段）；两者只进 `--explain` sidecar |
| CQ-9 | NOT_OBSERVED trust → 无条件 BLOCK | ✅ 已有；另见 C-07（MISSING 的区分） |
| CQ-10 | escape 检查优先于 MISSING；edge BLOCK 按 policy 字面 | ✅ 已改：检查顺序为 Copilot 句法 BLOCK → UNRESOLVABLE → Claude depth → resolved None → escape → MISSING → 允许；verdict edge 规则已按字面实现 |

## 6. 其他对齐细节（与 T005 可执行代码逐条核对后改动）

- **检查顺序**：旧 Oracle 先查 MISSING 再查 escape；已按 T005
  `imports.py` 改为 escape 在前（`claude-symlink-escape` 与
  `copilot-absolute` 金样本覆盖）。
- **reason 词汇**：允许边用 `WITHIN_REPO` / `WITHIN_CUSTOM_DIR` /
  `WITHIN_HOME`（旧 Oracle 用 `OK`）；compare 脚本在 resolver
  段做 `OK` ↔ `WITHIN_*` 映射。
- **verdict 推导**（与 T005 `receipt.derive_verdict` 结构逐条一致）：
  MISSING 只在 `block_missing_reference` 时 BLOCK；
  GIT_MODIFIED 不继承 `allow_repo_tracked` 的 BLOCK（只作用于
  GIT_TRACKED）；user/managed scope 检查按键 `scope` 而非 trust
  （与 trust 无关的独立检查）。
- **precedence `detail`**：跟生产 receipt 构建器的常量（见 C-06），
  否则 receipt hash 无法逐字节对齐。
- **Windows bug-compat**：`C:\x` 的 resolved 为 `/C:/x`（与 Python
  `canonicalize` 的 Linux 行为逐字节一致）；旧 Oracle 的
  resolved=canonical 特殊处理已删除，单元测试已 pin 住。
- **Copilot `@~user/...`**：T005 会因 `canon` 未绑定而崩溃
  （`UnboundLocalError`，见 C-08）；Oracle 改为 fail-closed
  （IMPORT_ESCAPE，targets null）。无金样本覆盖。
- **receipt 字段**：`policy` 恒 present；每 source 恒带
  `symlink_target` / `is_symlink`；每 edge 恒带 `resolved_target`；
  `profile.rules_hash` 与 `workspace.home` 恒 present。

## 7. 契约问题

### C-01（已由协调员裁决，关闭）

Copilot 相对引用基准：按 CQ-1 文件相对解析（工作假设），U-09
仍为 UNVERIFIED。Oracle 与 T005 同口径。

### C-02（已知缺陷，终审披露）

CQ-4：T003 解析器缺口——`"@path"`（引号在 @ 之前）仍被解析，
只有 `@"path"` 被排除。T005 与 Oracle 均为保 parity 原样复用，
未修。终审时披露。

### C-03（SPEC-01，已裁决）

Claude import 最大深度 4 跳（不是 spec book 的 5 跳）。

### C-04（SPEC-04，已裁决）

`considered_but_not_applicable` 在 DiscoveryReport 内部，不进
receipt（CQ-8）。Oracle 把它与 `also_discovered_by` 一起放在
`--explain` sidecar，compare 脚本据此核对。

### C-05（待协调员确认）⚠️

CQ-3 的措辞与代码不一致：协调员补充口径写批准根为 "repo +
home"；T005 的可执行代码（`imports.py` §2.1 +
`_reason_for_roots`）实际取 repo + cwd + home +
additional-dirs（cwd/additional 判 WITHIN_REPO），T005
TASK_RESULT §5 的 CQ-3 行写的是简写。Oracle 跟**代码**（parity
以可执行代码 + golden 为准）。两读法在全部 35 个现有金样本上
等价：所有 fixture 的 cwd 都在 repo 内，且没有任何 fixture 设
additional dirs。分叉只会出现在未来用例（非 git 的 Claude 工作
区且 cwd 在 home 外、或设置了 additional dirs）。请协调员确认
以代码为准，还是把代码收紧为 "repo + home"。

### C-06（待协调员确认）⚠️

precedence `detail` 字符串：契约 `profile_contract.json` 的
per-rule 文本与生产构建器的常量有 3 处差异——

1. `claude-code.project`：契约多一句 "Override semantics between
   files: UNSPECIFIED."，生产没有；
2. `claude-code.rules-path-scoped`：契约 "ordering relative to
   other sources"，生产 "ordering relative to the startup chain"；
3. `copilot-cli.user` / `copilot-cli.repo-wide`：契约各有 per-rule
   文本，生产对全部 copilot 规则用同一通用 detail。

receipt hash 覆盖这些字符串，Oracle 跟生产构建器才有 hash
parity（compare 已证 100%）。请协调员确认：改契约 JSON 对齐
生产，还是改生产对齐契约。

### C-07（已按 T005 裁决实现，记录在案）

MISSING trust 只在 `block_missing_reference` 时 BLOCK；
NOT_OBSERVED trust 无条件 BLOCK（CQ-9）。两者在旧 Oracle 里
曾被合并为无条件 BLOCK，现已区分。

### C-08（T005 潜在缺陷，Oracle 已 fail-closed）

Copilot `@~user/...` 引用：T005 `imports.py` 的句法 BLOCK
分支在 `canonicalize` 抛 `InvalidTilde` 后仍引用未绑定的
`canon`（`exists=canon.exists ...`），会抛 `UnboundLocalError`
导致整个 import 图构建崩溃。Oracle 在此分支 fail-closed
（IMPORT_ESCAPE，targets null，exists=false）。无金样本覆盖；
建议 T005 或终审跟进。

### C-09（receipt 无位置的字段）

receipt schema 没有 edge `depth` 与 canonical target 的槽位，
也没有 reason code 的槽位；Oracle 把 depth、canonical target、
reason code（R001–R010）、also_discovered_by、
considered_but_not_applicable 放在 `--explain` sidecar JSON，
compare 脚本据此核对。若 T007 需要把这些放进正式比对产物，
以 sidecar 为准。

## 8. 已知限制

- Windows 真实解析仍为 NOT_RUN（Linux 上只有纯字符串用例，
  T011 负责 Windows runner）。
- `/etc/claude-code/CLAUDE.md` 在本机不存在，managed source 在
  全部金样本中均为空集；managed 路径逻辑仅由单元/集成测试覆盖
  （`managed_path` 可注入）。
- Oracle 二进制不依赖 Python，可独立运行；唯一外部依赖是
  `git` 二进制（4 条 allowlisted 命令，30s 超时）。
