# P028 InstructionRoot Resolve — Harness Profiles

> 冻结日期：2026-11-18（T001）
> 契约文件：`00_contract/profile_contract.json`（机器可读的唯一权威版本；本文档是它的人类可读版，两者冲突时以 JSON 为准）
> 官方来源拉取日期：2026-11-18。官方文档可能更新；profile 版本号（`codex-2026-11` 等）锚定的是本次拉取的文档状态。

## 通则

- **每个 profile 只建模官方文档写明的东西。** 文档没写的，标 `UNVERIFIED`，绝不猜。
- **precedence 未定义时标 `UNSPECIFIED`。** 不得自行编造“第一优先级”。
- **“文件可被发现” ≠ “内容安全”**，**“Git tracked” ≠ “作者可信”**。
- scope 取值：`managed`（组织托管）｜`user`（用户全局）｜`project`（项目：CWD 及祖先/仓库链）｜`nested`（CWD 之下的子目录）。
- phase 取值：`startup`（启动时加载）｜`on_demand`（满足触发条件时才加载）。
- trust 枚举（共 9 个，见 `00_contract/receipt_schema.json`）：`GIT_TRACKED`、`GIT_MODIFIED`、`GIT_UNTRACKED`、`USER_SCOPE`、`OUTSIDE_REPO`、`SYMLINK_ESCAPE`、`IMPORT_ESCAPE`、`MISSING`、`NOT_OBSERVED`。

---

## 1. Codex — `codex` / `codex-2026-11`

主来源：<https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide>
辅助来源：<https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference>

### 发现规则（共 3 条）

| rule_id | scope | pattern | phase | precedence | 状态 | 来源 |
|---|---|---|---|---|---|---|
| `codex.user` | user | `~/.codex/AGENTS.md` | startup | ORDERED（链首，全局指令最先注入） | VERIFIED | [Codex prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide)；文件名由 [VS Code 参考](https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference)佐证（"AGENTS.md in the Codex home directory, which defaults to ~/.codex"） |
| `codex.repo-chain` | project | 每个目录一个 `AGENTS.md`：repo root → … → CWD（含两端） | startup | ORDERED（root-to-leaf；越深的目录越后、覆盖前面的） | VERIFIED | [Codex prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide)："Files are pulled from ~/.codex plus each directory from repo root to CWD"；"merged in order, later directories overriding earlier ones"；"in root-to-leaf order: global instructions first, then repo root, then each deeper directory" |
| `codex.override-fallback` | project | `<dir>/AGENTS.override.md`（与 repo-chain 相同的目录集合） | startup | **UNSPECIFIED** | **UNVERIFIED** | [Codex prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide) 只写了一句："If an AGENTS.override.md was used, its directory name still appears in the header"。它是否替代还是补充同目录的 `AGENTS.md`、fallback 的选择顺序，文档均未定义 |

### 组合语义

- 每个被发现的文件成为一条独立的 user-role 消息，形如 `# AGENTS.md instructions for <directory>`（`<directory>` 为相对 repo root 的路径），注入到对话历史顶部、用户提示之前。
- 发现范围上以 repo root 为界、下以 CWD 为界：文档没有给出 CWD 之下子目录或 repo root 之上目录的发现规则。VS Code 参考佐证："To use instructions in a subfolder, start the session with that subfolder as its working directory."

### Import 语法

- **UNVERIFIED：拉取的 Codex 来源没有记载 `AGENTS.md` 的 `@` import / 文件引用机制。** 没有文档不等于机制不存在；T003 在拿到主来源确认之前不得为 codex 实现 import 解析。

### 未确认项（UNVERIFIED）

1. `AGENTS.override.md` 的 fallback 选择语义（替代 / 补充 / 优先级）。
2. 除 `AGENTS.override.md` 之外的 fallback 文件名：文档说 "optional fallback names"（复数），但正文只点名了这一个。
3. size cap 的具体数值：文档只说 "with … a size cap"，没有给字节/行数值，不得凭此设限。
4. "repo root" 如何确定（例如是否等于 git top-level）；CWD 不在任何 git 仓库内时的行为。

---

## 2. Claude Code — `claude-code` / `claude-code-2026-11`

主来源：<https://docs.anthropic.com/zh-CN/docs/claude-code/memory>（页面更新时间 2026-11-17T19:50:16Z）
辅助来源：<https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference>

### 发现规则（共 11 条）

| rule_id | scope | pattern | phase | precedence | 状态 | 来源 |
|---|---|---|---|---|---|---|
| `claude-code.managed` | managed | Linux/WSL：`/etc/claude-code/CLAUDE.md`；macOS：`/Library/Application Support/ClaudeCode/CLAUDE.md`；Windows：`C:\Program Files\ClaudeCode\CLAUDE.md` | startup | ORDERED（最先，在用户与项目指令之前） | VERIFIED | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)："托管策略"一行；`claudeMdExcludes` 不能排除它；会话以完全关闭 CLAUDE.md 加载启动时也不加载它 |
| `claude-code.user` | user | `~/.claude/CLAUDE.md` | startup | ORDERED（托管之后、项目之前） | VERIFIED | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)："用户指令"一行 |
| `claude-code.project` | project | CWD 及每个祖先目录中的 `./CLAUDE.md` 或 `./.claude/CLAUDE.md` | startup | ORDERED（从文件系统根向下排到 CWD；各文件是连接起来、不是互相覆盖；文件间 override 语义 UNSPECIFIED） | VERIFIED | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)："Claude Code 从您的当前工作目录和其上方的每个目录加载 CLAUDE.md 和 CLAUDE.local.md"；"内容从文件系统根目录向下排序到您的工作目录"；"如果两条指令相互矛盾，Claude 可能会任意选择一条" |
| `claude-code.local` | project | CWD 及每个祖先目录中的 `./CLAUDE.local.md` | startup | ORDERED（同一目录内，`CLAUDE.local.md` 附加在 `CLAUDE.md` 之后） | VERIFIED | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)："在每个目录中，CLAUDE.local.md 附加在 CLAUDE.md 之后"；惯例是加入 `.gitignore`，harness 本身不强制 |
| `claude-code.nested` | nested | CWD 之下子目录中的 `<subdir>/CLAUDE.md` 与 `<subdir>/CLAUDE.local.md` | on_demand | **UNSPECIFIED**（触发条件已定义，与启动链的相对顺序未定义） | VERIFIED（触发条件） | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)："子目录中的文件按需加载"；"在 Claude 读取、写入或编辑该子目录中的其他文件时逐个加载"；用 Bash `cat`/`head` 看文件也算读取 |
| `claude-code.rules-user` | user | `~/.claude/rules/**/*.md`（递归全部 `.md`） | startup | ORDERED（在项目规则之前加载；冲突时两者互不覆盖） | VERIFIED | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)："Claude Code 在项目规则之前加载用户级规则……如果用户规则和项目规则冲突，Claude 可能会遵循任一个" |
| `claude-code.rules-startup` | project | `<project>/.claude/rules/**/*.md`（无 `paths` frontmatter 的，递归） | startup | ORDERED（与 `.claude/CLAUDE.md` 相同优先级） | VERIFIED | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)："没有 paths frontmatter 的规则在启动时加载，优先级与 .claude/CLAUDE.md 相同" |
| `claude-code.rules-path-scoped` | project | `<project>/.claude/rules/**/*.md`（带 `paths` frontmatter glob） | on_demand | **UNSPECIFIED**（触发条件已定义，相对顺序未定义） | VERIFIED（触发条件） | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)：仅当 Claude 对匹配的文件使用 Read/Write/Edit（或算作读取的 Bash 命令）时加载；模式相对于含 `.claude` 文件夹的目录；`paths` 是唯一读取的 frontmatter 字段；YAML 无法解析时忽略 frontmatter、按无 `paths` 加载 |
| `claude-code.agents-fallback` | project | CWD 及每个祖先目录中的 `<dir>/AGENTS.md` 与 `<dir>/.claude/AGENTS.md` | startup | ORDERED（与 CLAUDE.md 链相同的 root-to-CWD 连接顺序），**仅当条件成立** | VERIFIED | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)："默认情况下，Claude 仅在您的工作目录或其上方没有 CLAUDE.md 时才读取 AGENTS.md"。条件：CWD 或其上方任一目录不存在 `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md`；`~/.claude/CLAUDE.md`、托管 `CLAUDE.md`、`.claude/rules/` 不计入该判断。`AGENTS.local.md`、`AGENTS.override.md`、`.agents/` 下内容一律不读 |
| `claude-code.agents-nested` | nested | CWD 之下子目录中的 `<subdir>/AGENTS.md` | on_demand | **UNSPECIFIED** | VERIFIED（触发条件） | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)：当 Claude 在子目录中工作、且该子目录没有任何一个 `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md` 时加载；其内 `@path` 导入会展开，`claudeMdExcludes` 适用 |
| `claude-code.additional-dirs` | project | 附加目录中的 `CLAUDE.md`、`.claude/CLAUDE.md`、`CLAUDE.local.md`、`.claude/rules/*.md` | startup | **UNSPECIFIED** | VERIFIED（机制） | [Claude Code memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)：仅当使用 `--add-dir` **且**设置了 `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` 环境变量；带 `paths` 字段的规则不从附加目录加载；`--setting-sources` 排除 `local` 时跳过 `CLAUDE.local.md` |

### Import 语法

- 语法：`@path`。相对路径相对于**包含 import 的文件**（不是 CWD）；绝对路径允许。
- 递归导入，**最大深度 4 跳**（VERIFIED；原规格冲突 SPEC-01 已在 FIX-R1 解决，见下文）。
- Markdown 代码跨度 / 围栏代码块内的 `@` 不导入；用引号包裹的路径不导入；含空格的路径须在每个空格前加反斜杠。
- 解析到工作目录之外的 `@` 导入需要按项目一次批准（交互式对话框）；经 `AGENTS.md` 路径读取的文件，仅在该项目已批准过外部导入时才加载、无提示。**批准状态在文件系统快照中是 NOT_OBSERVED，不得猜测。**

### 未确认 / 边界项

1. **SPEC-01（已解决，FIX-R1）：导入最大深度。** 官方文档（2026-11-17 更新）写明"最大深度为四跳"；PROJECT_BOOK.md §15 S13/S14 与 IMPLEMENTATION_PLAN.md §3.3/§10.3 现已同步为 depth ≤ 4（S13 depth 4 PASS、S14 depth 5 BLOCK），与官方文档一致。原 depth ≤ 5 的写法是规格缺陷，已修正；金样本按 depth 4 PASS / depth 5 BLOCK 编写，与实现一致。
2. on-demand 类规则（nested、path-scoped、agents-nested、additional-dirs）与启动链的相对顺序未定义 → precedence 一律 UNSPECIFIED。
3. `claudeMdExcludes` 配置、非默认的"项目说明"设置（`claude-md-and-agents-md` / `claude-md` / `managed-only`）会改变加载行为，但属于配置状态，快照中为 NOT_OBSERVED；本 profile 只建模默认设置 `claude-md-or-agents-md`。
4. 自动记忆（`~/.claude/projects/<project>/memory/MEMORY.md`，启动时前 200 行 / 25KB）是机器写的笔记，不是 instruction file，**不建模为发现规则**。
5. 超过 4 MiB 的 `CLAUDE.md` 会被跳过；按需加载的文件会被截断（200K 上下文窗口下 40,000 字符）——这是加载上限，不是发现规则。
6. `.claude/rules/` 指向工作目录外的符号链接被当作 external import：批准前不加载，批准后也只加载无 `paths` 字段的规则；指向网络路径（UNC `\\server\share`、`/net`、`/Network`）的符号链接一律不跟随（`\\wsl$` 不算网络路径）。

---

## 3. Copilot CLI — `copilot-cli` / `copilot-cli-2026-11`

主来源：<https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions>
辅助来源：<https://docs.github.com/en/copilot/concepts/prompting-and-context/custom-instructions>、<https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference>

"标准位置"（standard locations）定义：仓库根目录、当前工作目录、两者之间的中间目录、以及 Copilot CLI 正在处理的文件路径上嵌套的目录。

### 发现规则（共 8 条）

| rule_id | scope | pattern | phase | precedence | 状态 | 来源 |
|---|---|---|---|---|---|---|
| `copilot-cli.user` | user | `$HOME/.copilot/copilot-instructions.md`（设置了 `COPILOT_HOME` 时用该目录代替 `$HOME/.copilot`） | startup | COMBINE_UNORDERED | VERIFIED | [Copilot CLI custom instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions) |
| `copilot-cli.user-modular` | user | `$HOME/.copilot/instructions/**/*.instructions.md`（或 `$COPILOT_HOME` 之下） | on_demand | COMBINE_UNORDERED | VERIFIED | 同上。条件：仅当其 `applyTo` 匹配 Copilot CLI 正在处理的文件 |
| `copilot-cli.repo-wide` | project | 标准位置中的 `.github/copilot-instructions.md` | startup | COMBINE_UNORDERED | VERIFIED | 同上 |
| `copilot-cli.repo-modular` | project | 标准位置中的 `.github/instructions/**/*.instructions.md`，**但不含中间目录** | on_demand | COMBINE_UNORDERED | VERIFIED | 同上。条件：仅当其 `applyTo` 匹配正在处理的文件。注意：这是唯一明确排除中间目录的位置 |
| `copilot-cli.agents` | project | 标准位置中的 `AGENTS.md` | startup | COMBINE_UNORDERED | VERIFIED | 同上 |
| `copilot-cli.claude` | project | 标准位置中的 `CLAUDE.md` 与 `.claude/CLAUDE.md` | startup | COMBINE_UNORDERED | VERIFIED | 同上 |
| `copilot-cli.gemini` | project | 标准位置中的 `GEMINI.md` | startup | COMBINE_UNORDERED | VERIFIED | 同上。注意：`GEMINI.md` 内不展开 `@` 引用 |
| `copilot-cli.custom-dirs` | project | `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` 列出的每个目录（逗号分隔）中的 `AGENTS.md` 与 `*.instructions.md` | startup | COMBINE_UNORDERED | VERIFIED | 同上 |

### 组合语义

- **没有通用 precedence。** GitHub 文档原文："When multiple applicable user-level and repository instruction files exist, Copilot CLI combines their instructions. … but does not define a general precedence order between these files." VS Code 参考同样写明："There is no precedence rule that applies across all harnesses. Copilot combines applicable user and repository instructions without a general precedence order."
- **不要把 GitHub.com 的 precedence 套到 CLI 上。** 概念页列出的顺序（personal > path-specific > repo-wide > agent > organization）明确适用于 Copilot Chat on GitHub.com，概念页同时写明 "Precedence depends on the client and feature. Most surfaces and clients, including Copilot CLI, … combine applicable instruction files without defining a general precedence order." 本 profile 不建模 GitHub.com 的顺序。
- 完全相同的 user-level `copilot-instructions.md`、repo-wide 与 agent instruction 副本会被去重。
- `applyTo` 用 glob 语法，多个模式逗号分隔，没有默认模式（VS Code 参考："There is no default pattern"）。`applyTo` 目标是 agent 正在处理的文件。

### Import 语法

- 语法：`@<相对路径>`。可用位置：`.github/copilot-instructions.md`、`AGENTS.md`、`CLAUDE.md`；**不展开**的位置：`GEMINI.md`、`*.instructions.md`。
- 被引用的文件会立即读取；被引用文件内的引用也支持（嵌套）。
- 被引用文件必须留在仓库内（本地指令则留在 custom instructions directory 内）；**绝对路径与 `~/` 开头的路径不加载**。
- **UNVERIFIED：相对 `@` 路径的基准目录。** 拉取的 CLI 文档只写 "@ followed by a relative path"，未说明相对谁（引用文件所在目录 / CWD）。不得假设。
- **UNVERIFIED：`@` 是否在 `.claude/CLAUDE.md` 内展开。** 文档只列出 `CLAUDE.md`。

### 未确认 / 边界项

1. 缺少 `applyTo` 的 `*.instructions.md` 在 CLI 下的行为：VS Code 参考只描述了 Local 会话的手动挂载，CLI 行为未定义。
2. `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` 下的 `*.instructions.md` 是否仍受 `applyTo` 约束：文档未写。
3. `excludeAgent` frontmatter 针对 Copilot cloud agent / code review；在 CLI 内是否生效未定义。
4. 用 `/instructions` 禁用的文件不被包含；禁用状态是会话状态，快照中为 NOT_OBSERVED。
5. 组织级 custom instructions 不支持本地客户端会话：不在本 profile 范围内，记 NOT_OBSERVED。
6. 对 custom instructions 文件的修改不会立即对活动中的 CLI 会话生效（须重启 / `--continue` / `/new`）：会话行为，不是发现规则。

---

## UNVERIFIED 总登记（T001）

| # | 项目 | 内容 |
|---|---|---|
| U-01 | codex | `AGENTS.override.md` 的选择语义（规则 `codex.override-fallback` 整体 UNVERIFIED） |
| U-02 | codex | 除 `AGENTS.override.md` 外的 fallback 文件名 |
| U-03 | codex | size cap 数值 |
| U-04 | codex | "repo root" 的确定方法；非 git 目录下 CWD 的行为 |
| U-05 | codex | 是否存在 `@` import / 文件引用机制（拉取来源无记载） |
| U-06 | claude-code | on-demand 规则与启动链的相对顺序（4 条规则 precedence UNSPECIFIED） |
| U-07 | claude-code | 外部 `@` 导入的批准状态（快照中 NOT_OBSERVED） |
| U-08 | claude-code | 非默认"项目说明"设置与 `claudeMdExcludes` 的影响（配置状态，快照中 NOT_OBSERVED） |
| U-09 | copilot-cli | `@` 相对路径的基准目录 |
| U-10 | copilot-cli | `@` 在 `.claude/CLAUDE.md` 内是否展开 |
| U-11 | copilot-cli | 缺少 `applyTo` 的 `*.instructions.md` 在 CLI 下的行为 |
| U-12 | copilot-cli | custom-dirs 下 `*.instructions.md` 是否仍受 `applyTo` 约束 |
| U-13 | copilot-cli | `excludeAgent` 在 CLI 内是否生效 |
| U-14 | copilot-cli | `/instructions` 禁用状态（会话状态，快照中 NOT_OBSERVED） |

规则条数：codex 3 条（UNVERIFIED 规则 1 条）、claude-code 11 条（UNVERIFIED 规则 0 条；4 条 precedence UNSPECIFIED）、copilot-cli 8 条（UNVERIFIED 规则 0 条）。合计 22 条规则。

## 规格问题（T001 记录，不改规格）

见 `00_contract/profile_contract.json` 的 `known_spec_conflicts`（SPEC-01～SPEC-04），以及 `review/tasks/P028-T001/TASK_RESULT.md` 的"规格问题"一节。
