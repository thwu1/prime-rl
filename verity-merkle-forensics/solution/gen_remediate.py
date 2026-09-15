#!/usr/bin/env python3
"""
Generate a self-contained remediation shell script from forensic analysis results.

Reads /app/report.json and /app/manifest.json, parses superblock params from each
corrupted image, and writes /app/remediate.sh with veritysetup format commands
that rebuild hash trees preserving original cryptographic parameters.
"""

import json
import os
import struct


def read_sb_params(path, offset):
    """Extract verity parameters from on-disk superblock."""
    with open(path, "rb") as f:
        f.seek(offset)
        raw = f.read(512)
    alg = raw[32:64].split(b"\x00", 1)[0].decode("ascii")
    dbs = struct.unpack_from("<I", raw, 64)[0]
    hbs = struct.unpack_from("<I", raw, 68)[0]
    data_blocks = struct.unpack_from("<Q", raw, 72)[0]
    ss = struct.unpack_from("<H", raw, 80)[0]
    salt = raw[88 : 88 + ss].hex()
    return alg, dbs, hbs, salt, data_blocks


def main():
    with open("/app/report.json") as f:
        report = json.load(f)
    with open("/app/manifest.json") as f:
        manifest = json.load(f)

    lines = [
        "#!/bin/bash",
        "# Remediation: rebuild verity hash trees for corrupted images",
        "set -e",
        "",
        "RDIR=/tmp/verity_remediation",
        'mkdir -p "$RDIR"',
        "",
    ]

    corrupted_names = []
    for name in sorted(report["images"]):
        if report["images"][name]["integrity"] != "corrupted":
            continue
        corrupted_names.append(name)
        path = f"/app/images/{name}"
        ho = manifest[name]["hash_offset"]
        alg, dbs, hbs, salt, data_blocks = read_sb_params(path, ho)

        lines.append(f"echo 'Remediating {name}...'")
        lines.append(
            f"veritysetup format "
            f"--hash-offset {ho} "
            f"--data-blocks {data_blocks} "
            f"--data-block-size {dbs} "
            f"--hash-block-size {hbs} "
            f"--hash {alg} "
            f"--salt {salt} "
            f'"{path}" "{path}" '
            f"| grep 'Root hash:' | awk '{{print $3}}' "
            f'> "$RDIR/{name}.hash"'
        )
        lines.append("")

    # Use heredoc Python to collect root hashes into remediation.json
    lines.append("# Collect new root hashes into remediation.json")
    lines.append("python3 << 'PYEOF'")
    lines.append("import json, os")
    lines.append("rdir = '/tmp/verity_remediation'")
    lines.append("results = {}")
    lines.append("for fname in sorted(os.listdir(rdir)):")
    lines.append("    if fname.endswith('.hash'):")
    lines.append("        name = fname[:-5]")
    lines.append("        with open(os.path.join(rdir, fname)) as fh:")
    lines.append("            results[name] = fh.read().strip().lower()")
    lines.append(
        "json.dump(results, open('/app/remediation.json', 'w'), indent=2)"
    )
    lines.append(
        "print(f'Wrote /app/remediation.json with {len(results)} entries')"
    )
    lines.append("PYEOF")
    lines.append("")
    lines.append("echo 'Remediation complete.'")

    with open("/app/remediate.sh", "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod("/app/remediate.sh", 0o755)
    print("Generated /app/remediate.sh")


if __name__ == "__main__":
    main()
