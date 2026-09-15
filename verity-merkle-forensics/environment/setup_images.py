#!/usr/bin/env python3
"""
Setup script for dm-verity forensic analysis task.
Creates test images with varying dm-verity configurations, then corrupts some.
"""

import json
import os
import subprocess
import sys

IMAGE_DIR = "/app/images"
MANIFEST_PATH = "/app/manifest.json"
EXPECTED_PATH = "/var/verity/expected.json"

DATA_BLOCK_SIZE = 4096

SALTS = {
    "alpha.img": "0a" * 32,
    "bravo.img": "0b" * 32,
    "charlie.img": "0c" * 32,
    "delta.img": "0d" * 32,
    "echo.img": "0e" * 32,
    "foxtrot.img": "0f" * 32,
}


def create_raw_image(name, num_blocks):
    """Create a raw image with deterministic block content."""
    path = os.path.join(IMAGE_DIR, name)
    with open(path, "wb") as f:
        for i in range(num_blocks):
            block = bytearray(DATA_BLOCK_SIZE)
            for j in range(DATA_BLOCK_SIZE):
                block[j] = (i * 7 + j * 13 + 42) & 0xFF
            f.write(bytes(block))
    return path


def format_verity(path, data_size, salt_hex, hash_alg, hash_bs):
    """Run veritysetup format with specified parameters."""
    cmd = [
        "veritysetup",
        "format",
        "--hash-offset",
        str(data_size),
        "--data-block-size",
        str(DATA_BLOCK_SIZE),
        "--hash-block-size",
        str(hash_bs),
        "--hash",
        hash_alg,
        "--salt",
        salt_hex,
        path,
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"veritysetup format failed for {path}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    params = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            params[key.strip()] = value.strip()
    return params


def corrupt_data_block(path, block_index):
    """Corrupt a data block by XOR-ing all bytes with 0xFF."""
    with open(path, "r+b") as f:
        f.seek(block_index * DATA_BLOCK_SIZE)
        original = f.read(DATA_BLOCK_SIZE)
        f.seek(block_index * DATA_BLOCK_SIZE)
        corrupted = bytes([b ^ 0xFF for b in original])
        f.write(corrupted)


def main():
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(EXPECTED_PATH), exist_ok=True)

    test_cases = [
        {
            "name": "alpha.img",
            "num_blocks": 256,
            "hash_alg": "sha256",
            "hash_bs": 4096,
            "corrupt_blocks": [],
        },
        {
            "name": "bravo.img",
            "num_blocks": 512,
            "hash_alg": "sha256",
            "hash_bs": 4096,
            "corrupt_blocks": [37],
        },
        {
            "name": "charlie.img",
            "num_blocks": 1024,
            "hash_alg": "sha512",
            "hash_bs": 4096,
            "corrupt_blocks": [100, 500, 900],
        },
        {
            "name": "delta.img",
            "num_blocks": 128,
            "hash_alg": "sha256",
            "hash_bs": 1024,
            "corrupt_blocks": [],
        },
        {
            "name": "echo.img",
            "num_blocks": 768,
            "hash_alg": "sha512",
            "hash_bs": 4096,
            "corrupt_blocks": [0, 767],
        },
        {
            "name": "foxtrot.img",
            "num_blocks": 384,
            "hash_alg": "sha256",
            "hash_bs": 1024,
            "corrupt_blocks": [42, 200],
        },
    ]

    manifest = {}
    expected = {}

    for tc in test_cases:
        name = tc["name"]
        nb = tc["num_blocks"]
        data_size = nb * DATA_BLOCK_SIZE
        salt_hex = SALTS[name]
        hash_alg = tc["hash_alg"]
        hash_bs = tc["hash_bs"]

        path = create_raw_image(name, nb)
        params = format_verity(path, data_size, salt_hex, hash_alg, hash_bs)
        root_hash = params["Root hash"]

        manifest[name] = {
            "hash_offset": data_size,
            "description": f"{nb} data blocks with appended dm-verity metadata",
        }

        expected[name] = {
            "root_hash": root_hash.lower(),
            "data_blocks": nb,
            "hash_algorithm": hash_alg,
            "data_block_size": DATA_BLOCK_SIZE,
            "hash_block_size": hash_bs,
            "salt": salt_hex,
            "status": "clean" if not tc["corrupt_blocks"] else "corrupted",
            "corrupted_data_blocks": sorted(tc["corrupt_blocks"]),
        }

        for bi in tc["corrupt_blocks"]:
            corrupt_data_block(path, bi)

        print(
            f"  {name}: {nb} blocks, alg={hash_alg}, "
            f"hbs={hash_bs}, corrupt={tc['corrupt_blocks']}"
        )

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    with open(EXPECTED_PATH, "w") as f:
        json.dump(expected, f, indent=2)

    print(f"\nManifest written to {MANIFEST_PATH}")
    print(f"Expected results written to {EXPECTED_PATH}")


if __name__ == "__main__":
    main()
