# P028-T004 任务结果 — Git Provenance + Trust Classifier

- TASK_ID: P028-T004
- PROJECT_ID: P028 InstructionRoot Resolve
- 状态：**完成（PASS）**，未提交（留待协调员亲自核对后提交，与 T002 惯例一致）
- 工作目录：`~/workspace/p028-instructionroot/`（git main，基线 HEAD f9e9f8e）
- 环境：Python 3.12.3，`.venv/bin/python`，pytest 9.2.0，git 2.43.0

## 改动文件清单（仅 5 个新文件，零修改）

| 文件 | 行数 | 内容 |
|---|---|---|
| `02_src/instructionroot/git.py` | 280 | 只读 Git：allowlist 守卫的 4 条命令，`GitState` / `find_repo_root` / `is_git_repo` / `get_git_state` |
| `02_src/instructionroot/provenance.py` | 219 | provenance 组装：`Provenance` / `build_provenance` / `provenance_for_entry`（git + sha256 + 词法/解 symlink 双记录） |
| `02_src/instructionroot/trust.py` | 403 | trust 分类器：`classify_trust` / `TrustResult` / `trust_priority_index`，reason code R001–R010 |
| `05_tests/unit/test_git.py` | 380 | 24 个测试：只读 Git + provenance |
| `05_tests/unit/test_trust.py` | 458 | 35 个测试：trust 分类、优先级、R001–R010 全覆盖、端到端 |

未动（`git diff --name-only` 验证为空）：`00_contract/*`、`03_oracle/*`、`04_ui/*`、`02_src/instructionroot/paths.py`、`snapshot.py`、`__init__.py`。`02_src/instructionroot/profiles/` 是 T003 并行会话的文件，本任务未碰。

## 验收命令输出

```
$ .venv/bin/python -m pytest 05_tests/unit/test_git.py 05_tests/unit/test_trust.py -q
59 passed in 0.70s
```

全量回归（确认未破坏 T002）：

```
$ .venv/bin/python -m pytest 05_tests/ -q
128 passed, 2 skipped in 0.89s
```

2 个 skipped 是 T002 已有的 Windows NOT_RUN 跳过，与本任务无关。

门槛对照：

- tracked / untracked / modified：100%（`test_tracked_unmodified_file`、`test_modified_working_tree_file`、`test_staged_modification_counts_as_modified`、`test_untracked_file`、`test_deleted_tracked_file`、`test_staged_but_uncommitted_file_is_tracked_without_head` 及端到端 `test_end_to_end_with_real_git_repo` 全过）
- outside repo：100%（`test_outside_repo_file`、`test_prefix_trap_is_not_within_repo`、非 git 工作区两例）
- escape：100%（symlink 逃逸派生/显式覆盖/断链两例、import 逃逸两例、优先级组合四例）
- git mutation calls：**0**（见下）

## Mutation / 网络调用 grep 证据

```
$ grep -nE 'fetch|pull|push|checkout|reset|clean|shell=True|os\.system' \
    02_src/instructionroot/git.py 02_src/instructionroot/provenance.py 02_src/instructionroot/trust.py
（无输出）
exit=1   # grep 无匹配即 0 次调用
```

`subprocess` 在三个源文件中仅出现于 `git.py`：

```
02_src/instructionroot/git.py:56:import subprocess
02_src/instructionroot/git.py:140:        return subprocess.run(
```

`subprocess.run(..., shell=False, ...)` 是唯一的进程调用点，且 `_run_git` 内部有 allowlist 守卫：除 `rev-parse --show-toplevel`、`ls-files --error-unmatch -- <path>`、`status --porcelain=v1 -- <path>`、`log -1 --format=%H -- <path>` 四种形式外一律抛 `ValueError`（`test_allowlist_refuses_non_allowlisted_invocations` 覆盖 8 种拒绝情形）。另有静态测试 `test_no_mutation_or_network_calls_in_t004_sources` 把上述 grep 断言进测试套件。

## Reason code 覆盖情况（R001–R010 全覆盖）

`test_all_reason_codes_reachable` 用一个具体输入产生每一个 code；映射如下：

| code | 含义 | trust |
|---|---|---|
| R001 | WITHIN_REPO_TRACKED | GIT_TRACKED |
| R002 | WITHIN_REPO_MODIFIED | GIT_MODIFIED |
| R003 | WITHIN_REPO_UNTRACKED | GIT_UNTRACKED |
| R004 | USER_SCOPE | USER_SCOPE |
| R005 | OUTSIDE_REPO | OUTSIDE_REPO |
| R006 | SYMLINK_ESCAPE | SYMLINK_ESCAPE |
| R007 | IMPORT_ESCAPE | IMPORT_ESCAPE |
| R008 | MISSING | MISSING |
| R009 | NOT_OBSERVED | NOT_OBSERVED |
| R010 | UNSPECIFIED_PRECEDENCE | 保持 provenance 派生的 trust（GIT_TRACKED 或 USER_SCOPE），仅 reason 改为 R010 |

优先级按 PROJECT_BOOK §13.4 实现，先匹配者胜：IMPORT_ESCAPE > SYMLINK_ESCAPE > MISSING > OUTSIDE_REPO > GIT_UNTRACKED > GIT_MODIFIED > GIT_TRACKED > USER_SCOPE；NOT_OBSERVED 无优先级位置（SPEC-03，`trust_priority_index("NOT_OBSERVED") is None`）。

## 实现要点（供 T005/T006/T008 复用）

- `git.py`：非 git 目录返回 `GitState(is_git_repo=False, repo=None, ...)`，不抛错（S25）；`modified` 仅对 tracked 文件以 `git status --porcelain` 非空为准，untracked 文件的 `??` 不算 modified；`head_commit` 是 `git log -1` 返回的最近触及该路径的提交 SHA（按契约指定的命令），无提交/未跟踪时为 `None`；`git` 二进制缺失或超时记入 `GitState.error`（`GIT_NOT_AVAILABLE` / `GIT_TIMEOUT`），不抛错。路径一律以相对 repo_root 的单个参数经 `--` 传入，Unicode/空格文件名原样透传（Q3）。
- `provenance.py`：hash 与 Git 状态一律取 **resolved** 路径（hash 词法路径会 hash 到链接本身）；缺失/目录/断链/unreadable 时 `sha256=None`；`provenance_for_entry` 复用 T002 snapshot entry 已算好的 hash，不重复读文件。
- `trust.py`：`classify_trust(resolved_path, *, repo_root, home, git_state, canonical_path, is_symlink, is_symlink_escape, is_import_escape, exists, precedence_kind, scope, policy)`。围堵一律按 resolved 路径判断；symlink 逃逸可由 canonical/resolved + roots 派生（canonical 在批准根内而 resolved 在全部批准根外），也可由 `is_symlink_escape` 显式覆盖；`policy` 只接受并校验为 dict，**绝不改变 trust 值**（SPEC-02：`block_repo_untracked` 只改 verdict WARN→BLOCK，trust 仍是 GIT_UNTRACKED，`test_policy_never_changes_trust` 锁定）；repo 在 home 之下时仍先按 Git 分类（GIT_* 优先级高于 USER_SCOPE）；`scope` 仅用于 managed（见契约问题 1），其余 scope 不覆盖 provenance。
- 两个执行中修正（均有测试锁定）：(1) `build_provenance` 入口用 `os.fspath` 把 `Path` 转 str，因 T002 `canonicalize` 只接受 str；(2) 已暂存未提交的新文件 `modified=True`，因 receipt schema 定义 modified 为“与 HEAD 不同”，不是“与 index 不同”。

## 契约问题（按 FAILURE_STOP：只记录，不改契约、不加新枚举值）

1. **Managed scope 无 trust 值（新增，建议编号 SPEC-05）。**冻结枚举无 MANAGED，但 policy 默认 `allow_managed_scope=true`，纯围堵判断会把 `/etc/claude-code/CLAUDE.md` 判为 OUTSIDE_REPO（默认 BLOCK），与允许 managed 的默认值矛盾。本任务取最小解读：`scope="managed"` 时判为 USER_SCOPE / R004（唯一“批准的非 repo 范围”trust 值），并在 `trust.py` 模块文档与测试 `test_managed_scope_maps_to_user_scope` 中明示。Verdict 层仍须另行应用 `allow_managed_scope`。请父级裁决是否接受此映射，或补一个 MANAGED 枚举值。
2. **R010 无对应的 trust 值。**契约只列出 R010 为 reason code，未定义它搭配哪个 trust。本任务取最小解读：R010 只是 reason 标注，trust 保持 provenance 派生值，且仅当基础 reason 为 R001/R004（无更具体事实）时才标注；R002/R003/R005–R008 更具体，不被 R010 覆盖。`REASON_TO_TRUST["R010"] is None`。
3. **R009 的两处触发未在契约中定义。**本任务定义为：(a) `resolved_path is None`（symlink loop / 不可解）；(b) 路径在 repo 内但未提供 `git_state`（无法观测 tracked/modified，不猜测）。NOT_OBSERVED 的 verdict 语义（fail-closed，不可静默 PASS）须由 T008 明确，本分类器只负责分类。
4. **`head_commit` 的语义。**契约写“Full HEAD commit SHA for the file (git log -1)”；本任务按指定命令实现，即最近触及该路径的提交，未必等于当前 HEAD。若终审要求严格 HEAD SHA，需另行裁决（命令本身由契约锁定，改命令即改契约）。
5. **`modified` 包含“已暂存的新文件”。**按 receipt schema“与 HEAD 不同”的字面定义，`git add` 后未提交的新文件 `modified=True`（`git status` 为 `A`）。若期望新文件算 GIT_UNTRACKED，需协调员裁决并同步 Oracle 口径；当前实现与测试均按字面定义。

## 已知限制

- Windows junction 解析不在本任务范围（T002 已在 Linux 上标记 NOT_RUN；本任务只做纯字符串围堵判断，不伪造 Windows 行为）。
- `is_import_escape` 是 T005 传入的边级事实，本分类器只执行优先级，不解析 import。
