# P028 FIX-R3 — Production 报告（根因 A、B、D）

- 工作树：`~/workspace/p028-fixr3-production/`，分支 `fix-r3-production`（自 `d234994`）
- 提交：`7c0dab9`（合并进 `fix-r3` 为 `5dbaa31`）
- 范围：V2 根因 A、B + 拼写统一 D 的生产侧；Oracle 侧（C + D 的 Rust 部分）由另一工人并行处理

## A. 相对 import 拼接再归一化（`02_src/instructionroot/paths.py`）

- `lexical_canonical()` 只在 `raw` 本身是 Windows 拼写时才归一化；import 传相对引用
  （`shared/ok.md`），与 cwd 用 `os.path.join` 拼成全反斜杠 `C:\...\shared\ok.md` 后
  不再归一化 → 盘符正则 `_DRIVE_ABS_RE = ^[A-Za-z]:/` 不匹配 → 落回 POSIX 分支 →
  `/C:\...` → `IMPORT_ESCAPE`。
- 修法：拼接结果（join / `~` 展开）再归一化；新增 `_is_absolute_path()`，使
  Windows 风格的 cwd/home 在任何宿主上都算绝对路径（Linux 上 `os_name="nt"`
  假 FS 测试需要）。
- 对照：`canonicalize` 直接吃绝对路径时任何写法都对；修后“相对 + cwd 拼接”与
  绝对路径一致。

## B. 四处 `normpath` + 写死 `/` 一次改完

- 新增共享 `_normalize_for_comparison()`：先把 Windows 拼写归一化成 `C:/` 再比较；
  POSIX 路径原样，Linux 行为逐字节不变；盘符根 `C:/` 按 `/` 同等处理。
- 四处实测结果（均与 V2 期望一致）：
  - `chain_dirs`（`profiles/_common.py`）：`['C:/repo','C:/repo/shared']`
  - `is_within_root`（`paths.py`）：`True`
  - `relative_posix`（`profiles/_common.py`）：`'AGENTS.md'`
  - `ancestor_chain`（`profiles/_common.py`，无 stop）：`['/','/C:','/C:/repo','/C:/repo/shared']`
    —— 与 Oracle 同名函数算法相同，输出一致。
- 包内“已知残差”只预判了 `ancestor_chain` 一处是错的；四处已一次改完。

## D. 收据拼写统一（生产侧，`02_src/instructionroot/receipt.py`）

- 新增 `_normalize_receipt_path()`，只在收据组装层：`workspace.cwd/home/repo_root` +
  `sources[].raw_path` → `C:/`；相对路径与 `~` 路径原样保留。
- 契约核对：workspace 字段是“Canonical absolute path”（归一化是合规，不是语义改动）；
  `raw_path` 是“Path as discovered（may contain ~ or be relative）”——只统一分隔符拼写，
  相对/`~` 路径逐字保留；`CanonicalPath.raw_path` 不动。
- 回归测试断言：同一收据的反斜杠版与正斜杠版 hash 相同。

## 规格同步（最小）

- `00_contract/PROJECT_BOOK.md` §13.1 +1 行；`paths.py` 模块 docstring +1 句。
- 未改 .docx（1 行，MD 同步即可）。

## 测试

- 新增 12 个 FIX-R3 回归测试（假 Windows FS + `os_name="nt"`），+236 行测试代码。
- 对照控制：把三处源码修复 stash 后，12 个新测试 11 个失败（唯一通过的是 D 的
  “相对/`~` 原样保留”守卫，本就应通过）。
- 本工作树验收：pytest **304 passed / 6 skipped**（292→304，+12）；S0 PASS（60 fixtures，
  parity 100%，determinism 100/100，fail_closed PASS；S0 内 pytest 304/6；cargo 35+5；
  compare_oracle 五项 parity 100% + fs 100% + git PASS）。

## 未修（范围外，诚实记录）

- `ancestor_chain` 带 Windows `stop` 时返回 `[cwd]`：与 Oracle 算法逐字节相同，
  为保 parity 未动。若终审要求 stop 在 Windows 上生效，两侧须一起改，绝不同时只改一侧。
- `paths.py` 的 `redact_home()` 仍是 `normpath` + `"/"`：只影响 CLI 显示文本，不进
  收据/hash，未动。
- 随机顺序跑时 `test_cli.py::test_version` 有一次失败：已存的顺序依赖（测试需要
  Oracle 二进制存在；全新工作树还没有二进制；确定性顺序 `-p no:randomly` 通过；
  隔离跑 stash 前后均通过；与本次改动无关）。
- `review/S0_RECEIPT_HASHES.txt` 的 504 行 diff 只是工作树路径差异（hash 内嵌绝对
  workspace 路径），非产品问题。
