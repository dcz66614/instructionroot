//! Trust classification — independent Rust implementation of the P028
//! contract (PROJECT_BOOK.md §13.4; receipt_schema.json `trust_enum` /
//! `trust_priority`; policy_schema.json verdict derivation; coordinator
//! rulings SPEC-02/SPEC-03/SPEC-05, R009/R010).
//!
//! Priority order (§13.4, highest first):
//!
//! ```text
//! IMPORT_ESCAPE
//! SYMLINK_ESCAPE
//! MISSING
//! OUTSIDE_REPO
//! GIT_UNTRACKED
//! GIT_MODIFIED
//! GIT_TRACKED
//! USER_SCOPE
//! ```
//!
//! The first condition that applies wins. Containment is always judged
//! on the **resolved** path. Policy never changes the trust value: it
//! only changes the verdict for a discovered file.
//!
//! Reason codes (IMPLEMENTATION_PLAN.md §9.4):
//!
//! ```text
//! R001 WITHIN_REPO_TRACKED        -> GIT_TRACKED
//! R002 WITHIN_REPO_MODIFIED       -> GIT_MODIFIED
//! R003 WITHIN_REPO_UNTRACKED      -> GIT_UNTRACKED
//! R004 USER_SCOPE                 -> USER_SCOPE
//! R005 OUTSIDE_REPO               -> OUTSIDE_REPO
//! R006 SYMLINK_ESCAPE             -> SYMLINK_ESCAPE
//! R007 IMPORT_ESCAPE              -> IMPORT_ESCAPE
//! R008 MISSING                    -> MISSING
//! R009 NOT_OBSERVED               -> NOT_OBSERVED
//! R010 UNSPECIFIED_PRECEDENCE     -> (annotates, no trust of its own)
//! ```
//!
//! Two forced mappings (frozen enum has no value for them; no new enum
//! value invented):
//! * **Managed scope** (`scope="managed"`): classified USER_SCOPE /
//!   R004 (SPEC-05, coordinator-accepted). The verdict layer must still
//!   apply `allow_managed_scope` separately.
//! * **R010** only annotates when the base reason is R001/R004; a more
//!   specific reason (R002/R003/R005–R008) already says what matters.
//!   The trust value stays the provenance-derived one.
//!
//! The receipt schema carries no reason-code slot, so R001–R010 are
//! internal classification evidence: the Oracle asserts them in its unit
//! tests and reports them via `--explain`; the receipt itself carries
//! only the `trust` value.

use crate::git::GitState;
use crate::paths::is_within_root;

/// Trust priority order, PROJECT_BOOK.md §13.4. NOT_OBSERVED has no
/// position here (SPEC-03).
pub const TRUST_PRIORITY: &[&str] = &[
    "IMPORT_ESCAPE",
    "SYMLINK_ESCAPE",
    "MISSING",
    "OUTSIDE_REPO",
    "GIT_UNTRACKED",
    "GIT_MODIFIED",
    "GIT_TRACKED",
    "USER_SCOPE",
];

/// Return the §13.4 priority index of `trust` (0 = highest).
/// `None` for NOT_OBSERVED (no priority position, SPEC-03) and for any
/// value outside the trust enum.
pub fn trust_priority_index(trust: &str) -> Option<usize> {
    TRUST_PRIORITY.iter().position(|t| *t == trust)
}

/// The outcome of [`classify_trust`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrustResult {
    pub trust: String,
    pub reason_code: String,
    pub detail: String,
}

/// Classify one source path into (trust, reason_code).
///
/// * `resolved_path` — canonical path after symlink resolution;
///   `None` when resolution failed (loop / unresolvable), which yields
///   NOT_OBSERVED / R009.
/// * `repo_root` / `home` — the approved roots (absolute paths, or
///   `None` when there is no repository / no home root to judge
///   against). A repository under the home still counts as a repository
///   first: the §13.4 order puts every GIT_* value above USER_SCOPE.
/// * `git_state` — `None` when no Git state was supplied at all (the
///   Oracle always probes, so it passes `Some`; `None` is only the
///   "cannot observe" case, R009).
/// * `canonical_path` — lexical path before symlink resolution.
/// * `is_symlink_escape` — explicit override (`None` derives it: the
///   canonical path lies within an approved root while the resolved
///   path lies outside every approved root).
/// * `is_import_escape` — true when an import/reference edge reaching
///   this source escapes the approved roots (edge-level fact).
/// * `exists` — whether the resolved target exists; `None` checks the
///   filesystem.
/// * `precedence_kind` — the harness precedence kind for this source;
///   `"UNSPECIFIED"` yields reason R010 when no more specific reason
///   applies (trust unchanged).
/// * `scope` — the harness scope (`"managed"` maps to USER_SCOPE /
///   R004; other scopes do not override provenance).
#[allow(clippy::too_many_arguments)]
pub fn classify_trust(
    resolved_path: Option<&str>,
    repo_root: Option<&str>,
    home: Option<&str>,
    git_state: Option<&GitState>,
    canonical_path: Option<&str>,
    is_symlink: bool,
    is_symlink_escape: Option<bool>,
    is_import_escape: bool,
    exists: Option<bool>,
    precedence_kind: Option<&str>,
    scope: Option<&str>,
) -> TrustResult {
    let resolved_path = match resolved_path {
        None => {
            return TrustResult {
                trust: "NOT_OBSERVED".to_string(),
                reason_code: "R009".to_string(),
                detail: "resolved path is unavailable (symlink loop or unresolvable); provenance cannot be observed".to_string(),
            };
        }
        Some(p) => p,
    };
    let resolved = crate::paths::normpath_posix(resolved_path);
    let canonical = canonical_path
        .map(crate::paths::normpath_posix)
        .unwrap_or_else(|| resolved.clone());
    let repo = repo_root.map(crate::paths::normpath_posix);
    let home_root = home.map(crate::paths::normpath_posix);

    let exists = exists.unwrap_or_else(|| std::path::Path::new(&resolved).exists());

    // SYMLINK_ESCAPE derivation (only when not overridden).
    let is_symlink_escape = match is_symlink_escape {
        Some(v) => v,
        None => {
            let symlink_seen = is_symlink || canonical != resolved;
            let allowed_roots: Vec<&str> = [repo.as_deref(), home_root.as_deref()]
                .into_iter()
                .flatten()
                .collect();
            if symlink_seen && !allowed_roots.is_empty() {
                let canonical_within = allowed_roots
                    .iter()
                    .any(|r| is_within_root(&canonical, r));
                let resolved_within = allowed_roots
                    .iter()
                    .any(|r| is_within_root(&resolved, r));
                canonical_within && !resolved_within
            } else {
                false
            }
        }
    };

    // §13.4 priority order: first matching condition wins.
    let mut result = if is_import_escape {
        TrustResult {
            trust: "IMPORT_ESCAPE".to_string(),
            reason_code: "R007".to_string(),
            detail: "import/reference edge escapes the approved roots".to_string(),
        }
    } else if is_symlink_escape {
        TrustResult {
            trust: "SYMLINK_ESCAPE".to_string(),
            reason_code: "R006".to_string(),
            detail: format!(
                "symlink target escapes the approved roots: canonical {canonical} resolves to {resolved}"
            ),
        }
    } else if !exists {
        TrustResult {
            trust: "MISSING".to_string(),
            reason_code: "R008".to_string(),
            detail: format!("resolved path does not exist: {resolved}"),
        }
    } else if let Some(repo) = &repo {
        if is_within_root(&resolved, repo) {
            match git_state {
                None => TrustResult {
                    trust: "NOT_OBSERVED".to_string(),
                    reason_code: "R009".to_string(),
                    detail: "inside repository but no git state was supplied; tracked/modified cannot be observed".to_string(),
                },
                Some(state) if !state.tracked => TrustResult {
                    trust: "GIT_UNTRACKED".to_string(),
                    reason_code: "R003".to_string(),
                    detail: "inside repository but not tracked by git".to_string(),
                },
                Some(state) if state.modified => TrustResult {
                    trust: "GIT_MODIFIED".to_string(),
                    reason_code: "R002".to_string(),
                    detail: "tracked by git and modified against HEAD".to_string(),
                },
                Some(_) => TrustResult {
                    trust: "GIT_TRACKED".to_string(),
                    reason_code: "R001".to_string(),
                    detail: "tracked by git and unmodified against HEAD".to_string(),
                },
            }
        } else if scope == Some("managed") {
            TrustResult {
                trust: "USER_SCOPE".to_string(),
                reason_code: "R004".to_string(),
                detail: "managed-scope source (no MANAGED trust value in the frozen enum; classified as approved non-repo scope — see contract issue in TASK_RESULT.md)".to_string(),
            }
        } else if let Some(home_root) = &home_root {
            if is_within_root(&resolved, home_root) {
                TrustResult {
                    trust: "USER_SCOPE".to_string(),
                    reason_code: "R004".to_string(),
                    detail: "inside the user home and outside any repository".to_string(),
                }
            } else {
                TrustResult {
                    trust: "OUTSIDE_REPO".to_string(),
                    reason_code: "R005".to_string(),
                    detail: "outside the repository and outside the user home".to_string(),
                }
            }
        } else {
            TrustResult {
                trust: "OUTSIDE_REPO".to_string(),
                reason_code: "R005".to_string(),
                detail: "outside the repository and outside the user home".to_string(),
            }
        }
    } else if scope == Some("managed") {
        TrustResult {
            trust: "USER_SCOPE".to_string(),
            reason_code: "R004".to_string(),
            detail: "managed-scope source (no MANAGED trust value in the frozen enum; classified as approved non-repo scope — see contract issue in TASK_RESULT.md)".to_string(),
        }
    } else if let Some(home_root) = &home_root {
        if is_within_root(&resolved, home_root) {
            TrustResult {
                trust: "USER_SCOPE".to_string(),
                reason_code: "R004".to_string(),
                detail: "inside the user home and outside any repository".to_string(),
            }
        } else {
            TrustResult {
                trust: "OUTSIDE_REPO".to_string(),
                reason_code: "R005".to_string(),
                detail: "outside the repository and outside the user home".to_string(),
            }
        }
    } else {
        TrustResult {
            trust: "OUTSIDE_REPO".to_string(),
            reason_code: "R005".to_string(),
            detail: "outside the repository and outside the user home".to_string(),
        }
    };

    // R010: unspecified precedence annotates, never overrides. Only the
    // two "plain" reasons are annotated.
    if precedence_kind == Some("UNSPECIFIED")
        && (result.reason_code == "R001" || result.reason_code == "R004")
    {
        result.reason_code = "R010".to_string();
        result.detail = format!(
            "{}; precedence is UNSPECIFIED by the harness profile (no order invented)",
            result.detail
        );
    }
    result
}

/// The 13 frozen policy fields (policy_schema.json `default_policy`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Policy {
    pub allow_user_scope: bool,
    pub allow_repo_tracked: bool,
    pub allow_managed_scope: bool,
    pub allow_nested_on_demand: bool,
    pub block_repo_untracked: bool,
    pub block_repo_modified: bool,
    pub block_outside_repo: bool,
    pub block_symlink_escape: bool,
    pub block_import_escape: bool,
    pub block_missing_reference: bool,
    pub warn_on_unspecified_precedence: bool,
    pub treat_warn_as_block: bool,
    pub allow_additional_directories: bool,
}

impl Default for Policy {
    fn default() -> Self {
        Policy {
            allow_user_scope: true,
            allow_repo_tracked: true,
            allow_managed_scope: true,
            allow_nested_on_demand: true,
            block_repo_untracked: false,
            block_repo_modified: false,
            block_outside_repo: true,
            block_symlink_escape: true,
            block_import_escape: true,
            block_missing_reference: true,
            warn_on_unspecified_precedence: true,
            treat_warn_as_block: false,
            allow_additional_directories: false,
        }
    }
}

impl Policy {
    /// Merge a caller policy object over the defaults, rejecting bad
    /// input (unknown field, non-bool value). `None` means defaults.
    pub fn from_json(value: Option<&serde_json::Value>) -> Result<Policy, String> {
        let mut policy = Policy::default();
        let Some(value) = value else {
            return Ok(policy);
        };
        let obj = value
            .as_object()
            .ok_or_else(|| "policy must be a dict or None".to_string())?;
        let known = [
            "allow_user_scope",
            "allow_repo_tracked",
            "allow_managed_scope",
            "allow_nested_on_demand",
            "block_repo_untracked",
            "block_repo_modified",
            "block_outside_repo",
            "block_symlink_escape",
            "block_import_escape",
            "block_missing_reference",
            "warn_on_unspecified_precedence",
            "treat_warn_as_block",
            "allow_additional_directories",
        ];
        for key in obj.keys() {
            if !known.contains(&key.as_str()) {
                return Err(format!("unknown policy field(s): {key}"));
            }
        }
        let get = |key: &str| -> Result<Option<bool>, String> {
            match obj.get(key) {
                None => Ok(None),
                Some(v) => v
                    .as_bool()
                    .map(Some)
                    .ok_or_else(|| format!("policy field {key:?} must be a bool")),
            }
        };
        if let Some(v) = get("allow_user_scope")? {
            policy.allow_user_scope = v;
        }
        if let Some(v) = get("allow_repo_tracked")? {
            policy.allow_repo_tracked = v;
        }
        if let Some(v) = get("allow_managed_scope")? {
            policy.allow_managed_scope = v;
        }
        if let Some(v) = get("allow_nested_on_demand")? {
            policy.allow_nested_on_demand = v;
        }
        if let Some(v) = get("block_repo_untracked")? {
            policy.block_repo_untracked = v;
        }
        if let Some(v) = get("block_repo_modified")? {
            policy.block_repo_modified = v;
        }
        if let Some(v) = get("block_outside_repo")? {
            policy.block_outside_repo = v;
        }
        if let Some(v) = get("block_symlink_escape")? {
            policy.block_symlink_escape = v;
        }
        if let Some(v) = get("block_import_escape")? {
            policy.block_import_escape = v;
        }
        if let Some(v) = get("block_missing_reference")? {
            policy.block_missing_reference = v;
        }
        if let Some(v) = get("warn_on_unspecified_precedence")? {
            policy.warn_on_unspecified_precedence = v;
        }
        if let Some(v) = get("treat_warn_as_block")? {
            policy.treat_warn_as_block = v;
        }
        if let Some(v) = get("allow_additional_directories")? {
            policy.allow_additional_directories = v;
        }
        Ok(policy)
    }

    /// Serialise the policy values exactly as policy_schema.json
    /// `default_policy` shape (for the receipt `policy.values`).
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "allow_user_scope": self.allow_user_scope,
            "allow_repo_tracked": self.allow_repo_tracked,
            "allow_managed_scope": self.allow_managed_scope,
            "allow_nested_on_demand": self.allow_nested_on_demand,
            "block_repo_untracked": self.block_repo_untracked,
            "block_repo_modified": self.block_repo_modified,
            "block_outside_repo": self.block_outside_repo,
            "block_symlink_escape": self.block_symlink_escape,
            "block_import_escape": self.block_import_escape,
            "block_missing_reference": self.block_missing_reference,
            "warn_on_unspecified_precedence": self.warn_on_unspecified_precedence,
            "treat_warn_as_block": self.treat_warn_as_block,
            "allow_additional_directories": self.allow_additional_directories,
        })
    }
}

/// One source's verdict-relevant facts.
pub struct VerdictInput<'a> {
    pub trust: &'a str,
    pub scope: &'a str,
    pub precedence_kind: &'a str,
}

/// Derive the receipt verdict from trust values, precedence kinds,
/// edge allow-flags and the policy (policy_schema.json
/// `verdict_derivation`).
///
/// * BLOCK: a source whose trust is OUTSIDE_REPO / SYMLINK_ESCAPE /
///   IMPORT_ESCAPE while the corresponding `block_*` field is true; an
///   edge with `allowed=false` while `block_import_escape` or
///   `block_missing_reference` is true; a user / managed / tracked
///   source while its `allow_*` field is false; `treat_warn_as_block`
///   with a WARN condition present. A source whose trust is
///   NOT_OBSERVED or MISSING is BLOCK fail-closed (the contract's
///   verdict derivation does not name them; T008 owns the final word —
///   the Oracle never silently PASSes an unobserved source).
/// * WARN: a GIT_UNTRACKED in-repo source while `block_repo_untracked`
///   is false; a GIT_MODIFIED source while `block_repo_modified` is
///   false; a source with precedence kind UNSPECIFIED while
///   `warn_on_unspecified_precedence` is true.
/// * PASS: no BLOCK and no WARN condition applies.
/// * `block_repo_untracked=true` / `block_repo_modified=true`
///   escalate the corresponding WARN to BLOCK.
pub fn derive_verdict(
    sources: &[VerdictInput],
    edges_allowed: &[bool],
    policy: &Policy,
) -> &'static str {
    let mut block = false;
    let mut warn = false;
    // Mirrors T005 `receipt.derive_verdict` exactly (same structure and
    // same branch order), so verdict parity is structural, not argued:
    //  * NOT_OBSERVED trust is fail-closed BLOCK (CQ-9).
    //  * MISSING trust blocks only when `block_missing_reference`
    //    (a MISSING receipt source is otherwise unreachable — discovered
    //    sources exist — so this branch is defensive).
    //  * GIT_MODIFIED blocks only on `block_repo_modified`; it does NOT
    //    inherit the `allow_repo_tracked` block (that applies to
    //    GIT_TRACKED only).
    //  * User/managed-scope checks are independent of trust: they key on
    //    `scope`, not on trust == USER_SCOPE. A managed-scope source is
    //    blocked by `!allow_managed_scope` whatever its trust is; a
    //    GIT_TRACKED source is blocked by `!allow_repo_tracked`.
    //  * Any disallowed edge blocks when `block_import_escape` OR
    //    `block_missing_reference` is true (policy-literal reading,
    //    CQ-10); `treat_warn_as_block` escalates a WARN afterwards.
    for src in sources {
        match src.trust {
            "NOT_OBSERVED" => {
                block = true;
            }
            "MISSING" => {
                if policy.block_missing_reference {
                    block = true;
                }
            }
            "OUTSIDE_REPO" => {
                if policy.block_outside_repo {
                    block = true;
                }
            }
            "SYMLINK_ESCAPE" => {
                if policy.block_symlink_escape {
                    block = true;
                }
            }
            "IMPORT_ESCAPE" => {
                if policy.block_import_escape {
                    block = true;
                }
            }
            "GIT_UNTRACKED" => {
                if policy.block_repo_untracked {
                    block = true;
                } else {
                    warn = true;
                }
            }
            "GIT_MODIFIED" => {
                if policy.block_repo_modified {
                    block = true;
                } else {
                    warn = true;
                }
            }
            _ => {}
        }
        if src.scope == "user" && !policy.allow_user_scope {
            block = true;
        }
        if src.scope == "managed" && !policy.allow_managed_scope {
            block = true;
        }
        if src.trust == "GIT_TRACKED" && !policy.allow_repo_tracked {
            block = true;
        }
        if src.precedence_kind == "UNSPECIFIED" && policy.warn_on_unspecified_precedence {
            warn = true;
        }
    }
    for allowed in edges_allowed {
        if !allowed && (policy.block_import_escape || policy.block_missing_reference) {
            block = true;
        }
    }
    if policy.treat_warn_as_block && warn {
        block = true;
    }
    if block {
        "BLOCK"
    } else if warn {
        "WARN"
    } else {
        "PASS"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state(tracked: bool, modified: bool) -> GitState {
        GitState {
            repo: Some("/repo".to_string()),
            tracked,
            modified,
            head_commit: None,
            is_git_repo: true,
            error: None,
        }
    }

    #[test]
    fn priority_order_is_first_match_wins() {
        // Import escape outranks symlink escape and everything below.
        let r = classify_trust(
            Some("/outside/x.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(true, false)),
            Some("/repo/link.md"),
            true,
            Some(true),
            true,
            Some(true),
            None,
            Some("project"),
        );
        assert_eq!(r.trust, "IMPORT_ESCAPE");
        assert_eq!(r.reason_code, "R007");
    }

    #[test]
    fn symlink_escape_derived_from_roots() {
        let r = classify_trust(
            Some("/outside/Downloads/x.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(true, false)),
            Some("/repo/escape.md"),
            true,
            None,
            false,
            Some(true),
            None,
            Some("project"),
        );
        assert_eq!(r.trust, "SYMLINK_ESCAPE");
        assert_eq!(r.reason_code, "R006");
        // Same symlink, target inside the repo: no escape.
        let r2 = classify_trust(
            Some("/repo/services/AGENTS.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(true, false)),
            Some("/repo/link.md"),
            true,
            None,
            false,
            Some(true),
            None,
            Some("project"),
        );
        assert_eq!(r2.trust, "GIT_TRACKED");
        assert_eq!(r2.reason_code, "R001");
    }

    #[test]
    fn missing_outranks_git_state() {
        let r = classify_trust(
            Some("/repo/gone.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(true, true)),
            None,
            false,
            None,
            false,
            Some(false),
            None,
            Some("project"),
        );
        assert_eq!((r.trust.as_str(), r.reason_code.as_str()), ("MISSING", "R008"));
    }

    #[test]
    fn git_states_map_to_r001_r002_r003() {
        let tracked = classify_trust(
            Some("/repo/a.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(true, false)),
            None,
            false,
            None,
            false,
            Some(true),
            None,
            Some("project"),
        );
        assert_eq!((tracked.trust.as_str(), tracked.reason_code.as_str()), ("GIT_TRACKED", "R001"));
        let modified = classify_trust(
            Some("/repo/a.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(true, true)),
            None,
            false,
            None,
            false,
            Some(true),
            None,
            Some("project"),
        );
        assert_eq!((modified.trust.as_str(), modified.reason_code.as_str()), ("GIT_MODIFIED", "R002"));
        let untracked = classify_trust(
            Some("/repo/a.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(false, false)),
            None,
            false,
            None,
            false,
            Some(true),
            None,
            Some("project"),
        );
        assert_eq!((untracked.trust.as_str(), untracked.reason_code.as_str()), ("GIT_UNTRACKED", "R003"));
    }

    #[test]
    fn no_git_state_is_r009() {
        let r = classify_trust(
            Some("/repo/a.md"),
            Some("/repo"),
            Some("/home/u"),
            None,
            None,
            false,
            None,
            false,
            Some(true),
            None,
            Some("project"),
        );
        assert_eq!((r.trust.as_str(), r.reason_code.as_str()), ("NOT_OBSERVED", "R009"));
        let looped = classify_trust(
            None,
            Some("/repo"),
            Some("/home/u"),
            None,
            None,
            false,
            None,
            false,
            None,
            None,
            Some("project"),
        );
        assert_eq!((looped.trust.as_str(), looped.reason_code.as_str()), ("NOT_OBSERVED", "R009"));
    }

    #[test]
    fn managed_scope_maps_to_user_scope_r004() {
        let r = classify_trust(
            Some("/etc/claude-code/CLAUDE.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(false, false)),
            None,
            false,
            None,
            false,
            Some(true),
            None,
            Some("managed"),
        );
        assert_eq!((r.trust.as_str(), r.reason_code.as_str()), ("USER_SCOPE", "R004"));
    }

    #[test]
    fn user_scope_and_outside_repo() {
        let user = classify_trust(
            Some("/home/u/.codex/AGENTS.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(false, false)),
            None,
            false,
            None,
            false,
            Some(true),
            None,
            Some("user"),
        );
        assert_eq!((user.trust.as_str(), user.reason_code.as_str()), ("USER_SCOPE", "R004"));
        let outside = classify_trust(
            Some("/tmp/x.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(false, false)),
            None,
            false,
            None,
            false,
            Some(true),
            None,
            Some("project"),
        );
        assert_eq!((outside.trust.as_str(), outside.reason_code.as_str()), ("OUTSIDE_REPO", "R005"));
    }

    #[test]
    fn r010_annotates_only_r001_and_r004() {
        let tracked = classify_trust(
            Some("/repo/a.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(true, false)),
            None,
            false,
            None,
            false,
            Some(true),
            Some("UNSPECIFIED"),
            Some("project"),
        );
        assert_eq!(tracked.trust, "GIT_TRACKED");
        assert_eq!(tracked.reason_code, "R010");
        // A more specific reason is NOT overwritten by R010.
        let untracked = classify_trust(
            Some("/repo/a.md"),
            Some("/repo"),
            Some("/home/u"),
            Some(&state(false, false)),
            None,
            false,
            None,
            false,
            Some(true),
            Some("UNSPECIFIED"),
            Some("project"),
        );
        assert_eq!(untracked.reason_code, "R003");
    }

    #[test]
    fn verdict_derivation() {
        let policy = Policy::default();
        // Clean tracked chain: PASS.
        let v = derive_verdict(
            &[VerdictInput { trust: "GIT_TRACKED", scope: "project", precedence_kind: "ORDERED" }],
            &[],
            &policy,
        );
        assert_eq!(v, "PASS");
        // Untracked -> WARN by default; BLOCK when escalated.
        let v = derive_verdict(
            &[VerdictInput { trust: "GIT_UNTRACKED", scope: "project", precedence_kind: "ORDERED" }],
            &[],
            &policy,
        );
        assert_eq!(v, "WARN");
        let mut p2 = Policy::default();
        p2.block_repo_untracked = true;
        let v = derive_verdict(
            &[VerdictInput { trust: "GIT_UNTRACKED", scope: "project", precedence_kind: "ORDERED" }],
            &[],
            &p2,
        );
        assert_eq!(v, "BLOCK");
        // Any disallowed edge -> BLOCK.
        let v = derive_verdict(
            &[VerdictInput { trust: "GIT_TRACKED", scope: "project", precedence_kind: "ORDERED" }],
            &[false],
            &policy,
        );
        assert_eq!(v, "BLOCK");
        // UNSPECIFIED precedence -> WARN.
        let v = derive_verdict(
            &[VerdictInput { trust: "GIT_TRACKED", scope: "project", precedence_kind: "UNSPECIFIED" }],
            &[],
            &policy,
        );
        assert_eq!(v, "WARN");
        // NOT_OBSERVED is fail-closed BLOCK.
        let v = derive_verdict(
            &[VerdictInput { trust: "NOT_OBSERVED", scope: "project", precedence_kind: "ORDERED" }],
            &[],
            &policy,
        );
        assert_eq!(v, "BLOCK");
        // MISSING trust blocks only when block_missing_reference is true.
        let v = derive_verdict(
            &[VerdictInput { trust: "MISSING", scope: "project", precedence_kind: "ORDERED" }],
            &[],
            &policy,
        );
        assert_eq!(v, "BLOCK");
        let mut p3 = Policy::default();
        p3.block_missing_reference = false;
        let v = derive_verdict(
            &[VerdictInput { trust: "MISSING", scope: "project", precedence_kind: "ORDERED" }],
            &[],
            &p3,
        );
        assert_eq!(v, "PASS");
        // Scope checks key on scope, not on trust: a GIT_TRACKED
        // user-scope source is blocked by !allow_user_scope, and a
        // GIT_MODIFIED source is NOT blocked by !allow_repo_tracked.
        let mut p4 = Policy::default();
        p4.allow_user_scope = false;
        let v = derive_verdict(
            &[VerdictInput { trust: "GIT_TRACKED", scope: "user", precedence_kind: "ORDERED" }],
            &[],
            &p4,
        );
        assert_eq!(v, "BLOCK");
        let mut p5 = Policy::default();
        p5.allow_repo_tracked = false;
        let v = derive_verdict(
            &[VerdictInput { trust: "GIT_MODIFIED", scope: "project", precedence_kind: "ORDERED" }],
            &[],
            &p5,
        );
        assert_eq!(v, "WARN");
    }
}
