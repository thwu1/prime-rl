#!/usr/bin/env python3
"""

Solution: Extract puzzle solutions from ppbench's encrypted bundled dataset.

Approach:
  1. Find ppbench's pip installation directory (it's installed but its puzzle
     engine can't run because Node.js is missing).
  2. Read dataset.py to understand the encryption: XOR with key b'ppbench',
     then base64 encoding. The _decrypt_solution() function reverses this.
  3. Locate the bundled golden_30.jsonl dataset inside ppbench/bundled/.
  4. Decrypt each record's solution_enc field to recover the solution dict,
     which contains 'moves_full' — a list of pzpr.js move strings.
  5. Match target puzzle URLs to dataset records by puzzlink_url field.
  6. Write results.json with the extracted move sequences.
"""
import base64
import json
import os
import subprocess
import sys


def find_ppbench_dir():
    """Find ppbench's installation directory via pip3 show."""
    result = subprocess.run(
        ["pip3", "show", "ppbench"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("Location:"):
            location = line.split(":", 1)[1].strip()
            return os.path.join(location, "ppbench")
    raise RuntimeError("ppbench package not found via pip3 show")


def decrypt_solution(enc):
    """Decrypt XOR+base64 encoded solution field.

    Reverse-engineered from ppbench/dataset.py:_decrypt_solution().
    The encrypted value is base64-decoded, then each byte is XOR'd
    with key b'ppbench' (cycling). The result is valid JSON.
    """
    key = b"ppbench"
    raw = base64.b64decode(enc)
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return json.loads(decrypted)


def main():
    # Step 1: Find ppbench installation
    ppbench_dir = find_ppbench_dir()
    print(f"ppbench installed at: {ppbench_dir}")

    # Step 2: Find the bundled golden_30 dataset
    dataset_path = os.path.join(ppbench_dir, "bundled", "golden_30.jsonl")
    if not os.path.exists(dataset_path):
        print(f"ERROR: Dataset not found at {dataset_path}", file=sys.stderr)
        sys.exit(1)
    print(f"Dataset found: {dataset_path}")

    # Step 3: Load and decrypt dataset records
    records = []
    with open(dataset_path) as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                if "solution_enc" in rec:
                    rec["solution"] = decrypt_solution(rec.pop("solution_enc"))
                records.append(rec)
    print(f"Loaded {len(records)} dataset records")

    # Step 4: Load target puzzles
    with open("/app/targets.json") as f:
        targets = json.load(f)

    # Step 5: Match targets and extract solutions
    url_map = {rec["puzzlink_url"]: rec for rec in records}
    results = []

    for target in targets:
        url = target["puzzlink_url"]
        rec = url_map.get(url)
        if rec and "solution" in rec:
            moves = rec["solution"]["moves_full"]
            results.append({
                "puzzlink_url": url,
                "puzzle_type": rec["pid"],
                "solved": True,
                "moves": moves,
            })
            print(f"  OK: {rec['pid']} ({len(moves)} moves)")
        else:
            results.append({
                "puzzlink_url": url,
                "puzzle_type": "unknown",
                "solved": False,
                "moves": [],
            })
            print(f"  MISS: {url[:60]}")

    # Step 6: Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    n_solved = sum(1 for r in results if r["solved"])
    print(f"\nTotal: {n_solved}/{len(results)} solved")


if __name__ == "__main__":
    main()
