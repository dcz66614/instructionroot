#!/bin/sh
# P028 T010 — shared `verify` entry point for the GitHub Action and the
# pre-commit hook. Single source of truth: both integrations run this
# script, so the command they execute cannot drift apart.
#
# Resolution order (first set wins):
#   1. environment: INSTRUCTIONROOT_HARNESS / _CWD / _HOME / _POLICY /
#      _ALLOW_WARN (the workflow sets HARNESS/CWD from workflow_dispatch
#      inputs; empty values are ignored)
#   2. repo config: .instructionroot.json in the caller's working
#      directory if present, else next to this script's repository root
#      (keys: harness, cwd, home, policy, allow_warn; see
#      PROJECT_BOOK.md section 14.2 for the config shape — note this
#      file's "policy" is a PATH to a policy JSON file, matching the
#      CLI's --policy flag, not the book example's inline object)
#   3. defaults: harness=codex, cwd=.
#
# Exits with the CLI's own exit code: 0 PASS, 10 WARN (unless
# allow_warn), 20 BLOCK, 30 INPUT_ERROR, 40 UNSUPPORTED_PROFILE,
# 50 INTERNAL_ERROR. A malformed config fails closed (exit 30).
# No network, no uploads, no third-party installs: only the repo's
# own ./instructionroot launcher and the system python3 (stdlib json).
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ -n "${INSTRUCTIONROOT_CONFIG:-}" ]; then
    CONFIG="$INSTRUCTIONROOT_CONFIG"
elif [ -f .instructionroot.json ]; then
    CONFIG=".instructionroot.json"
else
    CONFIG="$ROOT/.instructionroot.json"
fi

# Resolve effective settings with the stdlib only. Prints five lines:
# harness, cwd, home (may be empty), policy (may be empty), allow_warn.
RESOLVED="$(python3 - "$CONFIG" <<'PY'
import json
import sys

config_path = sys.argv[1]
settings = {"harness": "codex", "cwd": ".", "home": "",
            "policy": "", "allow_warn": False}
try:
    with open(config_path, encoding="utf-8") as fh:
        raw = json.load(fh)
except FileNotFoundError:
    raw = {}
except (OSError, ValueError) as exc:
    print("instructionroot: cannot read config %s: %s" % (config_path, exc),
          file=sys.stderr)
    sys.exit(30)
if not isinstance(raw, dict):
    print("instructionroot: config %s must be a JSON object" % config_path,
          file=sys.stderr)
    sys.exit(30)
for key in ("harness", "cwd", "home", "policy"):
    value = raw.get(key)
    if value is not None:
        if not isinstance(value, str) or not value:
            print("instructionroot: config %s: %r must be a non-empty string"
                  % (config_path, key), file=sys.stderr)
            sys.exit(30)
        settings[key] = value
allow_warn = raw.get("allow_warn")
if allow_warn is not None:
    if not isinstance(allow_warn, bool):
        print("instructionroot: config %s: 'allow_warn' must be a boolean"
              % config_path, file=sys.stderr)
        sys.exit(30)
    settings["allow_warn"] = allow_warn
print(settings["harness"])
print(settings["cwd"])
print(settings["home"])
print(settings["policy"])
print("true" if settings["allow_warn"] else "false")
PY
)"

{
    IFS= read -r CFG_HARNESS
    IFS= read -r CFG_CWD
    IFS= read -r CFG_HOME
    IFS= read -r CFG_POLICY
    IFS= read -r CFG_ALLOW_WARN
} <<EOF
$RESOLVED
EOF

HARNESS="${INSTRUCTIONROOT_HARNESS:-$CFG_HARNESS}"
CWD="${INSTRUCTIONROOT_CWD:-$CFG_CWD}"
HOME_DIR="${INSTRUCTIONROOT_HOME:-$CFG_HOME}"
POLICY="${INSTRUCTIONROOT_POLICY:-$CFG_POLICY}"
ALLOW_WARN="${INSTRUCTIONROOT_ALLOW_WARN:-$CFG_ALLOW_WARN}"

set -- verify --harness "$HARNESS" --cwd "$CWD"
if [ -n "$HOME_DIR" ]; then
    set -- "$@" --home "$HOME_DIR"
fi
if [ -n "$POLICY" ]; then
    set -- "$@" --policy "$POLICY"
fi
case "$ALLOW_WARN" in
    true|1|yes) set -- "$@" --allow-warn ;;
esac

exec "$ROOT/instructionroot" "$@"
