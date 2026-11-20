# P028-T003 任务结果 — Harness Resolution Engine

- **TASK_ID**: P028-T003
- **日期**: 2026-11-18
- **状态**: PASS（验收命令全部通过，见 §3）
- **工作目录**: `~/workspace/p028-instructionroot/`（git main，未提交；提交由协调员做）

## 1. 做了什么

实现 Harness Resolution Engine：三个 harness profile + 统一 resolver，
输出 deterministic effective instruction chain。只用 Python 标准库，
不联网，零真人，全部合成数据。

### 改动文件清单（新增，全部是 T003 所有权范围）

| 文件 | 说明 |
|---|---|
| `02_src/instructionroot/profiles/_common.py` | 共享基础：`SourceCandidate` / `Precedence` / `NotApplicable` / `ResolveContext`、canonical 双记录候选构造、目录枚举、YAML 子集 frontmatter 解析（`paths` / `applyTo`）、glob 匹配（含 `**/` 零目录匹配） |
| `02_src/instructionroot/profiles/codex.py` | Codex：`codex.user` + `codex.repo-chain`（ORDERED，root→CWD）+ `codex.override-fallback`（UNSPECIFIED，不猜语义） |
| `02_src/instructionroot/profiles/claude.py` | Claude：managed/user/project/local 四级、向上发现、nested 按需、`.claude/rules/`（`paths` 前置分流）、AGENTS.md fallback 条件、additional-dirs、4 MiB 跳过、symlink 外部规则排除、`@import` 候选（depth 计数，max 4 跳） |
| `02_src/instructionroot/profiles/copilot.py` | Copilot CLI：user/repo/modular/AGENTS.md/CLAUDE.md/GEMINI.md/custom-dirs、`applyTo` 门控、combine 语义全部 `COMBINE_UNORDERED`、repo-modular 排除中间目录 |
| `02_src/instructionroot/profiles/__init__.py` | profile 包导出 |
| `02_src/instructionroot/resolver.py` | 统一接口 `discover(snapshot, cwd, policy, harness=...) -> list[SourceCandidate]` + `discover_with_report(...) -> DiscoveryReport`（含 `considered_but_not_applicable`）；S10 去重（同一 canonical 只出现一次，`also_discovered_by` 记录后续规则）；policy 校验；`UnsupportedProfileError` |
| `05_tests/unit/test_resolver.py` | 41 个单元测试 |
| `01_s0/fixtures/resolver/build_resolver_fixtures.py` | 20 个 resolver 金样本生成器（确定性、可重跑） |
| `01_s0/fixtures/resolver/README.md` | 金样本格式说明（含 T003 对冻结格式的扩展字段） |
| `01_s0/fixtures/resolver/<20 个 case>/` | 生成的 case 树（`case.json` + `<case-id>.expected.json` + 合成 home/repo/extra） |
| `scripts/run_golden.py` | golden 运行器（`--stage resolver`；输出 `golden_source_order` 与 `golden_source_set`） |
| `review/tasks/P028-T003/TASK_RESULT.md` | 本文件 |

### 未动范围（核查）

- `00_contract/*` 未动；`02_src/instructionroot/paths.py`、`snapshot.py` 未动；
  `03_oracle/*`、`04_ui/*` 未动；`.venv/` 未动。
- T004 并行会话新增的 `git.py` / `trust.py` / `test_git.py` / `test_trust.py`
  我未碰；全量测试一起跑仍全绿（见 §3）。
- `review/COORDINATOR_LOG.md` 的 `M` 修改是我开工前就已存在的（并行会话），不是我改的。

## 2. 覆盖的 profile 规则清单（22/22）

### Codex 3/3

| rule | 实现 |
|---|---|
| `codex.user` | `~/.codex/AGENTS.md`，ORDERED，链首 |
| `codex.repo-chain` | repo root→CWD 每目录一个 `AGENTS.md`，ORDERED，root-to-leaf |
| `codex.override-fallback` | 每目录 `AGENTS.override.md` 列为候选，precedence `UNSPECIFIED`，不实现 replace/supplement 语义（UNVERIFIED） |

### Claude 11/11

| rule | 实现 |
|---|---|
| `claude-code.managed` | Linux `/etc/claude-code/CLAUDE.md`，ORDERED 首位（macOS/Windows 路径 Linux 上不可观察，见 §5 Q10） |
| `claude-code.user` | `~/.claude/CLAUDE.md`，ORDERED |
| `claude-code.project` | CWD 及每个祖先目录的 `CLAUDE.md` / `.claude/CLAUDE.md`，ORDERED，根→CWD 拼接 |
| `claude-code.local` | 每目录 `CLAUDE.local.md`，ORDERED，附于该目录 `CLAUDE.md` 之后 |
| `claude-code.nested` | working file 所在子目录的 `CLAUDE.md` / `CLAUDE.local.md`，on_demand，UNSPECIFIED |
| `claude-code.rules-user` | `~/.claude/rules/**/*.md` 递归，ORDERED，在 project rules 之前 |
| `claude-code.rules-startup` | project `.claude/rules/**/*.md`（无 `paths` 前置），ORDERED |
| `claude-code.rules-path-scoped` | 含 `paths` 前置的规则：working file 匹配 glob 才 on_demand 加载；不匹配记 `PATH_SCOPED_NO_MATCH`；无 trigger 记 `PATH_SCOPED_NO_TRIGGER`；不可解析的 YAML 按无 `paths` 处理（契约原文） |
| `claude-code.agents-fallback` | 仅当 CWD 及任一祖先目录都不存在 `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md` 时，才读每目录 `AGENTS.md` / `.claude/AGENTS.md`（`~/.claude/CLAUDE.md`、managed、rules 不计入该条件） |
| `claude-code.agents-nested` | 子目录无任一 CLAUDE 文件时，该子目录的 `AGENTS.md`，on_demand，UNSPECIFIED |
| `claude-code.additional-dirs` | 仅当 policy `allow_additional_directories=true` 且提供了目录时；`CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md` / `.claude/rules/*.md`（非递归，含 `paths` 的规则排除）；默认关闭记 `ADDITIONAL_DIRS_DISABLED_BY_POLICY` |

另：`@import` 候选（`iter_import_candidates`）：`@path` 相对含 import 的文件；
跳过 fenced code / 行内 code / 引号包裹路径；反斜杠转义空格；BFS depth 计数，
直接 import = depth 1，max 4 跳（SPEC-01 官方文档为准）；depth 5 候选仍列出
（`allowed=false, reason=DEPTH_EXCEEDED`，不再展开）；不存在的目标
`allowed=false, reason=MISSING`，`canonical_target=null`（receipt edge 的
`resolved_target` 为 null 口径）。仅从 startup 的 CLAUDE/AGENTS 源展开，
rules 文件内的 import 不展开（无来源佐证）。

### Copilot CLI 8/8（全部 COMBINE_UNORDERED，不排优先级）

| rule | 实现 |
|---|---|
| `copilot-cli.user` | `$HOME/.copilot/copilot-instructions.md`（`$COPILOT_HOME` 优先，环境变量回退），startup |
| `copilot-cli.user-modular` | `$HOME/.copilot/instructions/**/*.instructions.md`，`applyTo` 门控，on_demand |
| `copilot-cli.repo-wide` | `.github/copilot-instructions.md`，标准位置（含中间目录 + working file 路径上的嵌套目录），startup |
| `copilot-cli.repo-modular` | `.github/instructions/**/*.instructions.md`，标准位置**不含**中间目录，`applyTo` 门控，on_demand |
| `copilot-cli.agents` | `AGENTS.md`，标准位置，startup |
| `copilot-cli.claude` | `CLAUDE.md` 与 `.claude/CLAUDE.md`，标准位置，startup |
| `copilot-cli.gemini` | `GEMINI.md`，标准位置，startup（`@` 不展开） |
| `copilot-cli.custom-dirs` | `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` 每目录的 `AGENTS.md` + `*.instructions.md`（后者同样 `applyTo` 门控，见 §5 Q8），startup |

## 3. 验收命令输出（全部通过）

### 单元测试

```text
$ .venv/bin/python -m pytest 05_tests/unit/test_resolver.py -q
.........................................                                [100%]
41 passed in 0.20s
```

全量（T002 + T003 + 并行 T004 的测试一起跑）：

```text
$ .venv/bin/python -m pytest 05_tests/unit/ -q
........................................................................ [ 84%]
...........................                                              [100%]
169 passed, 2 skipped in 1.11s
```

### Golden（20 个 case，两次运行结果一致）

```text
$ .venv/bin/python scripts/run_golden.py --stage resolver -v
[PASS] claude-agents-fallback (claude-code)
[PASS] claude-agents-fallback-blocked (claude-code)
[PASS] claude-basic (claude-code)
[PASS] claude-import-depth4 (claude-code)
[PASS] claude-import-depth5 (claude-code)
[PASS] claude-nested (claude-code)
[PASS] claude-nested-disabled (claude-code)
[PASS] claude-rules-paths (claude-code)
[PASS] codex-basic (codex)
[PASS] codex-empty (codex)
[PASS] codex-norepo (codex)
[PASS] codex-override (codex)
[PASS] codex-user-only (codex)
[PASS] copilot-applyto-absent (copilot-cli)
[PASS] copilot-applyto-match (copilot-cli)
[PASS] copilot-applyto-nomatch (copilot-cli)
[PASS] copilot-basic (copilot-cli)
[PASS] copilot-custom-dirs (copilot-cli)
[PASS] copilot-dedup (copilot-cli)
[PASS] copilot-intermediate (copilot-cli)
cases=20 passed=20 failed=0
golden_source_order=100.0%
golden_source_set=100.0%
```

金样本覆盖：Codex 链顺序/override/空链/非 git；Claude 链/rules 前置/nested/
fallback 条件/import depth 4 PASS 与 depth 5 BLOCK；Copilot 全组合/
`applyTo` 匹配与不匹配与缺失/custom-dirs/中间目录排除/去重（S10）。

## 4. 关键设计决定（非契约发明，是接口层面的必要选择）

1. **`ancestor_stop`（祖先链上界）**：Claude 的向上发现按契约走到文件系统根。
   生产默认值就是根（`ancestor_stop=None`）。但金样本/单元测试必须把 walk
   界定在合成 fixture 内，否则会拾取 fixture 之上的真实文件——实测：
   本机 `/home/hatch/AGENTS.md` 真实存在，首次 smoke 就被 AGENTS fallback
   误拾。Golden runner 与单元测试统一传 `ancestor_stop=<case/tmp 根>`。
   这是对“被观测文件系统之根”的建模，不是新规则。
2. **Policy 只影响发现的两处**：`allow_nested_on_demand=false` 排除 on-demand
   源、`allow_additional_directories=false`（默认）排除 additional-dirs 源，
   其余 policy 字段只影响 verdict（T008），不改变发现集合——与
   `policy_schema.json` 的 verdict_effect 一致。
3. **去重键 = canonical（词法）路径**：同一 canonical 文件只出现一次，
   首个 rule 保留，后续 rule 进 `also_discovered_by`。symlink 别名拼写与目标
   拼写是不同的 canonical 路径，**不**合并（见 §5 Q9）。
4. **不存在的 pattern 路径不产生 source**：发现只列出磁盘上存在的文件；
   MISSING 信任值由 T004（git 已删除文件）与 T005（import 目标）产生，
   不是发现层的 source（见 §5 Q6）。
5. **Copilot 的顺序不断言**：`run_golden.py` 对 copilot-cli 只断言集合，
   order 分数取集合结果；模块内输出顺序是固定枚举顺序（user → modular →
   repo-wide → repo-modular → agents/claude/gemini → custom-dirs，组内按
   canonical 排序），不是优先级声明。
6. **Resolver 阶段 expected 文件不断言 trust/verdict**：trust 是 T004、
   verdict 是 T008 的职责；T007 的完整 expected 文件再补。`01_s0/expected/`
   目录我未动（T007 所有）；resolver expected 文件与 case 同目录存放，
   避免抢 T007 的目录。
7. **递归 pattern 发现走确定性 live walk**：snapshot 可能只含显式路径
   （不含整树），而 `.claude/rules/**/*.md` 这类递归 pattern 需要目录枚举；
   `list_dir_files` 按名排序、不跟随目录 symlink，sha 优先取 snapshot 条目，
   缺失时 live 计算。输出顺序与 snapshot 是否含树无关。

## 5. 契约问题（未改契约，请 T007 / parent 定夺）

- **Q5**：同一目录同时存在 `CLAUDE.md` 与 `.claude/CLAUDE.md` 时，契约写
  “`./CLAUDE.md` or `./.claude/CLAUDE.md`”，未说明互斥还是并存。T003 按
  **两者并存**实现（fallback 条件把两者列为独立文件也支持此读法）。若终审
  认定互斥，`claude.py` 需改为每目录只取其一。
- **Q6**：pattern 路径不存在时是否应产生 `trust=MISSING` 的 source？
  T003 按“不产生”实现（见 §4.4）。S23（git 已删除文件）的 MISSING 需
  T004 从 git 状态补，T007 金样本应明确 S23 的 source 是否由发现层产生。
- **Q7**：Copilot `@` 引用的相对基准未在官方文档中说明（UNVERIFIED）。
  T003 对 Copilot **不**输出已解析的 import 候选（只在模块 docstring 记录），
  T005 须先从一手来源确定基准（文件相对 vs CWD 相对），或标记该边
  `NOT_OBSERVED`。
- **Q8**：custom-dirs 下 `*.instructions.md` 是否仍受 `applyTo` 门控，
  契约标 UNVERIFIED。T003 按与 repo-modular 相同的门控 fail-closed 处理
  （无 `applyTo` → 排除，记 `APPLYTO_ABSENT_UNVERIFIED`）。
- **Q9**：S10 去重的键：T003 用 canonical（词法）路径。同一文件经 symlink
  别名拼写被发现时（如 `linkdir/AGENTS.md` 与 `services/AGENTS.md`），
  两者 canonical 不同，会成为两个 source（resolved 相同）。若 S10 本意是
  按 resolved 路径去重，需 T007 明确；改动只在 `resolver.py` 一处。
- **Q10**：Claude managed 路径只实现了 Linux `/etc/claude-code/CLAUDE.md`；
  macOS `/Library/Application Support/ClaudeCode/CLAUDE.md` 与 Windows
  `C:\Program Files\ClaudeCode\CLAUDE.md` 在 Linux 上不可观测，未伪造。
- **Q11**：Codex 非 git CWD 的 repo root 认定为 UNVERIFIED；T003 的链在
  `repo_root=None` 时只含 CWD（不向上猜 repo）。
- **Q12**：project rules 与同目录 CLAUDE 文件的相对顺序：契约只说 rules
  “与 `.claude/CLAUDE.md` 同等 precedence”。T003 按每目录交错排列
  （`CLAUDE.md` → `.claude/CLAUDE.md` → `CLAUDE.local.md` → 该目录 rules，
  目录间根→CWD）。若终审要求 rules 整体置于链后，只需改 `claude.py` 一处。
- **SPEC-04（S16）方案（供 T007 定夺）**：T003 不发明枚举值。
  不匹配的 path-specific 文件不出现在 `sources` 中，同时进入
  `DiscoveryReport.considered_but_not_applicable`（`NotApplicable{
  raw_path, canonical_path, discovery_rule, reason, detail }`，
  reason 如 `APPLYTO_NO_MATCH` / `PATH_SCOPED_NO_MATCH` /
  `APPLYTO_ABSENT_UNVERIFIED`）。建议 T007 在 receipt 中增加同名顶层字段
  `considered_but_not_applicable`（与 `sources` 平行，不进 hash 的字段
  由 T005/T006 定）；若不采纳，`discover()` 本身已满足“不出现即不适用”。
- **SPEC-01 已落实**：import max 4 跳，S13 = depth 4 PASS、S14 = depth 5 BLOCK，
  金样本 `claude-import-depth4/5` 已覆盖；T007 不得按 depth 5 编写金样本。

## 6. 工作手记（诚实记录）

- 生成器第一版 `build()` 用了 `shutil.rmtree(root)`，把
  `01_s0/fixtures/resolver/` 整个删掉，连同生成器自身与 README 一起删除
  （case 树已生成，无数据损失）。已重写：只删除含 `case.json` 的子目录
  与 `manifest.json`，并在文件头记下此事故；重跑后生成器与 README 均在，
  golden 仍 100%。
- 早期 golden 17/20，三处失败均已定位并修复，均非“调期望凑绿”：
  (a) `**/` glob 在 `fnmatch` 下不匹配零目录（`src/**/*.py` 漏配
  `src/app.py`）——`glob_matches` 增加 `**/` 去除变体；
  (b) 缺失 import 目标的 canonical 应为 null（按 receipt edge 口径），
  而非缺失文件的词法路径——`iter_import_candidates` 改为缺失时置 null；
  (c) 一处单元测试把 CWD 设成了 payments，导致 nested 源在 startup 链
  已被发现——测试本身用错 cwd，已修正为 cwd=repo（实现无改动）。
