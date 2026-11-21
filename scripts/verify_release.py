#!/usr/bin/env python3
"""P028 T014 — verify the frozen release in ``07_release/``.

Checks, all offline and deterministic:

1. Every file listed in ``RELEASE_MANIFEST.json`` exists under the
   release dir with the recorded size and SHA-256.
2. Every ``.zip`` in the manifest unzips cleanly (``testzip``).
3. ``source.zip`` matches the freeze commit: ``git archive`` of the
   manifest's ``freeze_commit`` must have the identical file list
   and identical per-file SHA-256 values.
4. The bundle (``P028-instructionroot-bundle.zip``) contains exactly
   ``source.zip``, ``dist.zip``, ``SHA256SUMS.txt``,
   ``RELEASE_MANIFEST.json``, ``FREEZE_REPORT.md``, ``README.md`` and
   ``LICENSE``; every member except ``SHA256SUMS.txt`` is
   byte-identical to the file in the release dir. (The bundled
   ``SHA256SUMS.txt`` predates the bundle itself, so it omits the
   bundle's own entry; every line it does contain must match the
   outer copy — see ``FREEZE_REPORT.md``.)
5. The outer ``SHA256SUMS.txt`` lists every file in the release dir
   except itself, each with the correct SHA-256.
6. The wheel inside ``dist.zip`` installs into a fresh temp venv
   (offline, ``--no-index --no-deps``) and its ``instructionroot
   verify`` on the regenerated demo fixture reproduces the exact
   receipt hash of the working-tree launcher on the same fixture.

Usage (from the P028 work directory)::

    python3 scripts/verify_release.py [--release-dir 07_release]

Exit 0 only when every check passes. No network, no writes outside
temporary directories (plus the demo-fixture regeneration, which is
the fixture builder's own deterministic rebuild).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
BUNDLE_NAME = "P028-instructionroot-bundle.zip"
BUNDLE_MEMBERS = {
    "source.zip", "dist.zip", "SHA256SUMS.txt", "RELEASE_MANIFEST.json",
    "FREEZE_REPORT.md", "README.md", "LICENSE",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_members(path: Path) -> dict[str, str]:
    """Return {member name: sha256 of member bytes} for a zip file."""
    out: dict[str, str] = {}
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise ValueError("corrupt member in %s: %s" % (path, bad))
        for info in zf.infolist():
            if info.is_dir():
                continue
            out[info.filename] = _sha256_bytes(zf.read(info.filename))
    return out


def _parse_sums(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if not digest or not name:
            digest, _, name = line.partition(" ")
        out[name.strip()] = digest.strip()
    return out


def _run(argv: list[str], *, cwd: Path | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd) if cwd else None, env=env,
                          capture_output=True, text=True)


def _receipt_hash(argv: list[str], *, env: dict | None = None) -> str | None:
    proc = _run(argv, env=env)
    if proc.returncode != 0:
        raise ValueError("command failed (%d): %s\n%s"
                         % (proc.returncode, " ".join(argv), proc.stderr))
    for line in proc.stdout.splitlines():
        if line.startswith("receipt_hash:"):
            return line.split(":", 1)[1].strip()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", default=str(WORKDIR / "07_release"))
    args = parser.parse_args(argv)
    release = Path(args.release_dir)
    checks: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))
        print("[%s] %s — %s" % ("PASS" if ok else "FAIL", name, detail))

    manifest_path = release / "RELEASE_MANIFEST.json"
    if not manifest_path.is_file():
        print("FAIL: RELEASE_MANIFEST.json missing")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    freeze = manifest.get("freeze_commit", "")
    files = manifest.get("files", {})

    # 1. Manifest entries: existence + size + SHA-256. Entries name
    # files in the release dir, except README.md / LICENSE, which are
    # repo-root files copied into the bundle (see the manifest notes).
    bad = []
    for name in sorted(files):
        entry = files[name]
        path = release / name
        if not path.is_file():
            path = WORKDIR / name
        if not path.is_file():
            bad.append("%s: missing" % name)
            continue
        size = path.stat().st_size
        digest = _sha256_file(path)
        if size != entry.get("size_bytes") or digest != entry.get("sha256"):
            bad.append("%s: size/sha mismatch (disk %d/%s...)" % (name, size, digest[:12]))
    record("manifest_entries", not bad,
           "%d entries checked" % len(files) if not bad else "; ".join(bad))

    # 2. Zips unzip cleanly.
    zips = [n for n in files if n.endswith(".zip")]
    bad = []
    for name in zips:
        try:
            _zip_members(release / name)
        except (zipfile.BadZipFile, ValueError) as exc:
            bad.append("%s: %s" % (name, exc))
    record("zips_unzip", not bad,
           "%d zips clean" % len(zips) if not bad else "; ".join(bad))

    # 3. source.zip == git archive of the freeze commit.
    ok = False
    detail = ""
    try:
        # Binary output: capture bytes, never text mode. Default
        # `git archive` format is tar; source.zip was built with the
        # zip format (inferred from its .zip name), so request it.
        raw = subprocess.run(
            ["git", "archive", "--format=zip", freeze], cwd=str(WORKDIR),
            capture_output=True)
        if raw.returncode != 0:
            detail = "git archive of %s failed" % freeze
        else:
            want: dict[str, str] = {}
            with zipfile.ZipFile(io.BytesIO(raw.stdout)) as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        want[info.filename] = _sha256_bytes(
                            zf.read(info.filename))
            got = _zip_members(release / "source.zip")
            # git archive emits a trailing "pax_global_header" entry
            # on some versions; ignore it on either side.
            want.pop("pax_global_header", None)
            got.pop("pax_global_header", None)
            ok = want == got
            detail = ("%d files, all hashes match" % len(want) if ok
                      else "file-list/hash mismatch: only-in-archive=%s only-in-source.zip=%s differing=%s"
                      % (sorted(set(want) - set(got))[:5],
                         sorted(set(got) - set(want))[:5],
                         sorted(k for k in set(want) & set(got)
                                if want[k] != got[k])[:5]))
    except (OSError, ValueError) as exc:
        detail = "error: %s" % exc
    record("source_zip_matches_freeze_commit", ok, detail)

    # 4. Bundle contents.
    ok = False
    detail = ""
    try:
        bundle_members = _zip_members(release / BUNDLE_NAME)
        names = set(bundle_members)
        if names != BUNDLE_MEMBERS:
            detail = ("members mismatch: missing=%s extra=%s"
                      % (sorted(BUNDLE_MEMBERS - names),
                         sorted(names - BUNDLE_MEMBERS)))
        else:
            mismatched = []
            with zipfile.ZipFile(release / BUNDLE_NAME) as zf:
                for name in sorted(BUNDLE_MEMBERS - {"SHA256SUMS.txt"}):
                    member_bytes = zf.read(name)
                    disk_bytes = (release / name).read_bytes() \
                        if name in ("source.zip", "dist.zip",
                                    "RELEASE_MANIFEST.json",
                                    "FREEZE_REPORT.md") \
                        else (WORKDIR / name).read_bytes()
                    if _sha256_bytes(member_bytes) != _sha256_bytes(disk_bytes):
                        mismatched.append(name)
                inner_sums = _parse_sums(
                    zf.read("SHA256SUMS.txt").decode("utf-8"))
            outer_sums = _parse_sums(
                (release / "SHA256SUMS.txt").read_text(encoding="utf-8"))
            sums_subset = all(
                outer_sums.get(k) == v for k, v in inner_sums.items())
            if mismatched:
                detail = "members differ from release dir: %s" % mismatched
            elif not sums_subset:
                detail = "bundled SHA256SUMS.txt disagrees with outer copy"
            else:
                ok = True
                detail = ("%d members, byte-identical except SHA256SUMS.txt "
                          "(inner copy omits the bundle's own entry, as "
                          "documented)" % len(names))
    except (zipfile.BadZipFile, ValueError, KeyError) as exc:
        detail = "error: %s" % exc
    record("bundle_contents", ok, detail)

    # 5. Outer SHA256SUMS.txt covers the release dir (except itself).
    ok = False
    detail = ""
    try:
        outer_sums = _parse_sums(
            (release / "SHA256SUMS.txt").read_text(encoding="utf-8"))
        disk_files = {p.name for p in release.iterdir() if p.is_file()}
        expected = disk_files - {"SHA256SUMS.txt"}
        missing = sorted(expected - set(outer_sums))
        extra = sorted(set(outer_sums) - expected)
        wrong = sorted(n for n in expected & set(outer_sums)
                       if outer_sums[n] != _sha256_file(release / n))
        ok = not missing and not extra and not wrong
        detail = ("%d entries, all match" % len(outer_sums) if ok
                  else "missing=%s extra=%s wrong=%s" % (missing, extra, wrong))
    except OSError as exc:
        detail = "error: %s" % exc
    record("sha256sums_covers_release_dir", ok, detail)

    # 6. Wheel installs offline and reproduces the demo verify hash.
    ok = False
    detail = ""
    tmp = Path(tempfile.mkdtemp(prefix="p028-verify-release-"))
    try:
        with zipfile.ZipFile(release / "dist.zip") as zf:
            wheels = [n for n in zf.namelist() if n.endswith(".whl")]
            if len(wheels) != 1:
                detail = "dist.zip must contain exactly 1 wheel, found %d" % len(wheels)
            else:
                wheel_name = wheels[0]
                zf.extractall(tmp / "dist")
                wheel_path = tmp / "dist" / wheel_name
                # Regenerate the demo fixtures deterministically.
                regen = _run([sys.executable, "fixtures/build_demo_fixtures.py"],
                             cwd=WORKDIR)
                if regen.returncode != 0:
                    detail = "demo fixture rebuild failed: %s" % regen.stderr.strip()
                else:
                    venv_dir = tmp / "venv"
                    mk = _run([sys.executable, "-m", "venv", str(venv_dir)])
                    if mk.returncode != 0:
                        detail = "venv creation failed: %s" % mk.stderr.strip()[-300:]
                    else:
                        pip = str(venv_dir / "bin" / "pip")
                        inst = _run([pip, "install", "--no-index", "--no-deps",
                                     str(wheel_path)])
                        if inst.returncode != 0:
                            detail = "wheel install failed: %s" % inst.stderr.strip()[-300:]
                        else:
                            exe = str(venv_dir / "bin" / "instructionroot")
                            demo = ["verify", "--harness", "codex",
                                    "--cwd", str(WORKDIR / "fixtures" / "demo"
                                                 / "services" / "payments"),
                                    "--home", str(WORKDIR / "fixtures" / "demo"
                                                  / "home")]
                            wheel_hash = _receipt_hash([exe, *demo])
                            repo_hash = _receipt_hash(
                                [str(WORKDIR / "instructionroot"), *demo])
                            ok = (wheel_hash is not None
                                  and wheel_hash == repo_hash)
                            detail = ("wheel %s; installed verify hash %s; "
                                      "repo launcher hash %s"
                                      % (wheel_name,
                                         (wheel_hash or "?")[:12],
                                         (repo_hash or "?")[:12]))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        detail = "error: %s" % exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    record("wheel_install_reproduces_demo_hash", ok, detail)

    failed = [name for name, passed, _ in checks if not passed]
    print("VERIFY_RELEASE: %s (%d/%d checks passed)"
          % ("PASS" if not failed else "FAIL", len(checks) - len(failed),
             len(checks)))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
