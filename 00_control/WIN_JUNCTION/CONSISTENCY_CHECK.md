# WIN-JUNCTION 包一致性核对记录

核对分两部分：§1–§2 是**包准备人**（本 VM，2026-11-18）在写包时亲自核实的内容；§3 是**执行 agent**在 PC 上填完证据后逐项打勾的自查清单。

## §1 包准备人的核实记录（本 VM，2026-11-18，只读核实 + 一次 Linux runner 复跑）

核对方式：只读源码、终审文件与 T011 任务记录；唯一一次“运行”是 Linux 下的 `run_windows_corpus.py` 复跑（为理解 runner 输出格式，**不作为 Windows 证据**）。未改任何已跟踪文件；未碰 Drive、未做 GitHub 上传、未改 `~/workspace/P028_FINAL_REVIEW_R1.md`。

| 核对项 | 期望值 / 来源 | 实测值 | 结果 |
|---|---|---|---|
| 终审 R1 P1-02 门槛 | 真实 Windows 10/11 NTFS 上 4 类测试；五项 parity 全一致；不用 Linux symlink 代替（`P028_FINAL_REVIEW_R1.md` §五 P1-02） | 全文已读；门槛逐字抄入任务书 §1–§2 | ✓ |
| Sam PC 实测环境（FIX-R2，2026-11-19 18:18–18:24 GMT，RESULT=FAIL） | 以实测为准，见 `~/workspace/user/files/P028_WIN_JUNCTION_RESULT.md` | Windows 11 Home 10.0.26200（NTFS）；PATH 首个 python 3.11.15，实测用原生 3.14.4；rustup 1.100.0 已装（Sam 批准，--no-modify-path）；`link.exe` / `cl.exe` 存在（MSVC 14.44.35207）；PS 5.1.26100.9818 + pwsh 7.7.0；git 2.55.0.windows.2；4 类 case 全部失败——与 junction 无关，是两侧实现都把盘符路径重建成 `/C:/…`（见任务书 §1 注与规格 §13.1 新增平台分支） | ✓（失败本身是产品发现，见 EVIDENCE_INDEX 已填版） |
| S12 NOT_RUN 标注 | S0 报告原文标注真实 junction NOT_RUN | `review/S0_GATE.md`：“real junction resolution is NOT_RUN on Linux (T011, Windows runner). Not faked as a pass.” | ✓ |
| 冻结身份 | freeze `0110fa8`、release `12b8d61`、HEAD `9d4fd93`（FIX-R1 重冻结；R1 值 freeze `30700bd`、release `16b958f`、HEAD `6fa67b7` 已 superseded，见 WIN_JUNCTION_TASK.md §0） | `git log` 与 FIX-R1 终报一致；`source.zip` SHA `fdcd98af…20acf8`（866,129 B）、`dist.zip` SHA `a780fba5…cd204f`（570,918 B），`sha256sum` 实测与 `07_release/SHA256SUMS.txt` 一致 | ✓ |
| dist.zip 内 Oracle 是 Linux ELF | 不能在 Windows 跑 | `file` 实测：`ELF 64-bit LSB pie executable, x86-64, for GNU/Linux`；SHA `60247a20…bf6b` 与终审 R1 §2 一致 | ✓ |
| 本 VM 交叉编译 Windows Oracle | 试过，结论见下 | cargo 1.100.0 在 `~/.cargo/bin`（默认 PATH 里没有，需 `export PATH="$HOME/.cargo/bin:$PATH"`）；已装 target 只有 `x86_64-unknown-linux-gnu`；无 `x86_64-pc-windows-gnu` target；无 MinGW 链接器（`which x86_64-w64-mingw32-gcc` 无结果，只有系统 `gcc`/`cc`）。**本 VM 无法交叉编译。** 未执行 `rustup target add`（任务要求：不擅自装大型工具链），结论写进任务书 OQ-1 | ✓（结论为“不可行”，已记录） |
| Linux runner 复跑 | 理解输出格式 | `python3 scripts/run_windows_corpus.py` exit 0：`receipt_cases=15 passed=15`，五项 parity 15/15，probes 10/10，`determinism=PASS distinct_hashes=1`，`RESULT=PASS`；其中 4 个 junction 模拟 case 全 PASS | ✓（仅作对照基线） |
| Python 版本要求 | `requires-python = ">=3.12"`（`pyproject.toml`），标准库 only，无第三方依赖 | 已读 `pyproject.toml`；本 VM `python3 --version` 为 3.12.3 | ✓ |
| Oracle 构建方式 | `cargo build --release --locked --manifest-path 03_oracle/rust/Cargo.toml`；工具链锁定 `rust-toolchain.toml` channel `1.100.0` | 已读 `03_oracle/rust/README.md`、`Cargo.toml`（依赖仅 serde_json + sha2）、`rust-toolchain.toml`；Linux runner 的 `build_oracle()` 用的就是这条命令 | ✓ |
| Oracle CLI | `resolve <case.json> [--explain <file>]`，exit = verdict 码；`canonicalize <input.json>`；`--version` | 已读 `03_oracle/rust/README.md` 与 `scripts/compare_oracle.py` 的 `run_oracle_resolve` / `run_oracle_canonicalize` | ✓ |
| Runner 核对逻辑 | 全 receipt 逐字段比较 + hash 比较 + 独立 JCS 重算 + INDEX 核对（sources/trust/edges/verdict/not-applicable）+ 确定性抽查 | 已读 `scripts/run_windows_corpus.py` 全文（`check_receipt_case`、`check_probes`、main）；FIX-F6 后 runner 不再读 INDEX 里的 `known_parity_gap`，任何 receipt diff 即失败 | ✓ |
| INDEX.json 4 类期望 | 见任务书 §2 的表 | 逐项读过 `fixtures/windows/expected/INDEX.json` 里 4 个 junction case 的 `expected_sources` / `expected_edges` / `expected_verdict` / `forbidden_trust`，与任务书 §2 一致 | ✓ |
| F6 已关闭 | FIX-F6 后 hash parity 15/15 | `review/tasks/P028-T011/TASK_RESULT.md` 的 FIX-F6 节 + 本次 Linux 复跑 `hash_parity=15/15` | ✓ |
| 4 类 case 的文件内容与提交信息 | 与 Linux 构建脚本逐项对应 | 逐项读过 `fixtures/windows/build_windows_fixtures.py` 的 `case_junction_inside` / `case_junction_escape` / `case_junction_import_inside` / `case_junction_import_escape`（文件内容、相对 symlink 目标、提交信息、固定 git 日期 `2026-11-18T07:00:00+00:00`、作者 `P028 Windows Fixture <win@p028.invalid>`）；PS 构建脚本照抄这些值，只把 symlink 换成绝对目标 junction | ✓ |
| 生产代码只调 4 条 git 命令 | `git.py` allowlist | `02_src/instructionroot/git.py`：仅 `rev-parse --show-toplevel`、`ls-files --error-unmatch`、`status --porcelain=v1`、`log -1 --format=%H`；git 缺失时记为未观测到（trust 会变）——所以 git 是前置门，不是可选项 | ✓ |
| receipt 无分支字段 | git 默认分支名不影响判定 | `grep branch 02_src/instructionroot/receipt.py 02_src/instructionroot/git.py` 无结果 | ✓ |
| `case.json` 的 `"os"` 字段 | runner 不读 | `scripts/compare_oracle.py` 的 `resolve_case_paths` 只用 `case_id/harness/profile_version/cwd/home/repo_root/policy/env/working_files` | ✓ |
| mklink /J 权限 | 公开资料说法不一 | **2026-11-19 实测：本机 `mklink /J` 不需要提权**，普通提示符即可建 junction，探测 4/4 通过（建链、读穿、`LinkType=Junction`、`fsutil` 含 `0xa0000003`）；任务书 OQ-7 已按实测更新 | ✓（已实测） |
| Rust/Python 是否把 junction 判为链接 | 未核实 | **2026-11-19 已分别实测（未经过 runner）**：Python 3.14.4 `os.path.islink(junction)` = **False**、不跟随；Rust 1.100.0（与 Oracle 同一 API）`file_type().is_symlink()` = **True**、会跟随；即使盘符路径修好，两边在 junction 上仍大概率 parity 失败（推断，未经 runner 验证）。任务书 OQ-5 已按实测更新；本次运行仍以 runner 实测为准 | △（探针级实测，runner 未验证） |

**分支说明（准备期间发生的并行工作）：** 本包分支 `fix-r1-winpack` 创建于 `6fa67b7`；准备期间，并行的 P1-01 修复工作亦提交到同一分支（`abbd4ff`“make S0 fixtures reproducible from a clean git archive”、`6d264f4`“S0 gate establishes its own git workspace on clean extraction”）。注意：因共享 git 索引，本包 6 个文件的初版随 `6d264f4` 一起被提交（该提交信息为 P1-01，内容为 P1-01 的 4 个文件 + 本包 6 个文件）；随后本包提交 `36206e3` 更新了其中 2 个文件（`WIN_JUNCTION_TASK.md`、`CONSISTENCY_CHECK.md` 的分支说明）。本包内容不依赖 P1-01 修复（§0 核对的仍是冻结 `source.zip` 的 SHA）。如需纯 `6fa67b7` 基底，可将 `6d264f4` 中 `00_control/WIN_JUNCTION/` 的内容连同后续更新一起 cherry-pick / checkout 过去。

## §2 包内引用与冻结源码的对应关系

| 包内引用 | 来源 | 核对 |
|---|---|---|
| 4 类测试的目录结构、文件内容、提交信息、固定 git 日期 | `fixtures/windows/build_windows_fixtures.py`（4 个 `case_junction_*` 函数）+ `fixtures/windows/expected/INDEX.json` | 内容逐字对应；唯一有意的差异：junction 目标用绝对路径（`mklink /J` 要求）、`case.json` 的 `"os"` 写 `"windows"`、`.git/info/exclude` 隔离 `linked/`、git 用 `-b main` + `core.autocrlf=false`——四处差异都在任务书 §2 末尾逐条说明了理由 |
| 期望 verdict / sources / edges / forbidden_trust | `fixtures/windows/expected/INDEX.json`（4 个 junction case） | 逐项抄入任务书 §2；冲突时以 INDEX.json 为准（任务书已注明） |
| 五项 parity 判定（source/trust/edge/verdict/hash） | 终审 R1 §五 P1-02 + `scripts/run_windows_corpus.py` 的 bucket 逻辑 | 一致；`run_win_junction.py` 直接复用 `check_receipt_case`，不另写判定逻辑 |
| Oracle 构建命令与工具链锁定 | `03_oracle/rust/README.md`、`rust-toolchain.toml`、`scripts/compare_oracle.py` 的 `build_oracle()` | 一致；唯一差异：Windows 产物带 `.exe` 后缀，`run_win_junction.py` 显式处理（`compare_oracle.py` 的 `ORACLE_BIN` 是无后缀的 Linux 路径，本包 runner 不用它） |
| 前置检查清单 | `pyproject.toml`（Python ≥ 3.12）、`02_src/instructionroot/git.py`（git 必需）、任务要求（python --version，无则停） | 一致；Node 与 Claude Code 只记录、不设门（P028 runner 不用它们，任务书 OQ-9 已说明） |
| T015 包结构仿照 | `~/workspace/p025-guidancepulse/00_control/T015/`（`T015_TASK.md`、`T015_AGENT_PROMPT.md`、`EVIDENCE_INDEX.md`、`CONSISTENCY_CHECK.md`） | 结构仿照；内容全部按 P028 重写，未复制 P025 的任何产品断言 |
| P025 教训的遵守情况 | “不要在包里写未经核实的先决条件，例如不要写‘需要安装 C++ 工作负载’”（任务要求；另见 `T015_NPM_INSTALL_PROMPT.md` 的更正：better-sqlite3 有预编译包，所谓“缺 MSVC 导致失败”是错的） | 本包**没有**把“装 C++ 工作负载”写成先决条件或行动步骤。Rust 链接器问题只写为 OQ-1：**2026-11-19 已核实——本机有 `link.exe` / `cl.exe`（MSVC 14.44.35207），“PC 的 VS Build Tools 无 C++ 组件”不成立；真正缺过的是 Rust 工具链（执行前全无），已于 2026-11-19 经 Sam 批准安装 rustup 1.100.0**。构建失败时仍停下存证、修复路径由 Sam / Muse 决定 |

## §3 执行 agent 的一致性自查清单（填完证据后逐项打勾）

- [ ] E00：操作系统、NTFS、PowerShell、Python（≥ 3.12）、git、cargo/rustc 的版本输出都已存证；缺失项（如无 Python）已按“停下并汇报”处理，没有绕过。
- [ ] E01：`source.zip` 的 SHA 与任务书 §0 逐字一致；本包 6 个文件齐全；未使用 `dist.zip` 里的 Linux Oracle 二进制。
- [ ] E02：junction 探测四项（建链、读穿、LinkType=Junction、`fsutil` 含 `0xa0000003`）全部通过并已存证；探测失败时已停下，没有改用 `/D`。
- [ ] E03：Oracle 是在 PC 上用 cargo 原生构建的（`instructionroot-oracle.exe`），`--version` 正常；构建日志完整；构建失败时已停下，没有自行装 C++ 工作负载/改 target/装 MinGW。
- [ ] E04：4 个 case 的目录树与任务书 §2 一致；每个 `linked` 都是 Junction（`fsutil` 证明）；每 case 提交后 `git status --porcelain` 为空；`git ls-files` 无 `linked/` 下的文件；`case.json` 的 `"os"` 为 `"windows"`。
- [ ] E05：runner 日志完整（`run_win_junction.log`）；汇总 JSON 在证据目录；每 case 的 Production/Oracle receipt 与 explain sidecar 齐全；runner exit code 已记录。
- [ ] E06：确定性抽查为 1 个 distinct hash（10 次 Production + 10 次 Oracle）。
- [ ] E07：判定汇总表已填；五项 parity 每项都是 x/4 的数字，不是“大概通过”。
- [ ] E08：任何与任务书不符的做法、未执行的步骤都已如实记录；没有“未执行”却填了结果的项。
- [ ] 任务书 §4 的判定表已填；`EVIDENCE_INDEX.md` 每项的“实际结果 / 文件”栏都不为空（未跑的写了“未执行”）。
- [ ] `C:\p028-src\fixtures\win-junction\` 与 `C:\p028-win-evidence\` 原样保留，未删除；没有把 fixtures 提交到任何 git 仓库。
- [ ] 总体结论（P1-02 是否关闭）**没有**由执行 agent 下；交付的是填好的证据索引 + 一页结果汇总。

## §4 已知残差（FIX-R3 更新，2026-11-19）

- **FIX-R2 冻结时发包副本的“已知残差”只预判了 `ancestor_chain` 一处，是错的。** V2 实测（2026-11-19 22:43–22:52 GMT，冻结 `d3847b9`，RESULT=FAIL，4/4 失败）证明同一缺陷模式（先 `normpath` 得反斜杠、再拿 `"/"` 做比较）还波及 `chain_dirs` / `is_within_root` / `relative_posix`，共四处；类 1“只找到 1 个 source”的主因是 `chain_dirs`，不是 `ancestor_chain`。
- **FIX-R3 已四处一次修完**：Production 侧统一先归一化成 `C:/` 再比较；相对 import 与 cwd 拼接的结果再归一化；Oracle `git.rs` 的 `abspath()` 改为盘符感知；两侧 receipt 的 `workspace.*` 与 `raw_path` 拼写统一成 `C:/`。
- **V2 的类 2 在 V2 已是语义全对、只差拼写**（两侧 BLOCK / OUTSIDE_REPO / 1 source，唯一差异是分隔符写法导致 `receipt_hash` 不等）；FIX-R3 修完拼写统一后，类 2 应直接通过。**V3 的判定标准不变：4 类全过 + 五项 parity 4/4 + 确定性 PASS，不要放宽。**
- 残留（未修，出 FIX-R3 范围）：`ancestor_chain` 带 Windows `stop` 时返回 `[cwd]`——与 Oracle 的同名函数逐字同算法，为保 parity 未改；`paths.py` 的 `redact_home()` 仍是 `normpath` + `"/"` 写法，只影响 CLI 显示文本，不进 receipt/hash，未修。

## §5 FIX-R4 更新（2026-11-19）

- **V3 的唯一剩余缺陷：`sources[].git.repo` 未归一化。** V3 实测（2026-11-19 23:34–23:42 GMT，冻结 `535879b`，RESULT=FAIL，passed=1/4）证明 4 类 verdict 全对、source/trust/edge 全对、类 2 完全通过、V2 的三处根因全部修好；唯一剩余差异是 `receipt.py:559` 的 `"repo": git.repo` 是 receipt 里唯一未包 `_normalize_receipt_path()` 的路径字段——Production 侧存反斜杠 `C:\…`，Oracle 侧存 `C:/…`，只差分隔符写法导致 `receipt_hash` 不等。类 2 恰恰通过，正因为它的 source 在仓库外、两侧 `git.repo` 都是 `None`。
- **FIX-R4 已修完，两条组装入口都已封闭**：`build_source_record` 里 `git.repo` 的 GitState 分支与 dict 分支都归一化；`_normalize_sources()` 里经 `build_receipt` 直通的 dict source 也补归一化（先拷贝 git dict 再改 `repo`，不 mutation 调用方 dict；`None` 仍为 `None`，缺 `repo` 仍报错）。字段层面审计结论：除 `git.repo` 外无第二处漏网；Oracle 侧无漏网；`git.py` 的 normpath 源头不改。
- **V3 行为面已全对，V4 的判定标准不变：4 类全过 + 五项 parity 4/4 + 确定性 PASS，不要放宽。**
- 残差照旧（未修，出 FIX-R4 范围）：`ancestor_chain` 带 Windows `stop` 时返回 `[cwd]`；`paths.py` 的 `redact_home()` 仍是 `normpath` + `"/"` 写法，只影响 CLI 显示文本，不进 receipt/hash。V3 已证明这两处残差未造成失败。

## §6 FIX-R5 更新（2026-11-20）

- **V4 全部通过，P1-02 已关闭。** V4 实测（2026-11-20 10:39–10:42 GMT，冻结 `b2f9ceb`，RESULT=PASS，runner exit 0）：4 类真实 NTFS junction 全部通过，五项 parity 各 4/4，Production 与 Oracle receipt 逐字节相同，确定性抽查 10+10 次 distinct_hashes=1。
- **V4 的新发现 E08-5（不在 P1-02 判定范围内，未用于任何 verdict）：生产 CLI（`python -m instructionroot verify/inspect`）产出的 receipt 与 runner 用的冻结库路径不同。** claude-code 两个 case 在 CLI 侧是 0 source / 0 edge / PASS，而库里是 1 source / 2 edges（类 4 为 BLOCK），`verify` 在类 4（import-escape）上 exit code 为 0 而期望 20。对照实验：一个完全不含 junction 的普通临时 git 仓库（repo/CLAUDE.md）上，CLI 同样给出 claude-code sources=0、codex sources=1——与 junction 无关，是 CLI / `build_receipt_for` 的一般行为，面向用户入口上的 fail-open。
- **根因（已在 Linux 上实证）：`ancestor_chain()` 发出的 `"/C:/…"` 形链在 Windows 主机上不可消费**——`canonicalize` 把 `"/C:/…"` 交给 Windows `ntpath.normpath`，被改写成 UNC 形 `"\C:\…"`，永不存在，于是 claude-code 的每个祖先探测都落空（CLI 传 `ancestor_stop=None`）；runner 的库路径只因 `stop=case_dir` 的过滤把链塌成 `[cwd]` 才偶然走对。codex 不受影响（它用 `chain_dirs`）。Oracle 侧有完全相同的缺陷（`profiles.rs:220` 同名函数），两侧在 `stop=None` 下一致地错、在 `stop=case_dir` 下一致地对。
- **FIX-R5 一次修完（两侧一起改，永不同侧单改）**：(1) Production `profiles/_common.py::ancestor_chain` 与 Oracle `profiles.rs::ancestor_chain` 在 Windows 主机上发盘符形链（`["C:/", "C:/repo", …]`），`stop` 过滤随之生效，walk 为 `[stop..cwd]`；Linux 上旧形状逐字节不变（FIX-R3 模拟行为保留）。(2) CLI 与库的 receipt 组装合为一条路径：`scripts/compare_oracle.py::build_production_receipt` 委托给 `instructionroot.cli.build_receipt_for`，CLI 传词法 workspace（与库一致），修掉 F6（CLI 传 resolved CWD 导致 `workspace.cwd`/receipt_hash 在 symlink/junction 下与库不同）。(3) `repo_root=None` 的含义统一为“无仓库”：`build_receipt_for` 不再自动探测（`--repo-root` 的自动探测移到 CLI 命令层，行为不变）；S0 的 `codex-norepo`（repo_root null）曾因此多出 1 个 source。
- 残差照旧（未修，出 FIX-R5 范围）：`paths.py` 的 `redact_home()` 仍是 `normpath` + `"/"` 写法，只影响 CLI 显示文本，不进 receipt/hash。`ancestor_chain` 的 Windows `stop` 残差已在 FIX-R5 中修掉（不再返回 `[cwd]`，改为 `[stop..cwd]`）。
- **V5 若跑，判定标准不变：4 类全过 + 五项 parity 4/4 + 确定性 PASS，不要放宽。** 另加一条 V5 专属核查：CLI（`python -m instructionroot verify`）与库路径在 4 类上的 receipt 必须逐字节相同，且类 4 的 CLI exit code 必须为 20。
