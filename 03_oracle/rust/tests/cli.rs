//! CLI end-to-end tests for the Oracle binary.
//!
//! Each test builds a small synthetic tree under the system temp dir
//! (a real `git` repo where the verdict depends on tracked state),
//! runs `instructionroot-oracle resolve` on a case JSON, and checks
//! the receipt, the exit code and determinism. These tests exercise
//! the whole pipeline (discovery + import graph + trust + verdict +
//! JCS hash) rather than any single module.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

const ORACLE: &str = env!("CARGO_BIN_EXE_instructionroot-oracle");

fn temp_root(name: &str) -> PathBuf {
    let dir = std::env::temp_dir()
        .join(format!("oracle-cli-test-{}-{}", std::process::id(), name));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

fn write(path: &Path, content: &str) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, content).unwrap();
}

fn git_init_commit(repo: &Path) {
    let run = |args: &[&str]| {
        let out = Command::new("git")
            .args(args)
            .current_dir(repo)
            .output()
            .expect("git must be installed for the CLI tests");
        assert!(
            out.status.success(),
            "git {args:?} failed: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    };
    run(&["init", "-q"]);
    run(&["add", "-A"]);
    run(&["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]);
}

fn run_oracle(case_path: &Path, explain: Option<&Path>) -> Output {
    let mut cmd = Command::new(ORACLE);
    cmd.arg("resolve").arg(case_path);
    if let Some(explain) = explain {
        cmd.arg("--explain").arg(explain);
    }
    cmd.output().expect("oracle binary must run")
}

fn receipt_of(out: &Output) -> serde_json::Value {
    assert!(
        out.status.success() || out.status.code() == Some(10) || out.status.code() == Some(20),
        "oracle failed: code={:?} stderr={}",
        out.status.code(),
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).expect("oracle stdout must be a receipt JSON")
}

fn case_json(root: &Path, harness: &str, cwd: &Path, home: &Path, repo: &Path) -> PathBuf {
    let case = serde_json::json!({
        "case_id": "cli-test",
        "harness": harness,
        "cwd": cwd.to_string_lossy(),
        "home": home.to_string_lossy(),
        "repo_root": repo.to_string_lossy(),
        "policy": "default",
        "working_files": [],
        "env": {},
        "ancestor_stop": repo.to_string_lossy(),
    });
    let path = root.join("case.json");
    fs::write(&path, serde_json::to_string(&case).unwrap()).unwrap();
    path
}

#[test]
fn resolve_claude_chain_pass_and_deterministic() {
    let root = temp_root("claude-chain");
    let repo = root.join("repo");
    let home = root.join("home");
    write(&repo.join("CLAUDE.md"), "# repo\n@shared/a.md\n");
    write(&repo.join("shared/a.md"), "# a\n@b.md\n");
    write(&repo.join("shared/b.md"), "# b\n");
    write(&home.join(".claude/CLAUDE.md"), "# user\n");
    git_init_commit(&repo);
    git_init_commit(&home);

    let case = case_json(&root, "claude-code", &repo, &home, &repo);
    let explain = root.join("explain.json");
    let out1 = run_oracle(&case, Some(&explain));
    assert_eq!(out1.status.code(), Some(0), "stderr: {}", String::from_utf8_lossy(&out1.stderr));
    let out2 = run_oracle(&case, None);
    assert_eq!(out1.stdout, out2.stdout, "receipt must be deterministic");

    let receipt = receipt_of(&out1);
    assert_eq!(receipt["verdict"], "PASS");
    let sources = receipt["sources"].as_array().unwrap();
    // user first, then project (discovery order).
    assert_eq!(sources.len(), 2);
    assert_eq!(sources[0]["discovery_rule"], "claude-code.user");
    assert_eq!(sources[1]["discovery_rule"], "claude-code.project");
    assert_eq!(sources[1]["trust"], "GIT_TRACKED");
    assert_eq!(sources[0]["trust"], "USER_SCOPE");

    let edges = receipt["edges"].as_array().unwrap();
    assert_eq!(edges.len(), 2);
    // Depth-1 importer is a receipt source -> `from` is its source id.
    assert_eq!(edges[0]["from"], "src-0002");
    assert_eq!(edges[0]["reason"], "WITHIN_REPO");
    assert!(edges[0]["allowed"].as_bool().unwrap());
    // Depth-2 importer (shared/a.md) is not a source -> `from` is its
    // canonical path (CQ-2).
    assert_eq!(
        edges[1]["from"].as_str().unwrap(),
        repo.join("shared/a.md").to_string_lossy()
    );
    assert_eq!(edges[1]["reason"], "WITHIN_REPO");

    // Explain sidecar: depth + canonical targets + reason codes.
    let explain: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(&explain).unwrap()).unwrap();
    assert_eq!(explain["edges"][1]["depth"], 2);
    assert_eq!(
        explain["edges"][1]["canonical_target"].as_str().unwrap(),
        repo.join("shared/b.md").to_string_lossy()
    );
    assert_eq!(explain["sources"][1]["reason_code"], "R001");

    let _ = fs::remove_dir_all(&root);
}

#[test]
fn resolve_import_escape_blocks() {
    let root = temp_root("claude-escape");
    let repo = root.join("repo");
    let home = root.join("home");
    write(&repo.join("CLAUDE.md"), "# repo\n@../outside.md\n");
    write(&root.join("outside.md"), "# outside\n");
    write(&home.join(".claude/CLAUDE.md"), "# user\n");
    git_init_commit(&repo);

    let case = case_json(&root, "claude-code", &repo, &home, &repo);
    let out = run_oracle(&case, None);
    assert_eq!(out.status.code(), Some(20), "stderr: {}", String::from_utf8_lossy(&out.stderr));
    let receipt = receipt_of(&out);
    assert_eq!(receipt["verdict"], "BLOCK");
    let edges = receipt["edges"].as_array().unwrap();
    assert_eq!(edges.len(), 1);
    assert_eq!(edges[0]["reason"], "IMPORT_ESCAPE");
    assert_eq!(edges[0]["allowed"], false);

    let _ = fs::remove_dir_all(&root);
}

#[test]
fn resolve_copilot_relative_expands_and_absolute_blocks() {
    let root = temp_root("copilot");
    let repo = root.join("repo");
    let home = root.join("home");
    // File-relative base is the importing file's directory
    // (.github/), so the repo-level target needs `../`.
    write(
        &repo.join(".github/copilot-instructions.md"),
        "# c\n@../shared/ok.md\n",
    );
    write(&repo.join("shared/ok.md"), "# ok\n");
    fs::create_dir_all(&home).unwrap();
    git_init_commit(&repo);

    let case = case_json(&root, "copilot-cli", &repo, &home, &repo);
    let out = run_oracle(&case, None);
    assert_eq!(out.status.code(), Some(0), "stderr: {}", String::from_utf8_lossy(&out.stderr));
    let receipt = receipt_of(&out);
    assert_eq!(receipt["verdict"], "PASS");
    let edges = receipt["edges"].as_array().unwrap();
    assert_eq!(edges.len(), 1);
    assert_eq!(edges[0]["reason"], "WITHIN_REPO");
    assert_eq!(edges[0]["from"], "src-0001");

    // Absolute reference in the same file blocks (CQ-1 file-relative
    // base does not save absolute paths).
    write(
        &repo.join(".github/copilot-instructions.md"),
        "# c\n@../shared/ok.md\n@/etc/nope.md\n",
    );
    git_init_commit(&repo);
    let out = run_oracle(&case, None);
    assert_eq!(out.status.code(), Some(20));
    let receipt = receipt_of(&out);
    assert_eq!(receipt["verdict"], "BLOCK");
    let edges = receipt["edges"].as_array().unwrap();
    assert_eq!(edges.len(), 2);
    assert_eq!(edges[1]["reason"], "IMPORT_ESCAPE");
    assert_eq!(edges[1]["resolved_target"], "/etc/nope.md");

    let _ = fs::remove_dir_all(&root);
}

#[test]
fn canonicalize_loop_and_windows() {
    let root = temp_root("canon");
    let a = root.join("a");
    let b = root.join("b");
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(&b, &a).unwrap();
        std::os::unix::fs::symlink(&a, &b).unwrap();
    }
    let input = serde_json::json!({
        "cwd": root.to_string_lossy(),
        "home": root.to_string_lossy(),
        "paths": [a.to_string_lossy(), "C:\\repo\\AGENTS.md"],
    });
    let input_path = root.join("input.json");
    fs::write(&input_path, serde_json::to_string(&input).unwrap()).unwrap();
    let out = Command::new(ORACLE)
        .arg("canonicalize")
        .arg(&input_path)
        .output()
        .unwrap();
    assert!(out.status.success());
    let records: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    let records = records.as_array().unwrap();
    assert_eq!(records.len(), 2);
    assert_eq!(records[0]["is_loop"], true);
    assert_eq!(records[0]["resolved_path"], serde_json::Value::Null);
    assert_eq!(records[0]["error"], "SYMLINK_LOOP");
    // Windows drive spelling resolves through the shared resolver
    // (bug-compatible with the Python canonicalize: /C:/...).
    assert_eq!(records[1]["canonical_path"], "C:/repo/AGENTS.md");
    assert_eq!(records[1]["resolved_path"], "/C:/repo/AGENTS.md");

    let _ = fs::remove_dir_all(&root);
}

#[test]
fn resolve_error_exit_codes() {
    let root = temp_root("errors");
    let repo = root.join("repo");
    let home = root.join("home");
    fs::create_dir_all(&repo).unwrap();
    fs::create_dir_all(&home).unwrap();

    // Unknown harness -> UNSUPPORTED_PROFILE (40).
    let case = case_json(&root, "not-a-harness", &repo, &home, &repo);
    let out = run_oracle(&case, None);
    assert_eq!(out.status.code(), Some(40));
    let err: serde_json::Value = serde_json::from_slice(&out.stderr).unwrap();
    assert_eq!(err["verdict"], "UNSUPPORTED_PROFILE");

    // Missing cwd -> INPUT_ERROR (30).
    let bad = serde_json::json!({
        "case_id": "bad",
        "harness": "codex",
        "cwd": root.join("no-such-dir").to_string_lossy(),
        "home": home.to_string_lossy(),
        "repo_root": repo.to_string_lossy(),
    });
    let bad_path = root.join("bad.json");
    fs::write(&bad_path, serde_json::to_string(&bad).unwrap()).unwrap();
    let out = run_oracle(&bad_path, None);
    assert_eq!(out.status.code(), Some(30));

    let _ = fs::remove_dir_all(&root);
}
