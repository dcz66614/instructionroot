#!/usr/bin/env python3
"""P028 FIX-R4 — upload release/review/evidence files to Drive and verify size+MD5.

Usage: python3 drive-upload.py [--verify-only]
Writes review/tasks/P028-FIX-R4/drive-archive.json with file IDs and
per-file verification (local size/md5 vs Drive metadata size/md5Checksum).
Exit 0 only when every file verifies.
Folders were created fresh under the P028 root (1QQ44A3krBc3pfvpWlu6bPmDpjqb7EZWD)
on 2026-11-19; nothing from FIX-R3 was touched.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

CLI = ["/opt/hatch/bin/hatch_gws_cli", "drive"]
WORKDIR = Path(__file__).resolve().parents[3]
OUT = WORKDIR / "review/tasks/P028-FIX-R4/drive-archive.json"

FOLDERS = {
    "05_release_FIXR4_b2f9ceb": "173nVYjUAjRaRl9nPFIYUzANcY8yYCMUw",
    "04_review_FIXR4_b2f9ceb": "1n6xKFuJWdtH6QtiV6NoJrnYuwNxQH3hm",
    "03_evidence_FIXR4_b2f9ceb": "1PBB5LEiVUhTCS3PCBf9GT7OpiRMXGc3-",
}

FILES = {
    "05_release_FIXR4_b2f9ceb": [
        ("07_release/source.zip", "source.zip", "application/zip"),
        ("07_release/dist.zip", "dist.zip", "application/zip"),
        ("07_release/P028-instructionroot-bundle.zip", "P028-instructionroot-bundle.zip", "application/zip"),
        ("07_release/RELEASE_MANIFEST.json", "RELEASE_MANIFEST.json", "application/json"),
        ("07_release/FREEZE_REPORT.md", "FREEZE_REPORT.md", "text/markdown"),
        ("07_release/p028-instructionroot-b2f9ceb.bundle", "p028-instructionroot-b2f9ceb.bundle", "application/octet-stream"),
        ("07_release/SHA256SUMS.txt", "SHA256SUMS.txt", "text/plain"),
    ],
    "04_review_FIXR4_b2f9ceb": [
        ("review/tasks/P028-FIX-R4/TASK_RESULT.md", "TASK_RESULT.md", "text/markdown"),
        ("review/tasks/P028-FIX-R4/battery.log", "battery.log", "text/plain"),
        ("review/tasks/P028-FIX-R4/verify_release.log", "verify_release.log", "text/plain"),
    ],
    "03_evidence_FIXR4_b2f9ceb": [
        ("review/S0_GATE.md", "S0_GATE.md", "text/markdown"),
        ("review/S0_LOG.txt", "S0_LOG.txt", "text/plain"),
        ("review/S0_ORACLE_SUMMARY.json", "S0_ORACLE_SUMMARY.json", "application/json"),
        ("review/S0_FIXTURE_MANIFEST.json", "S0_FIXTURE_MANIFEST.json", "application/json"),
        ("review/S0_RECEIPT_HASHES.txt", "S0_RECEIPT_HASHES.txt", "text/plain"),
        ("review/tasks/P028-FIX-R4/windows_corpus.log", "windows_corpus.log", "text/plain"),
    ],
}

PRE_UPLOADED = {}


def md5_file(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def run_cli(args, **kw):
    return subprocess.run(CLI + args, capture_output=True, text=True, **kw)


def parse_json_loose(text: str):
    """Parse the first {...} JSON object in text (CLI may append a retrieved_at block)."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON in output: %r" % text[:200])
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(text[start:])
    return obj


def get_meta(file_id: str):
    params = json.dumps({"fileId": file_id,
                         "fields": "id,name,size,md5Checksum,mimeType"})
    r = run_cli(["files", "get", "--params", params])
    if r.returncode != 0:
        raise RuntimeError("files get failed for %s: %s" % (file_id, r.stderr[:300]))
    return parse_json_loose(r.stdout)


def upload(folder_id: str, local: Path, name: str, mime: str) -> str:
    payload = json.dumps({"name": name, "parents": [folder_id], "mimeType": mime})
    r = run_cli(["files", "create", "--json", payload, "--upload", str(local)])
    if r.returncode != 0:
        raise RuntimeError("upload failed for %s: %s" % (name, r.stderr[:300]))
    return parse_json_loose(r.stdout)["id"]


def _local_rel(folder: str, name: str) -> str:
    for local_rel, n, _mime in FILES.get(folder, []):
        if n == name:
            return local_rel
    for local_rel, n, _fid in PRE_UPLOADED.get(folder, []):
        if n == name:
            return local_rel
    raise KeyError("no local path for %s/%s" % (folder, name))


def main() -> int:
    if "--verify-only" in sys.argv:
        results = json.loads(OUT.read_text())
        ok_all = True
        for entry in results["files"]:
            local = WORKDIR / _local_rel(entry["folder"], entry["name"])
            meta = get_meta(entry["id"])
            ok = (int(meta.get("size", -1)) == local.stat().st_size
                  and meta.get("md5Checksum") == md5_file(local))
            entry["drive_size"] = meta.get("size")
            entry["drive_md5"] = meta.get("md5Checksum")
            entry["verified"] = ok
            ok_all &= ok
            print("%s %s %s" % ("OK " if ok else "FAIL", entry["folder"], entry["name"]))
        results["all_verified"] = ok_all
        OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print("WROTE %s — %d/%d verified" % (OUT, sum(1 for f in results["files"] if f["verified"]), len(results["files"])))
        return 0 if ok_all else 1
    results = {"folders": FOLDERS, "files": []}
    ok_all = True
    for folder_name, folder_id in FOLDERS.items():
        for local_rel, name, mime in FILES[folder_name]:
            local = WORKDIR / local_rel
            fid = upload(folder_id, local, name, mime)
            meta = get_meta(fid)
            ok = (int(meta.get("size", -1)) == local.stat().st_size
                  and meta.get("md5Checksum") == md5_file(local))
            ok_all &= ok
            results["files"].append({
                "folder": folder_name, "name": name, "id": fid,
                "size_bytes": local.stat().st_size, "md5": md5_file(local),
                "drive_size": meta.get("size"), "drive_md5": meta.get("md5Checksum"),
                "verified": ok,
            })
            print("%s %s %s" % ("OK " if ok else "FAIL", folder_name, name))
        for local_rel, name, fid in PRE_UPLOADED.get(folder_name, []):
            local = WORKDIR / local_rel
            meta = get_meta(fid)
            ok = (int(meta.get("size", -1)) == local.stat().st_size
                  and meta.get("md5Checksum") == md5_file(local))
            ok_all &= ok
            results["files"].append({
                "folder": folder_name, "name": name, "id": fid,
                "size_bytes": local.stat().st_size, "md5": md5_file(local),
                "drive_size": meta.get("size"), "drive_md5": meta.get("md5Checksum"),
                "verified": ok, "pre_uploaded": True,
            })
            print("%s %s %s (pre-uploaded)" % ("OK " if ok else "FAIL", folder_name, name))
    results["all_verified"] = ok_all
    results["count"] = len(results["files"])
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("WROTE %s — %d/%d verified" % (OUT, sum(1 for f in results["files"] if f["verified"]), len(results["files"])))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
