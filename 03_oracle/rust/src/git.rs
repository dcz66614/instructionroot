//! Read-only Git metadata — independent Rust implementation of the P028
//! contract (PROJECT_BOOK.md §13.3; receipt_schema.json `git` object).
//!
//! Only these four Git invocations are ever issued, each as an argument
//! list through `std::process::Command` (no shell):
//!
//! * `git rev-parse --show-toplevel`
//! * `git ls-files --error-unmatch -- <path>`
//! * `git status --porcelain=v1 -- <path>`
//! * `git log -1 --format=%H -- <path>`
//!
//! No other git subcommand can be issued from this module: `_run_git`
//! refuses any argument list outside the allowlist. This module never
//! writes to a repository, never contacts a remote, never spawns a shell.
//!
//! Semantics (mirroring the contract and the coordinator rulings):
//! * `head_commit` is the SHA returned by `git log -1` for the path,
//!   i.e. the most recent commit touching that path; `None` for
//!   untracked files, for files in a repository with no commits yet,
//!   and for paths outside any repository.
//! * `modified` is true only for a *tracked* file whose
//!   `git status --porcelain` output for the path is non-empty
//!   (working-tree or staged difference from HEAD). An untracked file
//!   shows up in `git status` as `??` but is NOT modified. A tracked
//!   file deleted from the working tree does show a status entry and
//!   therefore counts as modified. An already-staged-but-uncommitted
//!   new file IS modified (it differs from HEAD) — and it is tracked,
//!   because `git ls-files` matches it once staged.
//! * Paths are passed to Git as a single argument after `--` and
//!   relative to the repository root, so names with spaces, dashes or
//!   non-ASCII bytes (Q3: Unicode passed through byte-for-byte) cannot
//!   be mistaken for options.

use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::Duration;

use crate::paths::{is_windows_style_path, normalize_windows_path, normpath_posix};

const GIT_TIMEOUT: Duration = Duration::from_secs(30);

/// Git metadata for one path (receipt `git` object + diagnostics).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GitState {
    pub repo: Option<String>,
    pub tracked: bool,
    pub modified: bool,
    pub head_commit: Option<String>,
    pub is_git_repo: bool,
    pub error: Option<String>,
}

impl GitState {
    fn not_in_repo() -> Self {
        GitState {
            repo: None,
            tracked: false,
            modified: false,
            head_commit: None,
            is_git_repo: false,
            error: None,
        }
    }
}

struct GitOutput {
    success: bool,
    stdout: String,
}

fn is_allowed(argv: &[&str]) -> bool {
    if argv == ["rev-parse", "--show-toplevel"] {
        return true;
    }
    if argv.len() == 4 && argv[..3] == ["ls-files", "--error-unmatch", "--"] {
        return true;
    }
    if argv.len() == 4 && argv[..3] == ["status", "--porcelain=v1", "--"] {
        return true;
    }
    if argv.len() == 5 && argv[..4] == ["log", "-1", "--format=%H", "--"] {
        return true;
    }
    false
}

#[derive(Debug)]
enum RunError {
    NotAvailable,
    Timeout,
}

/// Run one allowlisted Git command; `Ok(None)` when Git cannot run
/// (binary missing); `Err(Timeout)` when the invocation exceeds the
/// timeout. Panics on a non-allowlisted argument list (programmer
/// error — this module never builds one).
fn run_git(argv: &[&str], cwd: &str) -> Result<Option<GitOutput>, RunError> {
    assert!(is_allowed(argv), "refused non-allowlisted git invocation: {argv:?}");
    let mut child = match Command::new("git")
        .args(argv)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(_) => return Ok(None),
    };
    let mut stdout = child.stdout.take();
    let mut stderr = child.stderr.take();
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut out_buf = Vec::new();
        let mut err_buf = Vec::new();
        if let Some(mut s) = stdout.take() {
            let _ = s.read_to_end(&mut out_buf);
        }
        if let Some(mut s) = stderr.take() {
            let _ = s.read_to_end(&mut err_buf);
        }
        let status = child.wait();
        let _ = tx.send((status, out_buf, err_buf));
    });
    match rx.recv_timeout(GIT_TIMEOUT) {
        Ok((status, out_buf, _err_buf)) => {
            let ok = status.map(|s| s.success()).unwrap_or(false);
            Ok(Some(GitOutput {
                success: ok,
                stdout: String::from_utf8_lossy(&out_buf).into_owned(),
            }))
        }
        Err(_) => {
            // Best-effort kill of the wedged child is impossible here
            // (the child handle moved into the waiter thread); the
            // waiter thread exits when the child does. Record the
            // timeout and fail closed.
            Err(RunError::Timeout)
        }
    }
}

/// Normalise a path spelling for comparison inside this module: a
/// Windows drive / UNC spelling becomes its normalised `C:/...` (or
/// `//server/share/...`) form; anything else goes through
/// `normpath_posix` unchanged. Pure-string, host-independent — the
/// same rule `paths::normalize_windows_path` applies on every host,
/// so a drive spelling is recognised even where the host would not
/// treat it as absolute (Linux unit tests run here; the real Windows
/// host path is exercised by the WIN-JUNCTION runner pack).
fn normalise_spelling(p: &str) -> String {
    if is_windows_style_path(p) {
        normalize_windows_path(p).unwrap_or_else(|_| p.replace('\\', "/"))
    } else {
        normpath_posix(p)
    }
}

fn abspath(path: &str) -> String {
    // FIX-R3 (C): a Windows drive spelling (`C:/...`, `C:\...`) is
    // absolute too. The old code only recognised a leading `/`, so on
    // a Windows host `C:/...` was treated as relative and prefixed
    // with the process cwd (`C:\p028-tools/C:/...`), `relative_to_repo`
    // then returned `None`, and every source came back `GIT_UNTRACKED`
    // (V2 evidence E08-6). `Path::is_absolute` alone is not enough:
    // on Linux it says `C:/...` is relative, and the unit tests for
    // this fix run on Linux — hence the host-independent drive check
    // above (same rule as `paths::normalize_windows_path`). A bare
    // drive-relative spelling (`C:foo`) is NOT absolute and still
    // falls through to the cwd join, exactly as before.
    if is_windows_style_path(path) {
        return normalise_spelling(path);
    }
    if path.starts_with('/') {
        normpath_posix(path)
    } else {
        let cwd = std::env::current_dir()
            .map(|p| p.to_string_lossy().into_owned())
            .unwrap_or_else(|_| "/".to_string());
        // On a Windows host the process cwd is a backslash spelling
        // (`C:\...`); normalise it to `C:/...` before joining, or
        // the joined string keeps backslashes and `relative_to_repo`
        // (which splits on `/`) can never match it. A relative
        // spelling joined under a drive cwd is a Windows path too,
        // so its backslashes become `/` as well. On a POSIX host
        // neither branch fires and the join is byte-identical to
        // before.
        if is_windows_style_path(&cwd) {
            let cwd = normalize_windows_path(&cwd).unwrap_or(cwd);
            let joined = format!("{cwd}/{path}").replace('\\', "/");
            normpath_posix(&joined)
        } else {
            normpath_posix(&format!("{cwd}/{path}"))
        }
    }
}

fn nearest_existing_dir(path: &str) -> String {
    let mut candidate = abspath(path);
    // A bare drive spelling (`C:`) is the drive root: spell it
    // `C:/`, or the parent walk below would fall through to `/`.
    if candidate.len() == 2
        && candidate.as_bytes()[0].is_ascii_alphabetic()
        && candidate.as_bytes()[1] == b':'
    {
        candidate.push('/');
    }
    loop {
        if std::path::Path::new(&candidate).is_dir() {
            return candidate;
        }
        let parent = match candidate.rfind('/') {
            Some(0) => "/".to_string(),
            Some(i) => candidate[..i].to_string(),
            None => "/".to_string(),
        };
        if parent == candidate {
            return candidate;
        }
        candidate = parent;
    }
}

/// Return the top level of the Git repository containing `path`.
/// `None` when `path` is not inside a Git repository, when the `git`
/// binary cannot be run, or when Git does not answer in time.
pub fn find_repo_root(path: &str) -> Option<String> {
    let dir = nearest_existing_dir(path);
    match run_git(&["rev-parse", "--show-toplevel"], &dir) {
        Ok(Some(out)) if out.success => {
            let root = out.stdout.trim().to_string();
            if root.is_empty() {
                None
            } else {
                // FIX-R3 (C): git prints a drive top level as
                // `C:/...`; keep that spelling (a backslash spelling
                // would never match in `relative_to_repo`, which
                // splits on `/`). On a POSIX host this is a no-op.
                Some(normalise_spelling(&root))
            }
        }
        _ => None,
    }
}

/// `path` relative to `repo`, or `None` when it lies outside the
/// repository (`..` escape).
fn relative_to_repo(path: &str, repo: &str) -> Option<String> {
    let abs = abspath(path);
    let repo_norm = normalise_spelling(repo);
    let path_parts: Vec<&str> = abs.split('/').filter(|c| !c.is_empty()).collect();
    let repo_parts: Vec<&str> = repo_norm.split('/').filter(|c| !c.is_empty()).collect();
    let mut common = 0;
    while common < path_parts.len()
        && common < repo_parts.len()
        && path_parts[common] == repo_parts[common]
    {
        common += 1;
    }
    let mut rel: Vec<String> = Vec::new();
    for _ in common..repo_parts.len() {
        rel.push("..".to_string());
    }
    for part in &path_parts[common..] {
        rel.push(part.to_string());
    }
    if rel.is_empty() {
        return Some(".".to_string());
    }
    if rel[0] == ".." {
        return None;
    }
    Some(rel.join("/"))
}

/// Return the [`GitState`] for `path`.
///
/// * `repo_root` may supply a known repository top level; otherwise it
///   is discovered with [`find_repo_root`]. A path outside the supplied
///   repository is reported as not in a repository (`repo=None`).
/// * Never fails for a non-git directory, a missing path, an untracked
///   file, or a repository with no commits yet — those are ordinary
///   states, reported in the returned record.
pub fn get_git_state(path: &str, repo_root: Option<&str>) -> GitState {
    let repo: String = match repo_root {
        Some(root) => {
            // FIX-R3 (C/D): keep the `C:/...` spelling here too, so
            // the receipt `git.repo` field never carries a backslash
            // spelling on Windows.
            let repo_text = normalise_spelling(root);
            if relative_to_repo(path, &repo_text).is_none() {
                return GitState::not_in_repo();
            }
            repo_text
        }
        None => match find_repo_root(path) {
            Some(r) => r,
            None => return GitState::not_in_repo(),
        },
    };
    let rel = match relative_to_repo(path, &repo) {
        Some(r) => r,
        None => return GitState::not_in_repo(),
    };

    let ls = run_git(&["ls-files", "--error-unmatch", "--", &rel], &repo);
    let status = run_git(&["status", "--porcelain=v1", "--", &rel], &repo);
    let log = run_git(&["log", "-1", "--format=%H", "--", &rel], &repo);
    if matches!(ls, Err(RunError::Timeout))
        || matches!(status, Err(RunError::Timeout))
        || matches!(log, Err(RunError::Timeout))
    {
        return GitState {
            repo: Some(repo),
            tracked: false,
            modified: false,
            head_commit: None,
            is_git_repo: false,
            error: Some("GIT_TIMEOUT".to_string()),
        };
    }
    let (ls, status, log) = match (ls, status, log) {
        (Ok(Some(a)), Ok(Some(b)), Ok(Some(c))) => (a, b, c),
        _ => {
            return GitState {
                repo: Some(repo),
                tracked: false,
                modified: false,
                head_commit: None,
                is_git_repo: false,
                error: Some("GIT_NOT_AVAILABLE".to_string()),
            };
        }
    };

    let tracked = ls.success;
    let modified = tracked && !status.stdout.trim().is_empty();
    let mut head_commit: Option<String> = None;
    if log.success {
        if let Some(first) = log.stdout.lines().next() {
            let sha = first.trim();
            if sha.len() == 40 && sha.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()) {
                head_commit = Some(sha.to_string());
            }
        }
    }
    GitState {
        repo: Some(repo),
        tracked,
        modified,
        head_commit,
        is_git_repo: true,
        error: None,
    }
}

/// Map a Rust I/O error to the Python exception class name the
/// production implementation reports for unreadable files.
pub fn io_error_name(err: &std::io::Error) -> &'static str {
    use std::io::ErrorKind;
    match err.kind() {
        ErrorKind::PermissionDenied => "PermissionError",
        ErrorKind::NotFound => "FileNotFoundError",
        _ => "OSError",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowlist() {
        assert!(is_allowed(&["rev-parse", "--show-toplevel"]));
        assert!(is_allowed(&["ls-files", "--error-unmatch", "--", "x"]));
        assert!(is_allowed(&["status", "--porcelain=v1", "--", "x"]));
        assert!(is_allowed(&["log", "-1", "--format=%H", "--", "x"]));
        assert!(!is_allowed(&["fetch"]));
        assert!(!is_allowed(&["status", "--porcelain=v1", "x"]));
        assert!(!is_allowed(&["log", "-1", "--format=%H"]));
    }

    #[test]
    fn relpath() {
        assert_eq!(
            relative_to_repo("/repo/a/b.md", "/repo"),
            Some("a/b.md".to_string())
        );
        assert_eq!(relative_to_repo("/repo", "/repo"), Some(".".to_string()));
        assert_eq!(relative_to_repo("/other/x", "/repo"), None);
        assert_eq!(relative_to_repo("/repo2/x", "/repo"), None);
    }

    // FIX-R3 (C): a Windows drive spelling is absolute — `C:/...`
    // and `C:\...` alike — and must NOT be prefixed with the process
    // cwd (V2: `abspath("C:/p028-src-v2/...")` became
    // `C:\p028-tools/C:/p028-src-v2/...`, so every source came back
    // `GIT_UNTRACKED`). These tests run on Linux, where
    // `Path::is_absolute` would still call a drive spelling
    // relative — the drive check here is deliberately
    // host-independent (pure-string, same rule as
    // `paths::normalize_windows_path`).
    #[test]
    fn abspath_recognises_drive_spellings() {
        // POSIX absolute: unchanged behaviour.
        assert_eq!(abspath("/repo/a/../b.md"), "/repo/b.md");
        assert_eq!(abspath("/"), "/");
        // Drive absolute, both separator spellings, normalised to
        // the `C:/...` form.
        assert_eq!(abspath("C:/repo/AGENTS.md"), "C:/repo/AGENTS.md");
        assert_eq!(abspath("C:\\repo\\AGENTS.md"), "C:/repo/AGENTS.md");
        assert_eq!(abspath("D:/Downloads/x.md"), "D:/Downloads/x.md");
        // `..` clamps at the drive root, exactly as
        // `normalize_windows_path` does.
        assert_eq!(abspath("C:/repo/../shared/x.md"), "C:/shared/x.md");
        assert_eq!(abspath("C:/../x.md"), "C:/x.md");
        // A bare drive-relative spelling (`C:foo`, no separator)
        // is NOT absolute: it still takes the cwd join, as before.
        assert_ne!(abspath("C:foo"), "C:foo");
        assert!(abspath("C:foo").ends_with("/C:foo"));
        // Relative: joined under the process cwd, as before.
        let rel = abspath("rel/path.md");
        assert!(rel.ends_with("/rel/path.md"), "{rel}");
        assert!(rel.starts_with('/'), "{rel}");
    }

    #[test]
    fn relpath_drive_spellings() {
        assert_eq!(
            relative_to_repo("C:/repo/a/b.md", "C:/repo"),
            Some("a/b.md".to_string())
        );
        // Backslash spellings on either side normalise to `C:/...`
        // before the component comparison.
        assert_eq!(
            relative_to_repo("C:\\repo\\a\\b.md", "C:/repo"),
            Some("a/b.md".to_string())
        );
        assert_eq!(
            relative_to_repo("C:/repo/a/b.md", "C:\\repo"),
            Some("a/b.md".to_string())
        );
        assert_eq!(
            relative_to_repo("C:/repo", "C:/repo"),
            Some(".".to_string())
        );
        assert_eq!(relative_to_repo("C:/other/x", "C:/repo"), None);
        assert_eq!(relative_to_repo("D:/repo/x", "C:/repo"), None);
        // A drive path is never inside a POSIX repo, and vice versa.
        assert_eq!(relative_to_repo("C:/repo/x", "/repo"), None);
        assert_eq!(relative_to_repo("/repo/x", "C:/repo"), None);
    }
}
