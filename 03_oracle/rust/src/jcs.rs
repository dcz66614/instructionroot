//! RFC 8785 JSON Canonicalization Scheme (JCS) — independent Rust
//! implementation, written from the RFC, not from any other
//! implementation in this project.
//!
//! Rules applied (RFC 8785 §3.2):
//! * Object keys are sorted by their UTF-16 code units (not by bytes
//!   and not by Unicode scalar values — the two differ for characters
//!   outside the BMP, whose UTF-16 surrogates sort before U+E000).
//! * No whitespace anywhere; `,` and `:` are the only separators.
//! * Strings: only `"`, `\` and control characters U+0000–U+001F are
//!   escaped (`\b \t \n \f \r`, otherwise `\u00XX` lowercase hex).
//!   Non-ASCII characters are emitted as raw UTF-8; `/` is not escaped.
//! * Numbers use ECMAScript `Number::toString` semantics (RFC 8785
//!   §3.2.2.3). Integers serialise as plain decimal. Non-finite
//!   numbers serialise as `null`, as JSON requires.
//! * Arrays keep their order; objects recurse.
//!
//! The receipt hash is SHA-256 of the canonical JSON of the receipt
//! object with the `receipt_hash` field itself excluded (see
//! `receipt_schema.json`).

use serde_json::Value;

/// Serialise `value` to its RFC 8785 canonical JSON string.
pub fn canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_canonical(value, &mut out);
    out
}

fn write_canonical(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => out.push_str(&number_to_string(n)),
        Value::String(s) => write_string(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            // Sort keys by UTF-16 code units.
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort_by(|a, b| {
                let au: Vec<u16> = a.encode_utf16().collect();
                let bu: Vec<u16> = b.encode_utf16().collect();
                au.cmp(&bu)
            });
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_string(key, out);
                out.push(':');
                write_canonical(&map[*key], out);
            }
            out.push('}');
        }
    }
}

fn write_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{0008}' => out.push_str("\\b"),
            '\u{0009}' => out.push_str("\\t"),
            '\u{000A}' => out.push_str("\\n"),
            '\u{000C}' => out.push_str("\\f"),
            '\u{000D}' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// ECMAScript `Number::toString` for a serde_json number.
fn number_to_string(n: &serde_json::Number) -> String {
    if let Some(i) = n.as_i64() {
        return i.to_string();
    }
    if let Some(u) = n.as_u64() {
        return u.to_string();
    }
    let f = n.as_f64().unwrap_or(0.0);
    es_number_to_string(f)
}

/// ECMAScript `Number::toString` for an f64 (ECMA-262 §7.1.12.1,
/// as referenced by RFC 8785 §3.2.2.3).
///
/// Let the shortest decimal representation be the digit string `s`
/// (k digits) with decimal-point position `n` such that the value is
/// `s × 10^(n−k)`. Then:
/// * k ≤ n ≤ 21: `s` followed by n−k zeros.
/// * 0 < n ≤ 21: `s[..n]` + "." + `s[n..]`.
/// * −6 < n ≤ 0: "0." + (−n zeros) + `s`.
/// * otherwise: `s[0]` + ("." + `s[1..]` if k > 1) + "e" + sign +
///   (n−1), with an explicit `+` for non-negative exponents.
pub fn es_number_to_string(f: f64) -> String {
    if f == 0.0 {
        return "0".to_string();
    }
    if !f.is_finite() {
        return "null".to_string();
    }
    let neg = f < 0.0;
    // Shortest round-trip decimal in scientific notation, e.g.
    // "3.333333333333333e8" or "1e30" or "4.5e0".
    let sci = format!("{:e}", f.abs());
    let (mantissa, exp) = match sci.split_once('e') {
        Some((m, e)) => (m, e.parse::<i32>().unwrap_or(0)),
        None => (sci.as_str(), 0),
    };
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let digits = digits.trim_start_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };
    let k = digits.len() as i32;
    // n = position of the decimal point: exponent + 1, adjusted for
    // leading zeros stripped from the mantissa (none here: Rust's
    // shortest repr never has leading zeros before the first digit,
    // except for the "0.xxx" form which {:e} never produces).
    let n = exp + 1;
    let mut body = String::new();
    if k <= n && n <= 21 {
        body.push_str(digits);
        for _ in 0..(n - k) {
            body.push('0');
        }
    } else if 0 < n && n <= 21 {
        body.push_str(&digits[..n as usize]);
        body.push('.');
        body.push_str(&digits[n as usize..]);
    } else if -6 < n && n <= 0 {
        body.push_str("0.");
        for _ in 0..(-n) {
            body.push('0');
        }
        body.push_str(digits);
    } else if k == 1 {
        body.push_str(digits);
        body.push('e');
        let e = n - 1;
        if e >= 0 {
            body.push('+');
        }
        body.push_str(&e.to_string());
    } else {
        body.push_str(&digits[..1]);
        body.push('.');
        body.push_str(&digits[1..]);
        body.push('e');
        let e = n - 1;
        if e >= 0 {
            body.push('+');
        }
        body.push_str(&e.to_string());
    }
    if neg {
        format!("-{body}")
    } else {
        body
    }
}

/// SHA-256 (lowercase hex) of `bytes`.
pub fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::Digest;
    let mut digest = sha2::Sha256::new();
    digest.update(bytes);
    format!("{:x}", digest.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn rfc8785_example() {
        // RFC 8785 §3.2.1 / Appendix B example (numbers only; the
        // string/literal parts are covered by other tests).
        let v = json!({"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001]});
        assert_eq!(
            canonical_json(&v),
            r#"{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}"#
        );
    }

    #[test]
    fn key_sort_is_utf16_code_units() {
        // U+10000 (UTF-16 D800 DC00) sorts BEFORE U+E000 (single unit
        // E000) in UTF-16 code-unit order, although its scalar value is
        // larger. Byte order and scalar order would both get this wrong.
        // (Written with explicit escapes: an earlier draft used a literal
        // U+E000 character that did not survive editing and left an empty
        // key, which sorts first under every order and masked the test.)
        let v = json!({"\u{e000}": 1, "\u{10000}": 2});
        let expected = format!("{{\"{}\":2,\"{}\":1}}", '\u{10000}', '\u{e000}');
        assert_eq!(canonical_json(&v), expected);
        // ASCII keys sort as usual; nested objects recurse.
        let v = json!({"b": 1, "a": {"d": 4, "c": 3}});
        assert_eq!(canonical_json(&v), r#"{"a":{"c":3,"d":4},"b":1}"#);
    }

    #[test]
    fn string_escaping() {
        let v = json!("a\"b\\c\nd\te\x01f€\u{1f600}");
        assert_eq!(
            canonical_json(&v),
            "\"a\\\"b\\\\c\\nd\\te\\u0001f€\u{1f600}\""
        );
        // '/' is not escaped; DEL is not escaped.
        let v = json!("a/b\x7f");
        assert_eq!(canonical_json(&v), "\"a/b\x7f\"");
    }

    #[test]
    fn number_edge_cases() {
        assert_eq!(es_number_to_string(0.0), "0");
        assert_eq!(es_number_to_string(-0.0), "0");
        assert_eq!(es_number_to_string(1.0), "1");
        assert_eq!(es_number_to_string(100.0), "100");
        assert_eq!(es_number_to_string(1e21), "1e+21");
        assert_eq!(es_number_to_string(1.5e-7), "1.5e-7");
        assert_eq!(es_number_to_string(0.000001), "0.000001");
        assert_eq!(es_number_to_string(0.0000001), "1e-7");
        assert_eq!(es_number_to_string(-42.5), "-42.5");
        assert_eq!(es_number_to_string(f64::NAN), "null");
        assert_eq!(es_number_to_string(f64::INFINITY), "null");
        assert_eq!(es_number_to_string(123456789.123456789), "123456789.12345679");
    }

    #[test]
    fn no_whitespace_and_array_order() {
        let v = json!({"z": [3, 2, 1], "a": null});
        assert_eq!(canonical_json(&v), r#"{"a":null,"z":[3,2,1]}"#);
    }

    #[test]
    fn sha256_known_vector() {
        assert_eq!(
            sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
