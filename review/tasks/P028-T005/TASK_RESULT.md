# P028-T005 任务结果 — Import Graph + Escape Detection + Deterministic Receipt

- **TASK_ID**: P028-T005
- **日期**: 2026-11-18
- **状态**: PASS（验收命令全部通过，见 §3）
- **工作目录**: `~/workspace/p028-instructionroot/`（git main，HEAD 9e1fdb5；未提交，提交由协调员做）

## 1. 做了什么

实现 Import Graph + Escape Detection + Deterministic Receipt。只用 Python
标准库，不联网，零真人，全部合成数据。

### 改动文件清单（新增 / 修改，全部是 T005 所有权范围）

| 文件 | 说明 |
|---|---|
| `02_src/instructionroot/imports.py`（新增） | Import graph：只解析契约明确声明的 import 语法；Claude `@path`（文件相对、递归、BFS、depth 计数、max 4 跳 SPEC-01）、Copilot `@`（仓库内相对允许、绝对/`~/` → BLOCK、GEMINI.md 与 `*.instructions.md` 不展开）、Codex 不解析；每条 edge 含 from/raw_reference/resolved_target/allowed/reason；escape 一律按 resolved 路径判定 |
| `02_src/instructionroot/receipt.py`（新增） | Receipt Builder：**专用 RFC 8785 JCS 规范化器**（从零实现，不复用 snapshot.py 的内部 canonical JSON，不用 `json.dumps(sort_keys=True)` 冒充）；`receipt_hash = SHA-256(canonical_json(receipt))`（排除 `receipt_hash` 本身）；排除 wall-clock/duration/username；verdict 推导（PASS/WARN/BLOCK，按 policy_schema；INPUT_ERROR/UNSUPPORTED_PROFILE/INTERNAL_ERROR 由调用方显式传入，不推导） |
| `05_tests/unit/test_imports.py`（新增，33 个测试） | Claude depth 0–5、cycle、去重、dotdot/绝对/symlink escape、missing、malformed（URL/目录/空 `@`/`~user`）、code span/引号、home import、Copilot 相对/绝对/`~/`/custom-dir/no-expand/无深度上限、Codex 不解析、edge 形态 |
| `05_tests/unit/test_receipt.py`（新增，37 个测试） | JCS 专项（键排序、Unicode 键、数字、嵌套、转义、非法值拒绝）、hash 确定性（两次一致、键序无关、内容敏感、100 次重跑）、receipt 形态与校验、verdict 推导全分支 |
| `01_s0/fixtures/imports/build_imports_fixtures.py`（新增） | 15 个 import 金样本生成器（确定性、可重跑） |
| `01_s0/fixtures/imports/README.md`（新增） | 金样本格式说明（edge 比较口径、synthetic trust 说明） |
| `01_s0/fixtures/imports/manifest.json` + 15 个 case（新增） | 每个 case 含 `case.json` + `<case-id>.expected.json` + 合成 home/repo/outside/extra（含 1 个 symlink case） |
| `scripts/run_golden.py`（修改，仅追加） | 扩展支持 `--stage imports`（edge_parity、escape_detection、verdict）；resolver 阶段代码未动，仍 20/20 100% |
| `review/tasks/P028-T005/TASK_RESULT.md` | 本文件 |

### 未动范围（核查）

- `00_contract/*` 未动；`03_oracle/*` 未动（目录下未跟踪文件是并行 T006 会话的，我未碰）；`04_ui/*` 未动；`02_src/instructionroot/paths.py`、`snapshot.py`、`profiles/*`、`resolver.py`、`git.py`、`trust.py` 未动；`.venv/` 未动。
- `review/COORDINATOR_LOG.md` 的 `M` 修改是我开工前就已存在的（协调员自己的 T002/T003/T004 条目，`git diff` 已核对），不是我改的。

## 2. 实现要点与裁决

### 2.1 imports.py：检查顺序（每一步都 fail-closed）

对一条引用，依次判定：

1. Copilot 语法级拦截：绝对路径（`/...`、`C:\...`）与 `~/...` → `IMPORT_ESCAPE`（不解析为可加载引用）；
2. 无法 canonicalise（如 `~user`）→ `UNRESOLVABLE`；
3. Claude depth > 4 → `DEPTH_EXCEEDED`（候选仍列出，不再展开，与 T003 一致）；
4. resolved 路径越过全部 approved roots → `IMPORT_ESCAPE`（**优先于 MISSING**：越界就是越界，与目标文件是否存在无关）；
5. 目标不存在或不是常规文件（含目录）→ `MISSING`（`resolved_target` 为 null，与 T003 一致）；
6. 否则允许，reason 按命中的 root 取 `WITHIN_REPO` / `WITHIN_HOME` / `WITHIN_CUSTOM_DIR`。

Approved roots：Claude = repo_root（若有）+ cwd + home + additional-dirs（与 T004
trust 的 repo + home 口径一致）；Copilot = repo_root（无 repo 时为 cwd）+
custom-dirs，**home 不是 Copilot 的 approved root**（契约 `home_allowed: false`）。
BFS：每个文件最多展开一次（最小 depth），import cycle 会终止；同一
`(from, syntax, target)` 只列一次；只读文本（UTF-8），不执行、不联网、不跟随
shell、不把 Markdown 链接当指令。URL 引用（如 `@https://…`）按字面相对路径处理，
结果为 MISSING，绝不 fetch。

Claude 只从 startup 的 CLAUDE/AGENTS 源展开（与 T003 的 `iter_import_candidates`
同一集合：managed/user/project/local/agents-fallback），`.claude/rules` 不展开；
Copilot 只展开 `copilot-instructions.md` / `AGENTS.md` / 顶层 `CLAUDE.md`，
`.claude/CLAUDE.md` 不展开（见 §5 CQ-6）。Copilot 无契约深度上限，故不设上限；
cycle 靠“展开一次”终止（金样本 7 跳链全 PASS）。

### 2.2 receipt.py：JCS 从零实现

- 键排序：UTF-16 码元序（`key.encode('utf-16-be', 'surrogatepass')`），非
  Python 码点序 —— 非 BMP 键（如 U+10000）排在 U+FFFF 之前，这正是
  `json.dumps(sort_keys=True)` 会错的地方。
- 数字：ECMAScript `Number::toString` 语义（最短往返十进制数字 + ECMAScript
  位放规则）：`1e16` → `10000000000000000`、`100.0` → `100`、`-0.0` → `0`、
  `1e-7` → `1e-7`、`1e21` → `1e+21`；安全范围外整数先按 JCS 输入即 double
  取整（`2**53+1` → `9007199254740992`）；NaN/Inf 拒绝（不冒充 `null`）。
- 字符串：仅转义 `"`、`\` 与 U+0000–U+001F（`\b \t \n \f \r` 短式，其余
  `\u00xx` 小写）；非 ASCII 原样输出；孤立 surrogate 转义为 `\udXXX`，
  合法 surrogate 对输出为单个 astral 字符（与 ECMAScript 一致）。
- 非 str 键、set、bytes 等一律 `TypeError`（fail-closed）；tuple 按数组处理。
- `receipt_hash = SHA-256(canonical_json(receipt minus receipt_hash))`；
  builder 不接受时间/耗时/用户名/文件内容输入，故 receipt 不可能泄漏它们；
  canonical path 存**未脱敏**原值（`<HOME>` 脱敏只做展示层，hash 永远用未脱敏值）。
- `build_receipt` 会校验：profile id/version 必须为冻结值（否则
  `UnsupportedProfileError`）；source/edge 未知字段、缺失必填字段、重复 id、
  非法枚举值、edge `to` 指向不存在的 source 一律 `ValueError`；缺失 id 时按
  列表顺序补 `src-NNNN` / `edge-NNNN`。
- `derive_verdict` 按 policy_schema 字面实现（见 §2.3）；`build_source_record`
  把 T003 `SourceCandidate` + T004 git/trust 转为 receipt source 记录
  （resolved 为 None 的源——symlink loop——拒绝建记录）。

### 2.3 verdict 推导的两个明确裁决（写在代码 docstring 中）

- **NOT_OBSERVED trust → BLOCK**（无 policy 字段可调）：T004 要求下游
  “fail-closed，永不静默 PASS”，故无条件 BLOCK。留给协调员 / T008 确认。
- **edge 的 BLOCK 条件按 policy 字面读**：任一 `allowed=false` 的 edge，
  只要 `block_import_escape` 或 `block_missing_reference` 任一为 true 即
  BLOCK（含 DEPTH_EXCEEDED）；两字段同为 false 时，单条 disallowed edge
  不 BLOCK。默认 policy 下两者皆 true，故 S08/S09/S14 均为 BLOCK。

## 3. 验收命令输出（全部通过）

### 单元测试（T005 两个文件）

```text
$ .venv/bin/python -m pytest 05_tests/unit/test_imports.py 05_tests/unit/test_receipt.py -q
......................................................................   [100%]
70 passed in 0.26s
```

### 全量单元测试（确认无回归）

```text
$ .venv/bin/python -m pytest 05_tests/unit -q
239 passed, 2 skipped in 1.25s
```

（基线 169 passed、2 skipped；新增 70 passed。）

### Golden — imports 阶段（两次运行结果一致）

```text
$ .venv/bin/python scripts/run_golden.py --stage imports -v
[PASS] claude-code-span (claude-code)
[PASS] claude-cycle (claude-code)
[PASS] claude-depth4 (claude-code)
[PASS] claude-depth5 (claude-code)
[PASS] claude-escape (claude-code)
[PASS] claude-home-import (claude-code)
[PASS] claude-malformed (claude-code)
[PASS] claude-missing (claude-code)
[PASS] claude-no-import (claude-code)
[PASS] claude-symlink-escape (claude-code)
[PASS] codex-no-import (codex)
[PASS] copilot-absolute (copilot-cli)
[PASS] copilot-custom-dir (copilot-cli)
[PASS] copilot-no-expand (copilot-cli)
[PASS] copilot-relative (copilot-cli)
cases=15 passed=15 failed=0
golden_edge_parity=100.0%
golden_escape_detection=100.0%
```

### Golden — resolver 阶段（确认未动）

```text
$ .venv/bin/python scripts/run_golden.py --stage resolver
cases=20 passed=20 failed=0
golden_source_order=100.0%
golden_source_set=100.0%
```

## 4. JCS 专项测试结果

| 专项 | 结果 |
|---|---|
| RFC 8785 例向量 `{"numbers":[333333333.33333329,1E30,4.50,2e-3,1e-27]}` → `{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}` | 通过（逐字相等） |
| 键排序：非 BMP 键 U+10000 排在 U+FFFF 之前；孤立 surrogate 键按码元排序 | 通过 |
| 数字：21 个值与 Node（V8 ECMAScript `String(number)`）逐值对照 | **21/21 一致**（含 `1e16`、`1e20`、`1e21`、`5e-324`、`2.5e-10`、`123456789.12345679`、`-0.0`） |
| 字符串：引号/反斜杠/控制字符/DEL 不转义/emoji 原样/孤立 surrogate `\ud800` 转义/合法对 `"\ud83d\ude00"` → 😀 | 通过 |
| 与 `json.dumps(sort_keys=True)` 的差异点（键序 + 数字格式） | 已立专项断言，确认两者在该用例上确实不同、JCS 侧正确 |
| 拒绝：NaN/±Inf、非 str 键、set、bytes | 全部按预期抛错 |
| receipt hash 确定性：同一输入两次一致；键插入顺序无关；内容一改 hash 即变；**100 次重跑同一 hash** | 通过 |
| T005 import graph vs T003 `iter_import_candidates`（resolver 的 depth4/depth5 金样本，reason 映射 OK↔WITHIN_REPO） | **一致，5/5 边 × 2 case** |

## 5. 契约问题（未改契约、未加新枚举值、未给 receipt 加顶层字段）

- **CQ-1（Copilot 相对引用基准未定）**：契约 `relative_to: UNVERIFIED`。
  T005 采用**文件相对**解析（与 Claude 同口径）作为工作假设；若父级以后用
  主来源定为 repo-root 相对，只需改 `imports.py` 这一处 + 金样本期望。
  Oracle（T006）必须用同一口径，否则 edge parity 会分叉。
- **CQ-2（receipt edge `from` 无法命名 depth≥2 的导入者）**：schema 要求
  `edge.from` 为“导入源的 source_id”，但 depth≥2 的导入者本身是 import
  目标、不是 receipt source，无 source_id 可写。T005 的处理：depth-1 的
  `from` 写 `src-NNNN`；depth≥2 的 `from` 写导入者的 canonical path
  （schema 对 `from` 无 pattern 约束；冻结的金样本格式
  `01_s0/fixtures/README.md` §3 本来就用 path 标识 edge 端点）。
  `to` 仍按 schema：目标是 source 时写其 id，否则 null。
  建议协调员裁决：或把 import 目标也纳入 receipt sources，或给 schema
  补显式形式；T007 之前不要改。
- **CQ-3（Claude import 的 approval 状态）**：契约称 import 到 working
  directories 之外的文件需逐项目 approval，状态 NOT_OBSERVED、不得猜测。
  T005 的 approved roots 取 repo + home（与 T004 trust 口径一致），故
  `~/…`（home 内）目标判 `WITHIN_HOME` 允许；若按“working directories
  严格解释”，home 内非 cwd 的目标也应是 NOT_OBSERVED。已在模块 docstring
  标明，留给协调员裁决；改动只影响 roots 定义，不影响结构。
- **CQ-4（T003 解析器缺口，`"@path"`）**：契约称“引号包裹的路径永不导入”，
  但 T003 的 `parse_imports` 只排除 `@"path"`（引号在 @ 之后），
  `"@path"`（引号在 @ 之前）仍会被解析。T005 为保 edge parity 原样复用
  该解析器，未擅自修；单测已把该行为钉为“当前行为 + 待裁决”
  （`test_claude_quote_before_at_is_parsed_by_shared_parser`）。
  修解析器属于 T003 / 协调员，不管修不修，T005 的边都跟解析器走。
- **CQ-5（用户级 copilot-instructions.md 的 @）**：契约 `supported_in` 列的是
  `.github/copilot-instructions.md`；用户级 `$HOME/.copilot/copilot-instructions.md`
  同名。T005 按文件名展开两处（已在 docstring 标明为解释性选择）。
- **CQ-6（`.claude/CLAUDE.md` 的 @）**：契约明确 UNVERIFIED。T005 fail-closed：
  不展开（`_copilot_expandable` 排除含 `/.claude/` 的路径）。
- **CQ-7（Copilot 的 code-span / 引号排除）**：契约只对 Claude 证明了这些排除；
  T005 对 Copilot 复用同一 T003 解析器（含这些排除），属工作假设，已标明。
- **CQ-8（SPEC-04）**：`considered_but_not_applicable` 保持在 DiscoveryReport
  内部，不进 receipt（按任务要求，留给 T007 定夺）；receipt 未新增任何顶层字段。
- **SPEC-01**：已按协调员裁决落实（max 4 跳；depth 4 PASS、depth 5 BLOCK；
  规格书 depth-5 文字是规格缺陷，不采纳）。

## 6. 其他说明

- imports 金样本的 verdict 用 **synthetic trust** 推导（in-repo 文件视为
  GIT_TRACKED、home 文件视为 USER_SCOPE，经真实 T004 `classify_trust` 计算；
  真实 Git 状态是 T004/T007 的事）。该口径只用于 pin“edge → BLOCK”的链接，
  不替代 T007 的全量 verdict 金样本。
- 检查顺序中“escape 优先于 MISSING”是 T005 的明确选择（写在模块 docstring）：
  一条越界引用无论目标是否存在都是 escape；与 T003 的候选 reason
  （先 depth、后存在性）无冲突，depth 仍优先于 escape。
- 安全静态检查：新模块与改动的 runner / 生成器中 `shell=True` /
  `os.system` / `urllib` / `requests` / `socket` 匹配数为 0；无网络调用，
  无 `subprocess` 调用。
- 遗留说明：`imports.py` 中 `ImportGraph.blocked_edges` / `escape_edges`
  为派生属性；`receipt.py` 的 `DEFAULT_POLICY` 从 `resolver` 导入（与
  `policy_schema.json` 默认值逐字一致，单测同时对契约 JSON 与 resolver
  做等值断言，契约一变即 loud fail）。

## 7. 验收结论

- pytest：`05_tests/unit/test_imports.py 05_tests/unit/test_receipt.py` **70 passed**；全量 **239 passed、2 skipped**。
- golden `--stage imports`：**cases=15 passed=15，edge_parity=100.0%，escape_detection=100.0%**。
- DONE_WHEN 逐项：Claude depth 0–4 PASS、depth 5 BLOCK ✓；Copilot 绝对/`~/` BLOCK ✓；JCS 专项（含非 BMP 键、Node 21/21 对照）✓；同一输入 receipt hash 两次一致（及 100 次重跑）✓；malformed import（URL、目录、空 `@`、`~user`、缺失）不产生 PASS（均为 BLOCK / 无边）✓。
