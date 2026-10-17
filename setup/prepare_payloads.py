#!/usr/bin/env python3
"""
Build and verify the payloads.

build : copy every file of the extracted Kaggle dataset into
        wiki_L/, and wiki_S/ (of size --small-mb MB). 
        Writes manifest.json (file counts, bytes, aggregate SHA-256,
        size of the uncompressed tar stream = expected baseline byte count)
        and sha256sum-compatible lists wiki_S.sha256 / wiki_L.sha256.

verify: recompute everything and compare with manifest.json.

Run on the Pi after copying the payloads from the laptop:
    python3 setup/prepare_payloads.py build  --source ~/dataset_raw --root ~/greenwarriors/payloads
    python3 setup/prepare_payloads.py verify --root ~/greenwarriors/payloads
"""
import argparse
import fnmatch
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

DIRS = {"S": "wiki_S", "L": "wiki_L"}

# Compute SHA-256 checksum of a file at provided path.
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)

    return h.hexdigest()

# List all files under base, excluding dotfiles and any matching exclude globs.
def list_files(base: Path, exclude=()):
    files = []

    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base).as_posix()

        if not p.is_file() or any(part.startswith(".") for part in p.relative_to(base).parts):
            continue

        if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
            continue

        files.append(p)

    return files

# Describe the payload directory: number of files, total bytes, aggregate SHA-256, and size of the uncompressed tar stream.
def describe(root: Path, key: str):
    d = root / DIRS[key]
    files = list_files(d)
    lines = [f"{sha256_file(p)}  {DIRS[key]}/{p.relative_to(d).as_posix()}" for p in files]
    tar_bytes = int(subprocess.run(["bash", "-o", "pipefail", "-c", f"tar -cf - {DIRS[key]} | wc -c"],
                                   cwd=root, capture_output=True, text=True, check=True).stdout)
    
    return {
        "dir": DIRS[key],
        "n_files": len(files),
        "total_bytes": sum(p.stat().st_size for p in files),
        "sha256_aggregate": hashlib.sha256("\n".join(lines).encode()).hexdigest(),
        "tar_stream_bytes": tar_bytes,
    }, lines

# Build the payloads from the source directory, creating both the "wiki_L" and "wiki_S" payloads, and write the manifest and SHA-256 files.
def build(args):
    src, root = Path(args.source).expanduser(), Path(args.root).expanduser()
    files = list_files(src, args.exclude)

    if not files:
        sys.exit(f"No files found under {src}")

    for key in DIRS:
        if (root / DIRS[key]).exists():
            sys.exit(f"{root / DIRS[key]} already exists - remove it first (payloads are built once).")
    limit = args.small_mb * 1e6
    small, acc = [], 0

    for p in files:
        if acc >= limit:
            break
        small.append(p)
        acc += p.stat().st_size

    for key, chosen in (("L", files), ("S", small)):
        for p in chosen:
            dst = root / DIRS[key] / p.relative_to(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)

    manifest = {"created_wall": time.time(), "source": str(src), "exclude": args.exclude,
                "small_target_mb": args.small_mb, "payloads": {}}
    
    for key in DIRS:
        info, lines = describe(root, key)
        manifest["payloads"][key] = info
        (root / f"{DIRS[key]}.sha256").write_text("\n".join(lines) + "\n")

    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["payloads"], indent=2))

# Verify the payloads against the manifest, recomputing the file counts, total bytes, aggregate SHA-256, and tar stream size, and report any mismatches.
def verify(args):
    root = Path(args.root).expanduser()
    manifest = json.loads((root / "manifest.json").read_text())
    ok = True

    for key, expected in manifest["payloads"].items():
        actual, _ = describe(root, key)
        for field in ("n_files", "total_bytes", "sha256_aggregate", "tar_stream_bytes"):
            if actual[field] != expected[field]:
                ok = False
                print(f"[{key}] {field}: manifest={expected[field]} actual={actual[field]}")
                
    print("Payloads OK" if ok else "Payloads MISMATCH")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", required=True, help="extracted Kaggle dataset directory")
    b.add_argument("--root", required=True, help="PAYLOAD_ROOT on the Pi")
    b.add_argument("--small-mb", type=float, default=50)
    b.add_argument("--exclude", nargs="*", default=[], help="glob(s) of files to leave out")
    v = sub.add_parser("verify")
    v.add_argument("--root", required=True)
    a = ap.parse_args()
    build(a) if a.cmd == "build" else verify(a)
