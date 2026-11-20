# S0 Golden Fixtures — 格式说明（T001 冻结）

> 本文件只冻结 **格式**。fixture 内容由 T007 生成；T001 不创建任何 fixture case。
> 权威契约：`../00_contract/profile_contract.json`、`../00_contract/receipt_schema.json`、`../00_contract/policy_schema.json`。

## 1. 目录结构

```text
01_s0/
├── fixtures/                  # 输入：合成 workspace（全部由脚本生成，零真人、零真实 repo/home）
│   └── <case-id>/             # 例如 S01、S07、S13；case-id 与 PROJECT_BOOK.md §15 的 S01–S25 对应
│       ├── case.json          # 输入描述（见 §2）
│       └── workspace/         # 合成文件系统快照的根
│           ├── home/          # 合成的 HOME（~/.codex、~/.claude、~/.copilot …）
│           ├── repo/          # 合成的 git 仓库（.git 由 fixture 生成器建）
│           └── outside/       # 合成的仓库外目录（如 Downloads）
├── expected/                  # 期望输出（由 T007 按契约编写，不由 production 生成）
│   └── <case-id>.expected.json
├── oracle/                    # Oracle 的输入/输出对照（T006 所有）
└── logs/                      # S0 gate 运行日志（T007 所有）
```

补充规则：

- 一个 case 只测一个主场景；变体用后缀区分，如 `S07-a`、`S07-b`。
- `workspace/` 下不得出现真实用户 home、真实 repo 的任何内容；所有文件内容均为合成占位文本，不得含真实恶意 payload（PROJECT_BOOK.md §12.3 / IMPLEMENTATION_PLAN.md §12.3）。
- Windows 专用 case（junction、盘符、大小写）放在 `fixtures/windows/<case-id>/`，结构相同，`case.json` 中 `os: "windows"`；Linux 上记 `NOT_RUN`，不得伪造通过。

## 2. `case.json`（输入）格式

```json
{
  "case_id": "S07",
  "title": "symlink escape: in-repo AGENTS.md links outside the repo",
  "harness": "codex",
  "profile_version": "codex-2026-11",
  "cwd": "workspace/repo/services/payments",
  "repo_root": "workspace/repo",
  "home": "workspace/home",
  "policy": "default",
  "os": "linux",
  "notes": "给人读的场景说明，不参与判定"
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `case_id` | 是 | 与 PROJECT_BOOK.md §15 的 S01–S25 对应；变体加 `-a`、`-b` 后缀 |
| `title` | 是 | 一句话场景说明 |
| `harness` | 是 | `codex` \| `claude-code` \| `copilot-cli`；其他值用于"unsupported profile"类 case，期望 verdict 为 `UNSUPPORTED_PROFILE` |
| `profile_version` | 是 | 必须是 `00_contract/profile_contract.json` 中该 harness 的冻结版本；错版用于版本不匹配类 case |
| `cwd` | 是 | 相对 `fixtures/<case-id>/` 的路径；即 harness 启动时的工作目录 |
| `repo_root` | 是 | 相对路径，或 `null`（非 git 目录场景，如 S25） |
| `home` | 是 | 相对路径，合成 HOME |
| `policy` | 是 | `"default"`（用 `policy_schema.json` 的 `default_policy`）或一个内联 policy 对象（字段同 `policy_schema.json`） |
| `os` | 是 | `"linux"` \| `"windows"` |
| `notes` | 否 | 仅供人阅读 |

路径一律用 `/` 分隔；`workspace/` 下的路径在断言时先解析为 canonical 绝对路径再比较，比较的是解析后的值，不是字面字符串。

## 3. `<case-id>.expected.json`（期望输出）格式

```json
{
  "case_id": "S07",
  "expected_verdict": "BLOCK",
  "expected_sources": [
    {
      "discovery_rule": "codex.repo-chain",
      "scope": "project",
      "phase": "startup",
      "relative_path": "repo/AGENTS.md",
      "trust": "GIT_TRACKED",
      "precedence_kind": "ORDERED"
    }
  ],
  "expected_edges": [
    {
      "from_relative_path": "repo/AGENTS.md",
      "syntax": "@../shared/rules.md",
      "allowed": false,
      "reason": "IMPORT_ESCAPE"
    }
  ],
  "expected_source_count": 3,
  "forbidden_trust": ["OUTSIDE_REPO"],
  "notes": "期望中不写 receipt_hash：hash 由 production 与 Oracle 各自计算后比对一致性（parity），不与手写值比对"
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `case_id` | 是 | 必须与 `case.json` 一致 |
| `expected_verdict` | 是 | `PASS` \| `WARN` \| `BLOCK` \| `INPUT_ERROR` \| `UNSUPPORTED_PROFILE` \| `INTERNAL_ERROR` |
| `expected_sources` | 是 | 按发现顺序列出每个期望 source；`relative_path` 相对于 `workspace/`；`trust` 取 9 值 trust 枚举；`precedence_kind` 取 `ORDERED` \| `COMBINE_UNORDERED` \| `UNSPECIFIED`（`BEFORE`/`AFTER` 只在 receipt 的相对排序断言中使用）；未列出的 source 即不期望出现 |
| `expected_edges` | 是 | 边列表；无边时为空数组；`reason` 取值见 receipt schema 的 edge.reason（`WITHIN_REPO`、`IMPORT_ESCAPE`、`MISSING`、`NOT_OBSERVED` 等） |
| `expected_source_count` | 否 | 与 `expected_sources` 长度一致时可省略；显式写出时两者必须一致 |
| `forbidden_trust` | 否 | 本 case 绝不允许出现的 trust 值（用于 escape 漏报断言：出现即 FAIL） |
| `notes` | 否 | 仅供人阅读 |

## 4. 断言口径（T007 的 gate 按此执行）

1. **source 集合与顺序**：production 与 Oracle 的 source 列表（`discovery_rule` + canonical path）在集合与顺序上必须 100% 一致，且与 `expected_sources` 一致。顺序只对 `precedence_kind == ORDERED` 的 profile 断言；`COMBINE_UNORDERED` 只断言集合，不争顺序。
2. **trust**：每个 source 的 trust 必须与期望一致；production 与 Oracle 的 trust parity 100%。
3. **edges**：边集合（from + syntax + resolved_target + allowed + reason）production 与 Oracle 100% 一致，且与期望一致。
4. **verdict**：production 与 Oracle 的 verdict 必须一致且等于 `expected_verdict`。
5. **receipt hash**：同一 case 的 canonical receipt hash，production 与 Oracle 必须一致；同一实现重跑 100 次 hash 不变。hash 不与手写期望值比对（期望文件不含 hash）。
6. **fail-closed**：malformed fixture（`case.json` 非法、`profile_version` 不匹配、cwd 不存在、policy 字段非法等）不得产生 `PASS`；期望 verdict 为 `INPUT_ERROR` / `UNSUPPORTED_PROFILE` / `INTERNAL_ERROR`，且退出码非零。
7. **escape 零漏报**：`forbidden_trust` 中的值一旦出现在任一 source 的 trust 中，该 case 即 FAIL，无论 verdict 如何。
8. **UNSPECIFIED 不得分**：任何实现不得把 `UNSPECIFIED` 的 precedence"猜"成确定顺序来通过顺序断言；顺序断言只覆盖契约写明 ORDERED 的部分。
9. **不比较文件内容**：只比较 path、hash、git 状态、trust、edges、verdict；instruction 文件内容永不进入期望文件或 receipt。

## 5. S01–S25 覆盖映射（PROJECT_BOOK.md §15）

| ID | 场景 | 期望要点 |
|---|---|---|
| S01 | repo root 单文件 | PASS |
| S02 | nested instruction | PASS |
| S03 | user/global + repo | PASS |
| S04 | repo untracked | WARN（默认 policy；`block_repo_untracked=true` 时 BLOCK） |
| S05 | modified tracked | WARN（`block_repo_modified=true` 时 BLOCK） |
| S06 | symlink → repo 内 | PASS/WARN 按 policy |
| S07 | symlink → repo 外 | BLOCK（SYMLINK_ESCAPE） |
| S08 | missing import | BLOCK（MISSING） |
| S09 | import → repo 外 | BLOCK（IMPORT_ESCAPE） |
| S10 | duplicate 同一文件 | 去重：同一 canonical path 只出现一次 |
| S11 | unsupported precedence | precedence kind 为 `UNSPECIFIED` |
| S12 | Windows junction escape | BLOCK（windows-only；Linux 上 NOT_RUN） |
| S13 | Claude import depth 4 | PASS（规格书已在 FIX-R1 同步为 depth 4，与官方文档一致） |
| S14 | Claude import depth 5 | BLOCK（按官方文档 4 跳，depth 5 已超限；规格书已同步） |
| S15 | Copilot `applyTo` match | PASS（on_demand 触发） |
| S16 | Copilot `applyTo` no match | 不出现在 sources 中（NOT_APPLICABLE 在 trust/verdict 枚举中无对应值，见 SPEC-04；不得编造枚举值） |
| S17 | Codex root→CWD chain | 顺序正确（root-to-leaf） |
| S18 | home source | USER_SCOPE |
| S19 | outside home source | BLOCK（OUTSIDE_REPO） |
| S20 | path normalization | canonical 相等（`..`、重复分隔符、相对路径） |
| S21 | Unicode path | 稳定（hash 与路径表示一致） |
| S22 | case-sensitive/insensitive fixture | profile-specific（Linux 上区分大小写；Windows case 记 NOT_RUN） |
| S23 | git deleted file | MISSING |
| S24 | git rename | provenance 记录（新路径 + git 状态一致） |
| S25 | non-git directory | `repo_root: null`；trust 按规则判定，不伪造 git 状态 |

S0 共至少 60 个 workspace case：上述 25 个场景各自生成多个变体（不同 harness、不同目录深度、不同 policy），总数 ≥ 60，source 断言 ≥ 180 个。

## 6. 未决问题（留给 T007 / parent）

- SPEC-01（已解决，FIX-R1）：S13/S14 的深度边界已同步为官方文档（4 跳）；规格书原 depth 5 的写法已修正，金样本可冻结。
- SPEC-04：S16 的 NOT_APPLICABLE 在 receipt 中没有对应的字段/枚举；T003/T007 需定义显式表示（例如 `considered_but_not_applicable` 列表），或确认"不出现即表示不适用"。
