#!/usr/bin/env python3
"""Create firmware integrity manifest with SHA-256 hashes."""
import hashlib
import json
import os
import sys


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    root = sys.argv[1]             # CPIO filesystem root
    config_plain = sys.argv[2]     # plaintext config path

    gw_hash = sha256_file(os.path.join(root, "usr", "bin", "gateway"))
    conf_hash = sha256_file(config_plain)

    manifest = {
        "version": "2.0.0",
        "gateway_sha256": gw_hash,
        "config_sha256": conf_hash,
    }

    os.makedirs(os.path.join(root, "var"), exist_ok=True)
    manifest_path = os.path.join(root, "var", "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"gateway_sha256: {gw_hash}")
    print(f"config_sha256:  {conf_hash}")


if __name__ == "__main__":
    main()
