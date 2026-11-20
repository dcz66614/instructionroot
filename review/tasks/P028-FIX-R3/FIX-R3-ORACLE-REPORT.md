# P028 FIX-R3 — Oracle 报告（根因 C、D）

- 工作树：`~/workspace/p028-fixr3-oracle/`，分支 `fix-r3-oracle`（自 `d234994`）
- 提交：`bda88f6`（合并进 `fix-r3` 为 `0706d57`）
- 范围：V2 根因 C + 拼写统一 D 的 Oracle 侧；生产侧（A、B、D 的 Python 部分）
  由另一工人并行处理

## C. `git.rs` 的 `abspath()` 盘符感知（`03_oracle/rust/src/git.rs`）

- 旧逻辑：`if path.starts_with('/') { … } else { format!("{cwd}/{path}") }`——
  `C:/…` 被当相对路径前缀 cwd → `relative_to_repo()` = None → `git.repo=null` /
  `tracked=false` → 全部 `GIT_UNTRACKED` → `WARN`。
- 修法：新增 `normalise_spelling()`（Windows 盘符/UNC 拼写 → 归一化 `C:/…` 或
  `//server/share/…`，其余走 `normpath_posix`；纯字符串，与宿主无关）。
  `abspath()` 先判 `is_windows_style_path`（`C:/…` 与 `C:\…` 都算绝对，不再前缀 cwd）；
  `..` 在盘符根截断；裸盘符相对 `C:foo` 仍走 cwd（与之前一致）；相对拼接先把
  反斜杠 cwd 归一化成 `C:/…`，再去掉结果中的反斜杠。
- 刻意不用 `Path::is_absolute()`：在 Linux 上它仍判定 `C:/…` 为相对路径，
  而单元测试在 Linux 上跑。
- 同一规则同步修了 `find_repo_root()`（git 的 top-level 输出保持 `C:/…`，
  否则 `relative_to_repo` 按 `/` 切分永远匹配不上）、`relative_to_repo()` 与
  `get_git_state()` 的 repo 拼写（收据 `git.repo` 不再带反斜杠）；
  `nearest_existing_dir()` 加了裸盘符根 `C:` → `C:/` 守卫。
- spawn 逻辑（allowlist、4 条 git 命令）未动。

## D. 收据拼写统一（Oracle 侧，`03_oracle/rust/src/receipt.rs`，+87 行）

- 先读契约：`receipt_schema.json` + 生产侧 `paths.py` 都要求 `raw_path` 在发现层
  保持“caller verbatim”（"Path as discovered"，可含 `~` 或为相对路径），所以发现层
  不改；只在收据组装层新增 `receipt_raw_path()`：Windows 风格拼写 → 归一化 `C:/…`，
  其余（`~/…`、相对、POSIX）逐字保留；`sources[].raw_path` 组装时调用它。
- 审计：`workspace.cwd/home/repo_root` 在 Windows 上本来就是 `C:/…`（来自
  `canonicalize` 的 canonical/resolved 路径），未重写（重写只会掩盖 `canonicalize`
  的 bug）；Oracle 内部拼接的 `raw_path`（chain/ancestor/list_dir）本来就是 `C:/…`；
  唯一逐字泄露的是调用方传入的 `managed_path`——收据层归一化已覆盖。
- `canonicalize` 子命令 + explain sidecar 的 `raw_path` 保持逐字（不在收据 hash 内，
  在本次冻结契约之外）。

## `starts_with('/')` 全量审计（grep，逐项）

- `git.rs:145`：已修（本项 C）。
- `paths.rs:79` `normpath_posix` 内部函数：未改。
- `paths.rs:158` `is_absolute_on_host`：未改（有盘符分支，刻意宿主门控；Linux 上
  盘符 cwd/home 仍拒绝，由 fixture `drive_cwd_home_absolute_only_on_windows_host` 锁定）。
- `paths.rs:375` `target.is_absolute()`：未改（Linux 上对 `/C:/…` 的 bug 兼容，刻意保留；
  Windows 走另一分支）。
- `paths.rs:609`、`paths.rs:789`、`paths.rs:946`：不是输入路径的绝对判定。
- `profiles.rs:1123` `copilot_syntactic_block`：已有盘符感知（`ref[1] == ':'`）。

## 测试

- `cargo test --locked`：**43 passed，0 failed**——单元 38（基线 35，+3 个新测试：
  `abspath_recognises_drive_spellings`、`relpath_drive_spellings`、
  `receipt_raw_path_spelling`）+ CLI 集成 5。
- Windows corpus `scripts/run_windows_corpus.py`：**15/15 全 parity**（source/trust/
  edge/verdict/hash 各 15/15，probes 10/10，determinism PASS，RESULT=PASS），与修前
  基线相同——Linux 行为未变。
- `cargo fmt` / `clippy` 未安装（toolchain 1.100.0 不带），未另行安装；代码按仓库
  风格手写。

## 注意事项（诚实记录）

- `run_windows_corpus.py` 重写了 `review/tasks/P028-T011/windows_corpus_summary.json`，
  15 个收据 hash 全变：对干净树（stash）重跑得到**完全相同的 15 个新 hash**（如
  `bfccf714…`）——原因是 runner 的 `tempfile.mkdtemp` 随机临时目录进入收据 hash，
  与本次改动无关；有意义的信号是两次均为 15/15 parity + RESULT=PASS。文件已还原，未提交。
- 仍未验证：真实 Windows 端到端（只有 Sam 的 PC 上跑 V3 包才能证明）；
  `nearest_existing_dir` 的真实 `git rev-parse` 路径在 Linux 上无法接受盘符输入。
