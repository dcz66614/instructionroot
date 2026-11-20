# P028 InstructionRoot Resolve｜有效指令链核验镜
> 项目书（PROJECT_BOOK.md）  
> 版本：1.0.0  
> 立项日期：2026-11-18  
> 项目 ID：P028  
> slug：`instructionroot`  
> 许可：MIT  
> 目标工作量：88 Agent·小时  
> 零真人参与：是  
> 产品运行时：本地优先、默认无网络、无收费 API、无 LLM、无 GPU

---

## 0. 本书的决策结论

### 0.1 最终选题

本轮不照搬附件中的 RICE 排名。独立复核 10 个候选后，选择 **C05 InstructionRoot**，但对其做一次关键收窄和增强，正式立项名为：

> **InstructionRoot Resolve：在指定 coding-agent harness、指定工作目录和指定机器快照下，确定“哪些指令文件会被该 harness 纳入上下文、为什么会被纳入、按什么顺序/组合规则生效、这些文件来自哪里、是否越过信任边界”，并输出可独立复核的确定性收据。**

它**不是**另一个 AGENTS.md 内容扫描器，也不是 prompt-injection 检测器，更不是“判断某条指令好不好”的 LLM 审查器。

产品回答一个非常窄而高价值的问题：

> **“在我让 agent 开始工作之前，它究竟会把哪些 instruction files 当成上下文？”**

然后把第二个问题一起回答：

> **“这些文件的来源、Git 状态、真实路径、导入链和信任边界是什么？”**

### 0.2 为什么不是原候选 C04

独立复核后，C04 的“规约派生变异 + HTTP 边界变异”白空间已经明显缩小：当前公开 GitHub 项目 `caseforge` 已经实现 OpenAPI 驱动的 HTTP reverse-proxy mutation，并提供 `field_drop`、`field_type_swap`、`status_swap_2xx` 等 12 类算子；另有 `mewt` 等成熟通用 mutation testing 工具，以及 2119 直接把“要求是否有测试/测试是否可能失败”作为 enforcement 问题。  
因此 C04 仍有价值，但 88 小时内做出足够清晰的新产品边界会比表面 RICE 分数显示的困难。

本项目反而利用了 C05 的核心痛点，并把其从“来源扫描器”升级为**跨 harness 的有效指令链解析器 + 来源收据**。当前工具分别解决 lint、drift、文档审计，但没有把“harness 实际发现规则 + 当前 CWD + 文件 provenance + import/reference 边界”统一成一张可核验的启动前收据。

### 0.3 立项判断

**GO。**

但 GO 的对象是上述收窄后的 `InstructionRoot Resolve`，不是“做一个通用 agent 安全扫描平台”。

---

## 1. 独立候选评估

### 1.1 评分维度

不采用附件 RICE。独立评分为 1–5 分：

| 维度 | 权重 | 判断问题 |
|---|---:|---|
| 真实问题证据 | 20% | 是否存在近期真实事件、公开研究或高频工程摩擦 |
| 竞争白空间 | 15% | 当前开源/官方方案是否已经把核心价值做掉 |
| 88h 可行性 | 20% | 单人/Agent 两周是否能做出可信 MVP |
| 算法可证伪性 | 20% | 能否用确定性金样本和独立 Oracle 判真伪 |
| 演示价值 | 10% | README 首屏和 Demo 是否一眼看懂 |
| GitHub 传播/产品潜力 | 15% | 受众、CI 接入、标准化潜力、潜在收购方 |

### 1.2 我的排序

| 排名 | 候选 | 总分/100 | 核心判断 |
|---:|---|---:|---|
| **1** | **C05 InstructionRoot（改良为 Resolve）** | **90** | 真实攻击面强；官方已公开 harness 发现规则；现有工具分散解决 lint/drift/audit，仍缺启动前跨 harness provenance receipt；确定性强、88h 可控 |
| **2** | C01 PinProof | 88 | CVE/供应链痛点极强，但核心校验过于简单，且当前生态已有多种 agent 安全/供应链防护，独立白空间小于表面 |
| **3** | C04 SpecMutant | 81 | 问题真实且算法可证伪，但当前 `caseforge` 已直接覆盖 OpenAPI HTTP mutation，通用 mutation 工具也成熟 |
| **4** | C09 ArtifactRelay | 79 | 跨会话产物完整性是真问题，机制清楚；主要风险是 hash ledger 的信任锚本身，88h 内很难做成安全而非演示级 |
| **5** | C02 CacheTruth | 77 | 极强安全痛点和确定性，但当前 bytecode/skill 安全工具已经开始覆盖“缓存/字节码对账”，且 Python 版本/优化级/pyc 规范化边界较复杂 |
| **6** | C07 StaleApproval | 76 | 实现非常容易、Oracle 很强，但 GitHub 原生 stale-review 机制已覆盖大部分前置问题，产品差异主要剩历史审计 |
| **7** | C06 PortParity | 74 | 行为等价是常青痛点，但 `rust-anything` 等直接先例使核心方法不够新 |
| **8** | C10 DomainProof | 69 | 技术可证伪，但用户可在几十秒内手动 WHOIS/DNS，使用频率不足 |
| **9** | C03 SkillCombo | 64 | 组合权限问题真实，但能力抽取一旦离开显式 manifest 就会滑向语义判断；确定性边界难守 |
| **10** | C08 ContextClash | 54 | “矛盾”本身高度语义化；若禁止 LLM，只剩引用存在性和显式字符串冲突，产品价值会明显缩水 |

### 1.3 C05 为什么胜出

**第一，痛点是真实且发生在 agent 的最前置加载层。**  
2026-10-22，Forever Security 报告了真实客户机器上的恶意 `AGENTS.md`：文件位于 `~/Downloads`，其研究称 Codex 在受控测试中执行攻击的比例超过 90%，Claude Code 的对应攻击变体也被复现。关键不是文件“恶意”，而是 agent **把它当成 instruction source**。这正是本产品要核验的边界。

**第二，官方文档已经把“发现规则”变成了可计算对象。**  
OpenAI 的 Codex 文档明确描述了从 `~/.codex`、repo root 到 CWD 的 `AGENTS.md` 链及其顺序；Anthropic 的 Claude Code 文档描述了 `CLAUDE.md` 的向上发现、嵌套按需发现和 `@` import；VS Code/GitHub 文档则公开了 Copilot 的 `AGENTS.md`、`.github/copilot-instructions.md`、path-specific instructions 等位置及组合规则。也就是说，MVP 不需要猜模型“可能怎么想”，可以先核验**文件发现规则**。

**第三，现有开源工具的职责正好留下一个缝。**  
`agentsmd` 偏内容安全 lint；`agentdrift` 偏 Git 历史变更；`instruction-files` 偏文档漂移、路径和预算审计；`agent-security-skill` 偏让 agent 自己做安全审查。InstructionRoot Resolve 不复制这些能力，而是回答“这个 harness 在这个 CWD 会加载什么，以及这些文件到底从哪里来”。

**第四，演示极强。**  
一个 10 秒 Demo 就能显示：

```text
Codex / cwd=repo/services/payments

~/.codex/AGENTS.md                  USER_SCOPE        PASS
repo/AGENTS.md                      GIT_TRACKED       PASS
repo/services/AGENTS.md             GIT_TRACKED       PASS
repo/services/payments/AGENTS.md    GIT_UNTRACKED     WARN
~/Downloads/AGENTS.md               OUTSIDE_REPO      BLOCK
```

再点开 `BLOCK`，显示“为什么发现、为什么不信任、真实路径、SHA-256、Git 状态、是否为 symlink/import”。这比传统安全扫描器更直观。

---

## 2. 用户、场景与未满足需求

### 2.1 目标用户

首要用户：

- 每天使用 Codex、Claude Code、GitHub Copilot CLI/VS Code Agent 的开发者；
- 管理多仓库、多工作树或 monorepo 的 Tech Lead；
- 负责 agent 工作站安全边界的 AppSec/DevSecOps 工程师；
- CI 中希望在 agent 启动前记录“上下文来源”的平台团队。

### 2.2 核心人物

**人物：独立开发者 / 资深工程师。**

他不是安全专家，也不想每次启动 agent 前手工翻目录。他只想确认：

> “我现在在 `repo/services/payments` 启动 Codex，它到底会读哪些 `AGENTS.md`？其中有没有一个是 Downloads 里落下来的、未进 Git、或者通过 import 跳出仓库的？”

### 2.3 典型场景

周一上午：

1. 开发者进入 `repo/services/payments/`；
2. 这里有根目录 `AGENTS.md`；
3. `services/` 又有一个 `AGENTS.md`；
4. 用户 home 下还有 `~/.codex/AGENTS.md`；
5. 一个此前下载的目录里也有 `AGENTS.md`；
6. 某个 instruction file 通过 `@...` 引用了另一个文件；
7. 用户不知道哪些会进入当前 session；
8. 于是直接启动 agent。

### 2.4 频率与代价

规划假设：

- 个人开发者：每天 2–10 次 agent session；
- 多仓库团队：每天大量启动/切换 CWD；
- 每次不需要完整审查内容，只需一次 1–3 秒的 preflight；
- 一次错误 instruction source 可能造成错误配置、错误命令、错误依赖安装、数据外泄或后续会话持续受污染。

**强度：5/5。**

### 2.5 当前 workaround 为什么不够

| workaround | 不足 |
|---|---|
| 手工 `find`/`rg AGENTS.md` | 找得到文件，不知道当前 harness 是否真的会加载 |
| Claude `/memory` | 只解决 Claude 当前会话；不是跨 harness 的可审计机器收据 |
| Copilot `/instructions` | 能查看当前发现，但不是跨 harness 的 provenance/信任分析 |
| 看 Git diff | 能发现仓库内变化，不能解释 home/Downloads/import/symlink 来源 |
| `agentdrift` | 追踪变化，不回答当前 CWD 的有效加载链 |
| `agentsmd` | 查内容风险，不回答“这个文件为什么会进入上下文” |
| 人工打开每份文件 | 成本高，且无法形成机器可复核的启动前证据 |

---

## 3. 真实问题证据

### 3.1 真实攻击事件

Forever Security 于 2026-10-22 报告：

- 客户机器的 `~/Downloads` 中出现恶意 `AGENTS.md`；
- 该文件成为 Codex 的指令来源；
- 研究团队在隔离环境重现；
- 报告称 Codex 在其测试中超过 90% 的尝试执行攻击；
- 同一研究还展示了 Claude Code 的 `CLAUDE.md` 变体。

本项目不把这些比例当成普遍真实概率；它们属于研究方报告的实验结果。产品只采用其中确定的事实：**instruction file 是 agent 行为的实际输入面，且文件来源可能与用户预期不同。**

### 3.2 官方 harness 文档证据

**Codex：**官方 OpenAI 文档说明，Codex CLI 会从 `~/.codex` 以及 repo root 到 CWD 的目录寻找 `AGENTS.md`，并按从全局到更具体目录的顺序合并。

**Claude Code：**Anthropic 文档说明，Claude Code 会自动加载项目/用户内存文件，向上递归寻找 `CLAUDE.md`，并允许 `@path` 递归导入，导入最大深度为 4。

**Copilot：**VS Code/GitHub 文档说明 Copilot 支持 `AGENTS.md`、`.github/copilot-instructions.md`、`.github/instructions/**/*.instructions.md` 等多种来源；不同 surface 的组合/优先级规则并不统一。

因此，“有效 instruction chain”不是虚构概念，而是多个官方文档明确存在的机制差异。

---

## 4. 与现有方案的差异化

### 4.1 现有先例

| 方案 | 借鉴什么 | 不复制什么 |
|---|---|---|
| `agentdrift` | instruction files 是安全变更面；Git 历史有价值 | 不做其 20 条内容/变更规则 |
| `agentsmd` | instruction file 需要安全 lint | 不扫描自然语言恶意内容 |
| `instruction-files` | instruction file discovery 与 drift 可程序化 | 不做其文档质量/line budget |
| `agent-security-skill` | agent instruction 本身是安全边界 | 不让 LLM 审查内容 |
| Codex `/memory` / Copilot `/instructions` | 用户需要知道当前 session 的 instruction sources | 不依赖某一厂商 UI |
| Claude `@import` | import graph 是真实加载机制 | 不执行被引用文件，只解析来源边界 |

### 4.2 独立产品白空间

**InstructionRoot Resolve 的核心 artifact：**

> `effective-instruction-receipt.json`

它至少回答：

1. 当前 harness profile 是什么；
2. CWD 是什么；
3. repo root 是什么；
4. user/global source 有哪些；
5. project source 有哪些；
6. nested source 有哪些；
7. startup-loaded 与 on-demand source 哪些；
8. 每个文件为什么被发现；
9. 真实 canonical path；
10. symlink/junction target；
11. Git tracked/untracked/modified 状态；
12. commit SHA（如适用）；
13. SHA-256；
14. import/reference edges；
15. 是否越过 trust root；
16. harness 是否对其定义 precedence；
17. 若官方没有定义 precedence，明确标 `UNSPECIFIED`，不自行猜测。

### 4.3 不声称“全球首创”

项目不声称“第一个 instruction-file scanner”。已有很多工具。

本项目的差异化主张仅为：

> **把 documented harness resolution + local provenance + trust-boundary analysis 组合成一个跨 harness、启动前、确定性、机器可核验的 instruction-chain receipt。**

该组合是否最终足够新，必须以开发阶段再次检索的公开仓库为准；若出现直接同构竞品，应在 S0 前记录并重新评估，不允许用改名维持“创新”。

---

## 5. 目标与非目标

### 5.1 MVP 目标

1. 支持三个 harness profile：
   - `codex`
   - `claude-code`
   - `copilot-cli`
2. 根据 documented rules 解析当前 CWD 的 instruction sources；
3. 生成 deterministic effective instruction chain；
4. 生成 provenance receipt；
5. 检测：
   - repo 外 instruction；
   - untracked instruction；
   - modified instruction；
   - symlink/junction escape；
   - import escape；
   - missing referenced file；
   - ambiguous/undocumented precedence；
6. 输出 JSON + Markdown + 静态 HTML；
7. 提供 `verify` 退出码，可作为启动前门禁；
8. 提供 GitHub Action；
9. 提供独立 Rust Oracle；
10. 全部验证使用合成 workspace。

### 5.2 非目标

- 不解析 instruction 内容来判断“恶意”；
- 不使用 LLM；
- 不执行 instruction file；
- 不启动 Codex/Claude/Copilot；
- 不拦截 agent runtime；
- 不验证云端组织策略；
- 不证明 agent 实际二进制实现与官方文档完全一致；
- 不做 prompt-injection detector；
- 不做完整 endpoint security；
- 不做通用 agent security platform；
- 不上传文件；
- 不调用收费 API；
- 不要求用户提供账号。

---

## 6. 诚实边界

### 6.1 能证明什么

对给定的：

- harness profile；
- profile version；
- CWD；
- filesystem snapshot；
- Git metadata；

产品可以确定性地证明：

> “按照本产品锁定的、可引用的 harness discovery rules，这些 source 会被发现，并以这些 scope/phase/precedence semantics 进入有效 instruction chain。”

它还能证明文件当前的：

- canonical path；
- hash；
- Git 状态；
- import/reference 边；
- symlink/junction target；
- trust classification。

### 6.2 不能证明什么

1. **不能证明 agent 二进制真的按文档实现。**
2. **不能证明 instruction 内容是善意的。**
3. **不能证明文件是谁创建的。** 对 untracked 文件只能证明“当前不是 Git tracked”，不能虚构作者。
4. **不能证明云端 organization policy。** 未观察到的远端策略记为 `NOT_OBSERVED`。
5. **不能对官方没有定义 precedence 的 harness 自行编造 precedence。**
6. **不能保证 agent runtime 中途读取了新的文件。** MVP 是启动前 snapshot；运行时动态变化属于另一个问题。
7. **不能防止用户绕过门禁。** `verify` 能提供阻断退出码，但是否真正作为启动前门禁取决于用户/CI 如何接入。

---

## 7. 产品工作流

### 7.1 CLI

```text
instructionroot inspect \
  --harness codex \
  --cwd ./services/payments \
  --format html,json,md
```

然后：

```text
instructionroot verify \
  --harness codex \
  --cwd ./services/payments \
  --policy instructionroot.json
```

结果：

```text
InstructionRoot Resolve 1.0
Harness: codex
CWD:     /work/acme/services/payments
Repo:    /work/acme

FAIL

[BLOCK] ~/Downloads/AGENTS.md
  discovered_by: cwd-chain
  trust: OUTSIDE_REPO
  git: UNTRACKED
  sha256: 8a2...
  reason: source is outside approved instruction roots

[WARN] services/payments/AGENTS.md
  discovered_by: nested-directory
  trust: GIT_UNTRACKED
  reason: not present in HEAD

receipt: .instructionroot/receipt.json
```

### 7.2 用户流程

1. 安装；
2. 选择 harness；
3. 指定 CWD；
4. `inspect`；
5. 查看 effective chain；
6. 处理 BLOCK/WARN；
7. `verify`；
8. agent 才启动。

### 7.3 CI 流程

```text
PR
 └─ instructionroot verify
       ├─ PASS → continue
       └─ FAIL → block
```

---

## 8. 功能需求

### 8.1 FR-01 Harness Profile

必须支持：

- Codex；
- Claude Code；
- GitHub Copilot CLI。

每个 profile 有独立版本号，例如：

```text
codex-2026-11
claude-code-2026-11
copilot-cli-2026-11
```

### 8.2 FR-02 Filesystem Discovery

必须：

- 处理绝对/相对路径；
- 解析 `..`；
- 解析 symlink；
- Windows 支持 drive letter；
- Windows junction 必须识别；
- 不 follow 无限 symlink loop；
- 不把不存在文件伪造为存在。

### 8.3 FR-03 Harness Resolution

必须输出：

```text
source_id
path
scope
phase
discovery_rule
precedence
```

### 8.4 FR-04 Provenance

每个 source：

```json
{
  "path": "repo/AGENTS.md",
  "sha256": "...",
  "git": {
    "tracked": true,
    "modified": false,
    "head_commit": "..."
  }
}
```

### 8.5 FR-05 Trust Classification

固定枚举：

```text
GIT_TRACKED
GIT_MODIFIED
GIT_UNTRACKED
USER_SCOPE
OUTSIDE_REPO
SYMLINK_ESCAPE
IMPORT_ESCAPE
MISSING
NOT_OBSERVED
```

### 8.6 FR-06 Import Graph

MVP 只解析 profile 明确支持的 import/reference 机制。

例如 Claude/Copilot 的 `@path`：

```text
A.md
 └── @../shared/B.md
       └── @~/Downloads/C.md
```

若 `C.md` 越过 policy root：

```text
IMPORT_ESCAPE
```

### 8.7 FR-07 Deterministic Receipt

相同 snapshot + profile + policy：

```text
receipt_hash == receipt_hash
```

时间、耗时等非确定字段不得进入 canonical hash。

### 8.8 FR-08 Verify Exit Codes

| code | 含义 |
|---:|---|
| 0 | PASS |
| 10 | WARN |
| 20 | BLOCK |
| 30 | INPUT_ERROR |
| 40 | PROFILE_UNSUPPORTED |
| 50 | INTERNAL_ERROR |

默认 CI 模式：

- WARN 可配置；
- BLOCK 必须非零；
- INPUT_ERROR 必须非零；
- INTERNAL_ERROR fail-closed。

---

## 9. S0 门禁

**S0 = T001–T007，共 72 小时。**

T008 之前禁止进入 UI、GitHub Action、发布包装。

### 9.1 S0 必须证明

1. 3 个 harness profiles 可运行；
2. 60 个合成 workspace fixtures；
3. 至少 180 个 source-resolution assertions；
4. 12 类边界场景：
   - nested；
   - global；
   - untracked；
   - modified；
   - symlink；
   - junction；
   - import；
   - import escape；
   - missing；
   - duplicate；
   - ambiguous precedence；
   - unsupported profile；
5. Python production resolver 与 Rust Oracle：
   - source list parity 100%；
   - trust classification parity 100%；
   - canonical receipt hash parity 100%；
6. 重跑 100 次，canonical receipt hash 不变；
7. malformed fixture 不得产生 PASS；
8. 不允许网络访问；
9. 不允许人工改标签后再判定。

### 9.2 S0 失败条件

任一：

- Oracle mismatch；
- deterministic hash mismatch；
- trust escape 漏报；
- unsupported precedence 被错误“猜测”；
- fail-open；
- production 需要网络；
- 需要真人标注才能完成测试；

则：

```text
S0: FAIL
```

**立即停止，不执行 T008–T014。**

---

## 10. UI / 交互设计

### 10.1 首页

顶部：

```text
INSTRUCTIONROOT
Effective Instruction Chain
```

右上：

```text
Codex · repo/services/payments
PASS / WARN / BLOCK
```

主体三栏：

**左栏：Source Tree**

```text
HOME
 └─ ~/.codex/AGENTS.md       PASS
REPO
 ├─ AGENTS.md                PASS
 └─ services/
    └─ AGENTS.md             WARN
OUTSIDE
 └─ ~/Downloads/AGENTS.md    BLOCK
```

**中栏：Effective Chain**

每个 source 一张卡：

- scope；
- load phase；
- discovery rule；
- precedence；
- SHA-256；
- Git status。

**右栏：Why**

点击 source 后显示：

```text
WHY DISCOVERED
Codex rule: root → CWD upward chain

WHY TRUSTED
Inside repo root
Git tracked
No symlink escape

WHY BLOCKED
Outside approved root
Untracked
```

### 10.2 图视图

用有向图：

```text
~/.codex/AGENTS.md
        │
        ▼
repo/AGENTS.md
        │
        ▼
services/AGENTS.md
        │
        ▼
payments/AGENTS.md
```

import：

```text
payments/AGENTS.md
      │ @../shared/rules.md
      ▼
shared/rules.md
```

越界边显示为：

```text
payments/AGENTS.md
      │ @~/Downloads/x.md
      ▼
Downloads/x.md   BLOCK
```

### 10.3 演示模式

内置一个 synthetic malicious-looking workspace：

- `repo/AGENTS.md` 合法；
- `repo/services/AGENTS.md` 合法；
- `repo/services/payments/AGENTS.md` untracked；
- `~/Downloads/AGENTS.md`；
- `repo/CLAUDE.md` import Downloads。

点击一次 `Run preflight`，红色路径出现，随后生成 receipt。

**不展示真实恶意 payload。**

---

## 11. 技术栈与版本策略

### 11.1 Production

- Python 3.14.x；
- 标准库优先；
- `pathlib`；
- `subprocess`，所有 Git 调用 `shell=False`；
- `hashlib` SHA-256；
- `json`；
- `sqlite3` 可选，仅用于本地历史缓存，不进入 S0 核心；
- HTML/CSS/JavaScript 静态 UI；
- 无 Node.js 运行时依赖；
- 无外部网络依赖。

Python 的 `pathlib.Path.resolve()` 可用于确定性 canonical path / symlink resolution；`subprocess` 默认 `shell=False`，项目必须保持该安全边界。

### 11.2 Oracle

- Rust stable；
- T001 锁定 `rust-toolchain.toml`；
- `serde_json`；
- `sha2`；
- `std::fs`；
- 不调用 production Python；
- 不读取 production resolver rule module。

### 11.3 浏览器

只要求现代 Chromium/Firefox/Safari 中任一可打开静态 HTML；核心 CLI 不依赖浏览器。

### 11.4 版本策略

所有 release 必须保存：

```text
python --version
git --version
rustc --version
oracle --version
instructionroot --version
profile versions
```

---

## 12. 系统架构

```text
                    ┌───────────────────────┐
                    │ CLI                   │
                    │ inspect / verify      │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │ Snapshot Layer        │
                    │ cwd / repo / home     │
                    │ fs / git metadata      │
                    └───────────┬───────────┘
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
     ┌───────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐
     │ Harness       │  │ Provenance   │  │ Import       │
     │ Resolver      │  │ Resolver     │  │ Graph        │
     └───────┬───────┘  └──────┬───────┘  └──────┬───────┘
             │                  │                  │
             └──────────────────┼──────────────────┘
                                │
                       ┌────────▼────────┐
                       │ Receipt Builder │
                       │ JCS-like stable │
                       │ canonical JSON  │
                       └────────┬────────┘
                                │
                   ┌────────────┴────────────┐
                   │                         │
             JSON / MD / HTML           Verify exit code
                   │
                   ▼
              Independent
              Rust Oracle
```

---

## 13. 核心算法

### 13.1 A：Canonical Path

输入：

```text
raw_path
cwd
home
repo_root
```

步骤：

1. resolve absolute path；
2. resolve symlink/junction；
3. normalize separators；
4. canonical UTF-8 path representation；
5. 记录 lexical path 与 resolved path 两者。

**Windows 平台分支（FR-02 的细化；2026-11-19 Windows 实测后补）：**

- **盘符绝对路径**：输入含盘符（`X:` + `\` 或 `/`，如 `C:\…` / `C:/…`）时，在 Windows 上必须按该盘符的根解析（`C:\…`），canonical 形式保留盘符、以 `/` 作分隔符（`C:/…`）。**禁止**把绝对路径重建成 `"/" + "/".join(parts)`——`"/C:/…"` 在 Windows 上是当前盘的根相对路径，不存在。2026-11-19 实测：两侧实现都犯此错，4 类 junction case 全部在 cwd 校验阶段 INPUT_ERROR，与 junction 无关。
- **相对引用拼接**：相对引用（如 import 的 `@shared/ok.md`）与 cwd 拼接后的结果也要再经过同一 Windows 归一化（FIX-R3 A）——`os.path.join` 在 Windows 上产出反斜杠拼写，不归一化则盘符分支不匹配、落回 POSIX 分支拼成 `/C:\…`。
- **junction 判定**：Windows 上组件是否为链接，**只看 reparse tag**：`0xA0000003`（junction / mount point）与 `0xA000000C`（symlink）都算链接，都必须跟随解析；不得只认其中一种，也不得以只认 symlink 的 API 作唯一判定。实测：Python `os.path.islink()` 对 junction 返回 False，Rust `file_type().is_symlink()` 返回 True——两侧必须按本条统一，不得各行其是。
- **Linux 行为不变**：Linux 上 `/C:/…` 仍是普通路径形态（根下名为 `C:` 的目录），不得 reinterpret 为 Windows 盘符；Linux symlink 判定不变。
- **UNC 路径**（`\\server\share\…`）仍为纯字符串，不做文件系统解析。

本条只补算法 A 的平台分支；receipt schema 与 S0 固件不变。

输出：

```text
canonical_path
resolved_path
escape_flag
```

### 13.2 B：Harness Resolution

对每个 profile，维护：

```json
{
  "profile_id": "codex",
  "profile_version": "codex-2026-11",
  "rules": [...]
}
```

每条 rule：

```json
{
  "scope": "user|repo|nested",
  "pattern": "...",
  "phase": "startup|on_demand",
  "order": "..."
}
```

**不把未文档化行为补成规则。**

### 13.3 C：Git Provenance

只使用本地只读命令：

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
git checkout
git reset
```

### 13.4 D：Trust Classification

优先级：

```text
IMPORT_ESCAPE
SYMLINK_ESCAPE
MISSING
OUTSIDE_REPO
GIT_UNTRACKED
GIT_MODIFIED
GIT_TRACKED
USER_SCOPE
```

策略不是“猜文件是否恶意”，而是机械判断其 provenance。

### 13.5 E：Import Graph

只解析 profile 明确声明的 import syntax。

每条 edge：

```json
{
  "from": "...",
  "raw_reference": "...",
  "resolved_target": "...",
  "allowed": false,
  "reason": "IMPORT_ESCAPE"
}
```

### 13.6 F：Receipt Canonicalization

receipt 中排除：

- wall-clock timestamp；
- duration；
- temporary port；
- machine username（除非用户主动要求）。

保留：

- profile；
- CWD；
- repo root；
- source order；
- canonical paths；
- SHA-256；
- Git status；
- trust；
- import edges；
- rule IDs。

最终：

```text
receipt_hash = SHA256(canonical_json(receipt))
```

MVP 推荐采用 RFC 8785 JCS 兼容 canonical JSON，避免 Python 与 Rust 对 JSON key order/number serialization 的分歧。

---

## 14. 数据结构与接口

### 14.1 CLI

```text
instructionroot inspect
instructionroot verify
instructionroot export
instructionroot profile list
instructionroot oracle
instructionroot version
```

### 14.2 `instructionroot.yaml` 不使用 YAML

MVP 固定使用 JSON，减少依赖和 parser 差异：

```json
{
  "version": 1,
  "harness": "codex",
  "cwd": ".",
  "policy": {
    "allow_user_scope": true,
    "allow_repo_tracked": true,
    "block_repo_untracked": true,
    "block_outside_repo": true,
    "block_symlink_escape": true,
    "block_import_escape": true
  }
}
```

### 14.3 Receipt Schema

```json
{
  "receipt_version": 1,
  "profile": {
    "id": "codex",
    "version": "codex-2026-11"
  },
  "workspace": {
    "cwd": "/work/acme/services/payments",
    "repo_root": "/work/acme"
  },
  "verdict": "BLOCK",
  "sources": [
    {
      "path": "/work/acme/AGENTS.md",
      "scope": "repo",
      "phase": "startup",
      "discovery_rule": "codex.repo-root",
      "sha256": "…",
      "git": {
        "tracked": true,
        "modified": false,
        "head_commit": "…"
      },
      "trust": "GIT_TRACKED"
    }
  ],
  "edges": [],
  "receipt_hash": "…"
}
```

---

## 15. 合成数据与金样本

### 15.1 Fixture 原则

全部数据由测试脚本生成：

```text
fixtures/
  codex/
  claude/
  copilot/
```

不使用真人 repo，不使用真实用户 instruction file，不读取开发者 home 中的真实内容作为测试数据。

### 15.2 必备金样本

| ID | 场景 | 期望 |
|---|---|---|
| S01 | repo root 单文件 | PASS |
| S02 | nested instruction | PASS |
| S03 | user/global + repo | PASS |
| S04 | repo untracked | WARN/BLOCK |
| S05 | modified tracked | WARN |
| S06 | symlink → repo | PASS/WARN 按 policy |
| S07 | symlink → outside | BLOCK |
| S08 | missing import | BLOCK |
| S09 | import → outside | BLOCK |
| S10 | duplicate same file | 去重 |
| S11 | unsupported precedence | `UNSPECIFIED` |
| S12 | Windows junction escape | BLOCK |
| S13 | Claude import depth 4 | PASS |
| S14 | Claude import depth 5 | BLOCK |
| S15 | Copilot `applyTo` match | PASS |
| S16 | Copilot `applyTo` no match | NOT_APPLICABLE |
| S17 | Codex root→CWD chain | 顺序正确 |
| S18 | home source | USER_SCOPE |
| S19 | outside home source | BLOCK |
| S20 | path normalization | canonical equality |
| S21 | Unicode path | stable |
| S22 | case-sensitive/insensitive fixture | profile-specific |
| S23 | git deleted file | MISSING |
| S24 | git rename | provenance recorded |
| S25 | non-git directory | NOT_GIT_REPO |

S0 至少覆盖 60 个 workspace case；上述场景各自生成多个变体。

---

## 16. 独立 Oracle

### 16.1 原则

Oracle 必须：

- 使用 Rust；
- 不 import Python production package；
- 不读取 production resolver module；
- 不把 production receipt 当 ground truth；
- 独立实现 profile resolution；
- 独立实现 path normalization；
- 独立实现 SHA-256；
- 独立实现 trust classification；
- 独立计算 canonical receipt hash。

### 16.2 Oracle 输入

```text
oracle_case.json
```

包含：

```text
fixture_root
cwd
repo_root
harness_profile
policy
expected_sources
expected_edges
expected_verdict
```

### 16.3 Oracle 输出

```json
{
  "case_id": "S07",
  "pass": true,
  "source_parity": true,
  "edge_parity": true,
  "verdict_parity": true,
  "receipt_hash_parity": true
}
```

### 16.4 独立性门槛

禁止：

```text
Python -> Rust -> import generated production answer
```

允许：

```text
Shared fixture specification
        │
   ┌────┴────┐
   ▼         ▼
Python     Rust
resolver   oracle
```

---

## 17. 验证指标

### S0 核心指标

| 指标 | 门槛 |
|---|---:|
| Source discovery parity | 100% |
| Trust classification parity | 100% |
| Import edge parity | 100% |
| Verdict parity | 100% |
| Receipt hash parity | 100% |
| Deterministic rerun | 100/100 |
| Known escape detection | 100% |
| Malformed input fail-closed | 100% |
| Runtime network access | 0 |
| Human labels required | 0 |

### MVP 性能目标

在普通开发机：

- 500 个 instruction candidates；
- 100 个 import edges；
- 10 个 Git roots；

单次 preflight：

> p95 ≤ 500 ms（不包含 Git repository 初次启动冷缓存的极端情况）。

若未达标不自动扩大工程范围；记录为 P2，除非影响正常 CLI 使用。

---

## 18. 安全、隐私与许可证

### 18.1 默认隐私

不上传：

- instruction 内容；
- repo 内容；
- Git commit message；
- 用户名；
- home directory 全量列表。

默认 receipt 只保存：

- path；
- hash；
- Git state；
- source category；
- rule ID。

### 18.2 敏感路径

可配置：

```json
{
  "redact_paths": true
}
```

将：

```text
/home/sam/private/repo
```

显示为：

```text
<HOME>/private/repo
```

但 canonical hash 仍基于内部 canonical representation，确保 receipt 可验证。

### 18.3 安全边界

- 不执行 instruction；
- 不执行 import；
- 不访问网络；
- 不调用 shell；
- Git 子进程 `shell=False`；
- fail-closed；
- profile 不确定时不得 PASS。

### 18.4 MIT

仓库必须包含：

```text
LICENSE
```

内容为 MIT License。

第三方 profile 文档引用仅保留 URL 和必要事实，不复制大段受版权保护文本。

---

## 19. 示例输入 / 输出

### 19.1 输入

目录：

```text
workspace/
├── .git/
├── AGENTS.md
├── services/
│   ├── AGENTS.md
│   └── payments/
│       └── AGENTS.md
└── README.md

/home/user/
└── .codex/
    └── AGENTS.md

/home/user/Downloads/
└── AGENTS.md
```

命令：

```bash
instructionroot inspect \
  --harness codex \
  --cwd workspace/services/payments \
  --format json
```

### 19.2 输出摘要

```text
VERDICT: BLOCK

1  ~/.codex/AGENTS.md
   USER_SCOPE / startup / PASS

2  workspace/AGENTS.md
   GIT_TRACKED / startup / PASS

3  workspace/services/AGENTS.md
   GIT_TRACKED / startup / PASS

4  workspace/services/payments/AGENTS.md
   GIT_UNTRACKED / startup / WARN

5  ~/Downloads/AGENTS.md
   OUTSIDE_REPO / NOT_EXPECTED / BLOCK

Receipt:
  source_count = 5
  blocked = 1
  warnings = 1
  receipt_hash = sha256:…
```

---

## 20. T001–T014 总任务与 88 小时

| TASK_ID | 任务 | 小时 | 阶段 |
|---|---|---:|---|
| T001 | 问题/契约冻结 + harness profile 规格 | 8 | S0 |
| T002 | 文件系统 snapshot + canonical path | 12 | S0 |
| T003 | Harness resolution engine | 12 | S0 |
| T004 | Git provenance + trust classifier | 10 | S0 |
| T005 | Import graph + escape detection | 10 | S0 |
| T006 | Rust independent Oracle | 10 | S0 |
| T007 | S0 golden corpus + gate | 10 | S0 |
| T008 | CLI / policy / exit codes | 4 | Post-S0 |
| T009 | HTML dashboard | 4 | Post-S0 |
| T010 | GitHub Action / pre-commit | 2 | Post-S0 |
| T011 | 合成 corpus 扩充 + Windows cases | 2 | Post-S0 |
| T012 | Security / privacy / packaging | 1 | Post-S0 |
| T013 | README / examples / MIT docs | 1 | Post-S0 |
| T014 | 集成、性能、repeatability、release | 2 | Post-S0 |
| **合计** | | **88** | |

---

## 21. 最终交付物

```text
P028-instructionroot/
├── README.md
├── LICENSE
├── pyproject.toml
├── src/instructionroot/
│   ├── cli.py
│   ├── snapshot.py
│   ├── paths.py
│   ├── git.py
│   ├── profiles/
│   │   ├── codex.py
│   │   ├── claude.py
│   │   └── copilot.py
│   ├── resolver.py
│   ├── provenance.py
│   ├── trust.py
│   ├── imports.py
│   └── receipt.py
├── oracle/
│   ├── Cargo.toml
│   ├── rust-toolchain.toml
│   └── src/
├── fixtures/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── golden/
│   └── oracle/
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── .github/workflows/instructionroot.yml
└── docs/
    ├── PROFILES.md
    ├── RECEIPT_SCHEMA.md
    └── LIMITATIONS.md
```

---

## 22. 参考网址与用途

### 官方 harness 文档

1. OpenAI Codex prompting guide / `AGENTS.md` discovery  
   https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide  
   用途：Codex 从 `~/.codex` 与 repo root→CWD 发现 instruction chain 的依据。

2. Anthropic Claude Code memory  
   https://docs.anthropic.com/zh-CN/docs/claude-code/memory  
   用途：`CLAUDE.md`、向上发现、nested discovery、`@` import 的依据。

3. VS Code custom instructions reference  
   https://code.visualstudio.com/docs/agents/reference/custom-instructions-reference  
   用途：Codex/Claude/Copilot 的 instruction locations、nested behavior、组合语义。

4. GitHub Copilot custom instructions  
   https://docs.github.com/en/copilot/concepts/prompting-and-context/custom-instructions  
   用途：Copilot precedence / combination 的边界。

5. GitHub Copilot CLI custom instructions  
   https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions  
   用途：Copilot CLI 的 user/repo/agent instruction locations 与 references。

### 真实问题证据

6. Forever Security  
   https://forever.security/blog/hijacking-ai-agents-via-downloads-folder/  
   用途：2026-10-22 `AGENTS.md` / `CLAUDE.md` Downloads 攻击报告。

7. BleepingComputer  
   https://www.bleepingcomputer.com/news/security/ai-coding-agents-hijacked-using-agentsmd-file-in-downloads-folder/  
   用途：对事件、攻击条件与测试结果的独立报道。

### 现有开源先例

8. `agentdrift`  
   https://github.com/kriskimmerle/agentdrift  
   用途：change-tracking 先例；明确其职责不是当前有效 instruction resolution。

9. `agentsmd`  
   https://github.com/kriskimmerle/agentsmd  
   用途：instruction content lint 先例；明确不复制内容扫描。

10. `instruction-files`  
    https://github.com/btakita/instruction-files  
    用途：instruction discovery/audit 先例；明确不复制 harness-specific effective chain receipt。

11. `agent-security-skill`  
    https://github.com/olanokhin/agent-security-skill  
    用途：agent security review 先例；其本质是 guidance/LLM review，不是本地确定性 resolver。

### 方法参考

12. Python `pathlib`  
    https://docs.python.org/3/library/pathlib.html  
    用途：canonical path / symlink resolution。

13. Python `subprocess`  
    https://docs.python.org/3/library/subprocess.html  
    用途：安全调用 Git，保持 `shell=False`。

14. RFC 8785 JSON Canonicalization Scheme  
    https://www.rfc-editor.org/rfc/rfc8785.html  
    用途：跨 Python/Rust 的确定性 JSON canonicalization。

### 被本轮独立复核后降级的 C04 先例

15. Trail of Bits `mewt`  
    https://github.com/trailofbits/mewt  
    用途：成熟通用 mutation testing。

16. `caseforge`  
    https://github.com/testmind-hq/caseforge  
    用途：当前公开的 OpenAPI HTTP reverse-proxy mutation 先例；是本轮降低 C04 白空间评分的关键新证据。

---

## 23. 立项后的工程纪律

1. S0 失败不得继续 T008。
2. 任何 profile 行为必须有官方来源 URL 或明确标为 `UNVERIFIED`。
3. 不把文档未定义的 precedence 猜成确定规则。
4. 不把“文件可被发现”说成“内容安全”。
5. 不把 Git tracked 说成“作者可信”。
6. 不使用真人 workspace。
7. 不使用 LLM 参与生产判定。
8. Oracle 必须独立实现。
9. 所有发布 receipt 必须可由 Oracle 重算。
10. 任何未验证功能必须在 README/限制文档中明确写出。

**项目状态：PLANNED / S0 未执行。**
