//! Canonical path handling — independent Rust implementation of the
//! P028 contract (PROJECT_BOOK.md §13.1 algorithm A; receipt_schema.json
//! `canonical_path` / `resolved_path`; coordinator ruling Q1/Q3).
//!
//! * `canonical_path` — the *lexical* canonical path: absolute, `..` / `.`
//!   normalised, duplicate separators collapsed, trailing separator removed
//!   (except the filesystem root). Symlinks are NOT resolved here.
//! * `resolved_path` — the canonical path *after* symlink resolution.
//!   Equals `canonical_path` when no path component is a symlink; `None`
//!   when resolution fails fail-closed (loop / unresolvable).
//! * Unicode: the exact UTF-8 string of the normalised absolute path. No
//!   NFC/NFD normalisation is applied (Q3).
//! * `~` expands only against an explicitly supplied `home`; `~user` is an
//!   error; the real user home is never consulted.
//! * Windows-style spellings (drive letter / UNC) are pure-string
//!   normalisation on this Linux host, fed through the SAME
//!   component-wise resolver as POSIX paths — exactly as the Python
//!   `canonicalize` does. That resolver prepends `/` to the first
//!   component, so a drive spelling resolves to the (meaningless on
//!   Linux) `/C:/...` form, e.g. `C:\x` -> canonical `C:/x`,
//!   resolved `/C:/x`. This is a deliberate bug-compatibility choice
//!   (pinned by T005's copilot-absolute fixture, where an absolute
//!   `@/etc/nope.md` reference gets resolved_target `/etc/nope.md`
//!   and a `@C:\...` reference would get `/C:/...`): the Oracle must
//!   match the executable reference behaviour byte for byte, even
//!   where that behaviour is a Linux artifact. The T002 Windows
//!   resolution tests remain NOT_RUN on Linux.
//! * Windows-host carve-out (FIX-R2): the paragraph above holds on a
//!   non-Windows host ONLY. When the host is Windows (`cfg!(windows)`)
//!   and the lexical path is a drive-absolute spelling (`C:/...`), the
//!   resolver takes a separate Windows branch instead: the drive root
//!   `C:/` is the root, components are resolved against the real
//!   filesystem, `..` stops at the drive root and cannot escape the
//!   drive, `resolved` is rebuilt as `C:/` + components, and
//!   `exists` / `is_file` / `is_dir` come from native FS calls — so a
//!   `C:/...` cwd validates instead of failing as `/C:/...`
//!   (WIN-JUNCTION evidence: 4/4 INPUT_ERROR on Sam's PC, classes 3/4
//!   with plain-dir cwds). A link on Windows is a component whose
//!   reparse tag is 0xA0000003 (junction) or 0xA000000C (symlink); Rust
//!   std exposes no exact tag and this crate takes no winapi
//!   dependency, so `file_type().is_symlink()` — true for any reparse
//!   point on Windows — is used as the proxy (see `is_link_metadata`;
//!   the fixture set contains no other reparse type, so the proxy is
//!   exact there). `read_link` targets are normalised (backslash ->
//!   `/`, `\\?\` prefix stripped, `\\?\UNC\...` back to
//!   `//server/share/...`) before splitting, and the chain /
//!   `symlink_target` record the normalised target, never the raw
//!   value (CPython's `os.readlink` adds the `\\?\` prefix, Rust's
//!   `fs::read_link` does not — raw values could never match); an
//!   absolute drive target resets the root to that drive, a UNC target
//!   resets it to that share. UNC paths stay pure-string
//!   (not expanded this round). The Windows branch is unit-tested on
//!   Linux through a fake filesystem (`WinFs`); the real Windows host
//!   path is only exercised by the V2 runner pack on Sam's PC.
//!   A drive-letter `cwd` / `home` is likewise absolute only on a
//!   Windows host (the Python reference's `os.path.isabs` agrees on
//!   each host), so relative imports resolve against a drive `base_dir`
//!   and `~` expands against a drive `home` there; on Linux a drive
//!   `cwd` / `home` is still rejected exactly as before.
//! * Symlink resolution is component-by-component with a hard hop bound
//!   of 40 (kernel ELOOP limit). A loop returns `is_loop = true`,
//!   `error = "SYMLINK_LOOP"` instead of hanging. A broken symlink is
//!   NOT an error: it resolves lexically to its (missing) target.

use std::collections::{HashSet, VecDeque};
use std::fs;
use std::path::Path;

pub const MAX_SYMLINK_HOPS: u32 = 40;
const MAX_COMPONENTS: usize = 10_000;

/// POSIX `normpath` (mirrors Python `os.path.normpath` on Linux).
///
/// Handles absolute and relative inputs. `.` components are dropped,
/// `..` pops the last component (or is dropped at the filesystem root
/// for absolute paths, kept for relative paths), duplicate separators
/// collapse, a trailing separator is removed (except for `/`).
pub fn normpath_posix(path: &str) -> String {
    let absolute = path.starts_with('/');
    let mut out: Vec<&str> = Vec::new();
    for comp in path.split('/') {
        match comp {
            "" | "." => {}
            ".." => {
                if let Some(last) = out.last() {
                    if *last != ".." {
                        out.pop();
                        continue;
                    }
                }
                if !absolute {
                    out.push("..");
                }
            }
            c => out.push(c),
        }
    }
    if absolute {
        if out.is_empty() {
            "/".to_string()
        } else {
            format!("/{}", out.join("/"))
        }
    } else if out.is_empty() {
        ".".to_string()
    } else {
        out.join("/")
    }
}

fn is_drive_letter(b: u8) -> bool {
    b.is_ascii_alphabetic()
}

/// True when `raw` is spelled like a Windows path: a drive-letter path
/// (`C:\...` or `C:/...`) or a UNC path (`\\server\share\...`).
/// A bare `C:foo` (drive-relative, no separator) is NOT one.
pub fn is_windows_style_path(raw: &str) -> bool {
    let bytes = raw.as_bytes();
    if bytes.len() >= 3
        && is_drive_letter(bytes[0])
        && bytes[1] == b':'
        && (bytes[2] == b'\\' || bytes[2] == b'/')
    {
        return true;
    }
    if raw.starts_with("\\\\") {
        let rest = &raw[2..];
        if let Some(idx) = rest.find('\\') {
            let server = &rest[..idx];
            let share = &rest[idx + 1..];
            if !server.is_empty() && !share.is_empty() {
                return true;
            }
        }
    }
    false
}

/// True when `raw` is a drive-absolute spelling in normalised form:
/// a drive letter, a colon, and a `/` (`C:/...`). A bare `C:foo`
/// (drive-relative) is NOT one, and neither is a UNC path.
pub fn is_drive_absolute(raw: &str) -> bool {
    let bytes = raw.as_bytes();
    bytes.len() >= 3
        && is_drive_letter(bytes[0])
        && bytes[1] == b':'
        && bytes[2] == b'/'
}

/// True when `p` is an absolute path spelling on THIS host: a POSIX
/// `/...` path everywhere, plus a drive-letter `C:/...` path on a
/// Windows host (where `C:/...` is absolute; on Linux it is not —
/// the Python reference's `os.path.isabs` agrees on each host).
/// On Linux this is exactly `p.starts_with('/')`, so Linux behaviour
/// is byte-identical.
fn is_absolute_on_host(p: &str) -> bool {
    p.starts_with('/') || (cfg!(windows) && is_drive_absolute(p))
}

/// Normalise a `cwd` / `home` spelling before an absolute-path check:
/// on a Windows host a backslash drive spelling becomes `C:/...`;
/// elsewhere the spelling is returned unchanged (so Linux error
/// messages keep showing the caller's exact spelling).
fn normalise_base_spelling(p: &str) -> Result<String, String> {
    if cfg!(windows) && is_windows_style_path(p) {
        normalize_windows_path(p)
    } else {
        Ok(p.to_string())
    }
}

/// Normalise a Windows-style path spelling to `C:/...` (or
/// `//server/share/...`) form. Pure-string operation: backslashes become
/// `/`, `.` / `..` are resolved lexically, duplicate separators collapse.
/// Raises an error for a drive-relative spelling (`C:foo`) and for an
/// empty path.
pub fn normalize_windows_path(raw: &str) -> Result<String, String> {
    if raw.is_empty() {
        return Err("empty path".to_string());
    }
    let bytes = raw.as_bytes();
    if bytes.len() >= 2
        && is_drive_letter(bytes[0])
        && bytes[1] == b':'
        && (bytes.len() == 2 || (bytes[2] != b'\\' && bytes[2] != b'/'))
    {
        return Err(format!("drive-relative Windows path is ambiguous: {raw:?}"));
    }
    let slashed = raw.replace('\\', "/");
    if let Some(rest) = slashed.strip_prefix("//") {
        // UNC: //server/share/rest — never pop above the share.
        let mut parts = rest.splitn(3, '/');
        let server = parts.next().unwrap_or("");
        let share = parts.next().unwrap_or("");
        let tail = parts.next().unwrap_or("");
        let norm_tail = normpath_posix(&format!("/{tail}"));
        if norm_tail == "/" {
            return Ok(format!("//{server}/{share}"));
        }
        return Ok(format!("//{server}/{share}{norm_tail}"));
    }
    if slashed.len() >= 2 && is_drive_letter(slashed.as_bytes()[0]) && slashed.as_bytes()[1] == b':' {
        let drive = &slashed[..2];
        let rest = &slashed[2..];
        let norm_rest = normpath_posix(rest);
        if norm_rest == "/" {
            return Ok(format!("{drive}/"));
        }
        if let Some(stripped) = norm_rest.strip_prefix('/') {
            return Ok(format!("{drive}/{stripped}"));
        }
        return Ok(format!("{drive}{norm_rest}"));
    }
    Ok(normpath_posix(&slashed))
}

fn check_no_nul(raw: &str) -> Result<(), String> {
    if raw.contains('\x00') {
        return Err("path contains NUL byte".to_string());
    }
    Ok(())
}

/// Return the lexical canonical form of `raw` (absolute, normalised).
/// See the module docs. Errors only for malformed *input* (empty path,
/// NUL byte, `~` without an explicit `home`, `~user`, a relative path
/// without `cwd`, a drive-relative Windows spelling).
pub fn lexical_canonical(
    raw: &str,
    cwd: Option<&str>,
    home: Option<&str>,
) -> Result<String, String> {
    if raw.is_empty() {
        return Err("empty path".to_string());
    }
    check_no_nul(raw)?;

    if is_windows_style_path(raw) {
        return normalize_windows_path(raw);
    }

    let mut path: String = raw.to_string();
    if raw == "~" || raw.starts_with("~/") {
        let home = home.ok_or_else(|| "~ expansion requires an explicit home argument".to_string())?;
        check_no_nul(home)?;
        // A drive-letter home is absolute only on a Windows host
        // (see the module docs); on Linux it is still rejected below.
        let home = normalise_base_spelling(home)?;
        if !is_absolute_on_host(&home) {
            return Err(format!("home must be absolute: {home:?}"));
        }
        path = format!("{}{}", home, &raw[1..]);
    } else if raw.starts_with('~') {
        return Err(format!("~user expansion is unsupported: {raw:?}"));
    }

    if !is_absolute_on_host(&path) {
        let cwd = cwd.ok_or_else(|| format!("relative path requires an explicit cwd: {raw:?}"))?;
        check_no_nul(cwd)?;
        // A drive-letter cwd is absolute only on a Windows host
        // (see the module docs); on Linux it is still rejected below.
        let cwd = normalise_base_spelling(cwd)?;
        if !is_absolute_on_host(&cwd) {
            return Err(format!("cwd must be absolute: {cwd:?}"));
        }
        path = if cwd == "/" {
            format!("/{path}")
        } else {
            format!("{cwd}/{path}")
        };
    }

    let normal = normpath_posix(&path);
    Ok(normal)
}

fn split_components(abs_path: &str) -> VecDeque<String> {
    abs_path
        .split('/')
        .filter(|c| !c.is_empty() && *c != ".")
        .map(|c| c.to_string())
        .collect()
}

fn join_abs(out: &[String]) -> String {
    if out.is_empty() {
        "/".to_string()
    } else {
        format!("/{}", out.join("/"))
    }
}

/// Whether `md` describes a path component the resolver must follow
/// as a link.
///
/// * POSIX: `file_type().is_symlink()`.
/// * Windows: the contract is reparse tag ∈ {0xA0000003 junction,
///   0xA000000C symlink}. Rust std exposes no exact reparse tag and
///   this crate takes no winapi dependency, so the observable proxy
///   is `file_type().is_symlink()`, which is true for any reparse
///   point on Windows. Residual, stated honestly: a reparse point of
///   another type would be misread as a link. No fixture in this repo
///   contains such a reparse type — verified: every symlink under
///   `01_s0/fixtures/` and `fixtures/` is a plain symlink, and the
///   four `fixtures/windows/win-junction-*/repo/linked` entries are
///   Linux dir symlinks standing in for NTFS junctions (their
///   `case.json` says so) — so the proxy is exact on the fixture set;
///   on a foreign tree it errs toward following, never toward
///   silently skipping a junction or symlink.
fn is_link_metadata(md: &fs::Metadata) -> bool {
    md.file_type().is_symlink()
}

/// Resolve symlinks in `lexical` (absolute POSIX path) component-wise.
/// Returns `(resolved, chain, is_loop, error)` where `chain` is the list
/// of raw symlink targets encountered (in resolution order).
fn resolve_components(lexical: &str) -> (String, Vec<String>, bool, Option<String>) {
    let mut queue = split_components(lexical);
    let mut out: Vec<String> = Vec::new();
    let mut chain: Vec<String> = Vec::new();
    let mut seen: HashSet<(Vec<String>, String)> = HashSet::new();
    let mut hops: u32 = 0;
    let mut steps: usize = 0;
    while let Some(comp) = queue.pop_front() {
        steps += 1;
        if steps > MAX_COMPONENTS {
            return (join_abs(&out), chain, false, Some("UNRESOLVABLE".to_string()));
        }
        if comp == ".." {
            out.pop();
            continue;
        }
        let mut current_parts = out.clone();
        current_parts.push(comp.clone());
        let current = join_abs(&current_parts);
        let md = match fs::symlink_metadata(&current) {
            Ok(md) => md,
            Err(_) => {
                // Unreadable / missing component: stop resolving here,
                // keep the lexical rest.
                out.push(comp);
                out.extend(queue);
                return (join_abs(&out), chain, false, None);
            }
        };
        if !is_link_metadata(&md) {
            out.push(comp);
            continue;
        }
        // Symlink component.
        let key = (out.clone(), comp.clone());
        if seen.contains(&key) {
            out.push(comp);
            out.extend(queue);
            return (join_abs(&out), chain, true, Some("SYMLINK_LOOP".to_string()));
        }
        seen.insert(key);
        hops += 1;
        if hops > MAX_SYMLINK_HOPS {
            out.push(comp);
            out.extend(queue);
            return (join_abs(&out), chain, true, Some("SYMLINK_LOOP".to_string()));
        }
        let target = match fs::read_link(&current) {
            Ok(t) => t,
            Err(_) => {
                out.push(comp);
                out.extend(queue);
                return (join_abs(&out), chain, false, None);
            }
        };
        let target_str = target.to_string_lossy().into_owned();
        chain.push(target_str.clone());
        if target.is_absolute() {
            out = Vec::new();
            let mut new_queue = split_components(&target_str);
            new_queue.extend(queue);
            queue = new_queue;
        } else {
            let mut new_queue = split_components(&target_str);
            new_queue.extend(queue);
            queue = new_queue;
        }
    }
    (join_abs(&out), chain, false, None)
}

// ---------------------------------------------------------------------------
// Windows branch (FIX-R2; see the module docs). Only taken when the host
// is Windows and the lexical path is drive-absolute; on Linux the
// functions below are exercised solely by the unit tests, through a
// fake filesystem, so the Linux production behaviour is untouched.
// ---------------------------------------------------------------------------

/// Minimal filesystem surface the Windows branch needs. The real
/// implementation uses `std::fs` against native `C:/...` paths; the
/// tests substitute an in-memory fake, which is what makes the
/// Windows branch unit-testable on Linux.
trait WinFs {
    /// `Ok(true)` = link, `Ok(false)` = ordinary entry,
    /// `Err(())` = metadata unreadable (missing entry included).
    fn is_link(&self, path: &str) -> Result<bool, ()>;
    /// Raw `read_link` target of a link entry.
    fn read_link(&self, path: &str) -> Result<String, ()>;
    /// `Ok((is_file, is_dir))` for the entry `path` resolves to
    /// (links followed), `Err(())` when it does not exist.
    fn metadata(&self, path: &str) -> Result<(bool, bool), ()>;
}

/// The real filesystem, for the Windows host.
struct RealWinFs;

impl WinFs for RealWinFs {
    fn is_link(&self, path: &str) -> Result<bool, ()> {
        fs::symlink_metadata(path)
            .map(|md| is_link_metadata(&md))
            .map_err(|_| ())
    }

    fn read_link(&self, path: &str) -> Result<String, ()> {
        fs::read_link(path)
            .map(|t| t.to_string_lossy().into_owned())
            .map_err(|_| ())
    }

    fn metadata(&self, path: &str) -> Result<(bool, bool), ()> {
        fs::metadata(path)
            .map(|md| (md.is_file(), md.is_dir()))
            .map_err(|_| ())
    }
}

/// Normalise a raw `read_link` target for the Windows branch, exactly
/// as Production's `_normalize_windows_readlink_target` does (FIX-R2
/// D2; coordinator ruling: chain and `symlink_target` record the
/// NORMALISED target, never the raw value, because CPython's
/// `os.readlink` returns junction targets with a `\\?\` prefix the
/// Oracle's `fs::read_link` never reports).
///
/// Backslashes become `/`, a `\\?\` prefix (now `//?/`) is stripped,
/// and a `\\?\UNC\server\share\...` target maps back to
/// `//server/share/...`. The result is NOT lexically normalised
/// further: `..` components are left in place so the resolver can pop
/// them against the already-resolved prefix (an absolute target resets
/// the prefix first). The `UNC/` check is a separate step, exactly as
/// in Production — it also fires for a target that is literally
/// `UNC/...` with no prefix.
fn normalize_link_target(raw: &str) -> String {
    let mut s = raw.replace('\\', "/");
    if s.starts_with("//?/") {
        s = s[4..].to_string();
    }
    if s.starts_with("UNC/") {
        s = format!("//{}", &s[4..]);
    }
    s
}

/// Split a normalised link target that is an absolute drive path
/// (`C:/...`) into its root (`C:/`, trailing slash included, so the
/// join is a plain concatenation like Production's) and components.
/// Returns `None` for relative, root-relative (`/...`) and UNC targets.
fn split_drive_target(target: &str) -> Option<(String, VecDeque<String>)> {
    if !is_drive_absolute(target) {
        return None;
    }
    let root = target[..3].to_string();
    let rest = &target[3..];
    Some((root, split_components(rest)))
}

/// Split a normalised UNC link target (`//server/share/rest`) into its
/// share root (`//server/share/`) and remaining components. Mirrors
/// Production: fewer than server+share components is malformed — the
/// whole thing becomes the root and no components are prepended.
fn split_unc_target(target: &str) -> (String, VecDeque<String>) {
    let rest = target.strip_prefix("//").unwrap_or("");
    let parts: Vec<String> = split_components(rest).into_iter().collect();
    if parts.len() >= 2 {
        let root = format!("//{}/{}/", parts[0], parts[1]);
        let comps: VecDeque<String> = parts.into_iter().skip(2).collect();
        (root, comps)
    } else {
        let root = if parts.is_empty() {
            "//".to_string()
        } else {
            format!("//{}/", parts[0])
        };
        (root, VecDeque::new())
    }
}

fn join_windows(root: &str, out: &[String]) -> String {
    if out.is_empty() {
        root.to_string()
    } else {
        format!("{root}{}", out.join("/"))
    }
}

/// Resolve links in a drive-absolute lexical path (`C:/...`)
/// component-wise, mirroring `resolve_components` but with the drive
/// root as the root: `..` pops the last component and stops at the
/// drive root (it can never escape the drive), an absolute drive
/// target resets the root to that drive, a UNC target
/// (`//server/share/...`, e.g. from a `\\?\UNC\...` readlink target)
/// resets the root to that share, a root-relative (`/...`) target
/// resets to the same drive's root, and a relative target resolves
/// against the link's parent directory. Returns
/// `(resolved, chain, is_loop, error)`; `chain` holds the
/// NORMALISED link targets in resolution order (coordinator ruling:
/// never the raw `read_link` value).
fn resolve_windows_components<F: WinFs>(
    lexical: &str,
    fs: &F,
) -> (String, Vec<String>, bool, Option<String>) {
    let (mut root, mut queue) = match split_drive_target(lexical) {
        Some((r, q)) => (r, q),
        // Not drive-absolute (defensive; callers check first):
        // resolve lexically under `/` so nothing panics.
        None => ("/".to_string(), split_components(lexical)),
    };
    let mut out: Vec<String> = Vec::new();
    let mut chain: Vec<String> = Vec::new();
    let mut seen: HashSet<(String, Vec<String>, String)> = HashSet::new();
    let mut hops: u32 = 0;
    let mut steps: usize = 0;
    while let Some(comp) = queue.pop_front() {
        steps += 1;
        if steps > MAX_COMPONENTS {
            return (
                join_windows(&root, &out),
                chain,
                false,
                Some("UNRESOLVABLE".to_string()),
            );
        }
        if comp == ".." {
            // Stops at the drive root: pop on an empty `out` is a no-op.
            out.pop();
            continue;
        }
        let mut current_parts = out.clone();
        current_parts.push(comp.clone());
        let current = join_windows(&root, &current_parts);
        let is_link = match fs.is_link(&current) {
            Ok(b) => b,
            Err(_) => {
                // Unreadable / missing component: stop resolving here,
                // keep the lexical rest.
                out.push(comp);
                out.extend(queue);
                return (join_windows(&root, &out), chain, false, None);
            }
        };
        if !is_link {
            out.push(comp);
            continue;
        }
        // Link component.
        let key = (root.clone(), out.clone(), comp.clone());
        if seen.contains(&key) {
            out.push(comp);
            out.extend(queue);
            return (
                join_windows(&root, &out),
                chain,
                true,
                Some("SYMLINK_LOOP".to_string()),
            );
        }
        seen.insert(key);
        hops += 1;
        if hops > MAX_SYMLINK_HOPS {
            out.push(comp);
            out.extend(queue);
            return (
                join_windows(&root, &out),
                chain,
                true,
                Some("SYMLINK_LOOP".to_string()),
            );
        }
        let target = match fs.read_link(&current) {
            Ok(t) => normalize_link_target(&t),
            Err(_) => {
                out.push(comp);
                out.extend(queue);
                return (join_windows(&root, &out), chain, false, None);
            }
        };
        chain.push(target.clone());
        if let Some((t_root, t_comps)) = split_drive_target(&target) {
            // Absolute drive target: switch drive, reset to its root.
            root = t_root;
            out = Vec::new();
            let mut new_queue = t_comps;
            new_queue.extend(queue);
            queue = new_queue;
        } else if target.starts_with("//") {
            // UNC target: root is the share, the rest are components.
            let (t_root, t_comps) = split_unc_target(&target);
            root = t_root;
            out = Vec::new();
            let mut new_queue = t_comps;
            new_queue.extend(queue);
            queue = new_queue;
        } else if target.starts_with('/') {
            // Root-relative target: same drive, reset to its root.
            out = Vec::new();
            let mut new_queue = split_components(&target);
            new_queue.extend(queue);
            queue = new_queue;
        } else {
            let mut new_queue = split_components(&target);
            new_queue.extend(queue);
            queue = new_queue;
        }
    }
    (join_windows(&root, &out), chain, false, None)
}

/// Canonicalise a drive-absolute lexical path on a Windows host,
/// using `fs` for every filesystem judgement. Mirrors `canonicalize`
/// record-for-record (loop / error fail closed with `resolved_path`
/// `None`; a broken link resolves lexically to its missing target).
fn canonicalize_windows_inner<F: WinFs>(
    raw: &str,
    lexical: &str,
    fs: &F,
) -> CanonicalPath {
    // Trailing-component link target, same link rule as the resolver.
    let symlink_target = match fs.is_link(lexical) {
        Ok(true) => fs
            .read_link(lexical)
            .ok()
            .map(|t| normalize_link_target(&t)),
        _ => None,
    };

    let (resolved, chain, is_loop, error) = resolve_windows_components(lexical, fs);
    if is_loop || error.is_some() {
        return CanonicalPath {
            raw_path: raw.to_string(),
            canonical_path: lexical.to_string(),
            resolved_path: None,
            exists: false,
            is_file: false,
            is_dir: false,
            is_symlink: !chain.is_empty(),
            symlink_target,
            symlink_chain: chain,
            is_broken_symlink: false,
            is_loop,
            error: error.or_else(|| Some("UNRESOLVABLE".to_string())),
        };
    }

    let (exists, is_file, is_dir) = match fs.metadata(&resolved) {
        Ok((f, d)) => (true, f, d),
        Err(_) => (false, false, false),
    };
    let is_broken = !chain.is_empty() && !exists && fs.is_link(lexical).is_ok();
    CanonicalPath {
        raw_path: raw.to_string(),
        canonical_path: lexical.to_string(),
        resolved_path: Some(resolved),
        exists,
        is_file,
        is_dir,
        is_symlink: !chain.is_empty(),
        symlink_target,
        symlink_chain: chain,
        is_broken_symlink: is_broken,
        is_loop: false,
        error: None,
    }
}

/// The canonical record for one input path (lexical + resolved).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanonicalPath {
    pub raw_path: String,
    pub canonical_path: String,
    pub resolved_path: Option<String>,
    pub exists: bool,
    pub is_file: bool,
    pub is_dir: bool,
    pub is_symlink: bool,
    pub symlink_target: Option<String>,
    pub symlink_chain: Vec<String>,
    pub is_broken_symlink: bool,
    pub is_loop: bool,
    pub error: Option<String>,
}

impl CanonicalPath {
    pub fn valid(&self) -> bool {
        self.error.is_none()
    }
}

/// Canonicalise `raw` into a [`CanonicalPath`] (lexical + resolved).
/// Never fails for a loop, a broken symlink, or a missing path — those
/// are reported in the returned record. Errors only for malformed input.
pub fn canonicalize(
    raw: &str,
    cwd: Option<&str>,
    home: Option<&str>,
) -> Result<CanonicalPath, String> {
    let lexical = lexical_canonical(raw, cwd, home)?;

    // Windows-host carve-out (FIX-R2, see the module docs): a
    // drive-absolute lexical path resolves against the real
    // filesystem with the drive root as the root. On any other host
    // the drive spelling falls through to the POSIX resolver below,
    // which yields the `/C:/...` form — byte-identical to the Python
    // `canonicalize`. The lexical path "C:/x" is relative as a
    // string, so `symlink_metadata` below is evaluated against the
    // process cwd and returns None — again exactly like Python's
    // `os.path.islink("C:/x")`.
    if cfg!(windows) && is_drive_absolute(&lexical) {
        return Ok(canonicalize_windows_inner(raw, &lexical, &RealWinFs));
    }

    // Windows-style spellings go through the same component-wise
    // resolver as POSIX paths on a non-Windows host (see the module
    // docs): on Linux this yields the `/C:/...` form, matching the
    // Python `canonicalize` byte for byte.
    let symlink_target = match fs::symlink_metadata(&lexical) {
        Ok(md) if is_link_metadata(&md) => fs::read_link(&lexical)
            .ok()
            .map(|t| t.to_string_lossy().into_owned()),
        _ => None,
    };

    let (resolved, chain, is_loop, error) = resolve_components(&lexical);
    if is_loop || error.is_some() {
        return Ok(CanonicalPath {
            raw_path: raw.to_string(),
            canonical_path: lexical,
            resolved_path: None,
            exists: false,
            is_file: false,
            is_dir: false,
            is_symlink: !chain.is_empty(),
            symlink_target,
            symlink_chain: chain,
            is_broken_symlink: false,
            is_loop,
            error: error.or_else(|| Some("UNRESOLVABLE".to_string())),
        });
    }

    let exists = Path::new(&resolved).exists();
    let is_broken = !chain.is_empty() && !exists && fs::symlink_metadata(&lexical).is_ok();
    let (is_file, is_dir) = if exists {
        match fs::metadata(&resolved) {
            Ok(md) => (md.is_file(), md.is_dir()),
            Err(_) => (false, false),
        }
    } else {
        (false, false)
    };
    Ok(CanonicalPath {
        raw_path: raw.to_string(),
        canonical_path: lexical,
        resolved_path: Some(resolved),
        exists,
        is_file,
        is_dir,
        is_symlink: !chain.is_empty(),
        symlink_target,
        symlink_chain: chain,
        is_broken_symlink: is_broken,
        is_loop: false,
        error: None,
    })
}

/// Return true when canonical absolute `path` is `root` or under it.
/// Comparison is component-wise, not textual (`/repo2` is NOT within
/// `/repo`). The root itself counts as within; `/` contains everything.
pub fn is_within_root(path: &str, root: &str) -> bool {
    let norm_path = normpath_posix(path);
    let norm_root = normpath_posix(root);
    if norm_root == "/" {
        return norm_path.starts_with('/');
    }
    norm_path == norm_root || norm_path.starts_with(&format!("{norm_root}/"))
}

/// SHA-256 (lowercase hex) of the file at `path`, streamed in 64 KiB
/// chunks. Errors when the file cannot be read.
pub fn hash_file(path: &str) -> std::io::Result<String> {
    use sha2::Digest;
    let mut file = fs::File::open(path)?;
    let mut digest = sha2::Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        use std::io::Read;
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        digest.update(&buf[..n]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lexical_dotdot_and_separators() {
        assert_eq!(
            lexical_canonical("/a/b/../c", None, None).unwrap(),
            "/a/c"
        );
        assert_eq!(
            lexical_canonical("/a//b///c/", None, None).unwrap(),
            "/a/b/c"
        );
        assert_eq!(lexical_canonical("/", None, None).unwrap(), "/");
        assert_eq!(
            lexical_canonical("rel/path", Some("/cwd"), None).unwrap(),
            "/cwd/rel/path"
        );
        assert_eq!(
            lexical_canonical("~/.codex/AGENTS.md", None, Some("/home/u")).unwrap(),
            "/home/u/.codex/AGENTS.md"
        );
        assert_eq!(lexical_canonical("~", None, Some("/home/u")).unwrap(), "/home/u");
    }

    #[test]
    fn lexical_errors() {
        assert!(lexical_canonical("", None, None).is_err());
        assert!(lexical_canonical("~", None, None).is_err());
        assert!(lexical_canonical("~bob/x", None, Some("/h")).is_err());
        assert!(lexical_canonical("rel", None, None).is_err());
        assert!(lexical_canonical("a\x00b", None, None).is_err());
    }

    #[test]
    fn windows_spellings() {
        assert!(is_windows_style_path("C:\\a\\b"));
        assert!(is_windows_style_path("C:/a/b"));
        assert!(is_windows_style_path("\\\\server\\share\\x"));
        assert!(!is_windows_style_path("/repo/AGENTS.md"));
        assert!(!is_windows_style_path("C:foo"));
        assert_eq!(
            normalize_windows_path("C:\\repo\\services\\..\\AGENTS.md").unwrap(),
            "C:/repo/AGENTS.md"
        );
        assert_eq!(
            normalize_windows_path("C:/repo//services///AGENTS.md").unwrap(),
            "C:/repo/services/AGENTS.md"
        );
        assert_eq!(
            normalize_windows_path("\\\\server\\share\\repo\\AGENTS.md").unwrap(),
            "//server/share/repo/AGENTS.md"
        );
        assert_eq!(
            normalize_windows_path("D:\\Downloads\\AGENTS.md").unwrap(),
            "D:/Downloads/AGENTS.md"
        );
        assert!(normalize_windows_path("C:foo\\bar").is_err());
    }

    #[test]
    fn windows_drive_resolves_like_python() {
        // Bug-compatibility with the Python `canonicalize`: the
        // component-wise resolver prepends `/` to the first component,
        // so a drive spelling resolves to `/C:/...` on Linux. The
        // Oracle matches that byte for byte (see the module docs).
        let c = canonicalize("C:\\repo\\AGENTS.md", Some("/cwd"), Some("/home/u")).unwrap();
        assert_eq!(c.canonical_path, "C:/repo/AGENTS.md");
        assert_eq!(c.resolved_path.as_deref(), Some("/C:/repo/AGENTS.md"));
        assert!(!c.exists);
        assert!(!c.is_symlink);
        let c = canonicalize("\\\\server\\share\\x.md", Some("/cwd"), Some("/home/u")).unwrap();
        assert_eq!(c.canonical_path, "//server/share/x.md");
        assert_eq!(c.resolved_path.as_deref(), Some("/server/share/x.md"));
    }

    #[test]
    fn containment_is_component_wise() {
        assert!(is_within_root("/repo/a/b", "/repo"));
        assert!(is_within_root("/repo", "/repo"));
        assert!(!is_within_root("/repo2/a", "/repo"));
        assert!(is_within_root("/anything", "/"));
        assert!(!is_within_root("/repo/../outside", "/repo"));
    }

    // --- Windows branch tests (FIX-R2 D3) --------------------------------
    // The Windows branch is exercised on Linux through a fake
    // filesystem; the real Windows host path is only exercised by the
    // V2 runner pack on Sam's PC.

    use std::collections::HashMap;

    #[derive(Debug, Clone)]
    enum FakeEntry {
        File,
        Dir,
        Link(String),
    }

    struct FakeWinFs {
        entries: HashMap<String, FakeEntry>,
    }

    /// Root prefix of a Windows path string: `C:/` for a drive path,
    /// `//server/share/` for a UNC path.
    fn test_root_of(path: &str) -> String {
        if let Some(rest) = path.strip_prefix("//") {
            let mut parts = rest.splitn(3, '/');
            let server = parts.next().unwrap_or("");
            let share = parts.next().unwrap_or("");
            if !server.is_empty() && !share.is_empty() {
                return format!("//{server}/{share}/");
            }
            return "//".to_string();
        }
        path.get(..3).unwrap_or(path).to_string()
    }

    impl FakeWinFs {
        fn new(entries: &[(&str, FakeEntry)]) -> Self {
            FakeWinFs {
                entries: entries
                    .iter()
                    .map(|(p, e)| (p.to_string(), e.clone()))
                    .collect(),
            }
        }

        fn resolve_link_target(&self, from: &str, raw_target: &str) -> String {
            let target = normalize_link_target(raw_target);
            if is_drive_absolute(&target) || target.starts_with("//") {
                return target;
            }
            if target.starts_with('/') {
                let root = test_root_of(from);
                return format!("{root}{}", target.trim_start_matches('/'));
            }
            let parent = match from.rfind('/') {
                Some(i) => &from[..i],
                None => "",
            };
            let joined = if parent.is_empty() {
                target
            } else {
                format!("{parent}/{target}")
            };
            normpath_posix(&joined)
        }

        /// Follow links (bounded), like `fs::metadata` does.
        fn follow(&self, path: &str) -> Option<FakeEntry> {
            let mut cur = path.to_string();
            for _ in 0..=MAX_SYMLINK_HOPS {
                match self.entries.get(&cur) {
                    Some(FakeEntry::Link(t)) => {
                        cur = self.resolve_link_target(&cur, t);
                    }
                    Some(e) => return Some(e.clone()),
                    None => return None,
                }
            }
            None
        }
    }

    impl WinFs for FakeWinFs {
        fn is_link(&self, path: &str) -> Result<bool, ()> {
            match self.entries.get(path) {
                Some(FakeEntry::Link(_)) => Ok(true),
                Some(_) => Ok(false),
                None => Err(()),
            }
        }

        fn read_link(&self, path: &str) -> Result<String, ()> {
            match self.entries.get(path) {
                Some(FakeEntry::Link(t)) => Ok(t.clone()),
                _ => Err(()),
            }
        }

        fn metadata(&self, path: &str) -> Result<(bool, bool), ()> {
            match self.follow(path) {
                Some(FakeEntry::File) => Ok((true, false)),
                Some(FakeEntry::Dir) => Ok((false, true)),
                _ => Err(()),
            }
        }
    }

    fn win_fs(entries: &[(&str, FakeEntry)]) -> FakeWinFs {
        FakeWinFs::new(entries)
    }

    #[test]
    fn windows_branch_drive_root_resolution() {
        assert!(is_drive_absolute("C:/x"));
        assert!(is_drive_absolute("D:/"));
        assert!(!is_drive_absolute("C:foo"));
        assert!(!is_drive_absolute("//server/share/x"));
        assert!(!is_drive_absolute("/repo/x"));

        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            ("C:/repo/AGENTS.md", FakeEntry::File),
        ]);
        let c = canonicalize_windows_inner("C:\\", "C:/", &fs);
        assert_eq!(c.canonical_path, "C:/");
        assert_eq!(c.resolved_path.as_deref(), Some("C:/"));
        assert!(c.exists && c.is_dir && !c.is_file);
        assert!(!c.is_symlink);
        let c = canonicalize_windows_inner("C:\\repo\\AGENTS.md", "C:/repo/AGENTS.md", &fs);
        assert_eq!(c.resolved_path.as_deref(), Some("C:/repo/AGENTS.md"));
        assert!(c.exists && c.is_file);
    }

    #[test]
    fn windows_branch_dotdot_stops_at_drive_root() {
        // A link whose target climbs above the drive root: the `..`
        // components reach the resolver through the link, not through
        // the lexical path (lexical `..` is normalised away first).
        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/a", FakeEntry::Dir),
            (
                "C:/a/link",
                FakeEntry::Link("../../../escape.md".to_string()),
            ),
            ("C:/escape.md", FakeEntry::File),
        ]);
        let (resolved, chain, is_loop, error) =
            resolve_windows_components("C:/a/link", &fs);
        assert_eq!(resolved, "C:/escape.md");
        assert_eq!(chain, vec!["../../../escape.md".to_string()]);
        assert!(!is_loop && error.is_none());
        let c = canonicalize_windows_inner("C:/a/link", "C:/a/link", &fs);
        assert_eq!(c.resolved_path.as_deref(), Some("C:/escape.md"));
        assert!(c.exists && c.is_file);
        // Direct resolver check: `..` as the first component cannot
        // escape the drive root either.
        let (resolved, _, _, _) = resolve_windows_components("C:/../x", &fs);
        assert_eq!(resolved, "C:/x");
    }

    #[test]
    fn windows_branch_junction_follow() {
        // The win-junction-inside analogue: `linked` is a dir link to
        // in-repo `shared`.
        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            ("C:/repo/shared", FakeEntry::Dir),
            ("C:/repo/shared/AGENTS.md", FakeEntry::File),
            ("C:/repo/linked", FakeEntry::Link("shared".to_string())),
        ]);
        let c = canonicalize_windows_inner(
            "C:\\repo\\linked\\AGENTS.md",
            "C:/repo/linked/AGENTS.md",
            &fs,
        );
        assert_eq!(c.canonical_path, "C:/repo/linked/AGENTS.md");
        assert_eq!(
            c.resolved_path.as_deref(),
            Some("C:/repo/shared/AGENTS.md")
        );
        assert!(c.exists && c.is_file);
        assert!(c.is_symlink);
        assert_eq!(c.symlink_chain, vec!["shared".to_string()]);
        // Absolute drive target, as a real junction stores it.
        let fs2 = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            ("C:/repo/shared", FakeEntry::Dir),
            ("C:/repo/shared/AGENTS.md", FakeEntry::File),
            (
                "C:/repo/linked",
                FakeEntry::Link("C:\\repo\\shared".to_string()),
            ),
        ]);
        let c = canonicalize_windows_inner(
            "C:/repo/linked/AGENTS.md",
            "C:/repo/linked/AGENTS.md",
            &fs2,
        );
        assert_eq!(
            c.resolved_path.as_deref(),
            Some("C:/repo/shared/AGENTS.md")
        );
        assert_eq!(c.symlink_chain, vec!["C:/repo/shared".to_string()]);
        // The trailing component itself is a link: symlink_target is
        // the normalised target too.
        let c = canonicalize_windows_inner("C:/repo/linked", "C:/repo/linked", &fs2);
        assert_eq!(c.symlink_target.as_deref(), Some("C:/repo/shared"));
        assert_eq!(c.resolved_path.as_deref(), Some("C:/repo/shared"));
        assert!(c.is_dir);
    }

    #[test]
    fn windows_branch_readlink_target_normalisation() {
        // Direct unit tests of the normaliser (Production rule, D2):
        // backslashes, `\\?\` prefix, `\\?\UNC\...` restoration.
        assert_eq!(normalize_link_target("C:\\repo\\shared"), "C:/repo/shared");
        assert_eq!(
            normalize_link_target("\\\\?\\C:\\repo\\shared"),
            "C:/repo/shared"
        );
        assert_eq!(
            normalize_link_target("\\\\?\\UNC\\server\\share\\rest"),
            "//server/share/rest"
        );
        assert_eq!(normalize_link_target("shared\\sub"), "shared/sub");
        assert_eq!(
            normalize_link_target("..\\outside\\x.md"),
            "../outside/x.md"
        );
        // `..` is left for the resolver to pop, not normalised away.
        assert_eq!(
            normalize_link_target("..\\..\\escape.md"),
            "../../escape.md"
        );
        // A relative target literally starting with `UNC/` takes the
        // same second step as Production's two-step rule.
        assert_eq!(normalize_link_target("UNC/server"), "//server");

        // End-to-end: a junction target as CPython reports it (with
        // the `\\?\` prefix) resolves and is recorded without it.
        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            ("C:/repo/shared", FakeEntry::Dir),
            (
                "C:/repo/linked",
                FakeEntry::Link("\\\\?\\C:\\repo\\shared".to_string()),
            ),
        ]);
        let c = canonicalize_windows_inner("C:/repo/linked", "C:/repo/linked", &fs);
        assert_eq!(c.resolved_path.as_deref(), Some("C:/repo/shared"));
        assert_eq!(c.symlink_chain, vec!["C:/repo/shared".to_string()]);
        assert_eq!(c.symlink_target.as_deref(), Some("C:/repo/shared"));
    }

    #[test]
    fn windows_branch_absolute_target_switches_drive() {
        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            (
                "C:/repo/linked",
                FakeEntry::Link("D:/other/shared".to_string()),
            ),
            ("D:/", FakeEntry::Dir),
            ("D:/other", FakeEntry::Dir),
            ("D:/other/shared", FakeEntry::Dir),
            ("D:/other/shared/ok.md", FakeEntry::File),
        ]);
        let c =
            canonicalize_windows_inner("C:/repo/linked/ok.md", "C:/repo/linked/ok.md", &fs);
        assert_eq!(c.canonical_path, "C:/repo/linked/ok.md");
        assert_eq!(
            c.resolved_path.as_deref(),
            Some("D:/other/shared/ok.md")
        );
        assert!(c.exists && c.is_file);
        assert_eq!(c.symlink_chain, vec!["D:/other/shared".to_string()]);
    }

    #[test]
    fn windows_branch_unc_target_switches_to_share() {
        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            (
                "C:/repo/linked",
                FakeEntry::Link("\\\\?\\UNC\\server\\share\\rest".to_string()),
            ),
            ("//server/share/rest", FakeEntry::Dir),
            ("//server/share/rest/file.md", FakeEntry::File),
        ]);
        let c = canonicalize_windows_inner(
            "C:/repo/linked/file.md",
            "C:/repo/linked/file.md",
            &fs,
        );
        assert_eq!(
            c.resolved_path.as_deref(),
            Some("//server/share/rest/file.md")
        );
        assert!(c.exists && c.is_file);
        assert_eq!(c.symlink_chain, vec!["//server/share/rest".to_string()]);
    }

    #[test]
    fn windows_branch_symlink_loop_fail_closed() {
        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            ("C:/repo/a", FakeEntry::Link("b".to_string())),
            ("C:/repo/b", FakeEntry::Link("a".to_string())),
        ]);
        let c = canonicalize_windows_inner("C:/repo/a/x.md", "C:/repo/a/x.md", &fs);
        assert!(c.is_loop);
        assert_eq!(c.error.as_deref(), Some("SYMLINK_LOOP"));
        assert_eq!(c.resolved_path, None);
        assert!(!c.exists);
        assert!(c.is_symlink);
        // Self-loop: the same link seen twice.
        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            ("C:/repo/self", FakeEntry::Link("self".to_string())),
        ]);
        let c = canonicalize_windows_inner("C:/repo/self/x.md", "C:/repo/self/x.md", &fs);
        assert!(c.is_loop);
        assert_eq!(c.error.as_deref(), Some("SYMLINK_LOOP"));
        assert_eq!(c.resolved_path, None);
    }

    #[test]
    fn windows_branch_broken_symlink() {
        let fs = win_fs(&[
            ("C:/", FakeEntry::Dir),
            ("C:/repo", FakeEntry::Dir),
            (
                "C:/repo/broken.md",
                FakeEntry::Link("missing.md".to_string()),
            ),
        ]);
        let c =
            canonicalize_windows_inner("C:/repo/broken.md", "C:/repo/broken.md", &fs);
        assert_eq!(c.resolved_path.as_deref(), Some("C:/repo/missing.md"));
        assert!(!c.exists);
        assert!(c.is_symlink);
        assert!(c.is_broken_symlink);
    }

    #[test]
    fn drive_cwd_home_absolute_only_on_windows_host() {
        // D1: on Linux a drive-letter cwd/home is still rejected
        // exactly as before; on a Windows host it is absolute (that
        // path is only exercised by the V2 runner pack on Sam's PC).
        if cfg!(windows) {
            assert_eq!(
                lexical_canonical("rel/path", Some("C:/cwd"), None).unwrap(),
                "C:/cwd/rel/path"
            );
            assert_eq!(
                lexical_canonical("~/.codex/AGENTS.md", None, Some("C:/Users/u")).unwrap(),
                "C:/Users/u/.codex/AGENTS.md"
            );
        } else {
            assert!(lexical_canonical("rel/path", Some("C:/cwd"), None).is_err());
            assert!(
                lexical_canonical("~/.codex/AGENTS.md", None, Some("C:/Users/u")).is_err()
            );
        }
    }
}
