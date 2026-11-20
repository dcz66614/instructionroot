# P028-T001 任务结果 — 问题/契约冻结 + Harness Profiles

- TASK_ID：P028-T001
- PROJECT_ID：P028 InstructionRoot Resolve
- 日期：2026-11-18
- 结论：**T001 PASS**（见下方验收输出）
- 只做了 T001，未进入 T002 及以后；未修改任何禁改范围。

## 改动文件清单（全部新增，无修改）

| 文件 | 大小 | 内容 |
|---|---|---|
| `00_contract/profile_contract.json` | 30,702 B | 3 个 profile（codex / claude-code / copilot-cli），每条规则含 scope / pattern / phase / precedence / source_url / verification_status；import syntax；limits；trust 枚举；`known_spec_conflicts` SPEC-01～SPEC-04；每 profile 一个 `rules_hash` |
| `00_contract/receipt_schema.json` | 11,111 B | receipt_version 1；receipt / source / edge / git / precedence 的字段定义；trust 枚举与优先级；verdict 枚举（6 个）；退出码映射；RFC 8785 canonicalization 与 receipt_hash 定义 |
| `00_contract/policy_schema.json` | 6,103 B | policy_schema_version 1；13 个 policy 字段定义及默认值；`default_policy`；verdict 推导规则 |
| `06_docs/PROFILES.md` | 18,631 B | 三个 profile 的发现规则说明，每条规则注明官方来源 URL；UNVERIFIED 总登记 U-01～U-14；规格问题索引 |
| `01_s0/fixtures/README.md` | 9,339 B | S0 golden case 格式：fixture 目录结构、`case.json` 与 `.expected.json` 格式、9 条断言口径、S01–S25 覆盖映射、未决问题 |
| `review/tasks/P028-T001/TASK_RESULT.md` | 本文件 | 任务结果、验收输出、未决问题 |

禁改范围核查：`02_src/*`、`03_oracle/*`、`04_ui/*`、`.venv/` 未动；`00_contract/PROJECT_BOOK.md` 与 `00_contract/IMPLEMENTATION_PLAN.md` 未动（MD5 与 `~/workspace/p028-specs/` 副本一致：PROJECT_BOOK `be1f8a7c…`、IMPLEMENTATION_PLAN `af6ecd9e…`）。

## 官方来源核对（2026-11-18 用 browser.open 拉取页面文本）

| 来源 | URL | 拉取结果 |
|---|---|---|
| Codex AGENTS.md 发现 | https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide | 已核对：`~/.codex` + repo root→CWD、root-to-leaf、后者覆盖前者、每文件一条 user-role 消息、`AGENTS.override.md` 仅点名、"a size cap" 无数值 |
| Claude Code memory | https://docs.anthropic.com/zh-CN/docs/claude-code/memory | 已核对（页面更新 2026-11-17）：托管/用户/项目/本地四级、向上发现、嵌套按需、`.claude/rules/`（`paths`）、AGENTS.md fallback 条件、**`@` import 最大深度 4 跳** |
| VS Code custom instructions | https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference | 已核对：三 harness 位置表、用户级位置、嵌套行为、"no precedence rule applies across all harnesses"、Copilot combine 无通用顺序、`applyTo` 无默认模式 |
| GitHub Copilot custom instructions | https://docs.github.com/en/copilot/concepts/prompting-and-context/custom-instructions | 已核对：三类 repo 指令、GitHub.com precedence 列表（**仅适用于 GitHub.com，不适用于 CLI**）、组织指令不支持本地会话 |
| GitHub Copilot CLI | https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions | 已核对：8 个位置（含标准位置定义、`COPILOT_HOME`、`COPILOT_CUSTOM_INSTRUCTIONS_DIRS`）、combine 无通用顺序、去重、`@` 引用规则（仓库内、禁绝对路径与 `~/`、GEMINI.md 与 `*.instructions.md` 不展开） |

## 三个 profile 的规则条数与 UNVERIFIED 项

- **codex**（`codex-2026-11`）：规则 **3 条**，UNVERIFIED 规则 **1 条**（`codex.override-fallback`），precedence UNSPECIFIED 1 条。`rules_hash = sha256:a0a03c1cdd77f8d9110ccbc77dae937e30e288a2609e6b04b60d26d15af5dc23`
- **claude-code**（`claude-code-2026-11`）：规则 **11 条**，UNVERIFIED 规则 0 条，precedence UNSPECIFIED **4 条**（nested、rules-path-scoped、agents-nested、additional-dirs）。`rules_hash = sha256:7f1d074dc0bb8dde1eace4c01498f8899b8ef58aa47f71c32c649768104f6058`
- **copilot-cli**（`copilot-cli-2026-11`）：规则 **8 条**，UNVERIFIED 规则 0 条，precedence 全部为 COMBINE_UNORDERED（0 条 UNSPECIFIED）。`rules_hash = sha256:76a5f6c8fbd7fc4ff910bf5f471ecb9291ab2a575d871f93338fb1b298c73d0e`
- 合计 **22 条规则**；UNVERIFIED 规则 1 条；precedence UNSPECIFIED 规则 5 条。
- UNVERIFIED 总登记（PROFILES.md 末节 U-01～U-14，共 14 项）：Codex override 语义 / 其余 fallback 名 / size cap 数值 / repo-root 确定方法与非 git 行为 / Codex 是否有 `@` import；Claude on-demand 顺序 / 外部 import 批准状态（NOT_OBSERVED）/ 非默认设置与 `claudeMdExcludes`；Copilot `@` 基准目录 / `@` 在 `.claude/CLAUDE.md` 是否展开 / 缺 `applyTo` 行为 / custom-dirs 下 `*.instructions.md` 是否受 `applyTo` 约束 / `excludeAgent` 在 CLI 是否生效 / `/instructions` 禁用状态（NOT_OBSERVED）。

## 验收命令输出（2026-11-18，工作目录 `~/workspace/p028-instructionroot`）

```text
$ .venv/bin/python -m json.tool 00_contract/profile_contract.json
profile_contract.json: VALID JSON

$ .venv/bin/python -m json.tool 00_contract/receipt_schema.json
receipt_schema.json: VALID JSON

$ .venv/bin/python -m json.tool 00_contract/policy_schema.json
policy_schema.json: VALID JSON

$ 交叉一致性校验（json.tool 之外，校验 profile id/version、trust 枚举、rules_hash 重算、
  规则字段取值、receipt/policy 版本、policy 字段完备性）：
PASS profiles=3
PASS profile ids
PASS profile versions
PASS receipt profile id enum matches
PASS receipt profile version enum matches
PASS trust enum consistent
PASS rules_hash codex
PASS rules_hash claude-code
PASS rules_hash copilot-cli
PASS all rules: scope/phase/precedence/status/source_url valid
PASS receipt_schema_version=1
PASS verdict enum (6)
PASS exit codes
PASS receipt required fields
PASS policy_schema_version=1
PASS policy has required fields
PASS default_policy covers all fields
PASS policy defaults are booleans
PASS receipt policy ref version matches
total_rules=22 unverified_rules=1 unspecified_precedence_rules=5
codex: rules=3 unverified=1 unspecified_precedence=1
claude-code: rules=11 unverified=0 unspecified_precedence=4
copilot-cli: rules=8 unverified=0 unspecified_precedence=0
T001 PASS
profiles=3
receipt_schema_version=1
policy_schema_version=1
```

验收要求输出全部具备：T001 PASS、profiles=3、receipt_schema_version=1、policy_schema_version=1。

## 规格问题（记录，不改规格）

已同时写入 `00_contract/profile_contract.json` 的 `known_spec_conflicts`：

1. **SPEC-01 — Claude `@` import 最大深度冲突。** 官方文档（2026-11-17 更新）："导入的文件可以递归导入其他文件，最大深度为四跳"。PROJECT_BOOK.md §15 S13/S14 与 IMPLEMENTATION_PLAN.md §3.3/§10.3 写 depth ≤ 5（S13 depth 5 PASS、S14 depth 6 BLOCK）。**本合同以官方文档为准：`max_depth_hops = 4`。** T007 在冲突解决前不得把 depth-5 写进金样本；`01_s0/fixtures/README.md` 的 S13/S14 已按 4 跳改写并标注此冲突。
2. **SPEC-02 — untracked 仓库内文件的默认处理含糊。** PROJECT_BOOK.md §7.1 demo 中 untracked 的 `services/payments/AGENTS.md` 为 WARN；§14.2 示例 policy 却写 `block_repo_untracked: true`（会是 BLOCK）；§15 S04 写 WARN/BLOCK。**本合同默认 `block_repo_untracked = false`（WARN，与 §7.1 demo 一致），§14.2 的值视为示例 policy 而非默认值。** 设为 true 可升级为 BLOCK。
3. **SPEC-03 — trust 优先级表漏了 NOT_OBSERVED。** PROJECT_BOOK.md §13.4 的优先级顺序不含 NOT_OBSERVED。receipt_schema.json 原样复现该顺序，并注明 NOT_OBSERVED 无优先级位置（它标记未观测状态，不是 source 分类）。
4. **SPEC-04 — NOT_APPLICABLE 无 schema 位置。** PROJECT_BOOK.md §15 S16 要求 Copilot `applyTo` 不匹配时为 NOT_APPLICABLE，但该值既不在 trust 枚举（§8.5）也不在 verdict 枚举。**未编造新枚举值。** 不匹配的 path-specific 文件 simply 不出现在 receipt sources 中；如需显式表示，T003/T007 须定义（如 `considered_but_not_applicable` 列表）。
5. **其他已确认、无需改规格的点：** PLAN §3.3 要求以 T001 时官方文档为准的 `CLAUDE.local.md` 支持状态已确认——支持，与 `CLAUDE.md` 一起加载（`claude-code.local`，VERIFIED）；PLAN §3.2 要求的 Codex size cap / fallback 已记为 profile metadata，值 UNVERIFIED。

## 环境记录（供 T006 参考）

- Python：`.venv/bin/python` 为 **3.12.3**（规格推荐 3.14.x；本机 venv 提供 3.12.3，T001 不升级环境）。
- git：2.43.0。
- **Rust 未安装**：本机 `rustc` / `cargo` 均不存在（`command not found`）。PLAN §2.2 要求 T001 记录实际版本并锁定 `rust-toolchain.toml`，但 `03_oracle/*` 在 T001 禁改范围内，toolchain 锁定留给 T006（需先安装 Rust 工具链）。

## 未决问题（留给 parent / 后续任务）

1. SPEC-01（Claude import 深度 4 vs 5）需 parent 裁决：以官方文档为准（本合同已如此）还是以规格书为准。
2. SPEC-04（S16 NOT_APPLICABLE 的表示方式）需 T003/T007 定义。
3. Copilot `@` 相对路径的基准目录（U-09）需主来源确认，否则 T005 的边解析只能标 UNVERIFIED。
4. T006 需先解决本机无 Rust 工具链的问题，再锁定 `rust-toolchain.toml`。
