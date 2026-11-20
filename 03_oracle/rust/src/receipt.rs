//! Receipt assembly — builds the deterministic receipt
//! (`receipt_schema.json`) from discovery + provenance + trust + import
//! edges, and computes the RFC 8785 canonical receipt hash.
//!
//! The receipt carries exactly the schema fields — nothing else.
//! `considered_but_not_applicable` (SPEC-04) stays in the
//! DiscoveryReport, NOT in the receipt (CQ-8), and
//! `also_discovered_by` likewise lives only in the `--explain`
//! sidecar, never in the receipt: T005's `build_receipt` rejects
//! unknown source fields, so either would break the receipt. The
//! explain sidecar carries both, plus per-edge depth and canonical
//! targets, so `compare_oracle.py` can still check them.
//! Optional-field choices are fixed here and documented, because the
//! hash covers every field present: `profile.rules_hash` and
//! `workspace.home` are always present; `policy` is always present;
//! every source always carries `symlink_target` (null when none) and
//! `is_symlink`; every edge always carries `resolved_target` (null
//! when unresolvable). An edge's `from` is the importer's source id
//! when it is a receipt source, else the importer's canonical path
//! (CQ-2); `to` is the target's source id when it is a source, else
//! null.
//!
//! De-duplication (S10): the same canonical file appears once, under
//! the first rule that discovered it; later rules are recorded in
//! `also_discovered_by`. The resolved path is NOT the dedup key — two
//! different lexical paths resolving to one file are different
//! canonical paths and are NOT merged.

use serde_json::{json, Value};

use crate::git::get_git_state;
use crate::jcs::{canonical_json, sha256_hex};
use crate::paths::{canonicalize, is_windows_style_path, lexical_canonical, normalize_windows_path};
use crate::profiles::{
    build_import_graph, discover_claude, discover_codex, discover_copilot, profile_info,
    ResolveContext, SourceCandidate,
};
use crate::trust::{classify_trust, derive_verdict, Policy, VerdictInput};

/// Error kinds, mapped to the frozen exit codes
/// (INPUT_ERROR 30 / UNSUPPORTED_PROFILE 40 / INTERNAL_ERROR 50).
#[derive(Debug)]
pub enum OracleError {
    InputError(String),
    UnsupportedProfile(String),
    InternalError(String),
}

impl OracleError {
    pub fn exit_code(&self) -> i32 {
        match self {
            OracleError::InputError(_) => 30,
            OracleError::UnsupportedProfile(_) => 40,
            OracleError::InternalError(_) => 50,
        }
    }

    pub fn verdict(&self) -> &'static str {
        match self {
            OracleError::InputError(_) => "INPUT_ERROR",
            OracleError::UnsupportedProfile(_) => "UNSUPPORTED_PROFILE",
            OracleError::InternalError(_) => "INTERNAL_ERROR",
        }
    }

    pub fn message(&self) -> &str {
        match self {
            OracleError::InputError(m)
            | OracleError::UnsupportedProfile(m)
            | OracleError::InternalError(m) => m,
        }
    }
}

/// FIX-R3 (D): receipt spelling for `sources[].raw_path`.
///
/// The frozen contract keeps `raw_path` verbatim at the discovery
/// layer ("Path as discovered", `receipt_schema.json`; Production's
/// `paths.py`: "the path exactly as supplied by the caller") — so
/// discovery, `canonicalize`, and the explain sidecar still carry
/// the caller's exact spelling, and this function is applied ONLY
/// here, at receipt assembly. The FIX-R3 freeze ruling unifies the
/// *receipt* spelling to `C:/...` (the `canonical_path` spelling):
/// on Windows Production stores the caller's original backslash
/// spelling (`C:\...\repo\AGENTS.md`) while the Oracle stores the
/// normalised spelling, and the two receipts then hash differently
/// even when every semantic field agrees (V2 class 2: behaviour
/// fully correct on both sides, hash parity still 0/4).
///
/// A Windows-style spelling becomes its normalised `C:/...` form
/// (backslashes, `.` / `..`, duplicate separators resolved exactly
/// as `canonical_path` does); anything else — `~/...`, relative,
/// POSIX — is emitted unchanged, so `~/.codex/AGENTS.md` and every
/// Linux receipt are byte-identical to before. On Linux this is a
/// no-op for every receipt the S0 fixtures produce (no receipt
/// `raw_path` there is a Windows spelling).
///
/// `workspace.cwd` / `home` / `repo_root` need no equivalent step:
/// they are already the canonical / resolved paths out of
/// `canonicalize`, which normalises a Windows spelling to `C:/...`
/// on a Windows host (verified by audit, not by a second rewrite —
/// re-normalising them here would only mask a `canonicalize` bug).
/// `git.repo` is normalised in `git.rs` (FIX-R3 C).
fn receipt_raw_path(raw: &str) -> String {
    if is_windows_style_path(raw) {
        normalize_windows_path(raw).unwrap_or_else(|_| raw.replace('\\', "/"))
    } else {
        raw.to_string()
    }
}

/// Split a comma-separated env dir list into canonical absolutes,
/// skipping empty and invalid parts.
fn split_env_dirs(value: Option<&str>, cwd: &str, home: &str) -> Vec<String> {
    let Some(value) = value else {
        return Vec::new();
    };
    let mut out: Vec<String> = Vec::new();
    for part in value.split(',') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if let Ok(dir) = lexical_canonical(part, Some(cwd), Some(home)) {
            out.push(dir);
        }
    }
    out
}

/// Resolve one case input into `(receipt, explain)`.
///
/// Case input JSON:
/// ```json
/// {
///   "case_id": "codex-basic",
///   "harness": "codex", "profile_version": "codex-2026-11",
///   "cwd": "/abs/path", "home": "/abs/path",
///   "repo_root": "/abs/path" | null,
///   "policy": "default" | { ...13 fields... },
///   "working_files": ["/abs/path", ...],
///   "env": {"COPILOT_HOME": "...", "COPILOT_CUSTOM_INSTRUCTIONS_DIRS": "...",
///           "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "..."},
///   "ancestor_stop": "/abs/path" | null,
///   "managed_path": "/abs/path" | null
/// }
/// ```
/// Only the fields above are read; the environment of the Oracle
/// process itself is never consulted (deterministic, no ambient leak).
pub fn resolve_case(input: &Value) -> Result<(Value, Value), OracleError> {
    let harness = input
        .get("harness")
        .and_then(|v| v.as_str())
        .ok_or_else(|| OracleError::InputError("case input needs a string \"harness\"".to_string()))?;
    let info = profile_info(harness).ok_or_else(|| {
        OracleError::UnsupportedProfile(format!("unknown harness: {harness:?}"))
    })?;
    if let Some(version) = input.get("profile_version").and_then(|v| v.as_str()) {
        if version != info.version {
            return Err(OracleError::UnsupportedProfile(format!(
                "profile version {version:?} does not match frozen {:?} for harness {harness:?}",
                info.version
            )));
        }
    }

    // Workspace validation (mirrors build_snapshot: cwd/home must be
    // existing directories; repo_root may be null or an existing dir).
    let cwd_raw = input
        .get("cwd")
        .and_then(|v| v.as_str())
        .ok_or_else(|| OracleError::InputError("case input needs a string \"cwd\"".to_string()))?;
    let home_raw = input
        .get("home")
        .and_then(|v| v.as_str())
        .ok_or_else(|| OracleError::InputError("case input needs a string \"home\"".to_string()))?;
    let cwd_canon = canonicalize(cwd_raw, None, None)
        .map_err(|e| OracleError::InputError(format!("invalid cwd: {e}")))?;
    let home_canon = canonicalize(home_raw, None, None)
        .map_err(|e| OracleError::InputError(format!("invalid home: {e}")))?;
    let cwd = cwd_canon.resolved_path.clone().ok_or_else(|| {
        OracleError::InputError(format!("cwd does not resolve: {cwd_raw}"))
    })?;
    // FIX-F6: the receipt's workspace.cwd is the canonical (lexical)
    // path per the frozen receipt schema ("Canonical absolute path of
    // the working directory", T002 Q1: canonical = normalized lexical
    // absolute path). Discovery keeps running on the resolved `cwd`
    // below — only the receipt field uses the lexical path.
    let cwd_lexical = cwd_canon.canonical_path.clone();
    let home = home_canon.resolved_path.clone().ok_or_else(|| {
        OracleError::InputError(format!("home does not resolve: {home_raw}"))
    })?;
    if !cwd_canon.exists || !cwd_canon.is_dir {
        return Err(OracleError::InputError(format!(
            "cwd does not exist or is not a directory: {cwd_raw}"
        )));
    }
    if !home_canon.exists || !home_canon.is_dir {
        return Err(OracleError::InputError(format!(
            "home does not exist or is not a directory: {home_raw}"
        )));
    }
    let repo_root: Option<String> = match input.get("repo_root") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) => {
            let canon = canonicalize(s, None, None)
                .map_err(|e| OracleError::InputError(format!("invalid repo_root: {e}")))?;
            if !canon.exists || !canon.is_dir {
                return Err(OracleError::InputError(format!(
                    "repo_root does not exist or is not a directory: {s}"
                )));
            }
            canon.resolved_path
        }
        Some(_) => {
            return Err(OracleError::InputError(
                "repo_root must be a string or null".to_string(),
            ));
        }
    };

    // Policy.
    let policy = match input.get("policy") {
        None | Some(Value::Null) => Policy::default(),
        Some(Value::String(s)) if s == "default" => Policy::default(),
        Some(obj) => Policy::from_json(Some(obj))
            .map_err(OracleError::InputError)?,
    };

    // Working files (canonical absolutes).
    let mut working_files: Vec<String> = Vec::new();
    if let Some(Value::Array(files)) = input.get("working_files") {
        for f in files {
            let raw = f.as_str().ok_or_else(|| {
                OracleError::InputError("working_files entries must be strings".to_string())
            })?;
            let canon = canonicalize(raw, Some(&cwd), Some(&home))
                .map_err(|e| OracleError::InputError(format!("invalid working file: {e}")))?;
            working_files.push(
                canon
                    .resolved_path
                    .clone()
                    .unwrap_or(canon.canonical_path),
            );
        }
    }

    // Environment (from the case input only).
    let env = input.get("env");
    let env_str = |key: &str| -> Option<String> {
        env.and_then(|e| e.get(key))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
    };
    let additional_dirs = split_env_dirs(
        env_str("CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD").as_deref(),
        &cwd,
        &home,
    );
    let custom_dirs = split_env_dirs(
        env_str("COPILOT_CUSTOM_INSTRUCTIONS_DIRS").as_deref(),
        &cwd,
        &home,
    );
    let copilot_home = match env_str("COPILOT_HOME") {
        Some(v) => lexical_canonical(&v, Some(&cwd), Some(&home)).ok(),
        None => None,
    };
    let ancestor_stop = match input.get("ancestor_stop") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) => canonicalize(s, Some(&cwd), Some(&home))
            .ok()
            .and_then(|c| c.resolved_path),
        Some(_) => {
            return Err(OracleError::InputError(
                "ancestor_stop must be a string or null".to_string(),
            ));
        }
    };
    let managed_path = input
        .get("managed_path")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let mut ctx = ResolveContext {
        cwd: cwd.clone(),
        home: home.clone(),
        repo_root: repo_root.clone(),
        policy: policy.clone(),
        working_files,
        additional_dirs,
        custom_dirs,
        copilot_home,
        managed_path,
        ancestor_stop,
        not_applicable: Vec::new(),
    };

    // Discovery.
    let mut found: Vec<SourceCandidate> = match harness {
        "codex" => discover_codex(&mut ctx),
        "claude-code" => discover_claude(&mut ctx),
        "copilot-cli" => discover_copilot(&mut ctx),
        _ => unreachable!(),
    };

    // S10 de-duplication by canonical path (first rule wins).
    let mut by_canonical: Vec<SourceCandidate> = Vec::new();
    for cand in found.drain(..) {
        if let Some(existing) = by_canonical
            .iter_mut()
            .find(|e| e.canonical_path == cand.canonical_path)
        {
            if !existing
                .also_discovered_by
                .contains(&cand.discovery_rule)
            {
                existing.also_discovered_by.push(cand.discovery_rule);
            }
        } else {
            by_canonical.push(cand);
        }
    }
    let sources = by_canonical;

    // Import edges (unified graph for claude-code and copilot-cli;
    // codex has no `@` mechanism).
    let edges = build_import_graph(&ctx, &sources, harness);

    // Source ids and edge targets.
    let source_ids: Vec<String> = (1..=sources.len())
        .map(|i| format!("src-{i:04}"))
        .collect();
    let canonical_to_id: std::collections::HashMap<&str, &str> = sources
        .iter()
        .zip(source_ids.iter())
        .map(|(s, id)| (s.canonical_path.as_str(), id.as_str()))
        .collect();
    let edge_ids: Vec<String> = (1..=edges.len())
        .map(|i| format!("edge-{i:04}"))
        .collect();

    // Provenance + trust per source.
    let mut source_jsons: Vec<Value> = Vec::new();
    let mut explain_sources: Vec<Value> = Vec::new();
    let mut trusts: Vec<String> = Vec::new();
    let mut reason_codes: Vec<String> = Vec::new();
    let mut details: Vec<String> = Vec::new();
    let mut git_states: Vec<crate::git::GitState> = Vec::new();
    for (idx, src) in sources.iter().enumerate() {
        let probe = src
            .resolved_path
            .clone()
            .unwrap_or_else(|| src.canonical_path.clone());
        let git_state = get_git_state(&probe, repo_root.as_deref());
        let classified = classify_trust(
            src.resolved_path.as_deref(),
            repo_root.as_deref(),
            Some(&home),
            Some(&git_state),
            Some(&src.canonical_path),
            src.is_symlink,
            None,
            false,
            Some(true),
            Some(src.precedence.kind),
            Some(&src.scope),
        );
        git_states.push(git_state.clone());
        trusts.push(classified.trust.clone());
        reason_codes.push(classified.reason_code.clone());
        details.push(classified.detail.clone());
        let mut precedence = json!({"kind": src.precedence.kind});
        if !src.precedence.detail.is_empty() {
            precedence["detail"] = json!(src.precedence.detail);
        }
        let src_json = json!({
            "source_id": source_ids[idx],
            // FIX-R3 (D): receipt spelling only — see
            // `receipt_raw_path`. Discovery keeps the verbatim value.
            "raw_path": receipt_raw_path(&src.raw_path),
            "canonical_path": src.canonical_path,
            "resolved_path": src.resolved_path,
            "scope": src.scope,
            "phase": src.phase,
            "discovery_rule": src.discovery_rule,
            "precedence": precedence,
            "sha256": src.sha256,
            "git": {
                "repo": git_state.repo,
                "tracked": git_state.tracked,
                "modified": git_state.modified,
                "head_commit": git_state.head_commit,
            },
            "trust": classified.trust,
            "symlink_target": src.symlink_target,
            "is_symlink": src.is_symlink,
        });
        source_jsons.push(src_json);
        explain_sources.push(json!({
            "source_id": source_ids[idx],
            "canonical_path": src.canonical_path,
            "also_discovered_by": src.also_discovered_by,
            "trust": trusts[idx],
            "reason_code": reason_codes[idx],
            "detail": details[idx],
        }));
    }

    // Import-escape trust override: a source reached by an escaping
    // import edge is IMPORT_ESCAPE (highest priority, R007).
    let mut edge_jsons: Vec<Value> = Vec::new();
    let mut explain_edges: Vec<Value> = Vec::new();
    for (idx, edge) in edges.iter().enumerate() {
        let to: Option<String> = edge
            .canonical_target
            .as_deref()
            .and_then(|t| canonical_to_id.get(t))
            .map(|id| id.to_string());
        if edge.reason == "IMPORT_ESCAPE" {
            if let Some(to_id) = &to {
                if let Some(pos) = source_ids.iter().position(|id| id == to_id) {
                    let src = &sources[pos];
                    let reclassified = classify_trust(
                        src.resolved_path.as_deref(),
                        repo_root.as_deref(),
                        Some(&home),
                        Some(&git_states[pos]),
                        Some(&src.canonical_path),
                        src.is_symlink,
                        None,
                        true,
                        Some(true),
                        Some(src.precedence.kind),
                        Some(&src.scope),
                    );
                    trusts[pos] = reclassified.trust.clone();
                    reason_codes[pos] = reclassified.reason_code.clone();
                    details[pos] = reclassified.detail.clone();
                    source_jsons[pos]["trust"] = json!(trusts[pos]);
                    explain_sources[pos]["trust"] = json!(trusts[pos]);
                    explain_sources[pos]["reason_code"] = json!(reason_codes[pos]);
                    explain_sources[pos]["detail"] = json!(details[pos]);
                }
            }
        }
        edge_jsons.push(json!({
            "edge_id": edge_ids[idx],
            // CQ-2: a depth>=2 importer is not a receipt source, so
            // `from` falls back to its canonical path.
            "from": canonical_to_id
                .get(edge.from_canonical.as_str())
                .copied()
                .unwrap_or(edge.from_canonical.as_str()),
            "syntax": edge.syntax,
            "to": to,
            "resolved_target": edge.resolved_target,
            "allowed": edge.allowed,
            "reason": edge.reason,
        }));
        explain_edges.push(json!({
            "edge_id": edge_ids[idx],
            "from": edge.from_canonical,
            "syntax": edge.syntax,
            "depth": edge.depth,
            "canonical_target": edge.canonical_target,
            "resolved_target": edge.resolved_target,
            "allowed": edge.allowed,
            "reason": edge.reason,
        }));
    }

    // Verdict.
    let verdict_inputs: Vec<VerdictInput> = sources
        .iter()
        .zip(trusts.iter())
        .map(|(s, t)| VerdictInput {
            trust: t,
            scope: &s.scope,
            precedence_kind: s.precedence.kind,
        })
        .collect();
    let edges_allowed: Vec<bool> = edges.iter().map(|e| e.allowed).collect();
    let verdict = derive_verdict(&verdict_inputs, &edges_allowed, &policy);

    // Receipt (without the hash first).
    let mut receipt = json!({
        "receipt_version": 1,
        "profile": {
            "id": info.id,
            "version": info.version,
            "rules_hash": info.rules_hash,
        },
        "workspace": {
            "cwd": cwd_lexical,
            "repo_root": repo_root,
            "home": home,
        },
        "sources": source_jsons,
        "edges": edge_jsons,
        "policy": {
            "policy_schema_version": 1,
            "values": policy.to_json(),
        },
        "verdict": verdict,
    });
    let canonical = canonical_json(&receipt);
    let receipt_hash = sha256_hex(canonical.as_bytes());
    receipt["receipt_hash"] = json!(receipt_hash);

    // The explain sidecar carries what the receipt schema has no slot
    // for: per-source reason codes, also_discovered_by, per-edge depth
    // and canonical targets, and the SPEC-04 not-applicable list
    // (which lives in the DiscoveryReport, not in the receipt, CQ-8).
    let explain = json!({
        "case_id": input.get("case_id").and_then(|v| v.as_str()),
        "harness": harness,
        "sources": explain_sources,
        "edges": explain_edges,
        "considered_but_not_applicable": ctx.not_applicable.iter().map(|n| {
            json!({
                "raw_path": n.raw_path,
                "canonical_path": n.canonical_path,
                "discovery_rule": n.discovery_rule,
                "reason": n.reason,
                "detail": n.detail,
            })
        }).collect::<Vec<Value>>(),
    });
    Ok((receipt, explain))
}

#[cfg(test)]
mod tests {
    use super::*;

    // FIX-R3 (D): only a Windows-style spelling is rewritten, and
    // only to the `C:/...` form `canonical_path` uses. Everything
    // else — the `~/...` spellings discovery actually emits, relative
    // paths, POSIX paths — passes through byte-identical, so Linux
    // receipts and the S0 fixtures are unaffected.
    #[test]
    fn receipt_raw_path_spelling() {
        // Backslash drive spelling -> `C:/...` (the V2 class-2 gap:
        // Production stored this verbatim, the Oracle normalised).
        assert_eq!(
            receipt_raw_path("C:\\p028-src-v2\\repo\\AGENTS.md"),
            "C:/p028-src-v2/repo/AGENTS.md"
        );
        // Already-normalised drive spelling: unchanged.
        assert_eq!(
            receipt_raw_path("C:/repo/AGENTS.md"),
            "C:/repo/AGENTS.md"
        );
        // Lexical `.` / `..` / duplicate separators resolve, exactly
        // as `canonical_path` does.
        assert_eq!(
            receipt_raw_path("C:\\repo\\services\\..\\AGENTS.md"),
            "C:/repo/AGENTS.md"
        );
        // UNC spelling normalises its separators too.
        assert_eq!(
            receipt_raw_path("\\\\server\\share\\x.md"),
            "//server/share/x.md"
        );
        // Discovery spellings: verbatim, never rewritten.
        assert_eq!(receipt_raw_path("~/.codex/AGENTS.md"), "~/.codex/AGENTS.md");
        assert_eq!(receipt_raw_path("~/.claude/CLAUDE.md"), "~/.claude/CLAUDE.md");
        assert_eq!(receipt_raw_path("rel/path.md"), "rel/path.md");
        assert_eq!(receipt_raw_path("/repo/AGENTS.md"), "/repo/AGENTS.md");
        // Drive-relative (`C:foo`) is not a Windows-style absolute
        // spelling: verbatim.
        assert_eq!(receipt_raw_path("C:foo"), "C:foo");
    }
}
