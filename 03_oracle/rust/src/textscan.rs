//! Text scanning — independent Rust implementation of the P028 contract
//! helpers: the strict YAML-subset frontmatter parser, `fnmatch`-style
//! glob matching (for Copilot `applyTo` and Claude `paths`), file
//! reading, and the `@path` import scanner.
//!
//! Frontmatter (strict YAML subset): `key: scalar` lines (scalars
//! optionally single/double quoted), `key:` followed by `- item` lines,
//! and inline `[a, b]` lists. Anything else is unparseable and the
//! frontmatter is treated as absent — exactly the contract rule for
//! `.claude/rules` paths frontmatter ("unparseable YAML frontmatter is
//! ignored and the rule loads as if it had no paths").
//!
//! Glob matching: Python `fnmatch.fnmatchcase` semantics — `*` crosses
//! `/`, `?` matches one character, `[...]` character classes,
//! case-sensitive. A pattern with no `/` matches the basename. `**/`
//! also matches zero directories (the `**/`-stripped variant is tried
//! too).

use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FmValue {
    Scalar(String),
    List(Vec<String>),
}

/// Parse a leading `---` YAML frontmatter block (subset).
/// Returns the parsed mapping, or `None` when there is no frontmatter
/// block *or* the block is unparseable.
pub fn parse_frontmatter(text: &str) -> Option<BTreeMap<String, FmValue>> {
    let lines: Vec<&str> = text.lines().collect();
    if lines.is_empty() || lines[0].trim() != "---" {
        return None;
    }
    let mut end: Option<usize> = None;
    for i in 1..lines.len() {
        if lines[i].trim() == "---" {
            end = Some(i);
            break;
        }
    }
    let end = end?;
    let mut data: BTreeMap<String, FmValue> = BTreeMap::new();
    let mut current_key: Option<String> = None;
    for raw in &lines[1..end] {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if line.starts_with("- ") || line == "-" {
            let key = current_key.clone()?;
            let item = unquote(line[1..].trim())?;
            match data.get_mut(&key) {
                Some(FmValue::List(items)) => items.push(item),
                _ => return None,
            }
            continue;
        }
        let colon = line.find(':')?;
        let (key, value) = (&line[..colon], &line[colon + 1..]);
        let key = key.trim();
        if key.is_empty() || data.contains_key(key) || key.contains(' ') {
            return None;
        }
        current_key = None;
        let value = value.trim();
        if value.is_empty() {
            data.insert(key.to_string(), FmValue::List(Vec::new()));
            current_key = Some(key.to_string());
            continue;
        }
        if value.starts_with('[') && value.ends_with(']') {
            let inner = value[1..value.len() - 1].trim();
            let mut items: Vec<String> = Vec::new();
            if !inner.is_empty() {
                for part in inner.split(',') {
                    items.push(unquote(part.trim())?);
                }
            }
            data.insert(key.to_string(), FmValue::List(items));
            continue;
        }
        let scalar = unquote(value)?;
        data.insert(key.to_string(), FmValue::Scalar(scalar));
    }
    Some(data)
}

/// Strip one layer of matching quotes, or `None` if unbalanced.
/// An unquoted scalar containing `:` is ambiguous YAML; rejected.
fn unquote(value: &str) -> Option<String> {
    let chars: Vec<char> = value.chars().collect();
    if chars.len() >= 2
        && chars[0] == chars[chars.len() - 1]
        && (chars[0] == '\'' || chars[0] == '"')
    {
        return Some(chars[1..chars.len() - 1].iter().collect());
    }
    if value.starts_with('\'')
        || value.starts_with('"')
        || value.ends_with('\'')
        || value.ends_with('"')
    {
        return None;
    }
    if value.contains(':') {
        return None;
    }
    Some(value.to_string())
}

fn patterns_from(value: &FmValue) -> Option<Vec<String>> {
    match value {
        FmValue::Scalar(s) => Some(
            s.split(',')
                .map(|p| p.trim().to_string())
                .filter(|p| !p.is_empty())
                .collect(),
        ),
        FmValue::List(items) => {
            let mut out: Vec<String> = Vec::new();
            for item in items {
                out.extend(
                    item.split(',')
                        .map(|p| p.trim().to_string())
                        .filter(|p| !p.is_empty()),
                );
            }
            Some(out)
        }
    }
}

/// Return the `paths` frontmatter glob list, or `None` if absent.
/// `None` covers both "no frontmatter" and "unparseable" — per the
/// contract both load the rule as if it had no paths.
pub fn parse_paths_frontmatter(text: &str) -> Option<Vec<String>> {
    let data = parse_frontmatter(text)?;
    let value = data.get("paths")?;
    patterns_from(value)
}

/// Return the `applyTo` frontmatter glob list, or `None` if absent.
/// `None` means the behaviour is UNVERIFIED for Copilot CLI: callers
/// must not guess — they exclude the file.
pub fn parse_applyto(text: &str) -> Option<Vec<String>> {
    let data = parse_frontmatter(text)?;
    let value = data.get("applyTo")?;
    patterns_from(value)
}

/// Read a file as UTF-8 text (for frontmatter/import scanning).
/// Returns `None` when the file cannot be read or is not valid UTF-8.
/// Only the first 1,000,000 characters are read.
pub fn read_text(path: &str) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    let text = String::from_utf8(bytes).ok()?;
    if text.chars().count() > 1_000_000 {
        Some(text.chars().take(1_000_000).collect())
    } else {
        Some(text)
    }
}

// ---------------------------------------------------------------------------
// Glob matching (fnmatchcase)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
enum GlobToken {
    Star,
    AnyOne,
    Literal(char),
    Class { negated: bool, members: Vec<ClassMember> },
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ClassMember {
    Char(char),
    Range(char, char),
}

/// Translate an `fnmatch` pattern into tokens. An unterminated `[` is
/// treated as a literal `[` (matching Python `fnmatch.translate`).
fn translate_glob(pattern: &str) -> Vec<GlobToken> {
    let chars: Vec<char> = pattern.chars().collect();
    let mut tokens: Vec<GlobToken> = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        match chars[i] {
            '*' => {
                tokens.push(GlobToken::Star);
                i += 1;
            }
            '?' => {
                tokens.push(GlobToken::AnyOne);
                i += 1;
            }
            '[' => {
                // Find the closing ']'.
                let mut j = i + 1;
                if j < chars.len() && chars[j] == '!' {
                    j += 1;
                }
                if j < chars.len() && chars[j] == ']' {
                    j += 1;
                }
                while j < chars.len() && chars[j] != ']' {
                    j += 1;
                }
                if j >= chars.len() {
                    tokens.push(GlobToken::Literal('['));
                    i += 1;
                    continue;
                }
                let mut k = i + 1;
                let mut negated = false;
                if k < chars.len() && chars[k] == '!' {
                    negated = true;
                    k += 1;
                }
                let mut members: Vec<ClassMember> = Vec::new();
                if k < chars.len() && chars[k] == ']' {
                    members.push(ClassMember::Char(']'));
                    k += 1;
                }
                while k < j {
                    if k + 2 < j && chars[k + 1] == '-' && chars[k + 2] != ']' {
                        members.push(ClassMember::Range(chars[k], chars[k + 2]));
                        k += 3;
                    } else {
                        members.push(ClassMember::Char(chars[k]));
                        k += 1;
                    }
                }
                tokens.push(GlobToken::Class { negated, members });
                i = j + 1;
            }
            c => {
                tokens.push(GlobToken::Literal(c));
                i += 1;
            }
        }
    }
    tokens
}

fn glob_match_tokens(tokens: &[GlobToken], text: &[char]) -> bool {
    // Classic glob DP with memoisation on (token index, text index).
    fn rec(tokens: &[GlobToken], ti: usize, text: &[char], si: usize) -> bool {
        if ti == tokens.len() {
            return si == text.len();
        }
        match &tokens[ti] {
            GlobToken::Star => {
                // '*' matches any (possibly empty) run, including '/'.
                for skip in si..=text.len() {
                    if rec(tokens, ti + 1, text, skip) {
                        return true;
                    }
                }
                false
            }
            GlobToken::AnyOne => si < text.len() && rec(tokens, ti + 1, text, si + 1),
            GlobToken::Literal(c) => {
                si < text.len() && text[si] == *c && rec(tokens, ti + 1, text, si + 1)
            }
            GlobToken::Class { negated, members } => {
                if si >= text.len() {
                    return false;
                }
                let c = text[si];
                let hit = members.iter().any(|m| match m {
                    ClassMember::Char(x) => *x == c,
                    ClassMember::Range(a, b) => *a <= c && c <= *b,
                });
                (hit != *negated) && rec(tokens, ti + 1, text, si + 1)
            }
        }
    }
    rec(tokens, 0, text, 0)
}

/// Python `fnmatch.fnmatchcase(name, pattern)`: case-sensitive,
/// `*` crosses `/`.
pub fn fnmatchcase(name: &str, pattern: &str) -> bool {
    let tokens = translate_glob(pattern);
    let chars: Vec<char> = name.chars().collect();
    glob_match_tokens(&tokens, &chars)
}

/// Match one glob `pattern` against a `/`-separated relative path.
/// A pattern with no `/` matches the basename. `**/` also matches
/// zero directories.
pub fn glob_matches(pattern: &str, rel_posix_path: &str) -> bool {
    let pattern = pattern.trim();
    if pattern.is_empty() {
        return false;
    }
    if !pattern.contains('/') {
        let base = rel_posix_path.rsplit('/').next().unwrap_or(rel_posix_path);
        return fnmatchcase(base, pattern);
    }
    let mut variants = vec![pattern.to_string()];
    if pattern.contains("**/") {
        variants.push(pattern.replace("**/", ""));
    }
    variants
        .iter()
        .any(|v| fnmatchcase(rel_posix_path, v))
}

pub fn any_glob_matches(patterns: &[String], rel_posix_path: &str) -> bool {
    patterns.iter().any(|p| glob_matches(p, rel_posix_path))
}

// ---------------------------------------------------------------------------
// @path import scanner
// ---------------------------------------------------------------------------

/// Remove fenced code blocks and inline code spans (never imported).
fn strip_code(text: &str) -> String {
    let mut out_lines: Vec<String> = Vec::new();
    let mut in_fence = false;
    for line in text.lines() {
        let trimmed = line.trim_start();
        if trimmed.starts_with("```") || trimmed.starts_with("~~~") {
            in_fence = !in_fence;
            continue;
        }
        if in_fence {
            continue;
        }
        let segments: Vec<&str> = line.split('`').collect();
        let kept: String = segments
            .iter()
            .enumerate()
            .filter(|(i, _)| i % 2 == 0)
            .map(|(_, s)| *s)
            .collect();
        out_lines.push(kept);
    }
    out_lines.join("\n")
}

fn is_word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// Return the raw `@path` reference strings in `text`.
///
/// Imports inside Markdown code spans / fenced code blocks are skipped;
/// a path wrapped in quotes is never imported; spaces in a path must be
/// backslash-escaped (the escape is removed here). Mirrors the
/// contract's `@` scanner: `@` not preceded by a word character or
/// `@`, not followed by a quote, then a run of characters excluding
/// whitespace and `) ] , ; ' " \`` (backslash escapes the next char).
pub fn parse_imports(text: &str) -> Vec<String> {
    let stripped = strip_code(text);
    let chars: Vec<char> = stripped.chars().collect();
    let mut found: Vec<String> = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] != '@' {
            i += 1;
            continue;
        }
        // Not preceded by a word character or '@'.
        if i > 0 && (is_word_char(chars[i - 1]) || chars[i - 1] == '@') {
            i += 1;
            continue;
        }
        // Not followed by a quote.
        if i + 1 < chars.len() && (chars[i + 1] == '"' || chars[i + 1] == '\'') {
            i += 1;
            continue;
        }
        let mut j = i + 1;
        let mut raw = String::new();
        while j < chars.len() {
            let c = chars[j];
            if c == '\\' && j + 1 < chars.len() {
                raw.push(c);
                raw.push(chars[j + 1]);
                j += 2;
                continue;
            }
            if c.is_whitespace()
                || c == ')'
                || c == ']'
                || c == ','
                || c == ';'
                || c == '\''
                || c == '"'
                || c == '`'
            {
                break;
            }
            raw.push(c);
            j += 1;
        }
        if !raw.is_empty() {
            let unescaped = raw.replace("\\ ", " ").replace("\\\\", "\\");
            if !unescaped.is_empty() {
                found.push(unescaped);
            }
        }
        i = j.max(i + 1);
    }
    found
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frontmatter_scalars_and_lists() {
        let text = "---\napplyTo: \"src/**/*.py\"\n---\nbody\n";
        assert_eq!(
            parse_applyto(text),
            Some(vec!["src/**/*.py".to_string()])
        );
        let text = "---\npaths:\n  - \"docs/**\"\n  - src/**/*.py\n---\nbody\n";
        assert_eq!(
            parse_paths_frontmatter(text),
            Some(vec!["docs/**".to_string(), "src/**/*.py".to_string()])
        );
        let text = "---\npaths: [\"a/**\", 'b/**']\n---\nbody\n";
        assert_eq!(
            parse_paths_frontmatter(text),
            Some(vec!["a/**".to_string(), "b/**".to_string()])
        );
    }

    #[test]
    fn frontmatter_unparseable_is_absent() {
        // ': bad' — unquoted scalar containing ':' is unparseable.
        let text = "---\n: bad\n---\nbody\n";
        assert_eq!(parse_frontmatter(text), None);
        assert_eq!(parse_paths_frontmatter(text), None);
        // Unterminated block.
        assert_eq!(parse_frontmatter("---\npaths: x\n"), None);
        // No frontmatter.
        assert_eq!(parse_frontmatter("plain text\n"), None);
        // Duplicate keys.
        assert_eq!(
            parse_frontmatter("---\na: 1\na: 2\n---\n"),
            None
        );
    }

    #[test]
    fn glob_basename_and_doublestar() {
        assert!(glob_matches("*.py", "src/app.py"));
        assert!(!glob_matches("*.py", "src/app.md"));
        assert!(glob_matches("src/**/*.py", "src/app.py"));
        assert!(glob_matches("src/**/*.py", "src/a/b.py"));
        assert!(!glob_matches("src/**/*.py", "other/app.py"));
        assert!(glob_matches("docs/**", "docs/a/b.md"));
        assert!(glob_matches("**/*.py", "app.py"));
        assert!(glob_matches("[a-c].py", "b.py"));
        assert!(!glob_matches("[a-c].py", "d.py"));
        assert!(glob_matches("file?.md", "file1.md"));
    }

    #[test]
    fn imports_skip_code_and_quotes() {
        // CQ-4 (known T003 parser gap, preserved for parity): a quote
        // BEFORE `@` does NOT exclude the reference — `"@quoted/c.md"`
        // IS parsed. Only `@"path"` (quote AFTER @) is excluded.
        let text = "# title\n@shared/a.md\n\n```\n@code/block.md\n```\n\n`@inline/span.md` and @real/b.md and \"@quoted/c.md\" and @\"skip/d.md\" and @with\\ space/d.md\n";
        assert_eq!(
            parse_imports(text),
            vec![
                "shared/a.md".to_string(),
                "real/b.md".to_string(),
                "quoted/c.md".to_string(),
                "with space/d.md".to_string(),
            ]
        );
        // Email-like text is not an import.
        assert_eq!(parse_imports("contact foo@bar.com\n"), Vec::<String>::new());
    }
}
