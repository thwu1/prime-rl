#!/usr/bin/env python3
"""
Run binwalk on the evidence container and produce a structured JSON report.
Parses binwalk's columnar text output into machine-readable format.
"""

import subprocess
import json
import re


def main():
    result = subprocess.run(
        ["binwalk", "/app/evidence.bin"],
        capture_output=True, text=True,
    )

    signatures = []
    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('DECIMAL') or line.startswith('---'):
            continue
        # binwalk output: "DECIMAL    HEXADECIMAL    DESCRIPTION"
        match = re.match(r'^(\d+)\s+0x[0-9A-Fa-f]+\s+(.+)$', line)
        if match:
            signatures.append({
                "offset": int(match.group(1)),
                "description": match.group(2).strip(),
            })

    report = {
        "signatures": signatures,
        "total_signatures": len(signatures),
    }

    with open("/app/binwalk_scan.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Binwalk scan complete: {len(signatures)} signatures found")


if __name__ == "__main__":
    main()
