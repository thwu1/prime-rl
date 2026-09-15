#!/usr/bin/env python3
"""
Generate ssdeep fuzzy hashes for all extracted specimens.
Runs the ssdeep command-line tool and captures output.
"""

import subprocess
import glob


def main():
    specimens = sorted(glob.glob("/app/extracted/specimen_*.zip"))

    result = subprocess.run(
        ["ssdeep"] + specimens,
        capture_output=True, text=True,
    )

    with open("/app/integrity.ssdeep", "w") as f:
        f.write(result.stdout)

    print(f"ssdeep fuzzy hashes written for {len(specimens)} specimens")


if __name__ == "__main__":
    main()
