#!/usr/bin/env python3
"""
Repair damaged BagIt bags and generate forensic report.

Extracts each damaged .tar.gz archive, diagnoses RFC 8493 violations,
repairs the bag to v1.0 compliance, re-serializes as .tar.gz with proper
structure, and writes a forensic report classifying each violation.

"""
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile

DAMAGED_DIR = "/app/damaged-archives"
REPAIRED_DIR = "/app/repaired-archives"
REPORT_PATH = "/app/forensic-report.json"


def compute_hash(data, algorithm):
    h = hashlib.new(algorithm)
    h.update(data)
    return h.hexdigest()


def extract_archive(archive_path, dest_dir):
    """Extract tar.gz. Returns (bag_dir, is_flat).
    is_flat=True means files are at archive root (no top-level bag dir)."""
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(dest_dir)
    entries = os.listdir(dest_dir)
    if len(entries) == 1 and os.path.isdir(os.path.join(dest_dir, entries[0])):
        return os.path.join(dest_dir, entries[0]), False
    return dest_dir, True


def get_payload_files(bag_dir):
    """Get all payload files as {relative_path: bytes_content}."""
    data_dir = os.path.join(bag_dir, "data")
    if not os.path.isdir(data_dir):
        return {}
    result = {}
    for root, _, filenames in os.walk(data_dir):
        for fn in filenames:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, bag_dir)
            with open(full, "rb") as f:
                result[rel] = f.read()
    return result


def path_has_traversal(filepath):
    parts = filepath.replace("\\", "/").split("/")
    return ".." in parts or filepath.startswith("/") or filepath.startswith("~")


def diagnose_and_repair(name, archive_path, work_dir):
    """Diagnose all violations and repair the bag.
    Returns (repaired_bag_dir, list_of_violation_categories)."""
    violations = []

    # --- Extract ---
    extract_dir = os.path.join(work_dir, "extracted")
    os.makedirs(extract_dir)
    bag_dir, is_flat = extract_archive(archive_path, extract_dir)

    if is_flat:
        violations.append("serialization")
        proper = os.path.join(work_dir, "proper")
        os.makedirs(proper)
        bag_proper = os.path.join(proper, name)
        shutil.copytree(bag_dir, bag_proper)
        bag_dir = bag_proper

    # --- Diagnose and fix bagit.txt ---
    bagit_path = os.path.join(bag_dir, "bagit.txt")
    with open(bagit_path, "rb") as f:
        raw = f.read()

    if raw[:3] == b"\xef\xbb\xbf":
        violations.append("encoding")
        raw = raw[3:]

    text = raw.decode("utf-8")
    lines = [l.rstrip("\r") for l in text.split("\n") if l.strip()]

    has_enc_line = (
        len(lines) >= 2 and "Tag-File-Character-Encoding" in lines[1]
    )
    if not has_enc_line:
        if "structure" not in violations:
            violations.append("structure")

    with open(bagit_path, "w") as f:
        f.write("BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n")

    # --- Diagnose and fix bag-info.txt ---
    baginfo_path = os.path.join(bag_dir, "bag-info.txt")
    if os.path.isfile(baginfo_path):
        with open(baginfo_path) as f:
            info = f.read()
        if re.search(r"^\S+\s+:", info, re.MULTILINE):
            violations.append("metadata")
            info = re.sub(r"^(\S+)\s+:", r"\1:", info, flags=re.MULTILINE)
            with open(baginfo_path, "w") as f:
                f.write(info)

    # --- Get actual payload files ---
    payload = get_payload_files(bag_dir)

    # --- Discover existing manifests ---
    manifests = {}
    for entry in os.listdir(bag_dir):
        m = re.match(r"^manifest-([a-zA-Z0-9]+)\.txt$", entry)
        if m:
            manifests[entry] = m.group(1).lower()

    # --- Diagnose manifest issues ---
    for mf, alg in manifests.items():
        with open(os.path.join(bag_dir, mf)) as f:
            mf_lines = f.readlines()
        seen = set()
        for line in mf_lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^([0-9a-fA-F]+)\s+(.+)$", line)
            if not match:
                continue
            cs, fp = match.group(1), match.group(2)
            if path_has_traversal(fp):
                if "path-security" not in violations:
                    violations.append("path-security")
            if fp in seen:
                if "checksum" not in violations:
                    violations.append("checksum")
            seen.add(fp)
            full = os.path.join(bag_dir, fp)
            if os.path.isfile(full) and not path_has_traversal(fp):
                actual = compute_hash(open(full, "rb").read(), alg)
                if actual.lower() != cs.lower():
                    if "checksum" not in violations:
                        violations.append("checksum")

    # --- Check extra payload files not in any manifest ---
    manifested = set()
    for mf in manifests:
        with open(os.path.join(bag_dir, mf)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                match = re.match(r"^[0-9a-fA-F]+\s+(.+)$", line)
                if match and not path_has_traversal(match.group(1)):
                    manifested.add(match.group(1))

    for pf in sorted(payload.keys()):
        if pf not in manifested:
            if "completeness" not in violations:
                violations.append("completeness")
            break

    # --- Check different file sets across manifests ---
    if len(manifests) > 1:
        file_sets = []
        for mf in manifests:
            fs = set()
            with open(os.path.join(bag_dir, mf)) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    match = re.match(r"^[0-9a-fA-F]+\s+(.+)$", line)
                    if match and not path_has_traversal(match.group(1)):
                        fs.add(match.group(1))
            file_sets.append(frozenset(fs))
        if len(set(file_sets)) > 1:
            if "completeness" not in violations:
                violations.append("completeness")

    # --- Fix fetch.txt ---
    fetch_path = os.path.join(bag_dir, "fetch.txt")
    if os.path.isfile(fetch_path):
        with open(fetch_path) as f:
            fetch_lines = f.readlines()
        clean = []
        for line in fetch_lines:
            parts = line.strip().split(None, 2)
            if len(parts) >= 3 and path_has_traversal(parts[2]):
                if "path-security" not in violations:
                    violations.append("path-security")
            elif len(parts) >= 3:
                clean.append(line)
        if clean:
            with open(fetch_path, "w") as f:
                f.writelines(clean)
        else:
            os.remove(fetch_path)

    # --- Rewrite all manifests with correct checksums for ALL payload files ---
    for mf, alg in manifests.items():
        out = []
        for pf in sorted(payload.keys()):
            cs = compute_hash(payload[pf], alg)
            out.append(f"{cs}  {pf}")
        with open(os.path.join(bag_dir, mf), "w") as f:
            f.write("\n".join(out) + "\n")

    # --- Remove old tag manifests ---
    for entry in list(os.listdir(bag_dir)):
        if entry.startswith("tagmanifest-") and entry.endswith(".txt"):
            os.remove(os.path.join(bag_dir, entry))

    # --- Create fresh tag manifest ---
    tag_files = {}
    for entry in sorted(os.listdir(bag_dir)):
        if entry == "data" or entry.startswith("tagmanifest-"):
            continue
        full = os.path.join(bag_dir, entry)
        if os.path.isfile(full):
            with open(full, "rb") as f:
                tag_files[entry] = f.read()

    alg = list(manifests.values())[0]
    tm_name = f"tagmanifest-{alg}.txt"
    tm_out = []
    for tf in sorted(tag_files.keys()):
        cs = compute_hash(tag_files[tf], alg)
        tm_out.append(f"{cs}  {tf}")
    with open(os.path.join(bag_dir, tm_name), "w") as f:
        f.write("\n".join(tm_out) + "\n")

    return bag_dir, violations


def main():
    os.makedirs(REPAIRED_DIR, exist_ok=True)
    report = {}

    for archive_name in sorted(os.listdir(DAMAGED_DIR)):
        if not archive_name.endswith(".tar.gz"):
            continue
        name = archive_name[:-7]
        archive_path = os.path.join(DAMAGED_DIR, archive_name)
        work_dir = tempfile.mkdtemp()

        try:
            bag_dir, violations = diagnose_and_repair(
                name, archive_path, work_dir
            )
            output = os.path.join(REPAIRED_DIR, f"{name}.tar.gz")
            with tarfile.open(output, "w:gz") as tar:
                tar.add(bag_dir, arcname=name)
            report[name] = sorted(set(violations))
            print(f"Repaired {name}: {violations}")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    print(f"Wrote forensic report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
