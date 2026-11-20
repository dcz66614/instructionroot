# P028 WIN-JUNCTION fixture builder (Windows PowerShell)
#
# 在 Sam 的 PC 上生成 4 个真实 NTFS junction 测试 case，供 run_win_junction.py 使用。
# 与 fixtures/windows/build_windows_fixtures.py 的 4 个 junction case 逐项对应：
# 文件内容、提交信息、固定 git 日期、作者身份均相同；唯一有意的差异见
# WIN_JUNCTION_TASK.md §2 末尾（junction 目标用绝对路径、case.json 的 "os"
# 写 "windows"、.git/info/exclude 隔离 linked/、git init -b main +
# core.autocrlf=false）。
#
# 用法（PowerShell，见 WIN_JUNCTION_TASK.md §3 步骤 3）：
#   powershell -ExecutionPolicy Bypass -File .\00_control\WIN_JUNCTION\build_win_junction_fixtures.ps1 -RepoRoot C:\p028-src -EvidenceDir C:\p028-win-evidence
#
# 退出码：0 = 4 个 case 全部建成并通过验证；非 0 = 失败（日志见证据目录），
# 此时停下，不要手工改 fixtures 凑合。
# 注意：本脚本未经 Windows 实测（准备人在 Linux VM 上编写）；执行 agent 若发现
# 某条命令在实机上行为不符，停下、存证、汇报，不要自行改写脚本逻辑。

param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $false)][string]$OutRoot = "",
    [Parameter(Mandatory = $false)][string]$EvidenceDir = "C:\p028-win-evidence"
)

$ErrorActionPreference = "Stop"

if ($OutRoot -eq "") { $OutRoot = Join-Path $RepoRoot "fixtures\win-junction" }
$Placeholder = "# synthetic placeholder instruction content - P028 windows fixture`n"

# 与 Linux 构建脚本完全相同的 git 身份与固定日期（保证提交可复现）。
$env:GIT_AUTHOR_NAME = "P028 Windows Fixture"
$env:GIT_AUTHOR_EMAIL = "win@p028.invalid"
$env:GIT_COMMITTER_NAME = "P028 Windows Fixture"
$env:GIT_COMMITTER_EMAIL = "win@p028.invalid"
$env:GIT_AUTHOR_DATE = "2026-11-18T07:00:00+00:00"
$env:GIT_COMMITTER_DATE = "2026-11-18T07:00:00+00:00"

$LogLines = New-Object System.Collections.Generic.List[string]
function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $LogLines.Add($line)
    Write-Host $line
}

function Write-FileUtf8NoBomLf($path, $text) {
    # UTF-8 无 BOM、LF 换行写文件（与 Linux 构建脚本的字节一致）。
    $dir = Split-Path $path -Parent
    New-Item -ItemType Directory -Force $dir | Out-Null
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $text, $utf8NoBom)
}

function Invoke-Git($repo, $arguments) {
    # $arguments 是字符串数组；失败时抛错（含 stderr 原文）。
    $out = & git -C $repo @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($arguments -join ' ') failed in $repo (exit $LASTEXITCODE): $($out -join "`n")"
    }
    return $out
}

function New-CaseRepo($caseDir) {
    # 建 home/（空）+ repo/（git 仓库）；返回 repo 路径。
    New-Item -ItemType Directory -Force (Join-Path $caseDir "home") | Out-Null
    $repo = Join-Path $caseDir "repo"
    New-Item -ItemType Directory -Force $repo | Out-Null
    Invoke-Git $repo @("init", "-q", "-b", "main") | Out-Null
    Invoke-Git $repo @("config", "core.autocrlf", "false") | Out-Null
    Invoke-Git $repo @("config", "core.eol", "lf") | Out-Null
    return $repo
}

function New-Junction($link, $target) {
    # mklink 是 cmd.exe 内置命令，必须经 cmd /c 调用；目标必须是绝对路径，
    # 链接路径必须不存在。/J 是 junction（不需要符号链接特权，见任务书 OQ-7）；
    # 绝不用 /D（那是符号链接，不是 junction）。
    if (Test-Path $link) { throw "junction link path already exists: $link" }
    if (-not (Test-Path $target)) { throw "junction target does not exist: $target" }
    $out = cmd /c mklink /J "$link" "$target" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "mklink /J failed (exit $LASTEXITCODE): $($out -join "`n")"
    }
    Log "  mklink: $out"
}

function Write-CaseJson($caseDir, $caseId, $title, $harness, $profileVersion, $cwd, $notes, $windowsNote) {
    $data = [ordered]@{
        case_id         = $caseId
        title           = $title
        harness         = $harness
        profile_version = $profileVersion
        cwd             = $cwd
        repo_root       = "repo"
        home            = "home"
        policy          = "default"
        os              = "windows"
        env             = @{}
        working_files   = @()
        notes           = $notes
        windows_note    = $windowsNote
    }
    $json = ($data | ConvertTo-Json -Depth 10) + "`n"
    Write-FileUtf8NoBomLf (Join-Path $caseDir "case.json") $json
}

function Confirm-Case($caseDir, $caseId) {
    # 逐 case 验证：git 干净、ls-files 无 linked/、linked 是真 junction。
    $repo = Join-Path $caseDir "repo"
    $status = Invoke-Git $repo @("status", "--porcelain")
    if ($status) { throw "$caseId : git status not clean after commit: $($status -join "`n")" }
    $files = Invoke-Git $repo @("ls-files")
    Log "  ${caseId}: git ls-files: $($files -join ', ')"
    if ($files | Where-Object { $_ -like "linked/*" }) {
        throw "$caseId : git tracked files under linked/ (junction was followed by git): $($files -join ', ')"
    }
    $head = Invoke-Git $repo @("log", "-1", "--format=%H")
    Log "  ${caseId}: HEAD $head"
    $link = Join-Path $repo "linked"
    $item = Get-Item $link
    if ($item.LinkType -ne "Junction") { throw "$caseId : $link LinkType is '$($item.LinkType)', not Junction" }
    $reparse = fsutil reparsepoint query "$link" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "$caseId : fsutil reparsepoint query failed: $($reparse -join "`n")" }
    if (-not (($reparse -join "`n") -match "0xa0000003")) {
        throw "$caseId : reparse tag is not 0xa0000003 (junction): $($reparse -join "`n")"
    }
    Log "  ${caseId}: junction OK (LinkType=Junction, reparse tag 0xa0000003)"
}

# --- 类 1：win-junction-inside -------------------------------------------
function Build-JunctionInside($caseDir) {
    $caseId = "win-junction-inside"
    Log "Building $caseId ..."
    $repo = New-CaseRepo $caseDir
    Write-FileUtf8NoBomLf (Join-Path $repo "AGENTS.md") $Placeholder
    Write-FileUtf8NoBomLf (Join-Path $repo "shared\AGENTS.md") $Placeholder
    New-Junction (Join-Path $repo "linked") (Join-Path $repo "shared")
    # Git for Windows 会把 junction 当普通目录跟随；先隔离，见任务书 OQ-6。
    [System.IO.File]::AppendAllText((Join-Path $repo ".git\info\exclude"), "/linked/`n", (New-Object System.Text.UTF8Encoding($false)))
    Invoke-Git $repo @("add", "-A") | Out-Null
    Invoke-Git $repo @("commit", "-qm", "win-junction-inside: linked dir is a symlink to in-repo shared") | Out-Null
    Write-CaseJson $caseDir $caseId `
        "repo/linked is a dir symlink to in-repo shared -> GIT_TRACKED, PASS (junction analogue)" `
        "codex" "codex-2026-11" "repo/linked" `
        "NTFS junction: repo/linked is a junction to in-repo shared. Discovery runs on the RESOLVED cwd (repo/shared), so the discovered file is repo/shared/AGENTS.md." `
        "REAL NTFS junction (reparse point), built on Windows. Junction target is an absolute path (mklink /J requirement); the Linux analogue used a relative symlink."
    Confirm-Case $caseDir $caseId
}

# --- 类 2：win-junction-escape -------------------------------------------
function Build-JunctionEscape($caseDir) {
    $caseId = "win-junction-escape"
    Log "Building $caseId ..."
    $repo = New-CaseRepo $caseDir
    Write-FileUtf8NoBomLf (Join-Path $repo "AGENTS.md") $Placeholder
    Write-FileUtf8NoBomLf (Join-Path $caseDir "outside\Downloads\AGENTS.md") $Placeholder
    New-Junction (Join-Path $repo "linked") (Join-Path $caseDir "outside\Downloads")
    [System.IO.File]::AppendAllText((Join-Path $repo ".git\info\exclude"), "/linked/`n", (New-Object System.Text.UTF8Encoding($false)))
    Invoke-Git $repo @("add", "-A") | Out-Null
    Invoke-Git $repo @("commit", "-qm", "win-junction-escape: linked dir is a symlink outside") | Out-Null
    Write-CaseJson $caseDir $caseId `
        "repo/linked is a dir symlink to outside/Downloads -> OUTSIDE_REPO, BLOCK (junction analogue)" `
        "codex" "codex-2026-11" "repo/linked" `
        "NTFS junction: repo/linked is a junction to outside/Downloads. The resolved CWD is outside the repo, so the chain is [cwd] alone and only the Downloads file is discovered (OUTSIDE_REPO, BLOCK)." `
        "REAL NTFS junction (reparse point), built on Windows. Junction target is an absolute path (mklink /J requirement); the Linux analogue used a relative symlink."
    Confirm-Case $caseDir $caseId
}

# --- 类 3：win-junction-import-inside ------------------------------------
function Build-JunctionImportInside($caseDir) {
    $caseId = "win-junction-import-inside"
    Log "Building $caseId ..."
    $repo = New-CaseRepo $caseDir
    Write-FileUtf8NoBomLf (Join-Path $repo "CLAUDE.md") ($Placeholder + "@shared/ok.md`n@linked/also.md`n")
    Write-FileUtf8NoBomLf (Join-Path $repo "shared\ok.md") $Placeholder
    Write-FileUtf8NoBomLf (Join-Path $repo "shared\also.md") $Placeholder
    New-Junction (Join-Path $repo "linked") (Join-Path $repo "shared")
    [System.IO.File]::AppendAllText((Join-Path $repo ".git\info\exclude"), "/linked/`n", (New-Object System.Text.UTF8Encoding($false)))
    Invoke-Git $repo @("add", "-A") | Out-Null
    Invoke-Git $repo @("commit", "-qm", "win-junction-import-inside: import through in-repo dir symlink") | Out-Null
    Write-CaseJson $caseDir $caseId `
        "claude import @linked/also.md through a dir symlink to in-repo shared -> WITHIN_REPO, PASS (junction analogue)" `
        "claude-code" "claude-code-2026-11" "repo" `
        "NTFS junction on the import path: @linked/also.md through a junction to in-repo shared -> WITHIN_REPO, PASS." `
        "REAL NTFS junction (reparse point), built on Windows. Junction target is an absolute path (mklink /J requirement); the Linux analogue used a relative symlink."
    Confirm-Case $caseDir $caseId
}

# --- 类 4：win-junction-import-escape ------------------------------------
function Build-JunctionImportEscape($caseDir) {
    $caseId = "win-junction-import-escape"
    Log "Building $caseId ..."
    $repo = New-CaseRepo $caseDir
    Write-FileUtf8NoBomLf (Join-Path $repo "CLAUDE.md") ($Placeholder + "@shared/ok.md`n@linked/secret.md`n")
    Write-FileUtf8NoBomLf (Join-Path $repo "shared\ok.md") $Placeholder
    Write-FileUtf8NoBomLf (Join-Path $caseDir "outside\Downloads\secret.md") $Placeholder
    New-Junction (Join-Path $repo "linked") (Join-Path $caseDir "outside\Downloads")
    [System.IO.File]::AppendAllText((Join-Path $repo ".git\info\exclude"), "/linked/`n", (New-Object System.Text.UTF8Encoding($false)))
    Invoke-Git $repo @("add", "-A") | Out-Null
    Invoke-Git $repo @("commit", "-qm", "win-junction-import-escape: import through dir symlink outside") | Out-Null
    Write-CaseJson $caseDir $caseId `
        "claude import @linked/secret.md through a dir symlink to outside/Downloads -> IMPORT_ESCAPE, BLOCK (junction analogue)" `
        "claude-code" "claude-code-2026-11" "repo" `
        "NTFS junction on the import path: @linked/secret.md through a junction to outside/Downloads -> IMPORT_ESCAPE, BLOCK." `
        "REAL NTFS junction (reparse point), built on Windows. Junction target is an absolute path (mklink /J requirement); the Linux analogue used a relative symlink."
    Confirm-Case $caseDir $caseId
}

# --- 主流程 -----------------------------------------------------------------
try {
    if (-not (Test-Path (Join-Path $RepoRoot "fixtures\windows\expected\INDEX.json"))) {
        throw "INDEX.json not found under $RepoRoot\fixtures\windows\expected\ — is RepoRoot the extracted P028 source tree?"
    }
    if (Test-Path $OutRoot) {
        Log "Removing existing output root: $OutRoot"
        Remove-Item -Recurse -Force $OutRoot
    }
    New-Item -ItemType Directory -Force $OutRoot | Out-Null
    New-Item -ItemType Directory -Force $EvidenceDir | Out-Null

    Build-JunctionInside (Join-Path $OutRoot "win-junction-inside")
    Build-JunctionEscape (Join-Path $OutRoot "win-junction-escape")
    Build-JunctionImportInside (Join-Path $OutRoot "win-junction-import-inside")
    Build-JunctionImportEscape (Join-Path $OutRoot "win-junction-import-escape")

    Log "All 4 junction fixtures built and verified."
    $logPath = Join-Path $EvidenceDir "build_win_junction_fixtures.log"
    [System.IO.File]::WriteAllLines($logPath, $LogLines, (New-Object System.Text.UTF8Encoding($false)))
    Log "Log written to $logPath"
    exit 0
}
catch {
    $errLine = "[{0}] ERROR: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message
    $LogLines.Add($errLine)
    Write-Host $errLine
    try {
        New-Item -ItemType Directory -Force $EvidenceDir | Out-Null
        $logPath = Join-Path $EvidenceDir "build_win_junction_fixtures.log"
        [System.IO.File]::WriteAllLines($logPath, $LogLines, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
    exit 1
}
