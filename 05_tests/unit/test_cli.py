"""Unit / CLI tests for P028 T008 — CLI / Policy / Exit Codes.

All data is synthetic (tmp_path git repos + placeholder instruction
files); no network, no real home contents (every run passes an
explicit ``--home``), no wall-clock assertions. The CLI is exercised
end-to-end through the repo-root ``./instructionroot`` launcher, so
these tests cover argument parsing, policy loading, formatters,
exit codes and the Oracle subcommand exactly as a user runs them.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_src"))

from instructionroot.receipt import (  # noqa: E402
    receipt_hash_for,
    verify_receipt,
)

WORKDIR = Path(__file__).resolve().parents[2]
LAUNCHER = WORKDIR / "instructionroot"


def run_cli(*args, cwd=None):
    """Run the launcher; return the CompletedProcess (text mode)."""
    return subprocess.run(
        [str(LAUNCHER), *args],
        capture_output=True, text=True, cwd=str(cwd or WORKDIR),
    )


def _git(repo: Path, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def make_repo(tmp_path: Path, name="repo"):
    """Synthetic git repo + synthetic home; returns (repo, home)."""
    repo = tmp_path / name
    home = tmp_path / "home"
    (repo / "services" / "payments").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "AGENTS.md").write_text(
        "# synthetic user instructions\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text(
        "# synthetic repo instructions\n", encoding="utf-8")
    (repo / "services" / "AGENTS.md").write_text(
        "# synthetic service instructions\n", encoding="utf-8")
    (repo / "services" / "payments" / "AGENTS.md").write_text(
        "# synthetic payments instructions\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "synthetic fixture")
    return repo, home


def verify_args(repo: Path, home: Path, cwd=None, extra=()):
    return [
        "verify", "--harness", "codex",
        "--cwd", str(cwd or (repo / "services" / "payments")),
        "--home", str(home), *extra,
    ]


# ---------------------------------------------------------------------------
# Help / profile list / version
# ---------------------------------------------------------------------------

def test_top_level_help():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "instructionroot" in result.stdout
    assert "verify" in result.stdout and "oracle" in result.stdout


def test_subcommand_help():
    for sub in (["verify", "--help"], ["inspect", "--help"],
                ["export", "--help"], ["oracle", "--help"],
                ["profile", "list", "--help"]):
        result = run_cli(*sub)
        assert result.returncode == 0, sub
        assert "--harness" in result.stdout or "--format" in result.stdout, sub


def test_profile_list_terminal():
    result = run_cli("profile", "list")
    assert result.returncode == 0
    for harness, version in (("codex", "codex-2026-11"),
                             ("claude-code", "claude-code-2026-11"),
                             ("copilot-cli", "copilot-cli-2026-11")):
        assert harness in result.stdout
        assert version in result.stdout


def test_profile_list_json():
    result = run_cli("profile", "list", "--format", "json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert [p["id"] for p in data["profiles"]] == [
        "codex", "claude-code", "copilot-cli"]
    assert data["profiles"][0]["rules_hash"].startswith("sha256:")


def test_version():
    result = run_cli("version")
    assert result.returncode == 0
    assert "instructionroot 1.0.0" in result.stdout
    assert "codex-2026-11" in result.stdout
    assert "instructionroot-oracle 0.1.0" in result.stdout


# ---------------------------------------------------------------------------
# inspect / verify on the synthetic PASS repo
# ---------------------------------------------------------------------------

def test_inspect_json_pass_and_hash_verifies(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli(
        "inspect", "--harness", "codex",
        "--cwd", str(repo / "services" / "payments"),
        "--home", str(home), "--format", "json")
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["verdict"] == "PASS"
    assert len(receipt["sources"]) == 4
    assert [s["discovery_rule"] for s in receipt["sources"]] == [
        "codex.user", "codex.repo-chain", "codex.repo-chain",
        "codex.repo-chain"]
    assert verify_receipt(receipt)
    assert receipt["receipt_hash"] == receipt_hash_for(receipt)


def test_inspect_terminal_redacts_home(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli(
        "inspect", "--harness", "codex",
        "--cwd", str(repo / "services" / "payments"),
        "--home", str(home))
    assert result.returncode == 0
    assert "<HOME>/.codex/AGENTS.md" in result.stdout
    assert str(home) not in result.stdout
    assert "VERDICT: PASS" in result.stdout


def test_verify_pass_exit_0(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli(*verify_args(repo, home))
    assert result.returncode == 0, result.stderr
    assert "VERDICT: PASS" in result.stdout


def test_inspect_deterministic_hash(tmp_path):
    repo, home = make_repo(tmp_path)
    hashes = []
    for _ in range(2):
        result = run_cli(
            "inspect", "--harness", "codex",
            "--cwd", str(repo / "services" / "payments"),
            "--home", str(home), "--format", "json")
        assert result.returncode == 0
        hashes.append(json.loads(result.stdout)["receipt_hash"])
    assert hashes[0] == hashes[1]


def test_md_and_html_formats(tmp_path):
    repo, home = make_repo(tmp_path)
    for fmt in ("md", "html"):
        result = run_cli(
            "inspect", "--harness", "codex",
            "--cwd", str(repo / "services" / "payments"),
            "--home", str(home), "--format", fmt)
        assert result.returncode == 0, fmt
        assert "PASS" in result.stdout, fmt
        assert "receipt_hash" in result.stdout.lower().replace(" ", "") \
            or "Receipt hash" in result.stdout, fmt
    result = run_cli(
        "inspect", "--harness", "codex",
        "--cwd", str(repo / "services" / "payments"),
        "--home", str(home), "--format", "html")
    assert result.stdout.startswith("<!DOCTYPE html>")
    assert "https://" not in result.stdout.replace(
        "https://developers.openai.com", "").replace(
        "https://docs.anthropic.com", "").replace(
        "https://docs.github.com", "")
    # The HTML report carries no external references at all (the
    # profile source URLs live in `profile list`, not in receipts).


# ---------------------------------------------------------------------------
# WARN / BLOCK / policy escalation
# ---------------------------------------------------------------------------

def test_verify_warn_exit_10_and_allow_warn(tmp_path):
    repo, home = make_repo(tmp_path)
    nested = repo / "services" / "payments" / "AGENTS.md"
    nested.write_text("# synthetic untracked change\n", encoding="utf-8")
    _git(repo, "rm", "-q", "--cached", "services/payments/AGENTS.md")
    result = run_cli(*verify_args(repo, home))
    assert result.returncode == 10, result.stdout
    assert "VERDICT: WARN" in result.stdout
    result = run_cli(*verify_args(repo, home, extra=["--allow-warn"]))
    assert result.returncode == 0


def test_verify_block_exit_20_symlink_escape(tmp_path):
    repo, home = make_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_text(
        "# synthetic outside instructions\n", encoding="utf-8")
    target = repo / "services" / "payments" / "AGENTS.md"
    target.unlink()
    target.symlink_to(outside / "AGENTS.md")
    result = run_cli(*verify_args(repo, home))
    assert result.returncode == 20, result.stdout
    assert "VERDICT: BLOCK" in result.stdout
    assert "SYMLINK_ESCAPE" in result.stdout


def test_policy_file_escalates_warn_to_block(tmp_path):
    repo, home = make_repo(tmp_path)
    nested = repo / "services" / "payments" / "AGENTS.md"
    nested.write_text("# synthetic untracked change\n", encoding="utf-8")
    _git(repo, "rm", "-q", "--cached", "services/payments/AGENTS.md")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"block_repo_untracked": True}),
                      encoding="utf-8")
    result = run_cli(*verify_args(repo, home, extra=["--policy", str(policy)]))
    assert result.returncode == 20, result.stdout
    assert "VERDICT: BLOCK" in result.stdout


def test_strict_escalates_warn_to_block(tmp_path):
    repo, home = make_repo(tmp_path)
    nested = repo / "services" / "payments" / "AGENTS.md"
    nested.write_text("# synthetic untracked change\n", encoding="utf-8")
    _git(repo, "rm", "-q", "--cached", "services/payments/AGENTS.md")
    result = run_cli(*verify_args(repo, home, extra=["--strict"]))
    assert result.returncode == 20


def test_claude_import_escape_blocks(tmp_path):
    repo, home = make_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "shared.md").write_text(
        "# synthetic outside import target\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text(
        "# synthetic claude instructions\n\n@../outside/shared.md\n",
        encoding="utf-8")
    result = run_cli(
        "verify", "--harness", "claude-code",
        "--cwd", str(repo), "--home", str(home))
    assert result.returncode == 20, result.stdout
    assert "VERDICT: BLOCK" in result.stdout


# ---------------------------------------------------------------------------
# Fail-closed inputs: never a PASS, always non-zero
# ---------------------------------------------------------------------------

def test_unknown_harness_exit_40(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli("verify", "--harness", "bogus",
                     "--cwd", str(repo), "--home", str(home))
    assert result.returncode == 40
    assert "UNSUPPORTED_PROFILE" in result.stderr
    assert "PASS" not in result.stdout


def test_unknown_profile_version_exit_40(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli(*verify_args(
        repo, home, extra=["--profile-version", "codex-1999-01"]))
    assert result.returncode == 40
    assert "UNSUPPORTED_PROFILE" in result.stderr


def test_missing_cwd_exit_30(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli("verify", "--harness", "codex",
                     "--cwd", str(tmp_path / "nope"), "--home", str(home))
    assert result.returncode == 30
    assert "INPUT_ERROR" in result.stderr
    assert "PASS" not in result.stdout


@pytest.mark.parametrize("content", [
    '{"block_repo_untracked": "yes"}',   # non-bool value
    '{"unknown_field_xyz": true}',       # unknown field
    '{not json',                          # malformed JSON
    '[]',                                 # not an object
])
def test_malformed_policy_exit_30(tmp_path, content):
    repo, home = make_repo(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text(content, encoding="utf-8")
    result = run_cli(*verify_args(
        repo, home, extra=["--policy", str(policy)]))
    assert result.returncode == 30, (content, result.stdout, result.stderr)
    assert "INPUT_ERROR" in result.stderr
    assert "PASS" not in result.stdout


def test_missing_policy_file_exit_30(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli(*verify_args(
        repo, home, extra=["--policy", str(tmp_path / "nope.json")]))
    assert result.returncode == 30


def test_policy_values_wrapper_accepted(tmp_path):
    repo, home = make_repo(tmp_path)
    nested = repo / "services" / "payments" / "AGENTS.md"
    nested.write_text("# synthetic untracked change\n", encoding="utf-8")
    _git(repo, "rm", "-q", "--cached", "services/payments/AGENTS.md")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps({"values": {"block_repo_untracked": True}}),
        encoding="utf-8")
    result = run_cli(*verify_args(repo, home, extra=["--policy", str(policy)]))
    assert result.returncode == 20


# ---------------------------------------------------------------------------
# export / oracle
# ---------------------------------------------------------------------------

def test_export_writes_all_formats(tmp_path):
    repo, home = make_repo(tmp_path)
    out = tmp_path / "out"
    out.mkdir()  # --output names an existing directory -> receipt.<ext> inside
    result = run_cli(
        "export", "--harness", "codex",
        "--cwd", str(repo / "services" / "payments"),
        "--home", str(home), "--format", "json,md,html",
        "--output", str(out))
    assert result.returncode == 0, result.stderr
    receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["verdict"] == "PASS"
    assert verify_receipt(receipt)
    assert "PASS" in (out / "receipt.md").read_text(encoding="utf-8")
    assert (out / "receipt.html").read_text(encoding="utf-8").startswith(
        "<!DOCTYPE html>")


def test_export_default_location(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli(
        "export", "--harness", "codex",
        "--cwd", str(repo / "services" / "payments"),
        "--home", str(home))
    assert result.returncode == 0, result.stderr
    default = repo / "services" / "payments" / ".instructionroot" / "receipt.json"
    assert default.exists()
    assert json.loads(default.read_text(encoding="utf-8"))["verdict"] == "PASS"


def test_oracle_parity_pass(tmp_path):
    repo, home = make_repo(tmp_path)
    result = run_cli(
        "oracle", "--harness", "codex",
        "--cwd", str(repo / "services" / "payments"),
        "--home", str(home))
    assert result.returncode == 0, result.stderr
    assert "RESULT: PARITY" in result.stdout
    assert "receipt_hash_parity=100%" in result.stdout


def test_oracle_parity_block(tmp_path):
    repo, home = make_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_text(
        "# synthetic outside instructions\n", encoding="utf-8")
    target = repo / "services" / "payments" / "AGENTS.md"
    target.unlink()
    target.symlink_to(outside / "AGENTS.md")
    result = run_cli(
        "oracle", "--harness", "codex",
        "--cwd", str(repo / "services" / "payments"),
        "--home", str(home))
    assert result.returncode == 0, result.stderr
    assert "RESULT: PARITY" in result.stdout
    assert "oracle verdict: BLOCK" in result.stdout
