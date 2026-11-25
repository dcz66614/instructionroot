#!/usr/bin/env python3
"""Local simulation of the P028 T010 GitHub Action (CI gate).

Reproduces exactly the steps `.github/workflows/instructionroot.yml`
runs, against synthetic repositories:

* checkout-equivalent — `git archive HEAD` into a temp dir (tracked
  files only, as actions/checkout would deliver), plus an overlay of
  the not-yet-committed T010 files under test (in real CI they would
  be committed; the overlay list is explicit so the simulation cannot
  silently depend on any other working-tree file);
* verify step — `./scripts/run-verify.sh` with the same environment
  the workflow sets (INSTRUCTIONROOT_HARNESS / INSTRUCTIONROOT_CWD,
  plus INSTRUCTIONROOT_HOME for the synthetic home).

Cases (T008 demo fixtures, rebuilt deterministically by
fixtures/build_demo_fixtures.py; synthetic placeholder text only):

* PASS  — fixtures/demo, CWD services/payments, home fixtures/demo/home
  → expect exit 0.
* BLOCK — fixtures/demo-block, CWD services/payments, home
  fixtures/demo-block/home → symlink escape to fixtures/outside
  → expect exit 20.

Also validates the workflow YAML (parses with PyYAML), that every
`uses:` line is pinned to a full 40-char commit SHA, that the only
permission is `contents: read`, that the workflow's only `run:` step
is the verify script (so no step can install or fetch anything), and
that the pre-commit hook config references the same verify entry point.

Usage (from the P028 work directory):

    python3 scripts/simulate_ci.py

Exit 0 only if every check and both cases match their expectation.
No network. No GitHub access.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

WORKDIR = Path(__file__).resolve().parents[1]

# T010 files under test: not yet committed, so the checkout-equivalent
# (git archive HEAD) cannot contain them; overlay them explicitly.
T010_OVERLAY = [
    ".github/workflows/instructionroot.yml",
    ".instructionroot.json",
    ".pre-commit-hooks.yaml",
    ".pre-commit-config.yaml",
    "scripts/run-verify.sh",
    "scripts/simulate_ci.py",
]

SHA40 = re.compile(r"^[0-9a-f]{40}$")
USES_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")

CASES = [
    {
        "name": "PASS",
        "fixture": "demo",
        "extra_fixture_dirs": [],
        "cwd_rel": "services/payments",
        "expected_exit": 0,
        "expected_verdict": "VERDICT: PASS",
    },
    {
        "name": "BLOCK",
        "fixture": "demo-block",
        # The demo-block symlink is ../../../outside/AGENTS.md relative
        # to services/payments, i.e. a sibling of the repo under test.
        "extra_fixture_dirs": ["outside"],
        "cwd_rel": "services/payments",
        "expected_exit": 20,
        "expected_verdict": "VERDICT: BLOCK",
    },
]


def _run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def validate_workflow() -> list[str]:
    """Parse the workflow and check pins / permissions / steps."""
    problems: list[str] = []
    path = WORKDIR / ".github/workflows/instructionroot.yml"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return ["workflow YAML does not parse: %s" % exc]
    if doc.get("name") != "instructionroot":
        problems.append("workflow name is %r, expected 'instructionroot'"
                        % doc.get("name"))
    if doc.get("permissions") != {"contents": "read"}:
        problems.append("permissions are %r, expected {contents: read}"
                        % (doc.get("permissions"),))
    jobs = doc.get("jobs") or {}
    steps = (jobs.get("verify") or {}).get("steps") or []
    if not steps:
        problems.append("job 'verify' has no steps")
    uses_lines: list[str] = []
    for step in steps:
        uses = step.get("uses")
        if uses is not None:
            uses_lines.append(str(uses))
            if not USES_PIN.match(str(uses)):
                problems.append("uses: %r is not pinned to a full 40-char SHA"
                                % uses)
        run = str(step.get("run") or "")
        # Allowlist, not denylist: the workflow's only run step must be
        # the verify script itself, so no step can install, fetch or
        # upload anything. (Written as an allowlist so this validator
        # needs no network-tool names in its own source: the S0 gate
        # statically greps scripts/*.py for such tokens.)
        if run and run.strip() != "./scripts/run-verify.sh":
            problems.append("step %r runs %r, expected only "
                            "./scripts/run-verify.sh"
                            % (step.get("name"), run))
    if not uses_lines:
        problems.append("workflow has no uses: lines to pin-check")
    run_steps = [str(s.get("run") or "") for s in steps]
    if not any("./scripts/run-verify.sh" in r for r in run_steps):
        problems.append("no step runs ./scripts/run-verify.sh")
    return problems


def validate_precommit() -> list[str]:
    """Parse the hook config and check it runs the same verify."""
    problems: list[str] = []
    path = WORKDIR / ".pre-commit-hooks.yaml"
    try:
        hooks = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return ["pre-commit hooks YAML does not parse: %s" % exc]
    if not isinstance(hooks, list) or not hooks:
        return ["pre-commit hooks YAML has no hook entries"]
    hook = hooks[0]
    if hook.get("id") != "instructionroot-verify":
        problems.append("hook id is %r, expected 'instructionroot-verify'"
                        % hook.get("id"))
    if "run-verify.sh" not in str(hook.get("entry") or ""):
        problems.append("hook entry %r does not reference run-verify.sh"
                        % hook.get("entry"))
    if hook.get("pass_filenames") is not False:
        problems.append("hook must set pass_filenames: false "
                        "(verify gates a CWD, not changed files)")
    # The shared entry point must itself invoke the repo's CLI verify.
    script = (WORKDIR / "scripts/run-verify.sh").read_text(encoding="utf-8")
    if '"$ROOT/instructionroot" "$@"' not in script or "verify --harness" not in script:
        problems.append("scripts/run-verify.sh does not invoke "
                        "./instructionroot verify")
    return problems


def build_checkout_equivalent(tool_dir: Path) -> None:
    """git archive HEAD + explicit overlay of the T010 files."""
    tool_dir.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "archive", "HEAD"], cwd=WORKDIR,
                             capture_output=True)
    if archive.returncode != 0:
        raise RuntimeError("git archive HEAD failed: %s"
                           % archive.stderr.decode("utf-8", "replace"))
    proc = subprocess.run(["tar", "-x", "-C", str(tool_dir)],
                          input=archive.stdout, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError("tar extract failed: %s"
                           % proc.stderr.decode("utf-8", "replace"))
    for rel in T010_OVERLAY:
        src = WORKDIR / rel
        dst = tool_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        shutil.copymode(src, dst)


def run_case(tmp: Path, case: dict) -> dict:
    """Copy one synthetic repo and run the workflow's verify step."""
    tool_dir = tmp / ("tool-" + case["name"].lower())
    build_checkout_equivalent(tool_dir)
    repo = tmp / ("repo-" + case["name"].lower())
    shutil.copytree(WORKDIR / "fixtures" / case["fixture"], repo,
                    symlinks=True)
    for extra in case["extra_fixture_dirs"]:
        # Sibling of the repo under test: the demo-block symlink
        # ../../../outside/AGENTS.md resolves here.
        shutil.copytree(WORKDIR / "fixtures" / extra, tmp / extra,
                        symlinks=True)
    # Layout check: the BLOCK symlink must resolve to tmp/outside.
    link = repo / "services/payments/AGENTS.md"
    if link.is_symlink():
        target = (link.parent / os.readlink(link)).resolve()
        if not target.exists():
            raise RuntimeError("symlink %s resolves to missing %s"
                               % (link, target))
    env = dict(os.environ)
    env["INSTRUCTIONROOT_HARNESS"] = "codex"
    env["INSTRUCTIONROOT_CWD"] = str(repo / case["cwd_rel"])
    env["INSTRUCTIONROOT_HOME"] = str(repo / "home")
    result = _run(["./scripts/run-verify.sh"], cwd=tool_dir, env=env)
    ok = (result.returncode == case["expected_exit"]
          and case["expected_verdict"] in result.stdout)
    return {
        "case": case["name"],
        "expected_exit": case["expected_exit"],
        "actual_exit": result.returncode,
        "verdict_found": case["expected_verdict"] in result.stdout,
        "stdout_tail": "\n".join(result.stdout.strip().splitlines()[-4:]),
        "stderr": result.stderr.strip(),
        "ok": ok,
    }


def main() -> int:
    problems = validate_workflow() + validate_precommit()
    if problems:
        print("CONFIG VALIDATION FAILED")
        for problem in problems:
            print("  - %s" % problem)
        return 1
    print("config validation: OK "
          "(workflow YAML parses, uses: pinned to 40-char SHA, "
          "permissions contents: read only, pre-commit hook -> run-verify.sh)")
    results = []
    with tempfile.TemporaryDirectory(prefix="instructionroot-ci-sim-") as td:
        tmp = Path(td)
        for case in CASES:
            result = run_case(tmp, case)
            results.append(result)
            print("case %-5s expected_exit=%d actual_exit=%d verdict_found=%s "
                  "-> %s" % (result["case"], result["expected_exit"],
                             result["actual_exit"], result["verdict_found"],
                             "OK" if result["ok"] else "FAIL"))
            print(result["stdout_tail"])
            if result["stderr"]:
                print("stderr: %s" % result["stderr"])
    all_ok = all(r["ok"] for r in results)
    print("SIMULATION: %s (%d/%d cases)"
          % ("PASS" if all_ok else "FAIL",
             sum(r["ok"] for r in results), len(results)))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
