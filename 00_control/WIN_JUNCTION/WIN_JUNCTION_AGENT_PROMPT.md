# WIN-JUNCTION 执行提示词 — 给 Sam 电脑上的任意 Agent

## 你是谁，你要干什么

你是正在 Sam 的 Windows PC 上执行 **P028 InstructionRoot Resolve 项目终审验证任务 WIN-JUNCTION** 的 agent。

P028 是一个“指令链核验”工具：它判断一个 coding-agent harness（codex / claude-code / copilot-cli）在某个工作目录下会加载哪些指令文件，并给每个文件定信任等级、生成带 SHA-256 的确定性 receipt。Python 生产实现与一个完全独立的 Rust Oracle 必须在同一输入上输出完全相同的 receipt。你的任务是在**真实 Windows 10/11 NTFS** 上，用**真实 NTFS junction**（`mklink /J`）跑 4 类测试，验证两边在 junction 面前是否一致，收集证据，**不改产品代码，不编造结果**。预计 45–90 分钟（`cargo build` 本身约 15 秒；Rust 工具链 1.100.0 已于 2026-11-19 装好，首次构建仍可能联网下载依赖 crates 一次）。

终审 R1（GPT-6 + Extra High，2026-11-18）裁决 `FINAL_VERDICT: FAIL`，其中 P1-02 就是“真实 Windows junction 未验收”——Linux 上的 15/15 只是目录 symlink 模拟，不算数。**你的这次运行就是 P1-02 的证据。不要提前宣布 P1-02 已关闭**——总体结论由独立验证者与终审裁决。

**本包里有什么（先读 `WIN_JUNCTION_TASK.md`，它是权威步骤）**

| 文件 | 用途 |
|---|---|
| `WIN_JUNCTION_AGENT_PROMPT.md`（本文件） | 执行摘要：你先读这个，再按 `WIN_JUNCTION_TASK.md` 做 |
| `WIN_JUNCTION_TASK.md` | **权威程序**：4 类测试定义、判定标准、步骤、未解决问题。**与本提示词冲突时以它为准** |
| `EVIDENCE_INDEX.md` | 证据索引：执行中逐项填写实际结果和判定，完成后交回 |
| `CONSISTENCY_CHECK.md` | 一致性核对（包准备人的核实记录 + 你填完证据后的自查清单） |
| `build_win_junction_fixtures.ps1` | 生成 4 个 junction fixtures 的脚本（不要手写 fixtures） |
| `run_win_junction.py` | 跑 4 类测试 + 确定性抽查的 runner（复用 `scripts/` 的核对函数） |

冻结 release 身份（执行前核对，见 `WIN_JUNCTION_TASK.md` §0）：冻结 commit `0110fa8fbeac497a98801d14e5308d454ec52e31`，`source.zip` SHA-256 必须是 `fdcd98af548557a213cb1a5853804d04e1ed7b7302814363adada2ac4120acf8`（866,129 B）。对不上就停。**不要用 `dist.zip` 里的 Oracle 二进制——那是 Linux ELF，在 Windows 上跑不起来。**

## 前置检查（缺一项就停，先报给 Sam）

- Windows 10/11，C 盘是 **NTFS**（`Get-Volume C` 核对；不是 NTFS 就停）。
- **Python ≥ 3.12**（`python --version`；没有或版本低就停，不要用 WSL 的 Python 绕过）。实测：PATH 首个 python 为 3.11.15，须用原生 3.14.4（见任务书 OQ-2）。
- **git** 已安装（`git --version`；没有就停）。
- **cargo / rustc** 已安装（`cargo --version`；没有就先在会话内前置 `%USERPROFILE%\.cargo\bin` 再试——rustup 1.100.0 已于 2026-11-19 经 Sam 批准安装，`--no-modify-path`，未永久改 PATH；仍无则停，等 Sam 决定，不要自行下载安装）。
- 先在 `$env:TEMP` 里做一个 junction 探测（见任务书 §3 步骤 1）：`mklink /J` 建 junction、读穿过去的文件、`(Get-Item).LinkType` 必须是 `Junction`、`fsutil reparsepoint query` 须含 `0xa0000003`。探测失败就停，**不要改用 `mklink /D`**（那是符号链接，不是 junction）。

## 执行步骤（按 `WIN_JUNCTION_TASK.md` §3，逐节做）

1. **步骤 0 取得源码**：核对 `source.zip` SHA → 解压到 `C:\p028-src\` → 把本包 6 个文件复制到 `C:\p028-src\00_control\WIN_JUNCTION\`。不要 `git init` 外层源码树。
2. **步骤 1 前置检查**：按任务书逐项跑，完整输出存进 `C:\p028-win-evidence\`。Python、git、cargo、NTFS、junction 探测，缺一项就停。
3. **步骤 2 构建 Oracle**：`cargo build --release --locked --manifest-path C:\p028-src\03_oracle\rust\Cargo.toml`，产物必须是 `...\target\release\instructionroot-oracle.exe`。构建失败就停，把完整日志存证。实测本机已有 `link.exe` / `cl.exe`（MSVC 14.44.35207），链接器缺失不是已知阻塞；**如果仍报错链接器缺失（例如 `link.exe not found`）：只记录，不要自行安装 C++ 工作负载、不要自行改 target、不要装 MinGW**——修复路径由 Sam / Muse 决定（P025 有过教训：未经核实的“需要装 C++”不能当定论行动）。
4. **步骤 3 生成 fixtures**：跑 `build_win_junction_fixtures.ps1`（参数见任务书；FIX-R2：脚本已为 UTF-8 带 BOM，PS 5.1 可直接跑）。脚本 exit 非 0 就停，不要手工改 fixtures。跑完抽查一个 junction：`dir ...\win-junction-inside\repo` 应显示 `linked` 为 `<JUNCTION>`。
5. **步骤 4 跑 runner**：`python .\00_control\WIN_JUNCTION\run_win_junction.py --repo C:\p028-src --fixtures C:\p028-src\fixtures\win-junction --evidence C:\p028-win-evidence`，输出用 `Tee-Object` 存到 `C:\p028-win-evidence\run_win_junction.log`。期望 4 个 `[PASS]` + 五项 parity 4/4 + 确定性 PASS + `RESULT=PASS`。**`RESULT=FAIL` 是结果，不是事故**：保留证据、逐 case 记失败、继续完成证据索引，不要重跑刷到通过、不要改期望、不要改 fixtures。
6. **步骤 5 收尾**：填好 `EVIDENCE_INDEX.md` 与任务书 §4 判定表，按 `CONSISTENCY_CHECK.md` §3 逐项打勾。**不要删除** `C:\p028-src\fixtures\win-junction\` 与 `C:\p028-win-evidence\`。

## 4 类测试速查（精确定义见任务书 §2，期望值以 `fixtures/windows/expected/INDEX.json` 为准）

| 类 | case | harness | 期望 verdict |
|---|---|---|---|
| 1 仓库内部 junction | `win-junction-inside` | codex | PASS（2 个 source，均为 GIT_TRACKED） |
| 2 仓库外部逃逸 junction | `win-junction-escape` | codex | BLOCK（1 个 source，OUTSIDE_REPO；repo 根文件不在 chain 里） |
| 3 import 通过内部 junction | `win-junction-import-inside` | claude-code | PASS（`@linked/also.md` → WITHIN_REPO） |
| 4 import 通过外部 junction | `win-junction-import-escape` | claude-code | BLOCK（`@linked/secret.md` → IMPORT_ESCAPE） |

判定标准：每个 case 的 source / trust / edge / verdict / receipt_hash 五项必须**全部**与 INDEX.json 一致且 Production 与 Oracle 完全相同；另加 `win-junction-import-escape` 上 10 次 Production + 10 次 Oracle 的确定性抽查（20 个 hash 必须完全相同）。五项有一项不是 4/4，该 case 即失败。

## 纪律（违反就等于证据作废）

- **禁止变通**：不改产品代码、不改 Oracle 代码、不改 `case.json` 期望、不把 junction 换成 symlink（`/D`）、不用 WSL 或 Linux 结果代替、不重装旧版、不降级工具链。
- **禁止重做掩盖**：失败的步骤最多按“无效尝试”规则重做一次（仅当执行过程本身违规时）；同一失败重做两次以上仍失败，就是失败，不要刷到通过为止。
- **禁止编造**：没跑的写“未执行”，没看到的写“未观察到”，不确定的写“不确定”。空着比填错强。
- 每步的完整命令输出都要存进证据（不要只抄结论）；文件 SHA 一律用 `Get-FileHash <文件> -Algorithm SHA256`。

## 实测已更新的点（2026-11-19，执行前必读，见任务书 §6）

- **Rust 与 Python 在 Windows 上认不认 junction 为“链接”，已分别实测（未经过 runner）。** Python 3.14.4 `os.path.islink(junction)` = **False**、不跟随；Rust 1.100.0（与 Oracle 同一 API）`file_type().is_symlink()` = **True**、会跟随。即使盘符路径修好，两边在 junction 上仍大概率 parity 失败——此项为**推断**，未经 runner 验证。如果 runner 跑下来一边跟随、一边不跟随（parity 失败），或两边都不跟随（verdict 与期望不符），**那就是本次运行要发现的产品事实**：如实记为失败/产品发现，把两边 receipt 的 `resolved_path` / `is_symlink` / `symlink_chain` 原文存证，继续跑完其余 case，不要改代码、不要改期望。
- **Git for Windows 对 junction 的处理已实测。** 构建脚本已用 `.git/info/exclude` 隔离 `linked/`；2026-11-19 实测隔离有效（`git ls-files` 无 `linked/` 下文件，提交后 `git status` 为空）。如果提交后 `git status` 非空或 `ls-files` 出现 `linked/` 下的文件，停下来存证汇报，不要手工 `git rm` 凑合。
- **`mklink /J` 要不要管理员权限，已实测：不需要。** 2026-11-19 实测本机普通提示符即可建 junction，探测 4/4 通过。以步骤 1 的探测为准；探测报权限不足就停，等 Sam 决定，不要自行提权后不记录就继续。

## 交付（完成后交给 Sam / Muse）

1. **填好的 `EVIDENCE_INDEX.md`**：每项测试的实际结果、判定（通过 / 失败 / 部分通过）、证据编号与 SHA。判定汇总表（`WIN_JUNCTION_TASK.md` §4）也要填。
2. **证据文件夹 `C:\p028-win-evidence\`**：环境证明、前置检查输出、Oracle 构建日志、fixture 构建日志（含每个 junction 的 `fsutil` 证明）、runner 完整日志、每 case 的 Production/Oracle receipt 与 explain sidecar、汇总 JSON。**原件不改、不删。**
3. **一份简短结果汇总**：4 类各自 通过/失败 + 五项 parity 数字（各 x/4）+ 确定性抽查结果 + 任何失败的原文 + 证据文件夹路径。
4. 保留 `C:\p028-src\fixtures\win-junction\` 原样，不要删除。

## 完成标准

4 类测试全部执行（或如实标注未执行及原因）+ `EVIDENCE_INDEX.md` 填好 + 证据文件夹完整。总体结论由独立验证者与终审裁决，不由你下。
