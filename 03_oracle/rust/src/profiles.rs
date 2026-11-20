//! Harness resolution — independent Rust implementation of the three
//! P028 profiles from `00_contract/profile_contract.json` (the sole
//! authority for the rules; precedence `detail` strings below are
//! verbatim from the contract, aligned by FIX-C06 — C-06 in
//! TASK_RESULT.md: claude-code.project appends "Override semantics
//! between files: UNSPECIFIED.", claude-code.rules-path-scoped says
//! "ordering relative to other sources", and copilot-cli.user /
//! copilot-cli.repo-wide carry their per-rule details):
//!
//! * `codex` / `codex-2026-11` — user file, repo-root-to-CWD chain,
//!   `AGENTS.override.md` listed with UNSPECIFIED precedence (its
//!   selection semantics are UNVERIFIED; no override semantics are
//!   implemented). No `@`-import mechanism (undocumented for Codex).
//! * `claude-code` / `claude-code-2026-11` — managed, user, project
//!   chain, rules, AGENTS.md fallback, nested on-demand,
//!   additional-dirs; `@path` imports, maximum depth **4 hops**
//!   (SPEC-01: the fetched official doc; the spec book's depth-5 text
//!   is a recorded spec defect).
//! * `copilot-cli` / `copilot-cli-2026-11` — user, user-modular
//!   (applyTo-gated), repo-wide, repo-modular (no intermediate dirs),
//!   agents, claude, gemini, custom-dirs; all COMBINE_UNORDERED.
//!   `@` references: absolute and `~/` references are BLOCK
//!   (IMPORT_ESCAPE); relative references resolve **file-relative**
//!   (CQ-1 working assumption; U-09 still UNVERIFIED) with no depth
//!   cap, and allowed targets are expanded breadth-first.
//!
//! Unknown precedence is never guessed. Policy never changes *which*
//! files are discovered, except for the two discovery-affecting fields
//! `allow_nested_on_demand=false` (excludes on-demand sources) and
//! `allow_additional_directories=false` (the default; excludes Claude
//! additional-directory sources). De-duplication (S10) happens in the
//! receipt assembly: the same canonical file appears once, under the
//! first rule that discovered it; later rules are recorded in
//! `also_discovered_by`.

use std::collections::{HashMap, HashSet, VecDeque};

use crate::git::io_error_name;
use crate::paths::{
    canonicalize, hash_file, is_drive_absolute, is_within_root,
    is_windows_style_path, lexical_canonical, normalize_windows_path,
    normpath_posix,
};
use crate::textscan::{
    any_glob_matches, fnmatchcase, parse_applyto, parse_imports, parse_paths_frontmatter,
    read_text,
};
use crate::trust::Policy;

// ---------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Precedence {
    pub kind: &'static str,
    pub detail: &'static str,
}

#[derive(Debug, Clone)]
pub struct SourceCandidate {
    pub raw_path: String,
    pub canonical_path: String,
    pub resolved_path: Option<String>,
    pub scope: String,
    pub phase: String,
    pub discovery_rule: String,
    pub precedence: Precedence,
    pub sha256: Option<String>,
    pub exists: bool,
    pub is_symlink: bool,
    pub symlink_target: Option<String>,
    pub also_discovered_by: Vec<String>,
    pub depth: Option<u32>,
    pub error: Option<String>,
}

#[derive(Debug, Clone)]
pub struct NotApplicable {
    pub raw_path: String,
    pub canonical_path: Option<String>,
    pub discovery_rule: String,
    pub reason: String,
    pub detail: String,
}

#[derive(Debug, Clone)]
pub struct ImportEdge {
    pub from_canonical: String,
    pub syntax: String,
    pub canonical_target: Option<String>,
    pub resolved_target: Option<String>,
    pub depth: u32,
    pub exists: bool,
    pub allowed: bool,
    pub reason: String,
}

/// Inputs a profile discovery function needs.
pub struct ResolveContext {
    pub cwd: String,
    pub home: String,
    pub repo_root: Option<String>,
    pub policy: Policy,
    pub working_files: Vec<String>,
    pub additional_dirs: Vec<String>,
    pub custom_dirs: Vec<String>,
    pub copilot_home: Option<String>,
    pub managed_path: Option<String>,
    pub ancestor_stop: Option<String>,
    pub not_applicable: Vec<NotApplicable>,
}

// ---------------------------------------------------------------------------
// Precedence constants (detail strings verbatim from profile_contract.json)
// ---------------------------------------------------------------------------

const P_CODEX_USER: Precedence = Precedence {
    kind: "ORDERED",
    detail: "First in the chain: global instructions are injected before repo instructions.",
};
const P_CODEX_CHAIN: Precedence = Precedence {
    kind: "ORDERED",
    detail: "Root-to-leaf order: global first, then repo root, then each deeper directory; later (deeper) directories override earlier ones.",
};
const P_CODEX_OVERRIDE: Precedence = Precedence {
    kind: "UNSPECIFIED",
    detail: "Not defined in the fetched source: whether AGENTS.override.md replaces or supplements AGENTS.md in the same directory, and which directory's file wins, are unspecified.",
};
const P_CLAUDE_MANAGED: Precedence = Precedence {
    kind: "ORDERED",
    detail: "First: loaded before user and project instructions.",
};
const P_CLAUDE_USER: Precedence = Precedence {
    kind: "ORDERED",
    detail: "After managed, before project instructions.",
};
const P_CLAUDE_PROJECT: Precedence = Precedence {
    kind: "ORDERED",
    detail: "Concatenated from the filesystem root downward to the CWD (ancestors first, CWD last); files are concatenated, not overriding each other. Override semantics between files: UNSPECIFIED.",
};
const P_CLAUDE_LOCAL: Precedence = Precedence {
    kind: "ORDERED",
    detail: "In each directory, CLAUDE.local.md is appended after that directory's CLAUDE.md.",
};
const P_CLAUDE_RULES_USER: Precedence = Precedence {
    kind: "ORDERED",
    detail: "Loaded before project rules. On conflict, neither user nor project rules override the other.",
};
const P_CLAUDE_RULES_STARTUP: Precedence = Precedence {
    kind: "ORDERED",
    detail: "Same precedence as .claude/CLAUDE.md.",
};
const P_CLAUDE_AGENTS_FALLBACK: Precedence = Precedence {
    kind: "ORDERED",
    detail: "Root-to-CWD concatenation, same as the CLAUDE.md chain, when the condition holds.",
};
const P_CLAUDE_ON_DEMAND: Precedence = Precedence {
    kind: "UNSPECIFIED",
    detail: "Trigger is defined; ordering relative to the startup chain is not defined in the fetched source.",
};
const P_CLAUDE_PATH_SCOPED: Precedence = Precedence {
    kind: "UNSPECIFIED",
    detail: "Trigger is defined; ordering relative to other sources is not defined in the fetched source.",
};
const P_CLAUDE_ADDITIONAL: Precedence = Precedence {
    kind: "UNSPECIFIED",
    detail: "Ordering relative to the main chain is not defined in the fetched source.",
};
const P_COPILOT_COMBINE: Precedence = Precedence {
    kind: "COMBINE_UNORDERED",
    detail: "Combined with applicable instructions; no general precedence order between files.",
};
const P_COPILOT_USER: Precedence = Precedence {
    kind: "COMBINE_UNORDERED",
    detail: "Combined with applicable repository instructions; no general precedence order between files.",
};
const P_COPILOT_REPO_WIDE: Precedence = Precedence {
    kind: "COMBINE_UNORDERED",
    detail: "Combined with applicable user and repository instructions; no general precedence order between files.",
};

// (Per-rule copilot details, FIX-C06: copilot-cli.user and
// copilot-cli.repo-wide carry their own contract detail above; every
// other copilot rule uses the generic P_COPILOT_COMBINE.)

// ---------------------------------------------------------------------------
// Profile identity (frozen versions + rules hashes, from the contract)
// ---------------------------------------------------------------------------

pub struct ProfileInfo {
    pub id: &'static str,
    pub version: &'static str,
    pub rules_hash: &'static str,
}

pub fn profile_info(harness: &str) -> Option<ProfileInfo> {
    match harness {
        "codex" => Some(ProfileInfo {
            id: "codex",
            version: "codex-2026-11",
            rules_hash: "sha256:a0a03c1cdd77f8d9110ccbc77dae937e30e288a2609e6b04b60d26d15af5dc23",
        }),
        "claude-code" => Some(ProfileInfo {
            id: "claude-code",
            version: "claude-code-2026-11",
            rules_hash: "sha256:7f1d074dc0bb8dde1eace4c01498f8899b8ef58aa47f71c32c649768104f6058",
        }),
        "copilot-cli" => Some(ProfileInfo {
            id: "copilot-cli",
            version: "copilot-cli-2026-11",
            rules_hash: "sha256:76a5f6c8fbd7fc4ff910bf5f471ecb9291ab2a575d871f93338fb1b298c73d0e",
        }),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/// Directories from a top ancestor down to `cwd` (inclusive).
/// `stop` bounds the walk: the topmost ancestor to include (inclusive).
///
/// FIX-R5: on a Windows host a drive-letter `cwd` yields a *drive-form*
/// chain (`["C:/", "C:/repo", "C:/repo/shared"]`), mirroring the Python
/// `ancestor_chain` (`os_name="nt"`). The old `"/-prefixed"` shape
/// (`["/", "/C:", ...]`) is unconsumable on Windows: `"/C:/..."` is not
/// a drive-absolute spelling, so `canonicalize` sends it down the POSIX
/// branch and `Path::new("/C:/...")` never exists there — every
/// claude-code ancestor probe missed and the CLI returned 0 sources
/// (V4 E08-5 fail-open), while the runner's stop-collapsed `[cwd]` walk
/// still found the file. The drive-form chain is consumable (the drive
/// branch) and the stop filter now matches, so the walk is `[stop..cwd]`
/// instead of the degenerate `[cwd]` FIX-R3 recorded ("parity, not a
/// bug to fix alone" — both sides change together). On any other host
/// the old shape is kept byte-identical (FIX-R3 Linux simulation).
pub fn ancestor_chain(cwd: &str, stop: Option<&str>) -> Vec<String> {
    ancestor_chain_for_host(cwd, stop, cfg!(windows))
}

/// Host-selectable core of [`ancestor_chain`] (unit tests exercise the
/// Windows shape on Linux via `windows = true`; production passes
/// `cfg!(windows)`).
fn ancestor_chain_for_host(
    cwd: &str,
    stop: Option<&str>,
    windows: bool,
) -> Vec<String> {
    // Mirror the Python ancestor_chain: Windows spellings are
    // normalised to "C:/..." form first, so a backslash cwd takes
    // the drive-form branch too.
    let cwd = if windows && is_windows_style_path(cwd) {
        normalize_windows_path(cwd).unwrap_or_else(|_| normpath_posix(cwd))
    } else {
        normpath_posix(cwd)
    };
    if windows && is_drive_absolute(&cwd) {
        let drive = &cwd[..2]; // e.g. "C:"
        let rest: Vec<&str> = cwd[3..]
            .split('/')
            .filter(|c| !c.is_empty() && *c != ".")
            .collect();
        let mut chain = vec![format!("{drive}/")];
        let mut cur = drive.to_string();
        for part in rest {
            cur.push('/');
            cur.push_str(part);
            chain.push(cur.clone());
        }
        if let Some(stop) = stop {
            let stop = if windows && is_windows_style_path(stop) {
                normalize_windows_path(stop).unwrap_or_else(|_| normpath_posix(stop))
            } else {
                normpath_posix(stop)
            };
            if stop == format!("{drive}/") {
                return chain;
            }
            let filtered: Vec<String> = chain
                .into_iter()
                .filter(|d| d == &stop || d.starts_with(&format!("{stop}/")))
                .collect();
            if filtered.is_empty() || filtered[0] != stop {
                return vec![cwd];
            }
            return filtered;
        }
        return chain;
    }
    let parts: Vec<&str> = cwd.split('/').filter(|c| !c.is_empty()).collect();
    let mut chain = vec!["/".to_string()];
    let mut cur = String::new();
    for part in parts {
        cur.push('/');
        cur.push_str(part);
        chain.push(cur.clone());
    }
    if let Some(stop) = stop {
        let stop = normpath_posix(stop);
        if stop == "/" {
            return chain;
        }
        let filtered: Vec<String> = chain
            .into_iter()
            .filter(|d| d == &stop || d.starts_with(&format!("{stop}/")))
            .collect();
        if filtered.is_empty() || filtered[0] != stop {
            return vec![cwd];
        }
        return filtered;
    }
    chain
}

/// Directories from `repo_root` down to `cwd` (inclusive). When there
/// is no repo root (non-git workspace, S25) the chain is just `[cwd]`.
pub fn chain_dirs(repo_root: Option<&str>, cwd: &str) -> Vec<String> {
    let cwd = normpath_posix(cwd);
    let Some(root) = repo_root.map(normpath_posix) else {
        return vec![cwd];
    };
    if cwd == root {
        return vec![root];
    }
    if !cwd.starts_with(&format!("{root}/")) {
        return vec![cwd];
    }
    let rel = &cwd[root.len() + 1..];
    let mut out = vec![root.clone()];
    let mut cur = root;
    for part in rel.split('/') {
        cur.push('/');
        cur.push_str(part);
        out.push(cur.clone());
    }
    out
}

/// `path` relative to `base` with `/` separators, or `None`.
pub fn relative_posix(path: &str, base: &str) -> Option<String> {
    let path = normpath_posix(path);
    let base = normpath_posix(base);
    if path == base {
        return Some(String::new());
    }
    if base == "/" {
        return Some(path.trim_start_matches('/').to_string());
    }
    if let Some(rest) = path.strip_prefix(&format!("{base}/")) {
        return Some(rest.to_string());
    }
    None
}

/// Deterministically list files under `dir_canonical` (lexical paths).
/// Returns canonical (lexical, symlink-unresolved) absolute paths,
/// sorted. Directory symlinks are *not* descended into. A missing or
/// unreadable directory yields an empty list.
pub fn list_dir_files(
    dir_canonical: &str,
    recursive: bool,
    suffixes: Option<&[&str]>,
    filename_glob: Option<&str>,
) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let resolved = match std::fs::canonicalize(dir_canonical) {
        Ok(p) => p,
        Err(_) => return out,
    };
    let lex_root = normpath_posix(dir_canonical);
    let mut stack: Vec<(std::path::PathBuf, String)> = vec![(resolved, lex_root)];
    while let Some((real_dir, lex_dir)) = stack.pop() {
        let entries = match std::fs::read_dir(&real_dir) {
            Ok(e) => e,
            Err(_) => continue,
        };
        let mut children: Vec<(String, std::fs::DirEntry)> = Vec::new();
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            children.push((name, entry));
        }
        children.sort_by(|a, b| a.0.cmp(&b.0));
        let mut subdirs: Vec<(std::path::PathBuf, String)> = Vec::new();
        for (name, child) in children {
            let lex_child = if lex_dir == "/" {
                format!("/{name}")
            } else {
                format!("{lex_dir}/{name}")
            };
            let ft = match child.file_type() {
                Ok(ft) => ft,
                Err(_) => continue,
            };
            let is_dir = ft.is_dir();
            let is_link = ft.is_symlink();
            if is_dir && !is_link {
                if recursive {
                    subdirs.push((child.path(), lex_child));
                }
            } else if is_dir && is_link {
                continue; // never descend into a symlinked directory
            } else {
                if let Some(suffixes) = suffixes {
                    if !suffixes.iter().any(|s| name.ends_with(s)) {
                        continue;
                    }
                }
                if let Some(glob) = filename_glob {
                    if !fnmatchcase(&name, glob) {
                        continue;
                    }
                }
                out.push(normpath_posix(&lex_child));
            }
        }
        subdirs.reverse();
        stack.extend(subdirs);
    }
    out.sort();
    out
}

/// Byte size of the file at `canonical_path` (live read).
fn file_size(ctx: &ResolveContext, canonical_path: &str) -> Option<u64> {
    let canon = canonicalize(canonical_path, Some(&ctx.cwd), Some(&ctx.home)).ok()?;
    let resolved = canon.resolved_path?;
    std::fs::metadata(resolved).ok().map(|m| m.len())
}

// ---------------------------------------------------------------------------
// Candidate construction
// ---------------------------------------------------------------------------

/// Build a candidate for `raw_path`, or `None` when it is not a file.
/// A path that does not exist, or exists but is not a regular file,
/// produces no source. A file that cannot be read yields
/// `sha256=None` with `error="UNREADABLE: ..."` rather than a
/// fabricated hash.
pub fn make_candidate(
    ctx: &mut ResolveContext,
    raw_path: &str,
    scope: &str,
    phase: &str,
    discovery_rule: &str,
    precedence: Precedence,
) -> Option<SourceCandidate> {
    let canon = match canonicalize(raw_path, Some(&ctx.cwd), Some(&ctx.home)) {
        Ok(c) => c,
        Err(_) => {
            ctx.not_applicable.push(NotApplicable {
                raw_path: raw_path.to_string(),
                canonical_path: None,
                discovery_rule: discovery_rule.to_string(),
                reason: "NOT_A_FILE".to_string(),
                detail: "path could not be canonicalised".to_string(),
            });
            return None;
        }
    };
    if !canon.exists || !canon.is_file {
        return None;
    }
    let mut sha: Option<String> = None;
    let mut error: Option<String> = None;
    if let Some(resolved) = &canon.resolved_path {
        match hash_file(resolved) {
            Ok(h) => sha = Some(h),
            Err(e) => error = Some(format!("UNREADABLE: {}", io_error_name(&e))),
        }
    }
    if canon.error.is_some() {
        error = canon.error.clone();
    }
    Some(SourceCandidate {
        raw_path: raw_path.to_string(),
        canonical_path: canon.canonical_path,
        resolved_path: canon.resolved_path,
        scope: scope.to_string(),
        phase: phase.to_string(),
        discovery_rule: discovery_rule.to_string(),
        precedence,
        sha256: sha,
        exists: true,
        is_symlink: canon.is_symlink,
        symlink_target: canon.symlink_target,
        also_discovered_by: Vec::new(),
        depth: None,
        error,
    })
}

fn dir_name(path: &str) -> String {
    match path.rfind('/') {
        Some(0) => "/".to_string(),
        Some(i) => path[..i].to_string(),
        None => ".".to_string(),
    }
}

// ---------------------------------------------------------------------------
// Codex
// ---------------------------------------------------------------------------

pub fn discover_codex(ctx: &mut ResolveContext) -> Vec<SourceCandidate> {
    let mut out: Vec<SourceCandidate> = Vec::new();
    if let Some(user) = make_candidate(
        ctx,
        "~/.codex/AGENTS.md",
        "user",
        "startup",
        "codex.user",
        P_CODEX_USER,
    ) {
        out.push(user);
    }
    for directory in chain_dirs(ctx.repo_root.as_deref(), &ctx.cwd) {
        if let Some(agents) = make_candidate(
            ctx,
            &format!("{directory}/AGENTS.md"),
            "project",
            "startup",
            "codex.repo-chain",
            P_CODEX_CHAIN,
        ) {
            out.push(agents);
        }
        if let Some(ovr) = make_candidate(
            ctx,
            &format!("{directory}/AGENTS.override.md"),
            "project",
            "startup",
            "codex.override-fallback",
            P_CODEX_OVERRIDE,
        ) {
            out.push(ovr);
        }
    }
    out
}

// ---------------------------------------------------------------------------
// Claude Code
// ---------------------------------------------------------------------------

pub const MAX_IMPORT_DEPTH: u32 = 4;
pub const CLAUDE_MD_MAX_BYTES: u64 = 4_194_304;

const CLAUDE_RULES: &[&str] = &[
    "claude-code.managed",
    "claude-code.user",
    "claude-code.project",
    "claude-code.local",
    "claude-code.agents-fallback",
];

fn claude_file(
    ctx: &mut ResolveContext,
    raw_path: &str,
    scope: &str,
    rule: &str,
    precedence: Precedence,
) -> Option<SourceCandidate> {
    let canon = match canonicalize(raw_path, Some(&ctx.cwd), Some(&ctx.home)) {
        Ok(c) => c,
        Err(_) => return None,
    };
    if !canon.exists || !canon.is_file {
        return None;
    }
    let size = file_size(ctx, &canon.canonical_path);
    if let Some(size) = size {
        if size > CLAUDE_MD_MAX_BYTES {
            ctx.not_applicable.push(NotApplicable {
                raw_path: raw_path.to_string(),
                canonical_path: Some(canon.canonical_path),
                discovery_rule: rule.to_string(),
                reason: "OVERSIZE_CLAUDE_MD".to_string(),
                detail: "CLAUDE.md over 4 MiB is skipped by Claude Code".to_string(),
            });
            return None;
        }
    }
    make_candidate(ctx, raw_path, scope, "startup", rule, precedence)
}

fn rules_symlink_ok(ctx: &mut ResolveContext, cand: &SourceCandidate) -> bool {
    if !cand.is_symlink || cand.resolved_path.is_none() {
        return true;
    }
    let resolved = cand.resolved_path.as_ref().unwrap();
    let roots: Vec<&str> = [ctx.repo_root.as_deref(), Some(ctx.home.as_str())]
        .into_iter()
        .flatten()
        .collect();
    if roots.iter().any(|r| is_within_root(resolved, r)) {
        return true;
    }
    ctx.not_applicable.push(NotApplicable {
        raw_path: cand.raw_path.clone(),
        canonical_path: Some(cand.canonical_path.clone()),
        discovery_rule: cand.discovery_rule.clone(),
        reason: "SYMLINK_EXTERNAL_NOT_OBSERVED".to_string(),
        detail: "symlinked rules target outside working directories; external-import approval state is NOT_OBSERVED".to_string(),
    });
    false
}

#[allow(clippy::too_many_arguments)]
fn collect_rules(
    ctx: &mut ResolveContext,
    rules_dir: &str,
    scope: &str,
    rule_startup: &str,
    rule_path_scoped: &str,
    base_for_globs: &str,
    precedence_startup: Precedence,
) -> Vec<SourceCandidate> {
    let mut out: Vec<SourceCandidate> = Vec::new();
    for lex in list_dir_files(rules_dir, true, Some(&[".md"]), None) {
        let text = read_text(&lex);
        let paths = text
            .as_deref()
            .and_then(parse_paths_frontmatter);
        match paths {
            None => {
                if let Some(cand) = make_candidate(
                    ctx,
                    &lex,
                    scope,
                    "startup",
                    rule_startup,
                    precedence_startup.clone(),
                ) {
                    if rules_symlink_ok(ctx, &cand) {
                        out.push(cand);
                    }
                }
            }
            Some(patterns) => {
                if ctx.working_files.is_empty() {
                    ctx.not_applicable.push(NotApplicable {
                        raw_path: lex.clone(),
                        canonical_path: None,
                        discovery_rule: rule_path_scoped.to_string(),
                        reason: "PATH_SCOPED_NO_TRIGGER".to_string(),
                        detail: "paths-scoped rule needs a file Claude is working with"
                            .to_string(),
                    });
                    continue;
                }
                let mut matched = false;
                for wf in &ctx.working_files {
                    if let Some(rel) = relative_posix(wf, base_for_globs) {
                        if any_glob_matches(&patterns, &rel) {
                            matched = true;
                            break;
                        }
                    }
                }
                if !matched {
                    ctx.not_applicable.push(NotApplicable {
                        raw_path: lex.clone(),
                        canonical_path: None,
                        discovery_rule: rule_path_scoped.to_string(),
                        reason: "PATH_SCOPED_NO_MATCH".to_string(),
                        detail: "no working file matches the rule's paths globs".to_string(),
                    });
                    continue;
                }
                if let Some(cand) = make_candidate(
                    ctx,
                    &lex,
                    scope,
                    "on_demand",
                    rule_path_scoped,
                    P_CLAUDE_PATH_SCOPED,
                ) {
                    if rules_symlink_ok(ctx, &cand) {
                        out.push(cand);
                    }
                }
            }
        }
    }
    out
}

pub fn discover_claude(ctx: &mut ResolveContext) -> Vec<SourceCandidate> {
    let mut out: Vec<SourceCandidate> = Vec::new();

    // Managed (Linux path; overrideable for tests).
    let managed_raw = ctx
        .managed_path
        .clone()
        .unwrap_or_else(|| "/etc/claude-code/CLAUDE.md".to_string());
    if let Some(managed) = claude_file(
        ctx,
        &managed_raw,
        "managed",
        "claude-code.managed",
        P_CLAUDE_MANAGED,
    ) {
        out.push(managed);
    }

    // User CLAUDE.md + user rules.
    if let Some(user) = claude_file(
        ctx,
        "~/.claude/CLAUDE.md",
        "user",
        "claude-code.user",
        P_CLAUDE_USER,
    ) {
        out.push(user);
    }
    let home_rules = format!("{}/.claude/rules", ctx.home);
    let cwd_clone = ctx.cwd.clone();
    let mut user_rules = collect_rules(
        ctx,
        &home_rules,
        "user",
        "claude-code.rules-user",
        "claude-code.rules-path-scoped",
        &cwd_clone,
        P_CLAUDE_RULES_USER,
    );
    out.append(&mut user_rules);

    // Project chain: every ancestor, root to CWD.
    let ancestors = ancestor_chain(&ctx.cwd, ctx.ancestor_stop.as_deref());
    let mut claude_present_anywhere = false;
    for directory in &ancestors {
        for (name, rule, precedence) in [
            ("CLAUDE.md", "claude-code.project", P_CLAUDE_PROJECT),
            (".claude/CLAUDE.md", "claude-code.project", P_CLAUDE_PROJECT),
            ("CLAUDE.local.md", "claude-code.local", P_CLAUDE_LOCAL),
        ] {
            if let Some(cand) = claude_file(
                ctx,
                &format!("{directory}/{name}"),
                "project",
                rule,
                precedence,
            ) {
                claude_present_anywhere = true;
                out.push(cand);
            }
        }
        let rules_dir = format!("{directory}/.claude/rules");
        let dir_clone = directory.clone();
        let mut proj_rules = collect_rules(
            ctx,
            &rules_dir,
            "project",
            "claude-code.rules-startup",
            "claude-code.rules-path-scoped",
            &dir_clone,
            P_CLAUDE_RULES_STARTUP,
        );
        out.append(&mut proj_rules);
    }

    // AGENTS.md fallback: only when no CLAUDE file exists anywhere in
    // the CWD or above.
    if !claude_present_anywhere {
        for directory in &ancestors {
            for name in ["AGENTS.md", ".claude/AGENTS.md"] {
                if let Some(cand) = make_candidate(
                    ctx,
                    &format!("{directory}/{name}"),
                    "project",
                    "startup",
                    "claude-code.agents-fallback",
                    P_CLAUDE_AGENTS_FALLBACK,
                ) {
                    out.push(cand);
                }
            }
        }
    }

    // Nested on-demand: subdirectories below the CWD holding a
    // working file.
    if ctx.policy.allow_nested_on_demand && !ctx.working_files.is_empty() {
        let mut nested = nested_sources(ctx);
        out.append(&mut nested);
    } else if !ctx.working_files.is_empty() && !ctx.policy.allow_nested_on_demand {
        for wf in ctx.working_files.clone() {
            if let Some(rel) = relative_posix(&wf, &ctx.cwd) {
                if rel.contains('/') {
                    ctx.not_applicable.push(NotApplicable {
                        raw_path: wf,
                        canonical_path: None,
                        discovery_rule: "claude-code.nested".to_string(),
                        reason: "ON_DEMAND_DISABLED_BY_POLICY".to_string(),
                        detail: "allow_nested_on_demand is false".to_string(),
                    });
                }
            }
        }
    }

    // Additional directories: only when the policy allows them and
    // dirs were supplied.
    if ctx.policy.allow_additional_directories && !ctx.additional_dirs.is_empty() {
        for directory in ctx.additional_dirs.clone() {
            for (name, rule) in [
                ("CLAUDE.md", "claude-code.additional-dirs"),
                (".claude/CLAUDE.md", "claude-code.additional-dirs"),
                ("CLAUDE.local.md", "claude-code.additional-dirs"),
            ] {
                if let Some(cand) = claude_file(
                    ctx,
                    &format!("{directory}/{name}"),
                    "project",
                    rule,
                    P_CLAUDE_ADDITIONAL,
                ) {
                    out.push(cand);
                }
            }
            for lex in list_dir_files(
                &format!("{directory}/.claude/rules"),
                false,
                Some(&[".md"]),
                None,
            ) {
                let text = read_text(&lex);
                if let Some(t) = text.as_deref() {
                    if parse_paths_frontmatter(t).is_some() {
                        continue;
                    }
                }
                if let Some(cand) = make_candidate(
                    ctx,
                    &lex,
                    "project",
                    "startup",
                    "claude-code.additional-dirs",
                    P_CLAUDE_ADDITIONAL,
                ) {
                    out.push(cand);
                }
            }
        }
    } else if !ctx.additional_dirs.is_empty() && !ctx.policy.allow_additional_directories {
        for directory in ctx.additional_dirs.clone() {
            ctx.not_applicable.push(NotApplicable {
                raw_path: directory,
                canonical_path: None,
                discovery_rule: "claude-code.additional-dirs".to_string(),
                reason: "ADDITIONAL_DIRS_DISABLED_BY_POLICY".to_string(),
                detail: "allow_additional_directories is false (default)".to_string(),
            });
        }
    }

    out
}

fn nested_sources(ctx: &mut ResolveContext) -> Vec<SourceCandidate> {
    let mut subdirs: HashMap<String, usize> = HashMap::new();
    for wf in &ctx.working_files {
        let Some(rel) = relative_posix(wf, &ctx.cwd) else {
            continue;
        };
        if !rel.contains('/') {
            continue;
        }
        let parts: Vec<&str> = rel.split('/').collect();
        let mut cur = ctx.cwd.clone();
        for (i, part) in parts[..parts.len() - 1].iter().enumerate() {
            cur.push('/');
            cur.push_str(part);
            subdirs.entry(cur.clone()).or_insert(i + 1);
        }
    }
    let mut ordered: Vec<(usize, String)> =
        subdirs.into_iter().map(|(d, depth)| (depth, d)).collect();
    ordered.sort();
    let mut out: Vec<SourceCandidate> = Vec::new();
    for (_, directory) in ordered {
        let mut claude_here = false;
        for (name, rule) in [
            ("CLAUDE.md", "claude-code.nested"),
            ("CLAUDE.local.md", "claude-code.nested"),
        ] {
            if let Some(cand) = make_candidate(
                ctx,
                &format!("{directory}/{name}"),
                "nested",
                "on_demand",
                rule,
                P_CLAUDE_ON_DEMAND,
            ) {
                claude_here = true;
                out.push(cand);
            }
        }
        if !claude_here {
            if let Some(cand) = make_candidate(
                ctx,
                &format!("{directory}/AGENTS.md"),
                "nested",
                "on_demand",
                "claude-code.agents-nested",
                P_CLAUDE_ON_DEMAND,
            ) {
                out.push(cand);
            }
        }
    }
    out
}

// ---------------------------------------------------------------------------
// Copilot CLI
// ---------------------------------------------------------------------------

fn standard_dirs(ctx: &ResolveContext, include_intermediate: bool) -> Vec<String> {
    let chain = chain_dirs(ctx.repo_root.as_deref(), &ctx.cwd);
    let mut base: Vec<String> = if include_intermediate {
        chain.clone()
    } else if chain.is_empty() {
        Vec::new()
    } else {
        let keep: HashSet<&str> = [chain[0].as_str(), chain[chain.len() - 1].as_str()]
            .into_iter()
            .collect();
        chain
            .iter()
            .filter(|d| keep.contains(d.as_str()))
            .cloned()
            .collect()
    };
    let mut seen: HashSet<String> = base.iter().cloned().collect();
    let mut extra: Vec<(usize, String)> = Vec::new();
    for wf in &ctx.working_files {
        let Some(rel) = relative_posix(wf, &ctx.cwd) else {
            continue;
        };
        if !rel.contains('/') {
            continue;
        }
        let parts: Vec<&str> = rel.split('/').collect();
        let mut cur = ctx.cwd.clone();
        for (i, part) in parts[..parts.len() - 1].iter().enumerate() {
            cur.push('/');
            cur.push_str(part);
            if !seen.contains(&cur) {
                seen.insert(cur.clone());
                extra.push((i + 1, cur.clone()));
            }
        }
    }
    extra.sort();
    base.extend(extra.into_iter().map(|(_, d)| d));
    base
}

fn applyto_gate(
    ctx: &mut ResolveContext,
    lex_path: &str,
    rule: &str,
    base_for_globs: &str,
) -> bool {
    if ctx.working_files.is_empty() {
        ctx.not_applicable.push(NotApplicable {
            raw_path: lex_path.to_string(),
            canonical_path: None,
            discovery_rule: rule.to_string(),
            reason: "APPLYTO_NO_WORKING_FILE".to_string(),
            detail: "applyTo can only match a file Copilot is working with".to_string(),
        });
        return false;
    }
    let text = read_text(lex_path);
    let patterns = text.as_deref().and_then(parse_applyto);
    let Some(patterns) = patterns else {
        ctx.not_applicable.push(NotApplicable {
            raw_path: lex_path.to_string(),
            canonical_path: None,
            discovery_rule: rule.to_string(),
            reason: "APPLYTO_ABSENT_UNVERIFIED".to_string(),
            detail: "applyTo absent; behaviour for Copilot CLI is UNVERIFIED".to_string(),
        });
        return false;
    };
    for wf in &ctx.working_files {
        if let Some(rel) = relative_posix(wf, base_for_globs) {
            if any_glob_matches(&patterns, &rel) {
                return true;
            }
        }
    }
    ctx.not_applicable.push(NotApplicable {
        raw_path: lex_path.to_string(),
        canonical_path: None,
        discovery_rule: rule.to_string(),
        reason: "APPLYTO_NO_MATCH".to_string(),
        detail: "applyTo does not match any file Copilot is working with".to_string(),
    });
    false
}

fn modular_files(
    ctx: &mut ResolveContext,
    instructions_dir: &str,
    rule: &str,
    base_for_globs: &str,
) -> Vec<SourceCandidate> {
    let mut out: Vec<SourceCandidate> = Vec::new();
    for lex in list_dir_files(instructions_dir, true, None, Some("*.instructions.md")) {
        if !applyto_gate(ctx, &lex, rule, base_for_globs) {
            continue;
        }
        let scope = if rule == "copilot-cli.user-modular" {
            "user"
        } else {
            "project"
        };
        if let Some(cand) = make_candidate(
            ctx,
            &lex,
            scope,
            "on_demand",
            rule,
            P_COPILOT_COMBINE,
        ) {
            out.push(cand);
        }
    }
    out
}

pub fn discover_copilot(ctx: &mut ResolveContext) -> Vec<SourceCandidate> {
    let mut out: Vec<SourceCandidate> = Vec::new();
    let copilot_home = ctx
        .copilot_home
        .clone()
        .unwrap_or_else(|| format!("{}/.copilot", ctx.home));
    let repo_root_base = ctx.repo_root.clone().unwrap_or_else(|| ctx.cwd.clone());

    // User-level.
    if let Some(user) = make_candidate(
        ctx,
        &format!("{copilot_home}/copilot-instructions.md"),
        "user",
        "startup",
        "copilot-cli.user",
        P_COPILOT_USER,
    ) {
        out.push(user);
    }
    let user_mod_dir = format!("{copilot_home}/instructions");
    let cwd_clone = ctx.cwd.clone();
    let mut user_mod = modular_files(
        ctx,
        &user_mod_dir,
        "copilot-cli.user-modular",
        &cwd_clone,
    );
    out.append(&mut user_mod);

    // Repo-wide: .github/copilot-instructions.md (all standard dirs).
    for directory in standard_dirs(ctx, true) {
        if let Some(cand) = make_candidate(
            ctx,
            &format!("{directory}/.github/copilot-instructions.md"),
            "project",
            "startup",
            "copilot-cli.repo-wide",
            P_COPILOT_REPO_WIDE,
        ) {
            out.push(cand);
        }
    }

    // Repo-modular: standard dirs EXCEPT intermediate directories.
    for directory in standard_dirs(ctx, false) {
        let mod_dir = format!("{directory}/.github/instructions");
        let base = repo_root_base.clone();
        let mut mods = modular_files(ctx, &mod_dir, "copilot-cli.repo-modular", &base);
        out.append(&mut mods);
    }

    // Agents / Claude / Gemini in all standard locations.
    for directory in standard_dirs(ctx, true) {
        for (name, rule) in [
            ("AGENTS.md", "copilot-cli.agents"),
            ("CLAUDE.md", "copilot-cli.claude"),
            (".claude/CLAUDE.md", "copilot-cli.claude"),
            ("GEMINI.md", "copilot-cli.gemini"),
        ] {
            if let Some(cand) = make_candidate(
                ctx,
                &format!("{directory}/{name}"),
                "project",
                "startup",
                rule,
                P_COPILOT_COMBINE,
            ) {
                out.push(cand);
            }
        }
    }

    // Custom instruction directories.
    for directory in ctx.custom_dirs.clone() {
        let dir_canon = match lexical_canonical(&directory, Some(&ctx.cwd), Some(&ctx.home)) {
            Ok(d) => d,
            Err(_) => continue,
        };
        if let Some(cand) = make_candidate(
            ctx,
            &format!("{dir_canon}/AGENTS.md"),
            "project",
            "startup",
            "copilot-cli.custom-dirs",
            P_COPILOT_COMBINE,
        ) {
            out.push(cand);
        }
        for lex in list_dir_files(&dir_canon, false, None, Some("*.instructions.md")) {
            if !applyto_gate(ctx, &lex, "copilot-cli.custom-dirs", &repo_root_base) {
                continue;
            }
            if let Some(cand) = make_candidate(
                ctx,
                &lex,
                "project",
                "startup",
                "copilot-cli.custom-dirs",
                P_COPILOT_COMBINE,
            ) {
                out.push(cand);
            }
        }
    }

    out
}

/// Approved-root reason lookup, mirroring T005 `_reason_for_roots`:
/// first matching root wins, in order repo -> cwd -> custom dirs ->
/// additional dirs -> home. `home` may be `None` (Copilot: home is
/// NOT an approved root). A `None` resolved target means the path
/// could not be resolved at all (symlink loop) and is IMPORT_ESCAPE.
fn reason_for_roots(
    resolved: Option<&str>,
    repo_root: Option<&str>,
    cwd: &str,
    custom_dirs: &[String],
    additional_dirs: &[String],
    home: Option<&str>,
) -> (bool, String) {
    let Some(resolved) = resolved else {
        return (false, "IMPORT_ESCAPE".to_string());
    };
    if let Some(repo) = repo_root {
        if is_within_root(resolved, repo) {
            return (true, "WITHIN_REPO".to_string());
        }
    }
    if is_within_root(resolved, cwd) {
        return (true, "WITHIN_REPO".to_string());
    }
    if custom_dirs.iter().any(|d| is_within_root(resolved, d)) {
        return (true, "WITHIN_CUSTOM_DIR".to_string());
    }
    if additional_dirs
        .iter()
        .any(|d| is_within_root(resolved, d))
    {
        return (true, "WITHIN_REPO".to_string());
    }
    if let Some(home) = home {
        if is_within_root(resolved, home) {
            return (true, "WITHIN_HOME".to_string());
        }
    }
    (false, "IMPORT_ESCAPE".to_string())
}

/// True when a Copilot `@` reference is syntactically absolute or
/// home-based and therefore blocked by construction (T005): `/...`,
/// `~`, `~/...`, or a Windows drive spelling (`C:...` — second
/// character `:`; the check is on characters, not bytes, matching
/// Python's `ref[1] == ":"`).
fn copilot_syntactic_block(syntax: &str) -> bool {
    syntax.starts_with('/')
        || syntax == "~"
        || syntax.starts_with("~/")
        || syntax.chars().nth(1) == Some(':')
}

/// Whether a discovered source is expanded by the import walk.
/// Claude: managed/user/project/local/agents-fallback startup sources
/// only (rules files are not expanded). Copilot (CQ-5/CQ-6): rule in
/// {user, repo-wide, agents, claude, custom-dirs} AND basename in
/// {copilot-instructions.md, AGENTS.md, CLAUDE.md} AND NOT
/// (CLAUDE.md with `/.claude/` in the path — fail-closed, never
/// expanded). Codex has no `@` mechanism.
fn expandable(harness: &str, src: &SourceCandidate) -> bool {
    match harness {
        "claude-code" => {
            CLAUDE_RULES.contains(&src.discovery_rule.as_str()) && src.phase == "startup"
        }
        "copilot-cli" => {
            const RULES: &[&str] = &[
                "copilot-cli.user",
                "copilot-cli.repo-wide",
                "copilot-cli.agents",
                "copilot-cli.claude",
                "copilot-cli.custom-dirs",
            ];
            if !RULES.contains(&src.discovery_rule.as_str()) {
                return false;
            }
            let name = src.canonical_path.rsplit('/').next().unwrap_or("");
            if !matches!(
                name,
                "copilot-instructions.md" | "AGENTS.md" | "CLAUDE.md"
            ) {
                return false;
            }
            if name == "CLAUDE.md" && src.canonical_path.contains("/.claude/") {
                return false;
            }
            true
        }
        _ => false,
    }
}

/// Check one `@` reference and emit its edge, in the T005 check
/// order (escape before MISSING, CQ-10):
///
/// 1. Copilot syntactic block (absolute / `~/` / drive) -> IMPORT_ESCAPE,
///    canonical/resolved targets still computed when canonicalisable.
/// 2. Canonicalise failure (`~user`, NUL, ...) -> UNRESOLVABLE,
///    both targets null.
/// 3. Claude depth > 4 -> DEPTH_EXCEEDED, canonical+resolved kept.
/// 4. Resolved target None (symlink loop) -> IMPORT_ESCAPE, canonical
///    kept, resolved null.
/// 5. Approved roots -> escape (IMPORT_ESCAPE, targets kept) or
///    allowed (WITHIN_REPO / WITHIN_CUSTOM_DIR / WITHIN_HOME).
/// 6. Missing / not a regular file -> MISSING, both targets null.
///
/// Claude approved roots are repo + cwd + home + additional-dirs and
/// Copilot's are repo + cwd + custom-dirs (home excluded), exactly as
/// the T005 executable code computes them. NOTE (CQ-3 wording): the
/// coordinator's follow-up states the shorthand "repo + home" for
/// Claude; the code (and T005 §2.1) also counts cwd and
/// additional-dirs. The two readings coincide on every existing
/// fixture (cwd is always inside the repo there, no additional dirs
/// are set); the Oracle follows the code and flags the wording gap in
/// TASK_RESULT.md for the coordinator to confirm.
///
/// The returned edge's `exists` is the target's file existence from
/// the canonicalise step. A Copilot `@~user/...` reference fails
/// closed on both sides (canonicalisation raises, step 2 above
/// returns UNRESOLVABLE, targets null, exists=false) — C-08 was
/// NOT reproduced by the coordinator; the golden case
/// `copilot-tilde-user` pins this behaviour (FIX-C06).
fn check_edge(
    ctx: &ResolveContext,
    harness: &str,
    from_canonical: &str,
    syntax: &str,
    depth: u32,
) -> ImportEdge {
    let base_dir = dir_name(from_canonical);
    let emit = |canonical_target: Option<String>,
                resolved_target: Option<String>,
                exists: bool,
                allowed: bool,
                reason: &str| {
        ImportEdge {
            from_canonical: from_canonical.to_string(),
            syntax: format!("@{syntax}"),
            canonical_target,
            resolved_target,
            depth,
            exists,
            allowed,
            reason: reason.to_string(),
        }
    };

    // 1. Copilot syntactic block.
    if harness == "copilot-cli" && copilot_syntactic_block(syntax) {
        return match canonicalize(syntax, Some(&base_dir), Some(&ctx.home)) {
            Ok(canon) => emit(
                Some(canon.canonical_path),
                canon.resolved_path,
                canon.exists && canon.is_file,
                false,
                "IMPORT_ESCAPE",
            ),
            Err(_) => emit(None, None, false, false, "IMPORT_ESCAPE"),
        };
    }

    // 2. Canonicalise (resolves the file-relative base).
    let canon = match canonicalize(syntax, Some(&base_dir), Some(&ctx.home)) {
        Ok(c) => c,
        Err(_) => return emit(None, None, false, false, "UNRESOLVABLE"),
    };
    let canonical_target = Some(canon.canonical_path.clone());
    let resolved_target = canon.resolved_path.clone();
    let exists = canon.exists && canon.is_file;

    // 3. Claude depth cap (depth-5 is listed, never expanded).
    if harness == "claude-code" && depth > MAX_IMPORT_DEPTH {
        return emit(
            canonical_target,
            resolved_target,
            exists,
            false,
            "DEPTH_EXCEEDED",
        );
    }

    // 4. Symlink loop: no resolved target at all.
    if resolved_target.is_none() {
        return emit(canonical_target, None, exists, false, "IMPORT_ESCAPE");
    }

    // 5. Approved roots.
    let (allowed, reason) = if harness == "claude-code" {
        reason_for_roots(
            resolved_target.as_deref(),
            ctx.repo_root.as_deref(),
            &ctx.cwd,
            &[],
            &ctx.additional_dirs,
            Some(&ctx.home),
        )
    } else if harness == "copilot-cli" {
        reason_for_roots(
            resolved_target.as_deref(),
            ctx.repo_root.as_deref(),
            &ctx.cwd,
            &ctx.custom_dirs,
            &[],
            None,
        )
    } else {
        (true, "WITHIN_REPO".to_string())
    };
    if !allowed {
        return emit(canonical_target, resolved_target, exists, false, &reason);
    }

    // 6. Missing / not a regular file.
    if !exists {
        return emit(None, None, false, false, "MISSING");
    }
    emit(canonical_target, resolved_target, exists, true, &reason)
}

/// Build the `@` import graph for one harness (breadth-first).
///
/// Each file is expanded at most once, at its minimal depth;
/// identical `(from, syntax, target)` edges are listed once; an
/// allowed target is queued for expansion when first seen. Claude
/// expansion stops at depth 5: a depth-5 edge is listed (so the
/// BLOCK is observable) but never expanded. Copilot has no depth cap
/// and cycles terminate via the expanded set. The `from` of an edge
/// is the importing file's canonical path; the receipt assembly maps
/// it to a source id when the importer is a receipt source (CQ-2).
pub fn build_import_graph(
    ctx: &ResolveContext,
    sources: &[SourceCandidate],
    harness: &str,
) -> Vec<ImportEdge> {
    let mut edges: Vec<ImportEdge> = Vec::new();
    let mut seen_edges: HashSet<(String, String, Option<String>)> = HashSet::new();
    let mut expanded: HashSet<String> = HashSet::new();
    let mut queue: VecDeque<(String, u32)> = VecDeque::new();
    for src in sources {
        if expandable(harness, src) {
            queue.push_back((src.canonical_path.clone(), 0));
        }
    }
    while let Some((file_canonical, file_depth)) = queue.pop_front() {
        if expanded.contains(&file_canonical) {
            continue;
        }
        expanded.insert(file_canonical.clone());
        let Some(text) = read_text(&file_canonical) else {
            continue;
        };
        for syntax in parse_imports(&text) {
            let depth = file_depth + 1;
            let edge = check_edge(ctx, harness, &file_canonical, &syntax, depth);
            let key = (
                edge.from_canonical.clone(),
                edge.syntax.clone(),
                edge.canonical_target.clone(),
            );
            if seen_edges.contains(&key) {
                continue;
            }
            seen_edges.insert(key);
            if edge.allowed {
                if let Some(target) = &edge.canonical_target {
                    if !expanded.contains(target) {
                        queue.push_back((target.clone(), edge.depth));
                    }
                }
            }
            edges.push(edge);
        }
    }
    edges
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ancestor_chain_windows_drive_form() {
        // FIX-R5: on a Windows host a drive-letter cwd yields a
        // drive-form chain (mirrors the Python ancestor_chain with
        // os_name="nt"). The old "/-prefixed" shape is unconsumable
        // on Windows ("/C:/..." is not drive-absolute, so canonicalize
        // sends it down the POSIX branch and it never exists) — the
        // CLI returned 0 claude-code sources (V4 E08-5 fail-open).
        // The stop filter now matches, so the walk is [stop..cwd].
        assert_eq!(
            ancestor_chain_for_host("C:/repo/shared", None, true),
            vec!["C:/", "C:/repo", "C:/repo/shared"]
        );
        assert_eq!(
            ancestor_chain_for_host("C:\\repo\\shared", None, true),
            vec!["C:/", "C:/repo", "C:/repo/shared"]
        );
        assert_eq!(
            ancestor_chain_for_host("C:/repo/shared", Some("C:/repo"), true),
            vec!["C:/repo", "C:/repo/shared"]
        );
        assert_eq!(
            ancestor_chain_for_host("C:/repo/shared", Some("C:/"), true),
            vec!["C:/", "C:/repo", "C:/repo/shared"]
        );
        assert_eq!(
            ancestor_chain_for_host("C:/", None, true),
            vec!["C:/"]
        );
        // POSIX unchanged on any host; on Linux a Windows spelling
        // keeps the pinned "/C:" shape (FIX-R3 simulation behaviour).
        assert_eq!(
            ancestor_chain_for_host("C:/repo/shared", None, false),
            vec!["/", "/C:", "/C:/repo", "/C:/repo/shared"]
        );
        assert_eq!(
            ancestor_chain_for_host("/a/b/c", None, true),
            vec!["/", "/a", "/a/b", "/a/b/c"]
        );
        assert_eq!(
            ancestor_chain_for_host("/a/b/c", Some("/a"), false),
            vec!["/a", "/a/b", "/a/b/c"]
        );
    }
}
