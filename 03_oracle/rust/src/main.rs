//! `instructionroot-oracle` — independent Rust Oracle for P028.
//!
//! Subcommands:
//! * `resolve <case.json> [--explain <file>]` — read one case input,
//!   print the receipt JSON to stdout, exit with the verdict exit code
//!   (PASS 0 / WARN 10 / BLOCK 20; INPUT_ERROR 30 /
//!   UNSUPPORTED_PROFILE 40 / INTERNAL_ERROR 50 on failure, with an
//!   error object on stderr). With `--explain`, also write a JSON file
//!   with per-source reason codes (R001–R010) and per-edge depths —
//!   classification evidence the receipt schema itself has no slot for.
//! * `canonicalize <input.json>` — read `{"cwd","home","paths":[...]}`,
//!   print a JSON array of canonical-path records (lexical + resolved
//!   dual record, existence, symlink state, loop/error flags).
//! * `--version` — print the Oracle version.
//!
//! The binary reads only the filesystem and the local `git` binary; it
//! never touches the network, never calls Python, never reads any
//! production output. Its only ambient input is the case file it is
//! handed (environment variables come from the case JSON, not from the
//! process environment).

mod git;
mod jcs;
mod paths;
mod profiles;
mod receipt;
mod textscan;
mod trust;

use std::io::Write;
use std::process::ExitCode;

use paths::CanonicalPath;
use receipt::{resolve_case, OracleError};

const VERSION: &str = "instructionroot-oracle 0.1.0";

fn print_error(err: &OracleError) {
    let obj = serde_json::json!({
        "error": err.message(),
        "verdict": err.verdict(),
    });
    eprintln!("{}", serde_json::to_string(&obj).unwrap());
}

fn cmd_resolve(args: &[String]) -> ExitCode {
    let mut case_path: Option<String> = None;
    let mut explain_path: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--explain" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("--explain needs a file path");
                    return ExitCode::from(2);
                }
                explain_path = Some(args[i].clone());
            }
            other if other.starts_with("--") => {
                eprintln!("unknown option: {other}");
                return ExitCode::from(2);
            }
            other => {
                if case_path.is_some() {
                    eprintln!("unexpected argument: {other}");
                    return ExitCode::from(2);
                }
                case_path = Some(other.to_string());
            }
        }
        i += 1;
    }
    let Some(case_path) = case_path else {
        eprintln!("usage: instructionroot-oracle resolve <case.json> [--explain <file>]");
        return ExitCode::from(2);
    };
    let text = match std::fs::read_to_string(&case_path) {
        Ok(t) => t,
        Err(e) => {
            print_error(&OracleError::InputError(format!(
                "cannot read case file {case_path}: {e}"
            )));
            return ExitCode::from(30);
        }
    };
    let input: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(e) => {
            print_error(&OracleError::InputError(format!(
                "case file {case_path} is not valid JSON: {e}"
            )));
            return ExitCode::from(30);
        }
    };
    match resolve_case(&input) {
        Ok((receipt, explain)) => {
            let verdict = receipt
                .get("verdict")
                .and_then(|v| v.as_str())
                .unwrap_or("INTERNAL_ERROR");
            if let Some(explain_path) = explain_path {
                let text = serde_json::to_string_pretty(&explain).unwrap();
                if let Err(e) = std::fs::write(&explain_path, text) {
                    print_error(&OracleError::InternalError(format!(
                        "cannot write explain file {explain_path}: {e}"
                    )));
                    return ExitCode::from(50);
                }
            }
            println!("{}", serde_json::to_string(&receipt).unwrap());
            let _ = std::io::stdout().flush();
            ExitCode::from(match verdict {
                "PASS" => 0,
                "WARN" => 10,
                "BLOCK" => 20,
                _ => 50,
            })
        }
        Err(e) => {
            print_error(&e);
            ExitCode::from(e.exit_code() as u8)
        }
    }
}

fn cmd_canonicalize(args: &[String]) -> ExitCode {
    if args.len() != 1 {
        eprintln!("usage: instructionroot-oracle canonicalize <input.json>");
        return ExitCode::from(2);
    }
    let text = match std::fs::read_to_string(&args[0]) {
        Ok(t) => t,
        Err(e) => {
            print_error(&OracleError::InputError(format!(
                "cannot read input file {}: {e}",
                args[0]
            )));
            return ExitCode::from(30);
        }
    };
    let input: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(e) => {
            print_error(&OracleError::InputError(format!(
                "input file {} is not valid JSON: {e}",
                args[0]
            )));
            return ExitCode::from(30);
        }
    };
    let cwd = input.get("cwd").and_then(|v| v.as_str());
    let home = input.get("home").and_then(|v| v.as_str());
    let paths = input.get("paths").and_then(|v| v.as_array());
    let (Some(cwd), Some(home), Some(paths)) = (cwd, home, paths) else {
        print_error(&OracleError::InputError(
            "canonicalize input needs string \"cwd\"/\"home\" and array \"paths\"".to_string(),
        ));
        return ExitCode::from(30);
    };
    let mut records: Vec<serde_json::Value> = Vec::new();
    for p in paths {
        let Some(raw) = p.as_str() else {
            print_error(&OracleError::InputError(
                "canonicalize \"paths\" entries must be strings".to_string(),
            ));
            return ExitCode::from(30);
        };
        records.push(canonical_record(raw, Some(cwd), Some(home)));
    }
    println!("{}", serde_json::to_string(&serde_json::Value::Array(records)).unwrap());
    ExitCode::from(0)
}

fn canonical_record(raw: &str, cwd: Option<&str>, home: Option<&str>) -> serde_json::Value {
    match paths::canonicalize(raw, cwd, home) {
        Ok(c) => canonical_to_json(&c),
        Err(e) => serde_json::json!({
            "raw_path": raw,
            "canonical_path": null,
            "resolved_path": null,
            "exists": false,
            "is_file": false,
            "is_dir": false,
            "is_symlink": false,
            "symlink_target": null,
            "symlink_chain": [],
            "is_broken_symlink": false,
            "is_loop": false,
            "error": e,
        }),
    }
}

fn canonical_to_json(c: &CanonicalPath) -> serde_json::Value {
    serde_json::json!({
        "raw_path": c.raw_path,
        "canonical_path": c.canonical_path,
        "resolved_path": c.resolved_path,
        "exists": c.exists,
        "is_file": c.is_file,
        "is_dir": c.is_dir,
        "is_symlink": c.is_symlink,
        "symlink_target": c.symlink_target,
        "symlink_chain": c.symlink_chain,
        "is_broken_symlink": c.is_broken_symlink,
        "is_loop": c.is_loop,
        "error": c.error,
    })
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        eprintln!("usage: instructionroot-oracle <resolve|canonicalize|--version>");
        return ExitCode::from(2);
    }
    match args[0].as_str() {
        "--version" => {
            println!("{VERSION}");
            ExitCode::from(0)
        }
        "resolve" => cmd_resolve(&args[1..]),
        "canonicalize" => cmd_canonicalize(&args[1..]),
        other => {
            eprintln!("unknown subcommand: {other}");
            eprintln!("usage: instructionroot-oracle <resolve|canonicalize|--version>");
            ExitCode::from(2)
        }
    }
}
