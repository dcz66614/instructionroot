# P028-T002 任务结果 — 文件系统 snapshot + canonical path

- TASK_ID：P028-T002
- PROJECT_ID：P028 InstructionRoot Resolve
- 日期：2026-11-18
- 结论：**T002 PASS**（验收命令 69 passed、2 skipped、0 failed；门槛 ≥30 满足）
- 只做了 T002，未进入 T003 及以后；未修改任何禁改范围。

## 改动文件清单（全部新增，无修改）

| 文件 | 行数 | 内容 |
|---|---|---|
| `02_src/instructionroot/__init__.py` | 33 | 包入口：导出 `canonicalize` / `build_snapshot` 等，版本号 `0.1.0-t002` |
| `02_src/instructionroot/paths.py` | 500 | canonical path：lexical 与 resolved 双记录、逐组件 symlink 解析（hop 上限 40）、root containment、symlink escape 检测、Windows 拼写纯字符串归一化、`<HOME>` 显示脱敏 |
| `02_src/instructionroot/snapshot.py` | 420 | filesystem snapshot：`snapshot_entry` / `snapshot_tree` / `build_snapshot`、确定性 canonical JSON + SHA-256、无 wall-clock |
| `05_tests/unit/test_paths.py` | 658 | 71 个测试用例（69 通过、2 跳过，见下） |
| `01_s0/fixtures/fs/build_fs_fixtures.py` | 207 | fixture 生成器（幂等；重跑后 manifest 逐字节一致） |
| `01_s0/fixtures/fs/README.md` | — | fixture 布局与规则说明 |
| `01_s0/fixtures/fs/manifest.json` | — | 生成的 case 清单（12 个 case） |
| `01_s0/fixtures/fs/cases/**` | — | 12 个合成 case：34 个文件 + 9 个 symlink，全部合成占位内容 |
| `review/tasks/P028-T002/TASK_RESULT.md` | 本文件 | 任务结果、验收输出、契约问题 |

禁改范围核查：`00_contract/*`、`03_oracle/*`、`04_ui/*`、`02_src/instructionroot/profiles/*`、以及 `resolver.py` / `git.py` / `trust.py` / `imports.py` / `receipt.py`（后五者尚不存在）、`.venv/`、两份规格 MD 均未动（`git diff --stat` 对禁改路径为空）。`git status` 中 `M review/COORDINATOR_LOG.md` 是协调员在派工前已有的修改，不是本任务的改动，未碰它。

## 验收命令输出（2026-11-18，工作目录 `~/workspace/p028-instructionroot`）

```text
$ .venv/bin/python -m pytest 05_tests/unit/test_paths.py -q
.............................................ss........................  [100%]
69 passed, 2 skipped in 0.15s
```

同一命令连跑两次结果一致（0.32s / 0.13s 两次均为 69 passed、2 skipped）。Python 3.12.3（规格最低 3.12，推荐 3.14.x——本机 venv 提供 3.12.3，与 T001 相同）。

## 设计要点（按冻结契约，不改契约）

- **canonical vs resolved 的分工**（receipt_schema.json 的 source 字段）：`canonical_path` 是词法规范化路径（绝对化、`..`/`.` 归一化、分隔符归一化，**不解 symlink**）；`resolved_path` 是解 symlink 后的路径，无 symlink 时等于 `canonical_path`。两者永远双记录；`symlink_target` 为末组件 symlink 的原始 target，`symlink_chain` 记录解析顺序的全部 target（便于审阅 escape 是怎么发生的）。
- **symlink 解析**：逐组件解析，hop 上限 40（与内核 ELOOP 惯例一致）+ visited-set；loop 返回 `is_loop=True, error="SYMLINK_LOOP", resolved_path=None, valid=False`，实测 <5ms，不挂死。broken symlink 不是错误：`is_broken_symlink=True, exists=False`，resolved 仍指向（缺失的）target，绝不把缺失文件伪造成存在。
- **containment / escape 判定一律用 resolved 路径**：S07 形状（lexical 在 repo 内、resolved 在 repo 外）实测 `is_within_root(canonical)=True`、`is_within_root(resolved)=False`、`detect_escape(...)=escaped`。无 approved roots 或 resolved 为 None 时 fail-closed `escaped=True`。信任分类本身是 T004 的事，本任务只提供 containment/escape 原语。
- **`~` 与真实 home**：`~` 只按显式传入的 `home` 参数展开；无 `home` 报错、`~user` 报错；代码中无 `Path.home()` / `expanduser` 调用。所有测试/ fixture 均使用 `tmp_path` 下的合成 home 与合成 repo。
- **Unicode**：canonical 表示是归一化后绝对路径的精确 UTF-8 字符串，**不做 NFC/NFD 归一化**（见“契约问题”Q3）。
- **快照确定性**：entry 按 canonical_path 排序、JSON `sort_keys + 固定分隔符 + ensure_ascii=False`、无 timestamp/duration/username 等任何易变字段。同一输入两次运行 canonical JSON 逐字节一致、hash 一致；内容变则 hash 变、仅 mtime 变则 hash 不变（已测试）。
- **snapshot_tree**：`os.scandir` 按名字排序遍历；目录 symlink 默认不跟随；`follow_dir_symlinks=True` 时仍以 visited inode 集防循环；`max_depth` 超限记 `error="MAX_DEPTH"` 不再下钻；缺失的 tree root 返回单个 missing entry，不抛错。
- **依赖**：仅 Python 标准库（`pathlib`/`os`/`hashlib`/`json`/`ntpath`/`re`/`dataclasses`）；无网络、无 subprocess、无 shell。

## 覆盖的场景清单（69 通过）

- 绝对/相对路径、`..` 归一化（含跨出 CWD、`.` 与 `..` 混合）、重复分隔符、尾斜杠、根 `/`、幂等性（14 项）
- `~` 展开（显式 home）、无 home 报错、`~user` 拒绝、空路径/NUL/bytes 拒绝、相对路径无 cwd 拒绝
- lexical vs resolved 双记录、链式 symlink、symlink 到目录后继续解析、父组件 symlink、绝对 target symlink
- broken symlink、symlink loop（a↔b、自环）、超 40 跳链（均 fail-closed、不挂死，<5s 断言）
- missing 路径、缺失中间目录（记录、不伪造）
- Unicode 路径（✓、中文）往返、canonical JSON 含 UTF-8 不丢信息
- root containment（含字符串前缀反例 `/repo2` vs `/repo`、根 `/`）、`..` 逃逸、symlink escape（lexical 内 / resolved 外）、多 root（repo+home）下 user-scope 不逃逸、零 root 时 fail-closed、`<HOME>` 脱敏
- Windows 拼写纯字符串归一化（盘符 `C:\…`、`C:/…`、UNC `\\server\share`、盘符相对路径拒绝）+ committed `windows-paths.json` 的 4 个 case
- snapshot：单 entry（文件/missing/broken/escape/loop/Unicode）、workspace 字段、repo_root=None（S25 形状）、缺失 cwd/home 时 `SnapshotError`、路径去重、两次运行逐字节一致、无 wall-clock 字段、内容变 hash 变、仅 mtime 变 hash 不变、tree 遍历排序、缺失 root、目录 symlink 默认不跟随、目录 symlink 循环终止、`max_depth`、`hash_file` 与 hashlib 一致、committed `basic` fixture 快照确定性（6 entries）、fixture manifest 完备性、snapshot dataclass frozen

## NOT_RUN 项（明确跳过，未伪造）

| 测试 | 原因 |
|---|---|
| `test_windows_junction_resolution` | skip。真实 junction 解析需要 Windows 文件系统；本机 Linux 无法验证。属 T011（Windows runner）。 |
| `test_windows_drive_letter_resolution` | skip。同上：真实盘符路径解析需要 Windows 文件系统；属 T011。 |

Windows 相关只做了 Linux 上可验证的部分：纯字符串拼写归一化（`normalize_windows_path`，`ntpath`），以及 `cases/windows/windows-paths.json` 的 4 个纯字符串 case。junction 的**识别**（junction 本身）在 Linux 上同样无法真实验证，未写任何假装验证它的代码。

## 契约问题（记录，不改契约）

1. **Q1 — `canonical_path` 的定义：词法 vs 已解析。** PROJECT_BOOK.md §13.1 步骤“1. resolve absolute path；2. resolve symlink/junction”单看像要求 canonical_path 本身就解 symlink；但 receipt_schema.json 明确区分 `canonical_path`（“Canonical absolute path”）与 `resolved_path`（“Canonical path after symlink/junction resolution. Equals canonical_path when the file is not a symlink”），且 §13.1 第 5 步要求“记录 lexical path 与 resolved path 两者”。本任务按 receipt schema 执行：canonical = 词法、resolved = 解 symlink 后。若 parent 认为 canonical 应等于 resolved，则 receipt 的双字段定义需先修订，T003/T005 会受影响。
2. **Q2 — `snapshot_hash` 的 canonical JSON 与 receipt hash 的关系。** receipt_schema.json 规定 receipt 用 RFC 8785 JCS；本任务的 `FilesystemSnapshot.to_canonical_json()` 用的是 `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`（即“排序键 + 紧凑分隔符 + UTF-8 原文”）。两者在 ASCII 内容上一致，但 JCS 对非 ASCII、转义与数字序列化有更严格的规定。snapshot hash 目前只用于 T002 内部确定性断言；T005/T006 做 receipt canonicalization 时若复用此函数，需先确认 JCS 合规（尤其是 Unicode 转义口径），不要默认等同。
3. **Q3 — Unicode 归一化未做。** 契约与规格只要求“canonical UTF-8 表示”（S21：stable），未规定 NFC/NFD。本任务不做归一化：同一名字在 NFC 与 NFD 下是磁盘上的不同字节串，canonical 表示保留原样、不合并。macOS 上同一文件可能以 NFD 形式存在，跨平台比对 hash 时这会表现为“不同路径”——这是诚实记录磁盘事实的选择；若 parent 希望 NFC 归一化，需在契约中明确（会影响 Oracle parity 的定义）。
4. **Q4 — `snapshot_tree` 在经 symlink 目录可达同一 canonical 路径时可能出现重复 entry。** 例如 `linkdir -> services` 且 `follow_dir_symlinks=True` 时，`services/AGENTS.md` 会经两条路各出现一次（canonical 相同）。`build_snapshot` 按 canonical_path 去重，`snapshot_tree` 本身不去重（保持“所见即所得”的遍历语义）。若 T003/T007 要求 tree 输出本身无重复，需在任务包里明确去重口径。
5. **无其他契约模糊处。** T001 已冻结的 SPEC-01～SPEC-04（import 深度、untracked 默认、NOT_OBSERVED 优先级、NOT_APPLICABLE）均属 T003/T005/T007 范围，本任务未触及。

## 环境记录

- Python：`.venv/bin/python` 3.12.3；pytest 9.2.0。
- 仅标准库；无联网；无对外消息；未读真实用户 home / 真实 repo。
- Fixture 生成器幂等：重跑后 `manifest.json` 逐字节一致；case 树中 9 个 symlink 在磁盘上均为真实 symlink（`find -type l` 计数 9）。
