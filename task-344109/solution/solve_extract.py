#!/usr/bin/env python3
"""
Extract ZIP archives from the forensic evidence container.
Uses binary signature scanning and SHA-256 hash matching against the case database.
"""

import os
import struct
import hashlib
import sqlite3


def extract_archives(evidence_data, db_path):
    """
    Find and extract ZIP archives from evidence container using signature
    scanning and database hash verification.
    """
    # Load expected hashes from database
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT specimen_id, sha256 FROM specimens ORDER BY specimen_id"
    ).fetchall()
    conn.close()
    hash_to_sid = {sha: sid for sid, sha in rows}

    found = {}
    found_hashes = set()

    # Find all EOCD signature positions (PK\x05\x06)
    eocd_ends = []
    for i in range(len(evidence_data) - 22 + 1):
        if evidence_data[i:i + 4] == b'PK\x05\x06':
            comment_len = struct.unpack_from('<H', evidence_data, i + 20)[0]
            end = i + 22 + comment_len
            if end <= len(evidence_data):
                eocd_ends.append(end)

    # Find all local file header positions (PK\x03\x04)
    lfh_starts = []
    for i in range(len(evidence_data) - 4 + 1):
        if evidence_data[i:i + 4] == b'PK\x03\x04':
            lfh_starts.append(i)

    # Phase 1: Try each (lfh_start, eocd_end) pair — handles non-prepended archives
    for end_pos in eocd_ends:
        if len(found) == len(hash_to_sid):
            break
        for start_pos in lfh_starts:
            if start_pos >= end_pos - 22:
                continue
            chunk = evidence_data[start_pos:end_pos]
            h = hashlib.sha256(chunk).hexdigest()
            if h in hash_to_sid and h not in found_hashes:
                sid = hash_to_sid[h]
                found[sid] = (start_pos, len(chunk), h)
                found_hashes.add(h)
                break

    # Phase 2: Handle archives with prepended data — extend backward from LFH
    remaining = {sha: sid for sha, sid in hash_to_sid.items() if sha not in found_hashes}
    if remaining:
        for end_pos in eocd_ends:
            if not remaining:
                break
            for start_pos in lfh_starts:
                if start_pos >= end_pos - 22:
                    continue
                # Already matched in phase 1 — skip
                check = hashlib.sha256(evidence_data[start_pos:end_pos]).hexdigest()
                if check in found_hashes:
                    continue
                # Extend backward to find prepended data
                for offset in range(1, min(start_pos + 1, 16384)):
                    adj_start = start_pos - offset
                    chunk = evidence_data[adj_start:end_pos]
                    h = hashlib.sha256(chunk).hexdigest()
                    if h in remaining:
                        sid = remaining.pop(h)
                        found[sid] = (adj_start, len(chunk), h)
                        found_hashes.add(h)
                        break
                if not remaining:
                    break

    return found


def main():
    os.makedirs("/app/extracted", exist_ok=True)

    with open("/app/evidence.bin", "rb") as f:
        evidence = f.read()

    results = extract_archives(evidence, "/app/casedb.sqlite")

    # Write extracted specimens
    for sid in sorted(results):
        offset, size, sha = results[sid]
        chunk = evidence[offset:offset + size]
        path = f"/app/extracted/specimen_{sid}.zip"
        with open(path, "wb") as f:
            f.write(chunk)
        print(f"Extracted specimen_{sid}.zip: offset={offset}, size={size}")

    # Generate integrity manifest in sha256sum format
    with open("/app/integrity.sha256", "w") as f:
        for sid in sorted(results):
            _, _, sha = results[sid]
            f.write(f"{sha}  specimen_{sid}.zip\n")

    print(f"Extracted {len(results)} specimens to /app/extracted/")


if __name__ == "__main__":
    main()
