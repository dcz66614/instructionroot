# P028 InstructionRoot Resolve｜项目完成通知

- 项目：P028 InstructionRoot Resolve｜有效指令链核验镜（C05）
- 方向：对指定的 Codex / Claude Code / Copilot  harness、cwd 与本地快照，确定性回答哪些指令文件会被加载、为什么、按什么组合规则、来自哪里、哪些文件没有被加载。
- 冻结：`f7be362fba770b4733c763af74bab6cd219379f6`（FIX-R5），release `3210404c1bb5339dced627c77b38002642ba71b5`
- source.zip：977,169 B，SHA-256 `66b2f003f5ebdd35e50464f8537a70d6cf1443b5efc90c265c728b0b4f48e6fd`（557 个文件）
- 许可证：MIT；零真人；88h

## 终审结论

- R1（2026-11-18）：FAIL（P1×3：S0 夹具不可复现、真实 Windows junction 未验证、无 Git bundle）
- R2（2026-11-20 ~16:14 GMT）：FAIL，唯一阻断 P1-R2-01（V5 Windows 原始证据未完整归档：E09 清单 36 个文件，Drive 只有 3 个）
- **R3（2026-11-20 ~23:11 GMT）：FINAL_VERDICT: PASS（P0=0，P1=0，BLOCKERS: NONE）——P028 已接受（ACCEPTED）**

R3 中 GPT 从 Drive 独立核验：完整证据 zip（65,245 B，SHA-256 `d4e99174…0c230c3`）36/36 文件大小与 SHA 一致，12/12 收据三路（CLI / Production / Oracle）逐字节一致，4/4 NTFS junction（reparse tag 0xa0000003），CLI 退出码 0/20/0/20，内部 receipt_hash 4/4。

## 关键证据位置（Drive，P028-instructionroot 文件夹）

- `03_evidence_V5_2026-11-20`：完整 V5 证据 zip `p028-win-evidence-v5-full.zip`（id `19BKIVdoVPpYpFr5NRl-EdvmgRwXm6guJ`）+ 结果 md + 已填索引 + E09 清单
- `04_review_FIXR5_f7be362`：R3 裁决 `P028_FINAL_REVIEW_R3.md`（id `1gk1P8C4FhjAatPZKmz_Gcy0kGqY9N8iR`）+ GPT 独立核验报告 `P028_R3_INDEPENDENT_EVIDENCE_AUDIT.json`（id `19gzGOi5XQRJ0hfUOprnrg0pgkEoXNJUa`，SHA-256 `4ab9f3c07f51190ba39001e0dd07d53aa8156bae843e275cb8516df060cb9e3a`）
- 本文件夹（CLOSURE_2026-11-20_R3_PASS）：裁决 + 本通知

## 非阻断已知限制（11 项 P2，沿用 R2）

P2-01（510 源核验 p95 7.828s，高于 500ms 阈值）、P2-03～P2-09、P2-R2-10（冻结内 WIN_JUNCTION 旧版文档）、P2-R2-11（redact_home() Windows 显示路径）、P2-R2-12（Drive 根 PROJECT_BOOK 版本与冻结源码不一致）。

## 后续

- GitHub 上传（public + MIT，仓库 https://github.com/dcz66614/instructionroot，main）：API 集 541 个文件已完成 2026-11-21 ~11:06 GMT（batch 2/2 `eef4729c`，19 个文件；batch 1 `85e444c9`，522 个文件；2026-11-22 从远程核验）。其后有 symlink 探针提交 `18765c7`（`link.md` 错模式 100644，未决定处理）。Web 集 2026-11-25 ~22:46–22:51 GMT 经云端浏览器上传完成 6 个文件（2 份 docx、1 个 workflow、3 个 exec 文件），6/6 远端 blob SHA 与本地一致。**CI 状态（截至 2026-11-25 23:19 GMT）：workflow 上传触发 4 次运行，全部失败。原因已确认：网页上传丢了执行位——`instructionroot`、`scripts/run-verify.sh`、`scripts/simulate_ci.py` 在远端均为 100644（全树 548 个文件无一 100755），verify 步骤执行 `./scripts/run-verify.sh` 瞬间以 exit 126 失败（0 秒）；run #4（id 45716528560）经 job API 核实。修复（Sam 2026-11-25 ~23:13 GMT 批准，冻结未改动，属 post-freeze 修复）：workflow 改为 `sh scripts/run-verify.sh`，`run-verify.sh` 末尾改为 `exec sh "$ROOT/instructionroot"`，绕过执行位。修复提交：`186c5670`（workflow，blob `88943a73…`）与 `a9aa8f6a`（run-verify.sh，blob `03affadc…`），2/2 远端 blob 与本地逐字节一致，head `a9aa8f6ac296c85e009857fd706e2939b64e0cc7`（12 个提交）。run #6 预期失败（当时只换了 workflow，脚本未换）；**run #7（id 45720308281，head `a9aa8f6a`）PASS**：verify 作业 5 秒成功，日志 "InstructionRoot Resolve 1.0.0"、"VERDICT: PASS (exit 0)"、"sources=0 blocked=0 warnings=0"、receipt_hash `1e19172a22055f73645f0d1ec659e14635b75a3b2ca5b7d7b5822efb28d9cf54`。非阻断警告：actions/checkout 的 Node.js 20 已弃用。另：4 次运行均实际启动并跑完（各 6–9 秒），与此前“Actions 分钟已耗尽、不会启动”的预期不符，分钟余额未核实。仍阻塞：10 个 symlink（mode 120000）+ 3 个 exec 位待 Git Data API（`instructionroot`、`scripts/simulate_ci.py` 仍为 100644，CI 绕过后不影响运行）。**
- 本次 PASS 适用于 FIX-R5 冻结版本，不代表已延期的 P2 项得到修复，也不意味着产品能够判断指令内容本身是否安全。
