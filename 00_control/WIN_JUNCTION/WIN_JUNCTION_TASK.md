# P028 WIN-JUNCTION — 真实 Windows NTFS junction 验收任务（P1-02）

| 项目 | 内容 |
|---|---|
| TASK_ID | `P028-WIN-JUNCTION`（对应终审 R1 的 P1-02） |
| 状态 | `PENDING_OWNER_EXECUTION`（包已准备，未执行，未关闭 P1-02） |
| 终审 | P028 终审 R1（GPT-6 + Extra High，2026-11-18 ~09:26 GMT），`FINAL_VERDICT: FAIL`，P1-02 为三项阻断之一 |
| 终审文件 | `~/workspace/P028_FINAL_REVIEW_R1.md`（§五 P1-02、§二 2.3） |
| 执行人 | Sam 的 PC 上的执行 agent（Windows 10/11，NTFS） |
| 包位置 | 本仓库 `00_control/WIN_JUNCTION/`，在 `fix-r1` 分支上（由 `fix-r1-winpack` 合并而来；原始创建于 HEAD `6fa67b7`，FIX-R1 后重新冻结，见 §0） |
| 包内提交 | 见本分支上添加 `00_control/WIN_JUNCTION/` 的提交（`git log --oneline -1 -- 00_control/WIN_JUNCTION/`） |

## 本任务不是什么

- 不改产品源码（`02_src/`）、不改 Oracle（`03_oracle/`）、不改 S0 门禁与 fixtures、不改 `fixtures/windows/` 的 Linux corpus、不重新冻结、不动 Drive、不做 GitHub 上传。
- 不用 Linux symlink 模拟结果代替 Windows 实测：Linux 上 `run_windows_corpus.py` 的 15/15（含 4 个 junction 模拟 case）是**对照基线**，不是本任务的证据。
- 不预设结论：4 类测试按 §2 的判定表独立记录通过/失败；失败是证据，不是事故。**执行 agent 不下总体结论**（P1-02 是否关闭由独立验证者与终审 R2 裁决）。

## §0 冻结 release 身份（执行前核对，对不上就停）

| 产物 | 大小 | SHA-256 |
|---|---|---|
| 冻结 commit | — | `0110fa8fbeac497a98801d14e5308d454ec52e31` |
| Release commit | — | `12b8d6129933d760818556099a32fdb7732e226a` |
| HEAD（本包基于，§0 更新提交之前） | — | `9d4fd93` |
| `07_release/source.zip` | 866,129 B | `fdcd98af548557a213cb1a5853804d04e1ed7b7302814363adada2ac4120acf8` |
| `07_release/dist.zip` | 570,918 B | `a780fba55a1bdcbfbe923a5dd0a8684cc00f321a66a2c5ac3af0ae5744cd204f` |
| dist.zip 内 Oracle 二进制 `oracle/instructionroot-oracle` | 1,162,032 B | `60247a20a3dd83479ca255fc0a993ad4ee8ea42880899c7ce79d317fdea2bf6b` |
| Git bundle `07_release/p028-instructionroot-0110fa8.bundle` | 4,851,843 B | `15281b8481a3759a9342353cde3978a36d75a63a260135f3945116a57b3937fb` |

- **dist.zip 里的 Oracle 是 Linux ELF，绝对不能在 Windows PC 上运行。**（本机实测：`file` 显示 `ELF 64-bit LSB pie executable, x86-64, for GNU/Linux`。）Windows 上必须用 cargo 从 `03_oracle/rust/` 原生构建（见 §3 步骤 2 与未解决问题 OQ-1）。
- 规格版本 v1.0.0。S0 门禁：60/60，Oracle 五项 parity 100%（终审 R1 §2.1–2.2 独立复核一致）。
- **注意 P1-01 的影响（已修复）：** FIX-R1 已把冻结 `source.zip` 里的绝对路径 symlink 改为相对路径（`../../outside/secret.md`），并补了 42 个 `.gitkeep`；新冻结 `0110fa8` 的 source.zip 经核查含 0 条绝对路径 symlink。本任务的 fixtures 由 §3 步骤 3 的 PowerShell 脚本在 PC 上全新生成，不用 `source.zip` 里的任何 fixture，所以与 P1-01 无关。
- 安装/运行来源：**只用解压后的源码树**（`02_src/` + `03_oracle/rust/` + `scripts/` + `fixtures/windows/expected/INDEX.json`）。不要用 `dist.zip` 安装任何东西（它里面没有可用的 Windows 二进制；wheel 是纯 Python 包，也不是本任务的运行方式——本任务直接用源码树 + `PYTHONPATH=02_src` 跑 runner）。

## §1 背景：为什么需要这次运行

终审 R1 §2.3 独立复跑：Windows corpus 15/15 通过，但 GPT 明确指出——

> “这 15/15 不是实际 Windows junction 验收。win-junction-inside 和 win-junction-escape 的 Linux 测试实际使用的是目录 symlink。它们验证了路径解析及 Production/Oracle 一致性，但没有验证 NTFS junction 的真实解析。”

S0 报告原文已有标注：**S12 真实 junction NOT_RUN**（`review/S0_GATE.md`：“real junction resolution is NOT_RUN on Linux (T011, Windows runner). Not faked as a pass.”）。T011 任务记录（`review/tasks/P028-T011/TASK_RESULT.md`）的 NOT_RUN 清单第一条就是真实 NTFS junction 解析（reparse point、junction 循环、junction 到盘符根），只做了 Linux 目录 symlink 类比 + 纯字符串探针。

P1-02 修复门槛（终审 R1 §五原文）：“在真实 Windows 10/11 NTFS 环境执行至少以下四类测试：仓库内部 junction；仓库外部逃逸 junction；import 通过内部 junction；import 通过外部 junction。Production 与 Rust Oracle 必须在 source/trust/edge/verdict/hash 五项上全部一致；不得用 Linux symlink 模拟结果代替。”

### Linux 对照基线（本包准备人在本 VM 上亲自复跑，仅作理解 runner 用，不是 Windows 证据）

2026-11-18 本 VM 上 `python3 scripts/run_windows_corpus.py`（exit 0）：

```text
receipt_cases=15 passed=15 failed=0
source_parity=15/15, trust_parity=15/15, edge_parity=15/15,
verdict_parity=15/15, hash_parity=15/15
probes=10 passed=True
determinism=PASS distinct_hashes=1
RESULT=PASS
```

其中 4 个 junction 模拟 case 在 Linux 上全部 PASS（`win-junction-inside` PASS、`win-junction-escape` BLOCK、`win-junction-import-inside` PASS、`win-junction-import-escape` BLOCK）。**这些数字在 Windows 上必须重测，不得引用。**

## §2 四类测试的精确定义

所有 case 的期望值以源码树内 `fixtures/windows/expected/INDEX.json` 为准（手写期望，runner 会逐项核对；下表是它的中文转述，**冲突时以 INDEX.json 为准**）。所有文件内容均为合成占位文本（`# synthetic placeholder instruction content - P028 windows fixture`），无真实用户数据。

约定：下文 `$CASE` = 单个 case 的目录（如 `C:\p028-src\fixtures\win-junction\win-junction-inside`）；`repo/`、`home/`、`outside/` 都在 `$CASE` 之下；`linked` 永远是 NTFS **junction**（`mklink /J`，reparse tag `0xa0000003`），**绝不用 `mklink /D` 符号链接**（/D 需要管理员/开发者模式，且不是 junction；见 OQ-7）。

### 类 1 — win-junction-inside：仓库内部 junction（chain 路径）

- harness `codex`，profile `codex-2026-11`，cwd = `repo/linked`，repo_root = `repo`。
- 目录结构：

```text
$CASE/
  home/                          <- 空目录
  repo/
    AGENTS.md                    <- 占位文本，已提交（GIT_TRACKED）
    shared/
      AGENTS.md                  <- 占位文本，已提交（GIT_TRACKED）
    linked/                      <- JUNCTION -> <绝对路径>$CASE\repo\shared
  case.json
```

- 创建命令（PowerShell，目标必须是绝对路径；`mklink` 是 `cmd.exe` 内置命令，见 §3 步骤 3 的脚本）：

```powershell
cmd /c mklink /J "$CASE\repo\linked" "$CASE\repo\shared"
```

- 机制（Linux 类比已验证，Windows 上待实测）：发现过程跑在**解析后**的 cwd（`repo/shared`）上，chain 为 `[repo, repo/shared]`，chain 里不含 symlink/junction 成分。
- 期望：2 个 source，均为 `codex.repo-chain` / scope `project` / phase `startup` / precedence `ORDERED` / trust `GIT_TRACKED`：`repo/AGENTS.md`、`repo/shared/AGENTS.md`。edges 为空。**verdict PASS（exit 0）。** 禁止出现的 trust：`NOT_OBSERVED`、`SYMLINK_ESCAPE`、`IMPORT_ESCAPE`、`OUTSIDE_REPO`、`MISSING`。

### 类 2 — win-junction-escape：仓库外部逃逸 junction（chain 路径）

- harness `codex`，profile `codex-2026-11`，cwd = `repo/linked`，repo_root = `repo`。
- 目录结构：

```text
$CASE/
  home/                          <- 空目录
  repo/
    AGENTS.md                    <- 占位文本，已提交（但不在 chain 里，见下）
    linked/                      <- JUNCTION -> <绝对路径>$CASE\outside\Downloads
  outside/
    Downloads/
      AGENTS.md                  <- 占位文本，未进任何 git 仓库
  case.json
```

- 创建命令：

```powershell
cmd /c mklink /J "$CASE\repo\linked" "$CASE\outside\Downloads"
```

- 机制（Linux 类比已验证，Windows 上待实测）：解析后的 cwd（`outside/Downloads`）在 repo 之外，chain 只有 `[cwd]`，只发现 `outside/Downloads/AGENTS.md`，其 canonical 路径本身就不含 junction 成分，所以 trust 是 `OUTSIDE_REPO`（**不是** `SYMLINK_ESCAPE`——`SYMLINK_ESCAPE` 的推导要求 canonical 路径在根内而 resolved 路径在根外，这里 canonical 路径本身已在根外）。repo 根的 `AGENTS.md` **不在** chain 里。
- 期望：1 个 source：`outside/Downloads/AGENTS.md`，`codex.repo-chain` / `project` / `startup` / `ORDERED` / `OUTSIDE_REPO`。edges 为空。**verdict BLOCK（exit 20）。** 禁止出现的 trust：`NOT_OBSERVED`。
- 注意：Linux 构建脚本里本 case 的 `title` 写的是 `-> SYMLINK_ESCAPE, BLOCK`，那是旧措辞，与 INDEX.json 的期望（`OUTSIDE_REPO`）不一致；**以 INDEX.json 为准**，title 不参与判定。

### 类 3 — win-junction-import-inside：import 通过内部 junction

- harness `claude-code`，profile `claude-code-2026-11`，cwd = `repo`（cwd 本身不在 junction 上），repo_root = `repo`。
- 目录结构：

```text
$CASE/
  home/                          <- 空目录
  repo/
    CLAUDE.md                    <- 占位文本 + "@shared/ok.md" + "@linked/also.md"，已提交
    shared/
      ok.md                      <- 占位文本，已提交
      also.md                    <- 占位文本，已提交
    linked/                      <- JUNCTION -> <绝对路径>$CASE\repo\shared
  case.json
```

- 创建命令：与类 1 相同（`linked` -> `repo\shared`）。
- 期望：1 个 source：`repo/CLAUDE.md`，`claude-code.project` / `project` / `startup` / `ORDERED` / `GIT_TRACKED`。2 条 edge（depth 均为 1）：
  - `@shared/ok.md`：canonical `repo/shared/ok.md`，resolved `repo/shared/ok.md`，`WITHIN_REPO`，allowed。
  - `@linked/also.md`：canonical `repo/linked/also.md`，resolved `repo/shared/also.md`（junction 被跟随），`WITHIN_REPO`，allowed。
  **verdict PASS（exit 0）。** 禁止出现的 trust：`NOT_OBSERVED`、`SYMLINK_ESCAPE`、`IMPORT_ESCAPE`、`OUTSIDE_REPO`、`MISSING`。

### 类 4 — win-junction-import-escape：import 通过外部 junction

- harness `claude-code`，profile `claude-code-2026-11`，cwd = `repo`，repo_root = `repo`。
- 目录结构：

```text
$CASE/
  home/                          <- 空目录
  repo/
    CLAUDE.md                    <- 占位文本 + "@shared/ok.md" + "@linked/secret.md"，已提交
    shared/
      ok.md                      <- 占位文本，已提交
    linked/                      <- JUNCTION -> <绝对路径>$CASE\outside\Downloads
  outside/
    Downloads/
      secret.md                  <- 占位文本，未进任何 git 仓库
  case.json
```

- 创建命令：与类 2 相同（`linked` -> `outside\Downloads`）。
- 期望：1 个 source：`repo/CLAUDE.md`，`claude-code.project` / `project` / `startup` / `ORDERED` / `GIT_TRACKED`。2 条 edge（depth 均为 1）：
  - `@shared/ok.md`：canonical `repo/shared/ok.md`，resolved `repo/shared/ok.md`，`WITHIN_REPO`，allowed（对照边）。
  - `@linked/secret.md`：canonical `repo/linked/secret.md`，resolved `outside/Downloads/secret.md`（junction 被跟随到仓外），`IMPORT_ESCAPE`，allowed=false。
  **verdict BLOCK（exit 20）。** 禁止出现的 trust：与类 3 相同。

### 与 Linux 类比的已知差异（不是失败，执行时如实记录即可）

1. **junction 目标必须用绝对路径**（`mklink /J` 的要求；Linux symlink 用的是相对目标 `"shared"` / `"../outside/Downloads"`）。因此 receipt 里的 `symlink_chain` / `symlink_target` 字符串在 Windows 上是绝对路径、Linux 上是相对路径——**parity 是同一台 Windows 机器上 Production 与 Oracle 的比较**，两者看到的是同一个绝对目标，不受影响；INDEX.json 也不校验 chain 内容。
2. **Git 对 junction 的处理与 Linux 不同**：Linux 上 `linked` 以单个 symlink blob 入树；Git for Windows 会把 junction 当普通目录跟随，`git add -A` 可能把目标文件也加进来。为使树尽量接近 Linux 类比，构建脚本在 `git add` 之前先把 `/linked/` 写进该 case 仓库的 `.git/info/exclude`（仅本机配置，不进树、不改产品），然后记录 `git ls-files` 备查（见 OQ-6）。2026-11-19 实测：隔离有效，`git ls-files` 无 `linked/` 下文件，提交后 `git status` 为空。`git status --porcelain` 在提交后必须为空。
3. **换行与编码**：构建脚本用 UTF-8 无 BOM、LF 换行写所有文件，并在每个 case 仓库里设 `core.autocrlf=false` + `core.eol=lf`，使入库内容与 Linux 的字节一致。
4. **`case.json` 的 `"os"` 字段**：Linux 版写 `"linux"`；Windows 构建脚本写 `"windows"`。runner 不读该字段（已核实：`scripts/compare_oracle.py` 的 `resolve_case_paths` 只用 `case_id/harness/profile_version/cwd/home/repo_root/policy/env/working_files`），只作诚实标记。
5. **git 默认分支**：构建脚本用 `git init -q -b main`（Linux 版用 `git init -q`，分支名随机器配置）。receipt 里没有任何分支字段（已核实：`02_src/instructionroot/receipt.py` 与 `git.py` 均无 `branch`），不影响判定。

## §3 执行步骤

工作路径约定（全程用**无空格短路径**）：源码树 `C:\p028-src\`，fixtures `C:\p028-src\fixtures\win-junction\`，证据 `C:\p028-win-evidence\`。换路径时全包统一换，并在证据索引里注明实际路径。

### 步骤 0 — 取得源码与本包（不核对 SHA 就不开始）

1. 从派发渠道（Drive / Muse 交接）取得冻结 `source.zip` 与本包（`00_control/WIN_JUNCTION/` 的 6 个文件）。
2. `Get-FileHash source.zip -Algorithm SHA256`，与 §0 的表逐字核对。**对不上就停。**
3. 解压到 `C:\p028-src\`。不要 `git init` 外层源码树（解压包没有 `.git`，也不要伪造一个——外层有没有 git 不影响 runner；case 里的 git 仓库由步骤 3 的脚本新建）。
4. 把本包的 6 个文件复制到 `C:\p028-src\00_control\WIN_JUNCTION\`（若解压后的源码树里没有 `00_control/` 目录就新建；这只是执行现场的摆放，不改源码内容）。

### 步骤 1 — 前置检查（缺一项就停，先记录再汇报，不要绕过）

在 PowerShell 里逐项跑，把**完整输出原文**存进证据（见 `EVIDENCE_INDEX.md` E02）：

```powershell
$PSVersionTable.PSVersion      # 记录 PowerShell 版本
winver                          # 或 Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsHardwareAbstractionLayer
Get-Volume C | Select-Object FileSystem, DriveLetter   # 必须是 NTFS，否则停（junction 只能在 NTFS 上）
python --version                # 必须 >= 3.12（pyproject.toml: requires-python = ">=3.12"）；没有 / 低于 3.12 -> 停（实测：PATH 首个 python 为 3.11.15，须用原生 3.14.4，见 OQ-2）
git --version                   # 必须存在；没有 -> 停（git 缺失时生产代码会把 git 状态记为“未观测到”，trust 会变，测的就不是同一东西）
cargo --version; rustc --version  # 必须存在；没有 -> 停，见 OQ-1
node --version                  # 只记录（P028 不用 Node；Sam 的 PC 基线信息）
```

- **探测 junction（建正式 fixtures 之前先探）：**

```powershell
New-Item -ItemType Directory -Force "$env:TEMP\p028-junction-probe\target" | Out-Null
Set-Content "$env:TEMP\p028-junction-probe\target\probe.txt" "probe"
cmd /c mklink /J "$env:TEMP\p028-junction-probe\linked" "$env:TEMP\p028-junction-probe\target"
Get-Content "$env:TEMP\p028-junction-probe\linked\probe.txt"   # 必须读到 probe
(Get-Item "$env:TEMP\p028-junction-probe\linked").LinkType      # 必须是 Junction
fsutil reparsepoint query "$env:TEMP\p028-junction-probe\linked"  # 须含 Reparse Tag Value : 0xa0000003
Remove-Item -Recurse -Force "$env:TEMP\p028-junction-probe"
```

  探测失败（尤其 `You do not have sufficient privilege to perform this operation`）→ **停**，把原文存证并汇报，由 Sam 决定是否提权/开开发者模式重跑；**不要自行改用 `mklink /D`**（那是符号链接，不是 junction）。

### 步骤 2 — 构建 Rust Oracle（Windows 原生构建，禁止用 dist.zip 的 Linux 二进制）

```powershell
cd C:\p028-src
rustup show                    # 记录已安装工具链；rust-toolchain.toml 锁定 channel 1.100.0（实测：rustup 1.100.0 已于 2026-11-19 经 Sam 批准安装，--no-modify-path；首次构建仍可能联网下载依赖 crates 一次）
cargo build --release --locked --manifest-path C:\p028-src\03_oracle\rust\Cargo.toml
```

- 期望：构建成功，产物为 `C:\p028-src\03_oracle\rust\target\release\instructionroot-oracle.exe`。核对：`.\03_oracle\rust\target\release\instructionroot-oracle.exe --version` 能输出版本号。
- **如果 `cargo build` 失败：停。** 把完整输出（stdout + stderr，不截断）存证。特别注意链接错误（例如 `linker 'link.exe' not found`）：实测本机已有 `link.exe` / `cl.exe`（MSVC 14.44.35207），链接器缺失不是已知阻塞——若仍报此错，**只记录，不自行安装任何东西**（见 OQ-1 与 P025 的教训：不要把未经核实的“需要装 C++ 工作负载”写成定论或直接动手装；修复路径由 Sam / Muse 决定）。也不要改用 `--target x86_64-pc-windows-gnu` 或其他 target 自行换办法。
- **不要**从 `dist.zip` 里解出 `oracle/instructionroot-oracle` 来用（Linux ELF，在 Windows 上跑不起来）；也不要从本 VM 交叉编译——本包准备时已核实本 VM 无法交叉编译（见 `CONSISTENCY_CHECK.md` §1）。

### 步骤 3 — 生成 4 个 junction fixtures（用包里的 PowerShell 脚本）

```powershell
cd C:\p028-src
powershell -ExecutionPolicy Bypass -File .\00_control\WIN_JUNCTION\build_win_junction_fixtures.ps1 -RepoRoot C:\p028-src -EvidenceDir C:\p028-win-evidence
```

- FIX-R2：脚本已存为 UTF-8 **带 BOM**，Windows PowerShell 5.1 可直接跑（2026-11-19 实测：无 BOM 版在 PS 5.1 下 ParserError，需改用 pwsh 7.7.0 原样重跑）。

- 脚本做的事（与 `fixtures/windows/build_windows_fixtures.py` 的 4 个 junction case 逐项对应，文件内容、提交信息、固定 git 日期 `2026-11-18T07:00:00+00:00`、作者 `P028 Windows Fixture <win@p028.invalid>` 均相同）：建 `home/`（空）+ `repo/` + `outside/`、写占位文件、`git init -q -b main`、`core.autocrlf=false`、`.git/info/exclude` 加 `/linked/`、用 `mklink /J` 建 junction、`git add -A` + `git commit`、写 `case.json`（`"os": "windows"`），最后逐 case 验证（`git status --porcelain` 为空、`git ls-files` 清单、`(Get-Item linked).LinkType` 为 `Junction`、`fsutil reparsepoint query` 含 `0xa0000003`）并把日志写进证据目录。
- 脚本 exit 非 0 → **停**，把日志存证并汇报，不要手工改 fixtures 凑合。
- 脚本跑完后人工抽查一个 junction：`dir C:\p028-src\fixtures\win-junction\win-junction-inside\repo` 应显示 `linked` 为 `<JUNCTION>`。

### 步骤 4 — 跑 Windows runner（4 类 + 确定性抽查）

```powershell
cd C:\p028-src
python .\00_control\WIN_JUNCTION\run_win_junction.py --repo C:\p028-src --fixtures C:\p028-src\fixtures\win-junction --evidence C:\p028-win-evidence 2>&1 | Tee-Object -FilePath C:\p028-win-evidence\run_win_junction.log
```

- runner 做的事（复用 `scripts/run_windows_corpus.py` 的 `check_receipt_case` 与 `scripts/compare_oracle.py` 的 receipt 构建函数，不改它们）：对 4 个 case 逐一生成 Production receipt 与 Oracle receipt（Oracle 各跑两次验确定性），做**全 receipt 逐字段比较 + receipt_hash 比较 + 独立 JCS 重算**，再按 INDEX.json 核对 sources/trust/edges/verdict/not-applicable；随后在 `win-junction-import-escape`（BLOCK 且有 import 边）上做 10 次 Production + 10 次 Oracle 的确定性抽查（20 个 hash 必须完全相同）；最后把每 case 的 Production receipt、Oracle receipt、Oracle explain sidecar 与汇总 JSON 写进证据目录。
- 期望输出（与 Linux runner 同格式）：

```text
[PASS] win-junction-inside (PASS, <hash[:12]>)
[PASS] win-junction-escape (BLOCK, <hash[:12]>)
[PASS] win-junction-import-inside (PASS, <hash[:12]>)
[PASS] win-junction-import-escape (BLOCK, <hash[:12]>)
receipt_cases=4 passed=4 failed=0
source_parity=4/4, trust_parity=4/4, edge_parity=4/4, verdict_parity=4/4, hash_parity=4/4
determinism=PASS distinct_hashes=1
RESULT=PASS
```

- runner exit 非 0 或 `RESULT=FAIL` → **这是结果，不是事故**：把日志与证据原样保留，按 §2 判定表逐 case 记失败，继续完成证据索引，**不要重跑刷到通过、不要改期望、不要改 fixtures**。失败的 case 最多按“无效尝试”规则重做一次（仅当执行过程本身违规，例如 junction 建错且脚本已报错时）；同一失败重做两次以上仍失败，就是失败。

### 步骤 5 — 收尾与交付

1. 填好 `EVIDENCE_INDEX.md`（每项的实际结果/判定/文件/SHA），填好本任务书 §4 的判定汇总表。
2. 按 `CONSISTENCY_CHECK.md` §3 逐项打勾。
3. **不要删除** `C:\p028-src\fixtures\win-junction\` 与 `C:\p028-win-evidence\`，留着供独立验证者复核。不要把 fixtures 提交到任何 git 仓库（它们不在源码树的 git 管理下；执行现场也没有外层 git 仓库）。
4. 把填好的证据索引 + 汇总（一页结果：4 类各自通过/失败 + 五项 parity 数字 + 任何失败的原文 + 证据文件夹路径）交给 Sam / Muse。**总体结论（P1-02 是否关闭）由独立验证者与终审裁决，不由执行 agent 下。**

## §4 判定汇总表（执行后填写）

| 测试类 | 期望 verdict | 实际 verdict | source | trust | edge | verdict | hash | 判定 |
|---|---|---|---|---|---|---|---|---|
| 类 1 win-junction-inside | PASS | （待填） | （待填） | （待填） | （待填） | （待填） | （待填） | （待填） |
| 类 2 win-junction-escape | BLOCK | （待填） | （待填） | （待填） | （待填） | （待填） | （待填） | （待填） |
| 类 3 win-junction-import-inside | PASS | （待填） | （待填） | （待填） | （待填） | （待填） | （待填） | （待填） |
| 类 4 win-junction-import-escape | BLOCK | （待填） | （待填） | （待填） | （待填） | （待填） | （待填） | （待填） |
| 确定性抽查（win-junction-import-escape ×10+10） | 1 个 hash | （待填） | — | — | — | — | — | （待填） |

判定只取三种：**通过 / 失败 / 部分通过**（行为对、原因不对时用，例如 verdict 对但某条 edge 的 reason 与期望不同）。五项 parity 有一项不是 4/4，该 case 即为失败。

**V3 说明（FIX-R3，2026-11-19）**：V2（冻结 `d3847b9`）跑完 4/4 失败，但类 2 两侧语义已全对（BLOCK / OUTSIDE_REPO / 1 source），只差 `workspace.*` 与 `raw_path` 的分隔符写法；FIX-R3 已把 receipt 拼写统一成 `C:/`，并修了 V2 定位的三处根因（相对 import 拼接再归一化；`chain_dirs` / `is_within_root` / `relative_posix` / `ancestor_chain` 四处一次改完；Oracle `git.rs` 的 `abspath()` 盘符感知）。**V3 的判定标准不变：4 类全过 + 五项 parity 4/4 + 确定性 PASS，不要放宽。**

**V4 说明（FIX-R4，2026-11-19）**：V3（冻结 `535879b`）跑完 4 类 verdict 全对、source/trust/edge 全对、类 2 完全通过，只剩 `sources[].git.repo` 一个字段的分隔符写法差异（Production `C:\…` 对 Oracle `C:/…`）导致 receipt hash 不等；FIX-R4 已把 `git.repo` 在两条组装入口（`build_source_record` 与 `_normalize_sources` 的 dict 直通）都归一化成 `C:/`。**V3 行为面已全对，V4 的判定标准不变：4 类全过 + 五项 parity 4/4 + 确定性 PASS，不要放宽。**

**V5 说明（FIX-R5，2026-11-20）**：V4（冻结 `b2f9ceb`）跑完 RESULT=PASS，P1-02 已关闭。V4 另发现 E08-5（不在 P1-02 判定范围内）：生产 CLI 的 receipt 与库路径不同——claude-code 两个 case 在 CLI 侧是 0 source / 0 edge / PASS，而库里是 1 source / 2 edges（类 4 为 BLOCK），`verify` 在类 4 上 exit code 为 0 而期望 20；与 junction 无关，普通仓库上同样复现。根因是 `ancestor_chain()` 的 `"/C:/…"` 形链在 Windows 上不可消费（`ntpath.normpath` 改写成 UNC 形，永不存在）；FIX-R5 已把两侧的链都改成盘符形（`["C:/", "C:/repo", …]`），并把 CLI 与库的 receipt 组装合为一条路径、统一 `repo_root=None` 为“无仓库”。**V5 的判定标准不变：4 类全过 + 五项 parity 4/4 + 确定性 PASS，不要放宽；另加一条 V5 专属核查：CLI（`python -m instructionroot verify`）与库路径在 4 类上的 receipt 必须逐字节相同，且类 4 的 CLI exit code 必须为 20。** V5 只在主聊天一次定夺后才跑，绝不搞 PC 调试循环。

## §5 失败处理与诚实记录规则

1. 任何一步的实际结果与“期望”不符：**停下该步，记录原文，按判定表记失败/部分通过，然后继续下一项独立测试**——除非是搭建失败（步骤 0–3），搭建失败则整体停止。
2. **禁止变通：** 不改产品代码、不改 Oracle 代码、不改冻结配置语义、不改 `case.json` 的期望、不把 junction 换成 symlink（`/D`）、不用 WSL 或 Linux 结果代替、不重装旧版、不降级工具链。
3. **禁止重做掩盖：** 失败的步骤最多按“无效尝试”规则重做一次（仅当执行过程违规导致尝试无效时）；同一失败重做两次以上仍失败，就是失败，不要刷到通过为止。
4. **禁止编造：** 没有跑的步骤写“未执行”；没有看到的输出写“未观察到”；不确定的写“不确定”。证据索引里每项都有“实际结果”栏，空着比填错强。
5. 执行中遇到本包没写到的情况：记录完整上下文（命令、输出、时间），继续按最接近的步骤走，事后在证据索引的备注里写明。

## §6 未解决的前置问题与处理分支（执行前必读，不要假装都已解决）

| # | 问题 | 本包准备时已核实的部分 | 未核实的部分 / 处理分支 |
|---|---|---|---|
| OQ-1 | **Oracle 在 Windows 上怎么得到？** | dist.zip 的 Oracle 是 Linux ELF（本机 `file` 实测），不能在 Windows 跑；本 VM 的 cargo 1.100.0 只有 `x86_64-unknown-linux-gnu` target，无 `x86_64-pc-windows-gnu`、无 MinGW 链接器，**本 VM 无法交叉编译出 Windows 可执行文件**（见 `CONSISTENCY_CHECK.md` §1；未擅自 `rustup target add` 装大型工具链）。 | 唯一已安排的路径是**在 Sam 的 PC 上用 rustup + cargo 原生构建**（`cargo build --release --locked`，工具链由 `rust-toolchain.toml` 锁定 1.100.0）。**2026-11-19 实测更新**：“PC 的 VS Build Tools 2022 无 C++ 组件”**不成立**——本机有 `link.exe` / `cl.exe`（MSVC 14.44.35207），链接器从未成为阻塞点；真正缺过的是 **Rust 工具链**（执行前 cargo/rustc/rustup 全无），已于 2026-11-19 经 Sam 批准安装 rustup 1.100.0（`--no-modify-path`，未永久改 PATH，运行时在会话内前置 `%USERPROFILE%\.cargo\bin`），随后 `cargo build --locked` 一次通过（14.87s，产物 `instructionroot-oracle.exe` 828,928 B）。分支：① cargo 不在 PATH → 先在会话内前置 `%USERPROFILE%\.cargo\bin` 再试；仍无 → 停，记录，汇报，等 Sam 决定（不要自行重装）；② `cargo build` 报链接器缺失 → 停，存完整日志，汇报，**不要自行安装 C++ 工作负载、不要自行改 target 为 `-gnu`、不要自行装 MinGW**（P025 的教训：未经核实的“需要装 C++”不能当定论行动；修复路径由 Sam / Muse 决定）；③ 构建成功 → 继续。 |
| OQ-2 | **Python 装了没有？** | 生产代码要求 Python ≥ 3.12（`pyproject.toml`），且只用标准库、无第三方依赖（已核实）。 | **2026-11-19 实测**：PATH 首个 `python` 是 **3.11.15**（< 3.12 门），经 Sam 批准改用原生 **3.14.4**（py 启动器默认）。门仍为 ≥ 3.12。分支：`python --version` 无此命令或 < 3.12 → **停**，记录并汇报，等 Sam 安装/升级；不要用别的 Python（如 WSL 里的）绕过。 |
| OQ-3 | **Git 装了没有？** | 生产代码只调 4 条 allowlisted git 命令（`rev-parse --show-toplevel`、`ls-files --error-unmatch`、`status --porcelain=v1`、`log -1 --format=%H`），且 git 缺失时 trust 会变（`02_src/instructionroot/git.py` 注释已核实）。 | **2026-11-19 实测**：git **2.55.0.windows.2** 已装。分支：`git --version` 失败 → **停**，记录并汇报；不要在没 git 的情况下跑（结果不可比）。 |
| OQ-4 | **C 盘是 NTFS 吗？** | junction 只能建在 NTFS（ReFS 亦可，但本任务只认 NTFS）上。 | **2026-11-19 实测**：Windows 11 Home 10.0.26200，C 盘 **NTFS**。分支：`Get-Volume C` 显示非 NTFS → **停**，记录并汇报；不要换到别的盘自行决定（换盘要改全部路径与证据，须 Sam 确认）。 |
| OQ-5 | **Rust 与 Python 在 Windows 上认不认 junction 为“链接”？** | 两边解析都走“逐组件读链接目标”的手工实现：Rust `03_oracle/rust/src/paths.rs` 的 `resolve_components` 只在 `file_type().is_symlink()` 为真时才 `read_link` 跟随；Python `02_src/instructionroot/paths.py` 的 `_resolve_components` 只在组件是链接时才 `os.readlink` 跟随。**junction 的 reparse tag 是 `IO_REPARSE_TAG_MOUNT_POINT (0xa0000003)`，不是 symlink 的 `0xa000000c`**。**2026-11-19 已分别实测（未经过 runner）**：Python 3.14.4 `os.path.islink(junction)` = **False**、不跟随；Rust 1.100.0（与 Oracle 同一 API）`file_type().is_symlink()` = **True**、会跟随。含义：即使盘符路径修好，两边在 junction 上仍大概率 parity 失败——此项为**推断**，未经 runner 验证（runner 未到达该阶段）。 | 本次运行仍要以 runner 实测为准，不是前置条件。分支：① 两边都跟随且 verdict/parity 全对 → 通过；② 一边跟随、一边不跟随（parity 失败）或两边都不跟随（verdict 与期望不符）→ **如实记为失败/产品发现**，把两边的 receipt（`resolved_path`、`is_symlink`、`symlink_chain` 字段）原文存证，继续跑完其余 case，**不要改代码、不要改期望**。 |
| OQ-6 | **Git for Windows 会怎么处理 junction？** | Linux 上 `linked` 以单个 symlink blob 入树；Git for Windows 一般把 junction 当普通目录跟随，`git add -A` 可能把目标文件也加进来。**2026-11-19 实测**：加了 `/linked/` 隔离后，Git for Windows **没有**把 junction 目标吸进索引（`git ls-files` 无 `linked/` 下文件，提交后 `git status` 为空）。 | 构建脚本用 `.git/info/exclude` 加 `/linked/` 隔离（仅本机配置，不进树），并记录 `git ls-files` 备查。分支：提交后 `git status --porcelain` 非空，或 `ls-files` 出现 `linked/` 下的文件 → **停**，把 `ls-files` 与 status 全文存证，汇报后等指示；不要手工 `git rm`/`git reset` 凑合。 |
| OQ-7 | **`mklink /J` 需要管理员吗？** | 公开资料多数称 junction 不需要 `SeCreateSymbolicLinkPrivilege`（该特权只管符号链接 `/D`），`mklink /J` 可在普通提示符下运行；但也有指南称须提权。**2026-11-19 实测：本机 `mklink /J` 不需要提权**，普通提示符即可建 junction，探测 4/4 通过。 | 以步骤 1 的探测为准。分支：探测成功 → 继续；探测报权限不足 → **停**，存原文，汇报，由 Sam 决定提权或开开发者模式；不要自行改用 `/D`。 |
| OQ-8 | **源码以什么形式到 PC？** | 冻结 `source.zip` 的 SHA 见 §0；本包在分支 `fix-r2-pack` 上（FIX-R2，基于 FIX-R1 的 `fix-r1`）。 | 若 FIX-R1 在派发前重新冻结，§0 的 SHA 会过期。分支：派发人须先更新 §0；执行 agent 按更新后的表核对，对不上就停。 |
| OQ-9 | **Claude Code / Node 需要吗？** | **不需要。** P028 的 runner 只用 Python + cargo + git；PC 基线实测（2026-11-19）：Node **v22.22.2**、Claude Code **2.1.303**，只记录，不设门。 | `node --version` 与 `claude --version` 只记录，不设门；没有/版本低都不阻断本次运行。 |

## 附录：包内文件

| 文件 | 用途 |
|---|---|
| `WIN_JUNCTION_TASK.md`（本文件） | 权威任务说明：背景、4 类测试定义、判定标准、步骤、未解决问题 |
| `WIN_JUNCTION_AGENT_PROMPT.md` | 给 PC 上执行 agent 的一步步提示词（可直接复制使用） |
| `EVIDENCE_INDEX.md` | 证据索引模板（执行中逐项填写） |
| `CONSISTENCY_CHECK.md` | 一致性自查清单（包准备人的核实记录 + 执行 agent 的填后核对） |
| `build_win_junction_fixtures.ps1` | 在 PC 上生成 4 个 junction fixtures 的 PowerShell 脚本 |
| `run_win_junction.py` | 在 PC 上跑 4 类测试 + 确定性抽查的 runner（复用 `scripts/` 的核对函数） |
