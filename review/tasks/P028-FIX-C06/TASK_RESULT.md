# P028-FIX-C06 TASK_RESULT — precedence `detail` 对齐契约（C-06）

- **任务**: P028-FIX-C06，协调员裁决 C-06：契约已冻结，生产跟契约。
  生产 builder 与 Rust Oracle 的 3 处 precedence `detail` 常量改成与
  冻结契约 `00_contract/profile_contract.json` 完全一致；金样本
  expected receipt_hash 用生成器/脚本重算；全量 parity 重新验证 100%。
- **完成时间**: 2026-11-18（UTC）
- **工作目录**: `~/workspace/p028-instructionroot/`（git main；
  本任务开始时 HEAD 为 `e04742f`，未提交；提交由协调员做）
- **状态**: ✅ 完成。3 处 detail 在生产、Oracle、契约三方逐字一致；
  全部验收命令通过；无其他行为变化。

## 1. 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `02_src/instructionroot/profiles/claude.py` | `_P_PROJECT` 补最后一句；新增 `_P_PATH_SCOPED`（契约文本），`_collect_rules` 的 path-scoped 分支改用它；`_P_ON_DEMAND`（nested / agents-nested）不动 |
| `02_src/instructionroot/profiles/copilot.py` | 新增 `_P_COPILOT_USER`、`_P_COPILOT_REPO_WIDE`（契约各自文本），`discover()` 的 user / repo-wide 分支改用它们；其余 6 条 copilot 规则仍用通用 `_COMBINE` |
| `03_oracle/rust/src/profiles.rs` | `P_CLAUDE_PROJECT` 补最后一句；`P_CLAUDE_PATH_SCOPED` 改为 "other sources"；新增 `P_COPILOT_USER` / `P_COPILOT_REPO_WIDE` 并在 `discover_copilot` 的 user / repo-wide 分支使用；模块头注释更新为“detail 逐字取自契约（FIX-C06 对齐）”；另见 §5 的 C-08 注释修正 |
| `01_s0/fixtures/imports/build_imports_fixtures.py` | 新增 `copilot-tilde-user` case 定义（§4） |
| `01_s0/fixtures/imports/manifest.json` | 生成器重算：仅新增 `copilot-tilde-user` 一条（其余 15 条不动） |
| `01_s0/fixtures/imports/copilot-tilde-user/`（新增） | 生成器生成：`case.json`、`copilot-tilde-user.expected.json`、`repo/.github/copilot-instructions.md`（内容 `@~user/evil.md`）、空 `home/` |

未改动：`00_contract/*`（`git diff --stat HEAD -- 00_contract/` 为空，
冻结契约一字不动，包括 rules_hash）；`01_s0/fixtures/*/`
下既有 expected 文件的 sources/edges/verdict 期望内容（生成器重跑前后
`git status` 无变化，见 §6）；`.venv/`；`04_ui/*`。
`review/COORDINATOR_LOG.md` 的 modified 状态是本任务开始前就已有的
（T006 报告亦注明），本任务未碰它。

## 2. 改前改后字符串对照（三方逐字一致）

契约原文取自 `00_contract/profile_contract.json`（按 rule_id）；
生产取自 `02_src/instructionroot/profiles/{claude,copilot}.py`；
Oracle 取自 `03_oracle/rust/src/profiles.rs`。
三方对照用脚本程序化核对：生产侧 import 模块直接读常量并与契约
JSON 逐字比较（8 条规则全 OK，含未变的 nested/agents-nested 与
通用 copilot 规则）；Oracle 侧 grep 核对 4 处新串 + 2 处未变串。

### 2.1 `claude-code.project` —— 补一句

- **契约**: `Concatenated from the filesystem root downward to the CWD (ancestors first, CWD last); files are concatenated, not overriding each other. Override semantics between files: UNSPECIFIED.`
- **生产改前**: `Concatenated from the filesystem root downward to the CWD (ancestors first, CWD last); files are concatenated, not overriding each other.`
- **生产改后 / Oracle 改后**: 与契约完全一致（补 ` Override semantics between files: UNSPECIFIED.`）。

### 2.2 `claude-code.rules-path-scoped` —— 换措辞

- **契约**: `Trigger is defined; ordering relative to other sources is not defined in the fetched source.`
- **生产改前 / Oracle 改前**: `Trigger is defined; ordering relative to the startup chain is not defined in the fetched source.`
- **生产改后 / Oracle 改后**: 与契约完全一致（`other sources`）。
- 注意：`claude-code.nested` 与 `claude-code.agents-nested` 的契约文本
  本来就是 "ordering relative to the startup chain"，生产 `_P_ON_DEMAND`
  与 Oracle `P_CLAUDE_ON_DEMAND` 保持原样——本次只拆分了 path-scoped
  这一支（生产新增 `_P_PATH_SCOPED`；Oracle 的 `P_CLAUDE_PATH_SCOPED`
  本就独立存在，只改其文本）。

### 2.3 `copilot-cli.user` / `copilot-cli.repo-wide` —— 各用契约自有文本

- **契约 `copilot-cli.user`**: `Combined with applicable repository instructions; no general precedence order between files.`
- **契约 `copilot-cli.repo-wide`**: `Combined with applicable user and repository instructions; no general precedence order between files.`
- **生产改前 / Oracle 改前**：两条规则都用通用 detail
  `Combined with applicable instructions; no general precedence order between files.`
- **生产改后 / Oracle 改后**：user 用 user 文本，repo-wide 用 repo-wide
  文本，与契约逐字一致。其余 6 条 copilot 规则（user-modular、
  repo-modular、agents、claude、gemini、custom-dirs）的契约文本本来就是
  通用句，仍用 `_COMBINE` / `P_COPILOT_COMBINE`，不动。

## 3. receipt_hash 重算清单

**重要说明（先讲清口径，避免误读）**：现有的 35 个金样本 expected
文件里**没有任何一个存储 `receipt_hash` 字段**（resolver expected
只断言 rule/scope/phase/precedence_kind/relative_path；imports
expected 只断言 edges + verdict，其 notes 明写 "No receipt_hash is
asserted here"；`01_s0/expected/` 为空目录）。所以不存在需要手改的
stored hash——本任务的“重算”是：用 `scripts/compare_oracle.py` 的
`build_production_receipt`（生产模块现场组装：discover + 真实 git
状态 + classify_trust + build_import_graph + build_receipt）在改前
与改后各跑一遍全部 35 个 case，逐 case 对比 `receipt_hash`。
改前基线已存 `/tmp/fix-c06-baseline-hashes.txt`，改后存
`/tmp/fix-c06-after-hashes.txt`。结果恰好符合 3 处改动的波及面，
无一处多、无一处少：

- **变化 25 个**（17 个含 `claude-code.project` 源 + 8 个含 copilot
  user/repo-wide 源；`claude-rules-paths` 同时含 project 与
  path-scoped，只计一次）；
- **不变 10 个**（5 个 codex resolver + `codex-no-import` imports +
  `claude-agents-fallback`（无 project 源）+ `copilot-absolute` /
  `copilot-custom-dir` / `copilot-no-expand`（无 user/repo-wide 源））；
- **新增 1 个**：`copilot-tilde-user`（§4），新 receipt_hash 见下。

### 3.1 变化的 25 个（old → new）

| case | old receipt_hash | new receipt_hash |
| --- | --- | --- |
| claude-agents-fallback-blocked | f13b53c1dff0258be171e2a0c30fa480178cbcc9e76c4f2710eec7a03825389f | b2961af4a183c29b9f9315c5cbd13f105401d7ec7ccf0b0608510c16e1091105 |
| claude-basic | 0811bb4a353f7609fd52da68b4ea6292190f21b2ceb1c31438b94a6a29df3e68 | be9ed708dccb18e2cf30a4008e01a459af56cc5e7f6820248a1c29dcda848763 |
| claude-code-span | 61f4edfec95dccb900f8ce14114b74dde00a9eec6251ac08199e1dcb01569dc3 | 2450f579150b859a98d17eb6c22c5f67ba332ff75ef4c65277d013b3e0569a92 |
| claude-cycle | 99bbeb829243dfc4edd8ce2b68c187dbae287b79211941ee95e73ce0d95014ba | 009afb3aa5e3b75178a1658c14c6ca6b74684b4ca1866b91239a02a56ed9b857 |
| claude-depth4 | 611ea14c5e992a5235163f79ad3f0da2fddeb6bf6c7a2e1c4d1afde007fa6c93 | 9fb40154b5fe984fff0265a554c028df771fb21afbf91faed0d3c64158a3f11f |
| claude-depth5 | 24572bde27dae2f6ccd8a8bd28145ea81446d957bca53763a87c2d066f68918e | 7acff1931cfcb3850c2e2dd06e4454e3695e191de6601e8f9b987ef39081ce4d |
| claude-escape | b0cc1c82c615811801e7f17a575a234da55dc69993a5bc4545014b9fb27ded69 | a3dd69ab39c59811df1f1a6d74e7fa770be54d7fe9406b0834969c668d1fec56 |
| claude-home-import | 8da7e52be47e42c34dff4e4053eb1d6fb48a7cecbe40dfbe91011886098d60a4 | eb21ddf7d0901c517668cf860f9798c8a6682a981409d62abe5f53b07f8d8922 |
| claude-import-depth4 | 469d12873d2ac23f3fc7674516db9dde03e16002eef2c0e846a29dc77aa60996 | 12e8a96bb96575a2265b7bb690a246300a98544c856c7895058750ea13f25a2f |
| claude-import-depth5 | 04950915380e1bb01bc553eddf58bd1ae7c5dc59a218c45d193b94e7539d7c5e | 432d5c319c31e250c51b3588718da26a2aa7900e18b22c1308f1884dce7c3b63 |
| claude-malformed | 7114793814bc3dc574d2512996df3c0e8a79cf50152045c825169cf704d8b0a1 | 7266eabce716a74af4ddefbc383d1a7ef59ef72d3c36ecaedce954726b694db9 |
| claude-missing | e8cb94af9457236b8c477176b7af3a94639be0749adea53568c44d32b09128e2 | 576faad7c2fde9ea96a05d8bffa5800ec6d9a2d185057bae3b39524f17f531be |
| claude-nested | 02b96f7704e7b58b26664d89c7a2fe013855ef92f468e4840cd9b16d2a91b222 | 83b57ec4e2479ebe0fd2b37ab1cf08d9efdb1ff0c8de0597d67e2ee7236bff69 |
| claude-nested-disabled | 95b2d068406f3005cfcc556bfd77b621d09ce19e4b50b7a4bb19f56b7bc6d361 | abfcc90065ef149ec1ef16b7c1c2023df52eb6a426f7c845e999a229f95037e1 |
| claude-no-import | c40e87da619f8fa3c4838b3faff7a682a8167c91baa8202b6f858aacf1f52b9d | f958f4362a11bb164977d24b5e05c5b9d7a1221e2da5670b1f89cf0a9e114f1d |
| claude-rules-paths | 9a4ef53e14ac366806c4c5db1a0245ec32e9d196669dca7a3d32f49d4f9680d1 | 276ec0a32179ccdd9955c7d148e5d3dd629aac117d129733e8976f80fdad |
| claude-symlink-escape | ea06f54914dcdaf2928bc24309b5bad5fc3accc52f85bb6a62a8f9d7f72c5f84 | e3936de7a2b4a055fbd44f63570fe21861b17d0990bc4ad6401aa9c03eb52f5d |
| copilot-applyto-absent | 2ff147ca825186bad434c30bd84f3c3f56a1249d81ae826deb942b3937b88d2b | 36a4665f8e54ef03bdc6a2ecd8a66cb588870b5942976780f7a992c26cc589a9 |
| copilot-applyto-match | 42de9e39ddbb86a1ac79ee9286b8c2ad6d580424f725832cfb74c1445bf1a441 | b10cbc0f002e614feb8463d29b1d7dc8b27e9081a68b4c295bc05c3aa3d6cc8f |
| copilot-applyto-nomatch | 688b4415f5508e5c471f8e436128ebe5d2ca118029f565978540ebe832f53f16 | 89e641888b3a01c0a2df459bbd5a28ee289346688d03b34d7a94a161b7aff821 |
| copilot-basic | 340d352a8109f69438fb22127462922fa9c1398780c5848f1b1b89f0ff18e356 | 7d1abfe8c1f7c7bc95f1d241fc5ef07a97d31ec94beddc3fa3650eecccacc0b5 |
| copilot-custom-dirs | 7939034e549b0e1b9cfd86ac65f8219ca39485d65edc3e1d5f8e19ab892fdd33 | 223e0abf0ff991cc0c821af990d7bbddd32f98223154e234bcc7d429ec02a0c2 |
| copilot-dedup | b9acda9ea62e529337bb3138e671b70e81d606e23e02674ccf7558e1bbdcd017 | 9b3607d8819066b08a1a5d50dbf1422ca926566aa98f965b61c244fd8f4d2eb4 |
| copilot-intermediate | 7be872fbfe12eb25cef691c40488bd2682635a477c0c0ed5aa109925ef84cef0 | 41c7f67e4a64ae7db9cb4dbe9c449dc0ed12a5be525d7d04777493147df46d65 |
| copilot-relative | 9c4336a70397aa75cfb6ceb37ea1bc26b948d16b0944d6414f41bc8b6349adf0 | bf6d0a9bdf8f2c7cf19568cb209f065ed97703cd4e8ec8eb9bb3385e638938c7 |

### 3.2 不变的 10 个

`claude-agents-fallback`、`codex-basic`、`codex-empty`、`codex-no-import`、
`codex-norepo`、`codex-override`、`codex-user-only`、`copilot-absolute`、
`copilot-custom-dir`、`copilot-no-expand`——其 receipt 均不含 3 处改动
的 detail，hash 与改前逐字相同。

### 3.3 新增 case 的 hash

`copilot-tilde-user` 新 receipt_hash：
`2bfcc4f9f0f8731f9acc57863b25b814cca533d9094877b6971234cfa035ed26`
（生产组装；compare_oracle 证实 Oracle 同值，hash parity 100%。）

## 4. 新增金样本 case：`copilot-tilde-user`

- **来源**: 协调员裁决 C-08 未复现——Copilot `@~user/evil.md` 在当前
  代码上得边 `allowed=False, reason=UNRESOLVABLE`，import 图与 receipt
  均 fail-closed、无崩溃。T006 报告称 T005 会抛 `UnboundLocalError`
  是误报（应为 T006 开工时读到了 T005 未完成的中间版 imports.py；
  当前 `imports.py` 的句法 BLOCK 分支只覆盖 `/`、`~`、`~/`、盘符，
  `~user` 不命中，走 canonicalize → `ValueError("~user expansion is unsupported")`
  → UNRESOLVABLE 分支）。
- **定义**（`01_s0/fixtures/imports/build_imports_fixtures.py`，生成器生成，
  非手写 expected）：harness `copilot-cli`，cwd/repo_root `repo`，
  home `home`；文件 `repo/.github/copilot-instructions.md` 内容为
  `@~user/evil.md`（repo-wide 规则，basename 可展开）；期望边 1 条：
  from `repo/.github/copilot-instructions.md`，syntax `@~user/evil.md`，
  depth 1，relative_target null，relative_resolved_target null，
  allowed false，reason `UNRESOLVABLE`；期望 verdict `BLOCK`。
- **验证**: `run_golden.py --stage imports --cases copilot-tilde-user -v`
  → `[PASS] copilot-tilde-user`；`compare_oracle.py --imports --cases copilot-tilde-user -v`
  → 5 项 parity 100%（单 case）。

## 5. 其他说明

- **Oracle C-08 注释修正**（`03_oracle/rust/src/profiles.rs`，
  `check_edge` 文档注释）：旧注释称“`@~user/...` 会使 T005 以
  `UnboundLocalError` 崩溃，Oracle 改为 fail-closed IMPORT_ESCAPE”——
  与协调员“未复现”裁决及实测行为（两边均为 UNRESOLVABLE）不符，
  已按实测改写。Oracle 的 `check_edge` 代码本身未动（其 step 2
  本就返回 UNRESOLVABLE）。
- **生成器幂等性**：改动前先各跑一次两生成器（resolver 20 / imports
  15），`git status` 无变化，确认重跑只产出新增 case；改动后重跑
  imports 生成器，diff 仅 manifest +1 条与新 case 目录，既有 15 个
  case 的 `case.json` / expected 文件零改动。
- **无其他行为分歧**：25 个 hash 变化全部落在含 3 处 detail 的
  receipt 上；sources/edges/verdict 的期望内容未动；golden 与
  parity 全绿（§6），未发现 detail 之外的分歧，故未触发 FAILURE_STOP。

## 6. 验收命令输出（改后）

基线（改前，HEAD e04742f）：pytest 239 passed、2 skipped；
golden resolver 20/20、imports 15/15；cargo test 31 passed；
compare_oracle --all 5 项 100%、fs 100%、git PASS。

### `.venv/bin/python -m pytest 05_tests/ -q`

```text
239 passed, 2 skipped in 1.21s
```

与基线一致（无新增单元测试；新 case 由 golden runner 覆盖）。

### `.venv/bin/python scripts/run_golden.py --stage resolver`

```text
cases=20 passed=20 failed=0
golden_source_order=100.0%
golden_source_set=100.0%
```

### `.venv/bin/python scripts/run_golden.py --stage imports`

```text
cases=16 passed=16 failed=0
golden_edge_parity=100.0%
golden_escape_detection=100.0%
```

（15 → 16：新增 `copilot-tilde-user` 通过；单 case `-v` 见 §4。）

### `cargo test --manifest-path 03_oracle/rust/Cargo.toml`

```text
test result: ok. 26 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

26 单元 + 5 集成 = 31 passed（与基线一致；6 条既有 dead-code
警告未变）。

### `.venv/bin/python scripts/compare_oracle.py --all`（退出码 0）

```text
resolver_cases=20 imports_cases=16 fs_cases=12 fs_probes=25
source_parity=100.0% trust_parity=100.0% edge_parity=100.0% verdict_parity=100.0% hash_parity=100.0%
fs_parity=100.0% git_scenarios=PASS
```

release Oracle 二进制由 compare 脚本以 `cargo build --release --locked`
重建（mtime 06:53:57，晚于改动的 profiles.rs 06:53:02），非 stale
二进制；`--imports --cases copilot-tilde-user` 单 case 亦为 100%。

## 7. git diff 摘要（提交由协调员做）

```text
01_s0/fixtures/imports/build_imports_fixtures.py | 20 +++++++++
01_s0/fixtures/imports/manifest.json             |  4 ++
02_src/instructionroot/profiles/claude.py        | 12 +++++-
02_src/instructionroot/profiles/copilot.py       | 18 +++++++-
03_oracle/rust/src/profiles.rs                   | 52 ++++++++++++------------
01_s0/fixtures/imports/copilot-tilde-user/       | (新增，未跟踪)
```

`review/COORDINATOR_LOG.md` 的 modified 状态为任务开始前已有，
本任务未改。`00_contract/` 无 diff。
