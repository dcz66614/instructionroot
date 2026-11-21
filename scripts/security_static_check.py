#!/usr/bin/env python3
"""P028 T012 — static security / privacy / packaging check.

Walks the whole repository tree (as it stands at run time) and prints the
four numbers required by IMPLEMENTATION_PLAN.md §17 (TASK T012):

    shell_true=0
    network_runtime=0
    telemetry=0
    secret_fixture_leaks=0

Design notes (why this script does not fool itself):

* Python findings are found with ``ast`` first. A bare text grep for
  ``shell=True`` would flag the *check-pattern string literals* inside
  ``scripts/s0_gate.py``, ``05_tests/unit/test_git.py`` and this file
  itself — those literals are the pattern being searched for, not a
  shell call. AST analysis sees real ``Call`` nodes only.
* A raw-text sweep runs as a second net over every text file. Every raw
  hit is classified (real code vs string literal vs comment vs
  documentation prose vs JSON data) and listed explicitly. Nothing is
  silently excluded: accepted hits carry their reason in the output.
* ``subprocess`` call sites are enumerated with file:line and arguments,
  including the ones that rely on the ``shell=False`` default (no
  ``shell=`` keyword). ``os.system`` / ``os.popen`` / ``eval`` / ``exec``
  are flagged wherever they appear.
* Network findings are split by scope: production + scripts + Oracle +
  web count towards ``network_runtime``; test/support-only use
  (``05_tests/``, fixture builders) is listed separately and is never
  silently counted as clean.
* Secrets: known-pattern scan repo-wide, plus a Shannon-entropy scan of
  string literals / receipt values / fixture tokens. Pure hex hashes
  (SHA-256 / SHA-1 / MD5), UUIDs, URLs, file paths and profile version
  strings are allowlisted with reason — they are hashes / identifiers,
  not secrets. Candidate secrets are printed truncated (first 12 chars
  + length) and never in full.
* Receipt privacy (PROJECT_BOOK.md §18.1/§18.2, more specific than the
  plan): expected receipts and demo receipts must carry no instruction
  content, no usernames, no commit messages; the receipt source-field
  allowlist must contain no content field; CLI display must redact
  $HOME. Reported as a separate section, not one of the four numbers.
* License / packaging: MIT ``LICENSE`` present and referenced from
  ``pyproject.toml`` and the Oracle ``Cargo.toml``; ``pyproject.toml``
  must carry name / version (== ``CLI_VERSION``) / license / console
  entry point, and the entry-point target must resolve to a callable.

Exit code 0 only when all four numbers are 0 AND the license, package
and receipt-privacy checks pass; otherwise 1 (fail-closed).

Deterministic: sorted file order, no timestamps, no network, no writes.
Usage:  python3 scripts/security_static_check.py
"""

from __future__ import annotations

import ast
import json
import math
import re
import sys
import tokenize
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIR_NAMES = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".tox",
    ".mypy_cache", "node_modules", ".hg", ".svn",
}
SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".docx", ".zip", ".whl", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".pdf", ".sqlite3", ".db",
}
# Production / runtime scope: counts towards network_runtime.
PROD_PREFIXES = ("02_src/", "03_oracle/", "scripts/", "web/")
# Test / support scope: listed separately, never counted as clean.
TEST_PREFIXES = ("05_tests/", "01_s0/fixtures/", "fixtures/")
RECEIPT_GLOBS = ("01_s0/expected/*.json", "web/receipt*.json")

# --- shell -----------------------------------------------------------------
SHELL_FUNCS = {
    "subprocess.run", "subprocess.Popen", "subprocess.call",
    "subprocess.check_output", "subprocess.check_call",
    "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.system", "os.popen", "os.spawnl", "os.spawnle", "os.spawnlp",
    "os.spawnlpe", "os.spawnv", "os.spawnve", "os.spawnvp",
    "os.spawnvpe", "os.posix_spawn", "os.posix_spawnp",
    "os.execv", "os.execl", "os.execve", "os.execvp", "os.execlp",
    "os.execvpe", "pty.spawn", "pty.fork",
}
BUILTIN_DANGEROUS_CALLS = {"eval", "exec"}

# --- network ---------------------------------------------------------------
NETWORK_MODULES = {
    "socket", "urllib", "urllib.request", "urllib.error",
    "http.client", "http.server", "http.cookiejar",
    "requests", "httpx", "aiohttp", "urllib3",
    "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
    "xmlrpc.client", "websocket", "websockets", "socketserver",
}
NETWORK_CALL_PREFIXES = (
    "socket.", "urllib.", "requests.", "httpx.", "aiohttp.",
    "urlopen", "socket.socket", "socket.create_connection",
)
RUST_NETWORK_RES = [
    re.compile(r"\bstd::net\b"),
    re.compile(r"\bTcpStream\b"),
    re.compile(r"\bTcpListener\b"),
    re.compile(r"\bUdpSocket\b"),
    re.compile(r"\bSocketAddr\b"),
    re.compile(r"\breqwest\b"),
    re.compile(r"\bhyper::"),
    re.compile(r"\bUdpSocket::"),
]
NETWORK_CRATES = {
    "reqwest", "hyper", "tokio", "curl", "ureq", "tungstenite",
    "mio", "socket2", "async-std", "smol", "ws", "native-tls",
}
WEB_NETWORK_RES = [
    re.compile(r"\bfetch\s*\("),
    re.compile(r"\bXMLHttpRequest\b"),
    re.compile(r"\bWebSocket\s*\("),
    re.compile(r"\bEventSource\s*\("),
    re.compile(r"\bsendBeacon\s*\("),
    re.compile(r"""\bsrc\s*=\s*["']https?://"""),
]

# --- telemetry -------------------------------------------------------------
TELEMETRY_MODULES = {
    "sentry_sdk", "posthog", "mixpanel", "segment", "analytics",
    "amplitude", "datadog", "newrelic", "applicationinsights",
    "opentelemetry", "hotjar", "fullstory", "logrocket",
    "rudderstack", "heap",
}
TELEMETRY_CALL_RE = re.compile(
    r"\b(?:track|identify|capture|page|screen|report_usage|send_metrics)\s*\("
)

# --- secrets ---------------------------------------------------------------
SECRET_RES = [
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "github_pat_ghp"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "github_oauth_gho"),
    (re.compile(r"ghu_[A-Za-z0-9]{36}"), "github_user_ghu"),
    (re.compile(r"ghs_[A-Za-z0-9]{36}"), "github_server_ghs"),
    (re.compile(r"ghr_[A-Za-z0-9]{36}"), "github_refresh_ghr"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "github_fine_grained_pat"),
    (re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"), "openai_sk_proj"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "sk_token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_access_key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "slack_token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
     "private_key_header"),
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"), "bearer_token"),
]
ASSIGNMENT_RE = re.compile(
    r"""(?i)\b(password|passwd|pwd|api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)\b\s*[:=]\s*["']([^"']{8,})["']"""
)
PLACEHOLDER_MARKERS = (
    "example", "placeholder", "synthetic", "test", "fake", "changeme",
    "xxx", "your-", "dummy", "sample", "todo", "none", "null", "redacted",
    "<", "…", "...",
)
ENTROPY_MIN_LEN = 20
ENTROPY_MIN_BITS = 4.5
HEX_RE = re.compile(r"^[0-9a-f]{32}$|^[0-9a-f]{40}$|^[0-9a-f]{64}$|^[0-9a-f]{128}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# Raw-text sweep tokens (second net; every hit classified, none silent).
RAW_TOKENS = [
    ("shell", re.compile(r"shell\s*=\s*True")),
    ("shell", re.compile(r"os\.system\s*\(")),
    ("shell", re.compile(r"os\.popen\s*\(")),
    ("network", re.compile(r"import\s+socket\b")),
    ("network", re.compile(r"from\s+socket\b")),
    ("network", re.compile(r"urllib")),
    ("network", re.compile(r"http\.client")),
    ("network", re.compile(r"\brequests\b")),
    ("network", re.compile(r"\bhttpx\b")),
    ("network", re.compile(r"urlopen")),
    ("network", re.compile(r"socket\.")),
    ("network", re.compile(r"TcpStream")),
    ("network", re.compile(r"reqwest")),
    ("network", re.compile(r"std::net")),
    ("network", re.compile(r"\bcurl\b")),
    ("network", re.compile(r"\bwget\b")),
    ("telemetry", re.compile(r"sentry")),
    ("telemetry", re.compile(r"posthog")),
    ("telemetry", re.compile(r"mixpanel")),
    ("telemetry", re.compile(r"\btrack\s*\(")),
]

FORBIDDEN_RECEIPT_KEYS = {
    "content", "file_content", "instruction_text", "text", "body",
    "username", "user", "commit_message", "message", "env",
}
# NOTE: "home" is deliberately NOT forbidden: receipt.py stores
# workspace.home (the home root the <HOME> redaction is relative to)
# and canonical paths unredacted BY DESIGN — receipt.py and
# receipt_schema.json both state the <HOME> redaction is a display
# transform and the hash always uses the unredacted canonical path.
# Redaction is verified separately via redact_home in cli.py.


def scope_of(rel: str) -> str:
    """Return 'production', 'test', or 'other' for a repo-relative path."""
    if rel.startswith(PROD_PREFIXES) or "/" not in rel:
        return "production"
    if rel.startswith(TEST_PREFIXES):
        return "test"
    return "other"


def iter_text_files():
    """Yield (rel_posix, path, text) for every scannable text file."""
    out = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.name in {"SECURITY_STATIC_CHECK"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary / unreadable: stated exclusion, not a pass
        out.append((rel, path, text))
    return out


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return (base + "." + node.attr) if base else node.attr
    return ""


def _py_string_comment_spans(text: str):
    """(start, end) position spans of STRING/COMMENT tokens, or None."""
    try:
        spans = []
        for tok in tokenize.generate_tokens(StringIO(text).readline):
            if tok.type in (tokenize.STRING, tokenize.COMMENT):
                spans.append((tok.start, tok.end))
        return spans
    except (tokenize.TokenError, SyntaxError, IndentationError, ValueError):
        return None


def _classify_py(spans, line_no: int, col: int) -> str:
    if spans is None:
        return "unparseable-py"
    for (sr, sc), (er, ec) in spans:
        if sr <= line_no <= er:
            if sr == er == line_no and sc <= col < ec:
                return "string-or-comment"
            if sr < line_no < er:
                return "string-or-comment"
            if sr == line_no < er and col >= sc:
                return "string-or-comment"
            if sr < line_no == er and col < ec:
                return "string-or-comment"
    return "code"


def _classify_line(rel: str, line: str, col: int) -> str:
    if rel.endswith((".md", ".txt", ".log")):
        return "documentation-prose"
    if rel.endswith(".json"):
        return "data-value"
    if rel.endswith(".html"):
        # Inside a tag (an attribute) = code; text content between tags
        # is prose. Inline <script> code has no tag on its own line, so
        # JS is covered by the separate WEB_NETWORK_RES scan, not here.
        for m in re.finditer(r"<[^>\n]*>", line):
            if m.start() <= col < m.end():
                return "code"
        return "documentation-prose"
    stripped = line.strip()
    if stripped.startswith(("#", "//", "*", "<!--")):
        return "comment"
    hash_pos = line.find("#")
    slash_pos = line.find("//")
    if hash_pos != -1 and hash_pos < col:
        return "comment"
    if slash_pos != -1 and slash_pos < col:
        return "comment"
    for m in re.finditer(r'"[^"\n]*"|\'[^\'\n]*\'', line):
        if m.start() <= col < m.end():
            return "string-literal"
    return "code"


def _shannon(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _entropy_allowlisted(s: str) -> str | None:
    if HEX_RE.match(s):
        return "pure-hex hash (sha/md5/sha1 length), not a secret"
    if UUID_RE.match(s):
        return "uuid identifier, not a secret"
    if "://" in s:
        return "url, not a secret"
    if s.startswith("<HOME>/") or "/AGENTS.md" in s or "/CLAUDE.md" in s:
        return "file path, not a secret"
    if re.search(r"\.(md|py|rs|json|toml|txt|html|css|js)\b", s):
        return "file path, not a secret"
    if re.fullmatch(r"[a-z0-9]+-[0-9]{4}-[0-9]{2}", s):
        return "profile version id, not a secret"
    if re.search(r"[\u4e00-\u9fff]", s):
        return "CJK prose, not a secret"
    if any(ord(c) > 127 for c in s):
        return "non-ASCII prose/punctuation, not an ASCII credential"
    if " " in s:
        return "natural-language sentence, not a secret"
    return None


# ---------------------------------------------------------------------------
# 1. shell
# ---------------------------------------------------------------------------

def check_shell(files):
    """Return (shell_true_count, call_sites, raw_hits).

    call_sites: every subprocess / os-spawn / eval / exec call site found
    by AST, with its shell= status. shell_true counts only a real
    ``shell=True`` (or a non-constant ``shell=``) in real code.
    """
    shell_true = []
    call_sites = []
    for rel, _path, text in files:
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            call_sites.append((rel, exc.lineno or 0, "UNPARSEABLE: %s" % exc))
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = _dotted(node.func)
            if func in BUILTIN_DANGEROUS_CALLS:
                call_sites.append(
                    (rel, node.lineno, "%s(...) builtin call" % func))
                continue
            if func not in SHELL_FUNCS:
                continue
            src = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
            shell_kw = [kw for kw in node.keywords if kw.arg == "shell"]
            if not shell_kw:
                status = "no shell= kwarg (subprocess default shell=False)"
            else:
                val = shell_kw[0].value
                if isinstance(val, ast.Constant) and val.value is True:
                    status = "shell=True  <-- VIOLATION"
                    shell_true.append((rel, node.lineno, src))
                elif isinstance(val, ast.Constant) and val.value is False:
                    status = "shell=False (explicit)"
                else:
                    status = "shell=<non-constant>  <-- VIOLATION (unprovable)"
                    shell_true.append((rel, node.lineno, src))
            call_sites.append((rel, node.lineno, "%s :: %s" % (func, status)))
    # Rust: Command::new sites; sh / cmd are the shell equivalents.
    rust_shell = []
    for rel, _path, text in files:
        if not rel.endswith(".rs"):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = re.search(r'Command::new\(\s*"([^"]+)"', line)
            if m:
                prog = m.group(1)
                if prog in ("sh", "bash", "cmd", "powershell"):
                    rust_shell.append((rel, i, line.strip()))
                    shell_true.append((rel, i, line.strip()))
                else:
                    call_sites.append(
                        (rel, i, "Command::new(%r) (no shell)" % prog))
    # Shell launcher(s) at repo root: eval / curl / wget would be a finding.
    # Only the extensionless launcher (and *.sh) are shell scripts; other
    # root files (.gitignore, .toml, ...) are not.
    for rel, _path, text in files:
        if rel != "instructionroot" and not rel.endswith(".sh"):
            continue
        bad = False
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\beval\b|\bcurl\b|\bwget\b", line):
                shell_true.append((rel, i, line.strip()))
                bad = True
        call_sites.append((rel, 0, "shell launcher: execs python3 -m instructionroot "
                          "only (eval/curl/wget found: %s)" % bad))
    return shell_true, call_sites, rust_shell


# ---------------------------------------------------------------------------
# 2. network
# ---------------------------------------------------------------------------

def check_network(files):
    """Return (runtime_count, prod_findings, test_findings, other_findings,
    web_accepted_local_fetches).

    runtime_count counts production-scope network imports/calls only.
    Test/support findings are returned separately, never silently clean.
    """
    prod, test, other = [], [], []
    for rel, _path, text in files:
        if not rel.endswith(".py"):
            continue
        bucket = {"production": prod, "test": test, "other": other}[scope_of(rel)]
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_network_module(alias.name):
                        bucket.append((rel, node.lineno,
                                       "import %s" % alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module and _is_network_module(node.module):
                    bucket.append((rel, node.lineno,
                                   "from %s import ..." % node.module))
            elif isinstance(node, ast.Call):
                func = _dotted(node.func)
                if any(func == p or func.startswith(p)
                       for p in NETWORK_CALL_PREFIXES):
                    bucket.append((rel, node.lineno, "call %s(...)" % func))
                # Subprocess argv that is a string-list literal: a network
                # tool (curl/wget/...) as argv[0] would be a network call.
                # (String lists such as the s0 gate's own NETWORK_TOKENS
                # are data, not argv, and are not flagged by this.)
                if func in SHELL_FUNCS and node.args and isinstance(node.args[0], ast.List):
                    argv = [e.value for e in node.args[0].elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                    for el in argv:
                        if el.split("/")[-1] in ("curl", "wget", "nc", "telnet",
                                                 "ftp", "ssh", "scp"):
                            bucket.append((rel, node.lineno,
                                           "subprocess argv network tool: %s" % el))
    # Rust sources + Cargo manifests.
    for rel, _path, text in files:
        if rel.endswith(".rs"):
            for i, line in enumerate(text.splitlines(), 1):
                for rx in RUST_NETWORK_RES:
                    if rx.search(line):
                        prod.append((rel, i, "rust network token: %s"
                                     % line.strip()[:100]))
        elif rel.endswith("Cargo.toml"):
            try:
                import tomllib
                deps = tomllib.loads(text).get("dependencies", {})
            except Exception:
                deps = {}
            for dep in sorted(deps):
                if dep in NETWORK_CRATES:
                    prod.append((rel, 0, "network crate dependency: %s" % dep))
        elif rel.endswith("Cargo.lock"):
            for name in sorted(NETWORK_CRATES):
                if re.search(r'^name = "%s"$' % re.escape(name), text,
                             flags=re.M):
                    prod.append((rel, 0, "network crate in lockfile: %s" % name))
    # Web dashboard: real external loads only. A fetch() of a relative
    # file is the dashboard's local same-origin receipt load (plan §14:
    # "no external network"), recorded as accepted, not a violation.
    web_accepted = []
    for rel, _path, text in files:
        if not (rel.endswith(".js") or rel.endswith(".html")):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\bfetch\s*\(", line):
                if re.search(r"""fetch\s*\(\s*["'](?:https?:)?//""", line):
                    prod.append((rel, i, "web network call: %s"
                                 % line.strip()[:100]))
                else:
                    web_accepted.append((rel, i, "local same-origin fetch "
                                         "(relative receipt file, no external URL): %s"
                                         % line.strip()[:100]))
            for rx in WEB_NETWORK_RES[1:]:
                if rx.search(line):
                    prod.append((rel, i, "web network call: %s"
                                 % line.strip()[:100]))
    runtime = len(prod)
    return runtime, prod, test, other, web_accepted


def _is_network_module(name: str) -> bool:
    for mod in NETWORK_MODULES:
        if name == mod or name.startswith(mod + "."):
            return True
    return False


# ---------------------------------------------------------------------------
# 3. telemetry
# ---------------------------------------------------------------------------

def check_telemetry(files):
    """Return list of telemetry findings (imports or calls, real code)."""
    findings = []
    for rel, _path, text in files:
        if rel.endswith((".py", ".rs", ".toml", ".json", ".js")):
            if rel.endswith(".py"):
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            top = alias.name.split(".")[0]
                            if top in TELEMETRY_MODULES:
                                findings.append((rel, node.lineno,
                                                 "import %s" % alias.name))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module.split(".")[0] in TELEMETRY_MODULES:
                            findings.append((rel, node.lineno,
                                             "from %s import ..." % node.module))
    for rel, _path, text in files:
        if rel.endswith((".py", ".rs", ".js")):
            spans = _py_string_comment_spans(text) if rel.endswith(".py") else None
            for i, line in enumerate(text.splitlines(), 1):
                m = TELEMETRY_CALL_RE.search(line)
                if not m:
                    continue
                cls = (_classify_py(spans, i, m.start())
                       if spans is not None else _classify_line(rel, line, m.start()))
                if cls == "code":
                    findings.append((rel, i, "telemetry call: %s" % line.strip()[:100]))
    return findings


# ---------------------------------------------------------------------------
# 4. secrets
# ---------------------------------------------------------------------------

def _check_secret_value(value: str, rel: str, line_no: int, where: str):
    """Return a finding tuple, or None when the value is a placeholder."""
    lowered = value.lower()
    if any(m in lowered for m in PLACEHOLDER_MARKERS):
        return None
    return (rel, line_no, "%s: candidate secret (%s... len=%d)"
            % (where, value[:12], len(value)))


def check_secrets(files):
    """Return (leak_count, findings, accepted_placeholders).

    Known-pattern scan is repo-wide; the entropy scan covers fixture
    files, expected receipts, demo receipts and Python string literals.
    leak_count counts findings in fixture/receipt scope (the number the
    plan requires); any finding anywhere is also listed.
    """
    findings = []
    accepted = []
    fixture_prefixes = ("01_s0/fixtures/", "fixtures/", "01_s0/expected/")
    for rel, _path, text in files:
        for i, line in enumerate(text.splitlines(), 1):
            for rx, kind in SECRET_RES:
                m = rx.search(line)
                if m:
                    findings.append((rel, i, "known pattern %s: %s"
                                     % (kind, m.group(0)[:12] + "...")))
            m = ASSIGNMENT_RE.search(line)
            if m:
                hit = _check_secret_value(m.group(2), rel, i,
                                          "assignment %s=" % m.group(1))
                if hit:
                    findings.append(hit)
                else:
                    accepted.append((rel, i, "assignment %s= placeholder value"
                                     % m.group(1)))
    # Entropy scan: Python string literals.
    for rel, _path, text in files:
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = node.value
                if "\\" in s:
                    continue  # regex-pattern source, not a secret value
                if len(s) >= ENTROPY_MIN_LEN and _shannon(s) >= ENTROPY_MIN_BITS:
                    reason = _entropy_allowlisted(s)
                    if reason is None:
                        findings.append((rel, node.lineno,
                                         "high-entropy literal (%s... len=%d entropy=%.2f)"
                                         % (s[:12], len(s), _shannon(s))))
    # Entropy scan: JSON string values in receipt/fixture scope + fixture .md tokens.
    for rel, _path, text in files:
        in_scope = (rel.startswith(fixture_prefixes)
                    or (rel.startswith("web/") and rel.endswith(".json")))
        if not in_scope:
            continue
        if rel.endswith(".json"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            for s in _walk_json_strings(data):
                if len(s) >= ENTROPY_MIN_LEN and _shannon(s) >= ENTROPY_MIN_BITS:
                    if _entropy_allowlisted(s) is None:
                        findings.append((rel, 0, "high-entropy receipt/fixture value "
                                         "(%s... len=%d entropy=%.2f)"
                                         % (s[:12], len(s), _shannon(s))))
        elif rel.endswith(".md"):
            for i, line in enumerate(text.splitlines(), 1):
                for tok in re.split(r"\s+", line):
                    tok = tok.strip("`\"'.,;:()[]{}<>")
                    if len(tok) >= ENTROPY_MIN_LEN and _shannon(tok) >= ENTROPY_MIN_BITS:
                        if _entropy_allowlisted(tok) is None:
                            findings.append((rel, i, "high-entropy fixture token "
                                             "(%s... len=%d entropy=%.2f)"
                                             % (tok[:12], len(tok), _shannon(tok))))
    leak_count = sum(1 for (rel, _l, _m) in findings
                     if rel.startswith(fixture_prefixes)
                     or (rel.startswith("web/") and rel.endswith(".json")))
    return leak_count, findings, accepted


def _walk_json_strings(data):
    if isinstance(data, str):
        yield data
    elif isinstance(data, dict):
        for v in data.values():
            yield from _walk_json_strings(v)
    elif isinstance(data, list):
        for v in data:
            yield from _walk_json_strings(v)


# ---------------------------------------------------------------------------
# 5. raw-text sweep (second net; every hit classified, none silent)
# ---------------------------------------------------------------------------

def raw_sweep(files):
    """Return (code_hits, accepted_hits).

    code_hits: raw token hits in real code — these count towards the
    numbers (a shell=True in code would land here as well as in AST).
    accepted_hits: hits inside string literals / comments / docs / data,
    each with its reason.
    """
    code_hits = []
    accepted = []
    for rel, _path, text in files:
        spans = _py_string_comment_spans(text) if rel.endswith(".py") else None
        for kind, rx in RAW_TOKENS:
            for m in rx.finditer(text):
                start = m.start()
                line_no = text.count("\n", 0, start) + 1
                line_start = text.rfind("\n", 0, start) + 1
                col = start - line_start
                line = text.splitlines()[line_no - 1] if line_no <= len(text.splitlines()) else ""
                if spans is not None:
                    cls = _classify_py(spans, line_no, col)
                    reason = ("check-pattern string literal (the pattern being "
                              "searched for), not a call" if cls == "string-or-comment"
                              else "comment describing the rule" if cls == "comment"
                              else None)
                else:
                    cls = _classify_line(rel, line, col)
                    reason = {
                        "string-literal": "string literal (check-pattern data), not code",
                        "comment": "comment describing the rule",
                        "documentation-prose": "documentation prose describing the rule",
                        "data-value": "JSON data value, not executed code",
                    }.get(cls)
                entry = (rel, line_no, "%s token %r :: %s"
                         % (kind, m.group(0)[:40], line.strip()[:100]))
                if cls == "code":
                    code_hits.append(entry)
                else:
                    accepted.append(entry + ("[%s: %s]"
                                             % (cls, reason or "not code"),))
    return code_hits, accepted


# ---------------------------------------------------------------------------
# 6. license / packaging
# ---------------------------------------------------------------------------

def check_license_package():
    """Return (ok, notes, version_info)."""
    notes = []
    ok = True
    lic = ROOT / "LICENSE"
    if not lic.is_file():
        ok = False
        notes.append("LICENSE file MISSING")
    else:
        text = lic.read_text(encoding="utf-8", errors="replace")
        if "MIT License" not in text:
            ok = False
            notes.append("LICENSE does not contain 'MIT License'")
        if "Permission is hereby granted, free of charge" not in text:
            ok = False
            notes.append("LICENSE missing the MIT grant clause")
        else:
            notes.append("LICENSE present: MIT License, grant clause present")
    # CLI version is the release version (IMPLEMENTATION_PLAN §27: 1.0.0).
    cli_text = (ROOT / "02_src/instructionroot/cli.py").read_text(encoding="utf-8")
    m = re.search(r'CLI_VERSION\s*=\s*"([^"]+)"', cli_text)
    cli_version = m.group(1) if m else None
    notes.append("CLI_VERSION=%s" % cli_version)
    pyproject = ROOT / "pyproject.toml"
    version_info = {"cli_version": cli_version}
    if not pyproject.is_file():
        ok = False
        notes.append("pyproject.toml MISSING")
        return ok, notes, version_info
    import tomllib
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - report, do not crash
        ok = False
        notes.append("pyproject.toml unparsable: %s" % exc)
        return ok, notes, version_info
    proj = data.get("project", {})
    name = proj.get("name")
    version = proj.get("version")
    requires = proj.get("requires-python", "")
    scripts = proj.get("scripts", {})
    lic_field = proj.get("license")
    lic_text = lic_field if isinstance(lic_field, str) else (
        lic_field.get("text", "") if isinstance(lic_field, dict) else "")
    version_info.update({"name": name, "version": version,
                         "license": lic_text, "requires_python": requires,
                         "scripts": scripts,
                         "dependencies": proj.get("dependencies", [])})
    if name != "instructionroot":
        ok = False
        notes.append("pyproject name=%r (want 'instructionroot')" % name)
    else:
        notes.append("pyproject name=instructionroot")
    if version != cli_version or version is None:
        ok = False
        notes.append("pyproject version=%r != CLI_VERSION=%r"
                     % (version, cli_version))
    else:
        notes.append("pyproject version=%s (== CLI_VERSION)" % version)
    if "MIT" not in lic_text:
        ok = False
        notes.append("pyproject license=%r (want MIT)" % lic_text)
    else:
        notes.append("pyproject license=MIT")
    if not requires or not re.search(r">=\s*3\.12", requires):
        ok = False
        notes.append("requires-python=%r (want >=3.12)" % requires)
    else:
        notes.append("requires-python=%s" % requires)
    entry = scripts.get("instructionroot")
    if entry != "instructionroot.cli:main":
        ok = False
        notes.append("console entry point=%r (want 'instructionroot.cli:main')"
                     % entry)
    else:
        notes.append("console entry point: instructionroot = instructionroot.cli:main")
        sys.path.insert(0, str(ROOT / "02_src"))
        try:
            import importlib
            mod = importlib.import_module("instructionroot.cli")
            target = getattr(mod, "main", None)
            if callable(target):
                notes.append("entry-point target instructionroot.cli:main resolves (callable)")
            else:
                ok = False
                notes.append("entry-point target instructionroot.cli:main NOT callable")
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            ok = False
            notes.append("entry-point target unresolvable: %s" % exc)
        finally:
            sys.path.pop(0)
    if proj.get("dependencies"):
        ok = False
        notes.append("dependencies=%r (want stdlib-only: [])"
                     % (proj.get("dependencies"),))
    else:
        notes.append("dependencies=[] (stdlib only)")
    build = data.get("build-system", {})
    if "setuptools" not in " ".join(build.get("requires", [])):
        ok = False
        notes.append("build-system requires=%r (want setuptools)"
                     % (build.get("requires"),))
    else:
        notes.append("build-system: setuptools")
    cargo = ROOT / "03_oracle/rust/Cargo.toml"
    if cargo.is_file():
        ctext = cargo.read_text(encoding="utf-8")
        if 'license = "MIT"' in ctext:
            notes.append("oracle Cargo.toml license=MIT")
        else:
            ok = False
            notes.append("oracle Cargo.toml license != MIT")
    else:
        notes.append("oracle Cargo.toml missing (oracle not present?)")
    return ok, notes, version_info


# ---------------------------------------------------------------------------
# 7. receipt privacy (PROJECT_BOOK §18.1/§18.2 — book more specific than plan)
# ---------------------------------------------------------------------------

def check_receipt_privacy(files):
    """Return (ok, notes)."""
    notes = []
    ok = True
    checked = 0
    for rel, _path, text in files:
        in_scope = False
        for glob in RECEIPT_GLOBS:
            if Path(rel).match(glob):
                in_scope = True
        if not in_scope:
            continue
        checked += 1
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            ok = False
            notes.append("%s: unparsable JSON: %s" % (rel, exc))
            continue
        bad_keys = set()

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in FORBIDDEN_RECEIPT_KEYS:
                        bad_keys.add(k)
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)
            elif isinstance(obj, str) and "\n" in obj:
                bad_keys.add("<multiline-string-value>")

        walk(data)
        if bad_keys:
            ok = False
            notes.append("%s: forbidden receipt content: %s"
                         % (rel, sorted(bad_keys)))
    notes.append("receipt JSON files checked: %d (no content/username/commit-message keys, no multiline values)"
                 % checked)
    receipt_py = ROOT / "02_src/instructionroot/receipt.py"
    if receipt_py.is_file():
        rtext = receipt_py.read_text(encoding="utf-8")
        # Source fields live in _SOURCE_REQUIRED / _SOURCE_ALLOWED
        # frozensets (not a _SOURCE_FIELDS tuple).
        m = re.search(r"_SOURCE_ALLOWED\s*:\s*frozenset\[str\]\s*=\s*_SOURCE_REQUIRED\s*\|\s*frozenset\(\{(.*?)\}\)",
                      rtext, flags=re.S)
        m2 = re.search(r"_SOURCE_REQUIRED\s*:\s*frozenset\[str\]\s*=\s*frozenset\(\{(.*?)\}\)",
                       rtext, flags=re.S)
        fields = set()
        for mm in (m, m2):
            if mm:
                fields |= set(re.findall(r'"([^"]+)"', mm.group(1)))
        if fields and not (set(FORBIDDEN_RECEIPT_KEYS) & fields):
            notes.append("receipt.py source fields %s: no content field (paths/hashes/git/trust only)"
                         % sorted(fields))
        else:
            ok = False
            notes.append("receipt.py source-field check FAILED or sets not found (fields=%s)"
                         % sorted(fields))
    cli_py = ROOT / "02_src/instructionroot/cli.py"
    if cli_py.is_file():
        ctext = cli_py.read_text(encoding="utf-8")
        if "redact_home" in ctext:
            notes.append("cli.py uses redact_home ($HOME shown as <HOME>/...)")
        else:
            ok = False
            notes.append("cli.py does NOT use redact_home")
    return ok, notes


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    files = iter_text_files()
    print("P028 T012 security_static_check")
    print("root=%s" % ROOT)
    print("files_scanned=%d" % len(files))

    shell_true, call_sites, _rust_shell = check_shell(files)
    runtime, net_prod, net_test, net_other, web_accepted = check_network(files)
    telemetry = check_telemetry(files)
    leaks, secret_findings, secret_accepted = check_secrets(files)
    raw_code, raw_accepted = raw_sweep(files)
    # A raw code hit is a real code occurrence the AST pass should also
    # have caught; count it if the AST pass missed it (defence in depth).
    extra_shell = [h for h in raw_code if h[2].startswith("shell")]
    extra_net = [h for h in raw_code if h[2].startswith("network")]
    extra_tel = [h for h in raw_code if h[2].startswith("telemetry")]
    shell_total = len(shell_true) + len(extra_shell)
    net_total = runtime + len(extra_net)
    tel_total = len(telemetry) + len(extra_tel)
    lic_ok, lic_notes, _ver = check_license_package()
    priv_ok, priv_notes = check_receipt_privacy(files)

    print()
    print("== 1. shell ==")
    print("subprocess/os-spawn/eval/exec call sites: %d" % len(call_sites))
    for rel, line_no, desc in sorted(call_sites):
        print("  %s:%d %s" % (rel, line_no, desc))
    print("shell=True violations (AST): %d" % len(shell_true))
    for rel, line_no, src in sorted(shell_true):
        print("  VIOLATION %s:%d %s" % (rel, line_no, src))
    print("shell=True violations (raw code sweep): %d" % len(extra_shell))
    for rel, line_no, desc in sorted(extra_shell):
        print("  VIOLATION %s:%d %s" % (rel, line_no, desc))

    print()
    print("== 2. network ==")
    print("production network findings: %d" % len(net_prod))
    for rel, line_no, desc in sorted(net_prod):
        print("  %s:%d %s" % (rel, line_no, desc))
    print("test/support-only network findings (listed separately, not counted): %d"
          % (len(net_test) + len(net_other)))
    for rel, line_no, desc in sorted(net_test + net_other):
        print("  TEST/SUPPORT %s:%d %s" % (rel, line_no, desc))
    print("accepted local same-origin web fetches (relative receipt file): %d"
          % len(web_accepted))
    for rel, line_no, desc in sorted(web_accepted):
        print("  ACCEPTED %s:%d %s" % (rel, line_no, desc))
    print("network violations (raw code sweep): %d" % len(extra_net))
    for rel, line_no, desc in sorted(extra_net):
        print("  VIOLATION %s:%d %s" % (rel, line_no, desc))

    print()
    print("== 3. telemetry ==")
    print("telemetry findings: %d" % tel_total)
    for rel, line_no, desc in sorted(telemetry):
        print("  %s:%d %s" % (rel, line_no, desc))
    for rel, line_no, desc in sorted(extra_tel):
        print("  VIOLATION(raw) %s:%d %s" % (rel, line_no, desc))

    print()
    print("== 4. secrets in receipts/fixtures ==")
    print("secret findings (all scopes): %d" % len(secret_findings))
    for rel, line_no, desc in sorted(secret_findings):
        print("  %s:%d %s" % (rel, line_no, desc))
    print("accepted placeholder assignments: %d" % len(secret_accepted))
    for rel, line_no, desc in sorted(secret_accepted):
        print("  ACCEPTED %s:%d %s" % (rel, line_no, desc))

    print()
    print("== 5. raw-text sweep: accepted hits (string/comment/docs/data) ==")
    print("accepted raw hits: %d" % len(raw_accepted))
    for rel, line_no, desc, why in sorted(raw_accepted):
        print("  ACCEPTED %s:%d %s %s" % (rel, line_no, desc, why))

    print()
    print("== 6. license / packaging ==")
    for note in lic_notes:
        print("  %s" % note)
    print("license_package_ok=%s" % ("true" if lic_ok else "false"))

    print()
    print("== 7. receipt privacy (PROJECT_BOOK §18.1/§18.2) ==")
    for note in priv_notes:
        print("  %s" % note)
    print("receipt_privacy_ok=%s" % ("true" if priv_ok else "false"))

    print()
    print("shell_true=%d" % shell_total)
    print("network_runtime=%d" % net_total)
    print("telemetry=%d" % tel_total)
    print("secret_fixture_leaks=%d" % leaks)
    passed = (shell_total == 0 and net_total == 0 and tel_total == 0
              and leaks == 0 and lic_ok and priv_ok)
    print("RESULT=%s" % ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
