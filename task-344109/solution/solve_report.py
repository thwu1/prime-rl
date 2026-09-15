#!/usr/bin/env python3
"""
Generate the consolidated forensic report by running the parser on each
extracted specimen and merging with case database metadata, ssdeep hashes,
and YARA classification results.
"""

import json
import os
import subprocess
import sqlite3
import hashlib


def get_ssdeep_hashes():
    """Parse ssdeep output file to get per-specimen fuzzy hashes."""
    hashes = {}
    with open("/app/integrity.ssdeep") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('ssdeep,'):
                continue
            # ssdeep format: blocksize:hash1:hash2,"filename" or ,filename
            parts = line.rsplit(',', 1)
            if len(parts) == 2:
                hash_part = parts[0]
                filename = parts[1].strip('"').strip()
                basename = os.path.basename(filename)
                hashes[basename] = hash_part
    return hashes


def get_yara_results():
    """Read YARA classification results."""
    with open("/app/yara_results.json") as f:
        return json.load(f)


def main():
    db_path = "/app/casedb.sqlite"
    evidence_path = "/app/evidence.bin"
    extracted_dir = "/app/extracted"
    parser = "/app/zipforensics.py"
    report_path = "/app/report.json"

    # Read case metadata from database
    conn = sqlite3.connect(db_path)
    case = conn.execute("SELECT case_id, analyst FROM case_info").fetchone()
    specimens_db = conn.execute(
        "SELECT specimen_id, sha256, case_ref FROM specimens ORDER BY specimen_id"
    ).fetchall()
    conn.close()

    # Read evidence to compute extraction offsets
    with open(evidence_path, "rb") as f:
        evidence = f.read()

    ssdeep_hashes = get_ssdeep_hashes()
    yara_results = get_yara_results()

    specimens = []
    for sid, sha256, case_ref in specimens_db:
        specimen_path = os.path.join(extracted_dir, f"specimen_{sid}.zip")
        filename = f"specimen_{sid}.zip"

        # Run parser
        result = subprocess.run(
            ["python3", parser, specimen_path],
            capture_output=True, text=True, timeout=30,
        )
        analysis = json.loads(result.stdout)

        # Read specimen to find extraction offset in evidence
        with open(specimen_path, "rb") as f:
            specimen_data = f.read()

        specimen_hash = hashlib.sha256(specimen_data).hexdigest()
        extraction_offset = evidence.find(specimen_data)

        specimens.append({
            "specimen_id": sid,
            "sha256": specimen_hash,
            "ssdeep": ssdeep_hashes.get(filename, ""),
            "case_ref": case_ref,
            "extraction_offset": extraction_offset,
            "extraction_size": len(specimen_data),
            "yara_matches": yara_results.get(filename, []),
            "analysis": analysis,
        })

    report = {
        "case_id": case[0],
        "analyst": case[1],
        "specimens": specimens,
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
