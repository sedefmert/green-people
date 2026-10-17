#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from prepare_payloads import DIRS, describe  # noqa: E402

# Write manifest.json (+ wiki_S.sha256 / wiki_L.sha256) for EXISTING payloads, then verify.
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="~/greenwarriors/payloads", help="folder containing wiki_S/ and wiki_L/")
    args = ap.parse_args()
    root = Path(args.root).expanduser()

    for d in DIRS.values():
        if not (root / d).is_dir():
            sys.exit(f"{root / d} not found - check --root")

    manifest = {"created_wall": time.time(),
                "source": "existing wiki_S / wiki_L (prepare_dataset.py)",
                "payloads": {}}
    
    for key, d in DIRS.items():
        print(f"hashing {d} ...", flush=True)
        info, lines = describe(root, key)
        manifest["payloads"][key] = info
        (root / f"{d}.sha256").write_text("\n".join(lines) + "\n")

    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))

    for key, info in manifest["payloads"].items():
        print(f"{key}: {info['n_files']} files, {info['total_bytes'] / 1e6:.1f} MB, "
              f"tar stream {info['tar_stream_bytes'] / 1e6:.1f} MB")
        
    print(f"wrote {root / 'manifest.json'}")

    # verify with the package's own checker
    r = subprocess.run([sys.executable, str(HERE / "prepare_payloads.py"), "verify", "--root", str(root)])
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
