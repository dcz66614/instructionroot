# instructionroot-oracle — P028 独立 Rust Oracle

与 Python 生产实现完全独立的 P028 实现：path normalization、
harness resolution（codex / claude-code / copilot-cli 三 profile，
按 `00_contract/profile_contract.json`）、trust classification
（R001–R010 与 §13.4 优先级）、import edges、canonical receipt
（RFC 8785 JCS，从零实现）、SHA-256。只读 filesystem，不调用
网络，不调用 Python，不读取任何生产输出。

## 构建与测试

```sh
export PATH="$HOME/.cargo/bin:$PATH"
cargo test --manifest-path 03_oracle/rust/Cargo.toml
cargo build --release --locked --manifest-path 03_oracle/rust/Cargo.toml
```

工具链锁定在 `rust-toolchain.toml`（channel `1.100.0`）；
依赖锁定在 `Cargo.lock`（serde_json 1.0.154、sha2 0.10.9，
2026-11-18 从 crates.io 拉取成功）。

## 子命令

```sh
# 对一个 case 输入生成 receipt（stdout），退出码 = verdict 退出码
instructionroot-oracle resolve <case.json> [--explain <file>]
#   PASS 0 / WARN 10 / BLOCK 20
#   INPUT_ERROR 30 / UNSUPPORTED_PROFILE 40 / INTERNAL_ERROR 50
#   （错误时 stderr 输出 {"error": ..., "verdict": ...}）

# 对一组路径做 canonicalize 探测（FS 金样本用）
instructionroot-oracle canonicalize <input.json>
#   input: {"cwd": ..., "home": ..., "paths": [...]}
#   output: [{raw_path, canonical_path, resolved_path, exists,
#             is_file, is_dir, is_symlink, symlink_target,
#             symlink_chain, is_broken_symlink, is_loop, error}]

instructionroot-oracle --version
```

### Case 输入格式

```json
{
  "case_id": "claude-basic",
  "harness": "claude-code",
  "profile_version": "claude-code-2026-11",
  "cwd": "/abs/path",
  "home": "/abs/path",
  "repo_root": "/abs/path",
  "policy": "default",
  "working_files": ["/abs/path", "..."],
  "env": {
    "COPILOT_HOME": "...",
    "COPILOT_CUSTOM_INSTRUCTIONS_DIRS": "...",
    "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "..."
  },
  "ancestor_stop": "/abs/path",
  "managed_path": "/abs/path"
}
```

`policy` 可为 `"default"` 或 13 个字段的对象（见
`00_contract/policy_schema.json`）。环境变量只从 case JSON 取，
绝不读 Oracle 进程自身的环境（确定性、无 ambient 泄漏）。
`repo_root` / `ancestor_stop` / `managed_path` 可为 null。

`--explain` 写出的 sidecar JSON 包含 receipt schema 没有位置
放的内容：每 source 的 reason code（R001–R010）与
`also_discovered_by`、每 edge 的 depth 与 canonical target、
以及 SPEC-04 的 `considered_but_not_applicable` 列表
（它在 DiscoveryReport 内部，不进 receipt，CQ-8）。

## 模块

| 文件 | 内容 |
| --- | --- |
| `src/paths.rs` | 词法 canonical 化、component-wise symlink 解析（hop 上限 40）、Windows 拼写归一化、`is_within_root`、文件 SHA-256 |
| `src/git.rs` | 仅 4 条 allowlisted git 命令（30s 超时），`GitState` |
| `src/trust.rs` | R001–R010 分类（§13.4 first-match-wins）、13 字段 Policy、verdict 推导 |
| `src/jcs.rs` | RFC 8785 JCS（UTF-16 码元键排序、ECMAScript 数字、转义规则）、SHA-256 |
| `src/textscan.rs` | frontmatter 子集、applyTo、glob（Python fnmatchcase 语义）、`@` 引用扫描 |
| `src/profiles.rs` | 三 profile 的 discovery、去重（S10 在 receipt 组装）、统一 import 图 |
| `src/receipt.rs` | receipt 组装、hash、explain sidecar |
| `src/main.rs` | CLI |

## 与生产实现对齐的关键口径（CQ-1～CQ-10）

- **CQ-1** Copilot 相对引用按**文件相对**解析（U-09 仍 UNVERIFIED），无深度上限，允许目标继续 BFS 展开。
- **CQ-2** edge `from`：depth-1 导入者是 receipt source 时写其 source id，否则写导入者的 canonical path；`to` 是 source 时写其 id，否则 null。
- **CQ-3** Claude import 批准根：按 T005 可执行代码取 repo + cwd + home + additional-dirs（cwd/additional 判 WITHIN_REPO，home 判 WITHIN_HOME）；Copilot 取 repo + cwd + custom-dirs（home 不是根）。注意：协调员补充口径写的是简写 "repo + home"；两读法在全部现有金样本上等价（cwd 总在 repo 内、无 additional dirs），Oracle 跟代码、并把措辞差异记为契约问题 C-05。
- **CQ-4** T003 解析器缺口原样保留：` "@path" `（引号在 @ 之前）仍被解析，只有 ` @"path" ` 被排除。
- **CQ-5** 用户级 copilot-instructions.md 的 `@` 按文件名展开。
- **CQ-6** `.claude/CLAUDE.md` 的 `@` 不展开（fail-closed）。
- **CQ-7** Copilot 的 code-span/引号排除复用 T003 解析器行为。
- **CQ-8** `considered_but_not_applicable` 不进 receipt，只进 explain sidecar；`also_discovered_by` 同样只进 explain。
- **CQ-9** NOT_OBSERVED trust 无条件 BLOCK。
- **CQ-10** escape 检查优先于 MISSING；edge BLOCK 条件按 policy 字面读（任一 disallowed edge + `block_import_escape` 或 `block_missing_reference` 为 true 即 BLOCK）。

其他对齐细节（详见 `review/tasks/P028-T006/TASK_RESULT.md`）：

- precedence `detail` 字符串跟可执行 receipt 构建器的常量（与契约 per-rule 文本有 3 处差异：claude project、claude rules-path-scoped、两个 copilot 规则），否则 receipt hash 无法逐字节对齐。
- Windows 拼写经同一 component-wise 解析器，`C:\x` 的 resolved 为 `/C:/x`（与 Python `canonicalize` 的 Linux 行为逐字节一致，属 bug-compat）。
- MISSING trust 只在 `block_missing_reference` 时 BLOCK；GIT_MODIFIED 不继承 `allow_repo_tracked` 的 BLOCK；user/managed scope 检查按 scope 而非 trust。
- Copilot `@~user/...`：T005 会因 `canon` 未绑定而崩溃（`UnboundLocalError`），Oracle 改为 fail-closed（IMPORT_ESCAPE，targets null）；无金样本覆盖。
- 6 条 dead-code 警告（bin crate 内未被二进制入口直接使用的 pub 项，如 `TRUST_PRIORITY`）为已知、无害。
