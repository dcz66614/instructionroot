# WIN-JUNCTION 证据索引（模板——执行后填写）

TASK_ID：`P028-WIN-JUNCTION`｜终审 R1 P1-02｜冻结 `0110fa8fbeac497a98801d14e5308d454ec52e31`（FIX-R1 重冻结，R1 值 `30700bd` 已 superseded）｜HEAD `9d4fd93`｜
`source.zip` SHA-256 `fdcd98af548557a213cb1a5853804d04e1ed7b7302814363adada2ac4120acf8`（866,129 B）

## 填写规则

- 每项都有“实际结果 / 文件”栏：**执行后填写，执行前留空**。没有跑的写“未执行”，没有看到的写“未观察到”，不确定的写“不确定”。空着比填错强。
- 每个文件怎么产生、存在哪，见“产生方式 / 存放位置”栏；证据文件夹统一放在 `C:\p028-win-evidence\`（执行人自定路径时，在此注明实际路径：\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_）。
- SHA-256 一律用 `Get-FileHash <文件> -Algorithm SHA256` 生成；文本输出（如 `python --version`、构建日志）要保存完整原文，不要只抄结论。
- 所有证据文件命名用英文、日期前缀 `2026-11-18-`，不要用中文文件名（跨机器传递时少出问题）。

## E00. 执行环境

| # | 证据项 | 产生方式 / 存放位置 | 实际结果 / 文件 | SHA-256 |
|---|---|---|---|---|
| E00-1 | 操作系统与版本 | `winver` 或 `Get-ComputerInfo` 输出截图/文本 | （待填） | — |
| E00-2 | C 盘文件系统 | `Get-Volume C \| Select-Object FileSystem, DriveLetter` 输出（必须是 NTFS） | （待填） | — |
| E00-3 | PowerShell 版本 | `$PSVersionTable.PSVersion` 输出 | （待填） | — |
| E00-4 | Python 版本证明 | `python --version` 完整输出（须 ≥ 3.12；实测提示：PATH 首个 python 曾为 3.11.15（< 3.12 门），2026-11-19 实测改用原生 3.14.4） | （待填） | — |
| E00-5 | Git 版本证明 | `git --version` 完整输出 | （待填） | — |
| E00-6 | Rust 工具链证明 | `cargo --version` + `rustc --version` + `rustup show` 完整输出（实测：rustup 1.100.0 已于 2026-11-19 经 Sam 批准安装，`--no-modify-path`；cargo 不在 PATH 时先在会话内前置 `%USERPROFILE%\.cargo\bin`） | （待填） | — |
| E00-7 | Node.js 版本证明 | `node --version` 完整输出（只记录，不设门） | （待填） | — |
| E00-8 | Claude Code 版本证明 | `claude --version` 完整输出（只记录，不设门；若未安装写“未安装”） | （待填） | — |

## E01. 源码身份

| # | 证据项 | 产生方式 / 存放位置 | 实际结果 / 文件 | SHA-256 |
|---|---|---|---|---|
| E01-1 | `source.zip` 校验 | `Get-FileHash source.zip -Algorithm SHA256` 输出；期望 `fdcd98af…20acf8` | （待填） | （待填） |
| E01-2 | 解压位置与内容核对 | `C:\p028-src\` 下 `02_src/`、`03_oracle/rust/`、`scripts/`、`fixtures/windows/expected/INDEX.json` 均存在（`Get-ChildItem` 清单） | （待填） | — |
| E01-3 | 本包 6 个文件 | `C:\p028-src\00_control\WIN_JUNCTION\` 下 6 个文件清单 + 各自 SHA-256 | （待填） | （待填） |
| E01-4 | `dist.zip` 未被使用声明 | 确认未从 `dist.zip` 解出 Oracle 二进制使用（`dist.zip` 内 Oracle 为 Linux ELF，见任务书 §0） | （待填） | — |

## E02. 前置检查（步骤 1）

| # | 证据项 | 产生方式 / 存放位置 | 实际结果 / 文件 | SHA-256 |
|---|---|---|---|---|
| E02-1 | junction 探测：建链 | `cmd /c mklink /J "$env:TEMP\p028-junction-probe\linked" ...` 输出原文 | （待填） | — |
| E02-2 | junction 探测：读穿 | `Get-Content ...\linked\probe.txt` 输出（须读到 `probe`） | （待填） | — |
| E02-3 | junction 探测：类型证明 | `(Get-Item ...\linked).LinkType` 输出（须为 `Junction`）+ `fsutil reparsepoint query` 输出（须含 `0xa0000003`） | （待填） | — |
| E02-4 | junction 探测：清理 | `Remove-Item -Recurse -Force` 探测目录已删（`Test-Path` 为 False） | （待填） | — |

## E03. Oracle 构建（步骤 2）

| # | 证据项 | 产生方式 / 存放位置 | 实际结果 / 文件 | SHA-256 |
|---|---|---|---|---|
| E03-1 | `cargo build` 完整日志 | `cargo build --release --locked --manifest-path ...` 的 stdout + stderr 全文（存文本；若失败，exit code 一并记录） | （待填） | （待填） |
| E03-2 | Oracle 二进制 | `...\target\release\instructionroot-oracle.exe` 存在 + `--version` 输出 | （待填） | （待填） |
| E03-3 | 构建失败记录（如有） | 失败时的完整错误原文（尤其链接器错误）；记录是否停下、是否汇报（不得自行装 C++ 工作负载/改 target/装 MinGW）。实测：本机已有 `link.exe` / `cl.exe`（MSVC 14.44.35207），链接器缺失不是已知阻塞；真正缺过的是 Rust 工具链（见 E00-6） | （待填） | — |

## E04. Fixture 构建（步骤 3）

| # | 证据项 | 产生方式 / 存放位置 | 实际结果 / 文件 | SHA-256 |
|---|---|---|---|---|
| E04-1 | 构建脚本日志 | `build_win_junction_fixtures.ps1` 的完整输出（存文本）+ exit code | （待填） | （待填） |
| E04-2 | 4 个 case 的目录树 | 每 case 下 `home/`、`repo/`、`outside/`（如适用）、`case.json` 的 `Get-ChildItem -Recurse` 清单 | （待填） | — |
| E04-3 | junction 真实性证明（每 case） | `linked` 的 `(Get-Item).LinkType`（须为 `Junction`）+ `fsutil reparsepoint query` 输出（须含 `0xa0000003`）+ `dir <case>\repo` 显示 `<JUNCTION>` | （待填） | — |
| E04-4 | git 状态（每 case） | `git -C <case>\repo status --porcelain` 输出（提交后须为空）+ `git ls-files` 清单（须无 `linked/` 下的文件）+ `git log -1 --format=%H`（HEAD commit） | （待填） | — |
| E04-5 | `case.json`（每 case） | 4 个 `case.json` 全文（`"os"` 须为 `"windows"`） | （待填） | （待填） |

## E05. Runner 执行（步骤 4）

| # | 证据项 | 产生方式 / 存放位置 | 实际结果 / 文件 | SHA-256 |
|---|---|---|---|---|
| E05-1 | runner 完整日志 | `run_win_junction.log`（`Tee-Object` 保存的 stdout + stderr 全文） | （待填） | （待填） |
| E05-2 | 汇总 JSON | `win_junction_summary.json`（receipt_cases / receipt_passed / 五项 buckets / determinism / RESULT） | （待填） | （待填） |
| E05-3 | 类 1 receipt 对 | `win-junction-inside-production-receipt.json` + `win-junction-inside-oracle-receipt.json` + explain sidecar（Production 与 Oracle 的 `receipt_hash` 各自值） | （待填） | （待填） |
| E05-4 | 类 2 receipt 对 | 同上（`win-junction-escape-*`） | （待填） | （待填） |
| E05-5 | 类 3 receipt 对 | 同上（`win-junction-import-inside-*`） | （待填） | （待填） |
| E05-6 | 类 4 receipt 对 | 同上（`win-junction-import-escape-*`） | （待填） | （待填） |
| E05-7 | runner exit code | `run_win_junction.py` 的 `$LASTEXITCODE` | （待填） | — |

## E06. 确定性抽查

| # | 证据项 | 产生方式 / 存放位置 | 实际结果 / 文件 | SHA-256 |
|---|---|---|---|---|
| E06-1 | 抽查结果 | `win-junction-import-escape` 上 10 次 Production + 10 次 Oracle 的 hash 清单（须为 1 个 distinct hash） | （待填） | — |

## E07. 判定汇总（与 `WIN_JUNCTION_TASK.md` §4 一致，执行后填写）

| 测试类 | 判定 | 五项 parity（各 x/4） | 备注 |
|---|---|---|---|
| 类 1 win-junction-inside | （待填） | （待填） | |
| 类 2 win-junction-escape | （待填） | （待填） | |
| 类 3 win-junction-import-inside | （待填） | （待填） | |
| 类 4 win-junction-import-escape | （待填） | （待填） | |
| 确定性抽查 | （待填） | — | |

## E08. 偏差与未执行记录

| # | 证据项 | 产生方式 / 存放位置 | 实际结果 / 文件 |
|---|---|---|---|
| E08-1 | 与任务书不符的任何地方 | 逐条记录：步骤、实际做法、原因、完整输出 | （待填） |
| E08-2 | 未执行的步骤 | 步骤编号 + 原因（未执行就是未执行，不要补写结果） | （待填） |
| E08-3 | OQ-5 观察 | 两边 receipt 里 `resolved_path` / `is_symlink` / `symlink_chain` 对 junction 的实际表现（从 E05-3~E05-6 的 receipt 原文抄录） | （待填） |
| E08-4 | 完成后的证据索引 | 本文件填写完毕的版本 | （待填） |

执行人签字（姓名 + 日期时间）：\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_
