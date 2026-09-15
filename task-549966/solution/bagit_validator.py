#!/usr/bin/env python3
"""
BagIt RFC 8493 Conformance Validator

Validates BagIt bags conforming to spec versions 0.93 through 1.0.
Handles all edge cases in the Library of Congress conformance suite.

"""

import sys
import os
import hashlib
import re


HASH_ALGORITHMS = {
    "md5": hashlib.md5,
    "sha1": hashlib.sha1,
    "sha224": hashlib.sha224,
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}


def compute_hash(filepath, algorithm):
    """Compute hex digest of a file using the named algorithm."""
    h = HASH_ALGORITHMS[algorithm]()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def check_path_security(filepath):
    """
    Check a filepath for out-of-scope references per RFC 8493 Section 5.1.

    Returns an error string if the path is unsafe, or None if OK.
    """
    normalized = filepath.replace("\\", "/")
    parts = normalized.split("/")

    if ".." in parts:
        return f"Path traversal via dot-notation: {filepath}"
    if filepath.startswith("/"):
        return f"Absolute path: {filepath}"
    if filepath.startswith("~"):
        return f"Home directory shortcut: {filepath}"
    if len(filepath) >= 2 and filepath[1] == ":":
        return f"Windows absolute path: {filepath}"
    if filepath.startswith("\\\\"):
        return f"UNC path: {filepath}"
    if filepath.startswith("%") and "\\" in filepath:
        return f"Windows environment variable path: {filepath}"

    return None


def parse_manifest_line(line):
    """
    Parse a single manifest line into (checksum, filepath).

    Handles standard format, md5sum-style asterisk prefix, leading ./ prefix,
    and filenames containing whitespace.
    """
    line = line.strip()
    if not line:
        return None

    match = re.match(r"^([0-9a-fA-F]+)\s+(.+)$", line)
    if not match:
        return None

    checksum = match.group(1).lower()
    filepath = match.group(2)

    if filepath.startswith("*"):
        filepath = filepath[1:]

    while filepath.startswith("./"):
        filepath = filepath[2:]

    return (checksum, filepath)


def read_tag_file_text(filepath, encoding):
    """Read a tag file and decode it using the specified encoding."""
    with open(filepath, "rb") as f:
        raw = f.read()

    enc_upper = encoding.upper().replace("-", "").replace("_", "")

    if enc_upper in ("UTF16", "UTF16LE", "UTF16BE"):
        return raw.decode("utf-16")
    elif enc_upper in ("ISO88591", "LATIN1", "ISO_8859_1"):
        return raw.decode("iso-8859-1")
    elif enc_upper == "UTF8":
        return raw.decode("utf-8")
    else:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            return raw.decode("utf-8", errors="replace")


def parse_manifest_file(filepath, encoding):
    """Parse a manifest or tag-manifest file."""
    text = read_tag_file_text(filepath, encoding)
    entries = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        parsed = parse_manifest_line(line)
        if parsed:
            entries.append(parsed)
    return entries


def parse_fetch_file(filepath, encoding):
    """Parse fetch.txt. Returns list of (url, size, filepath)."""
    text = read_tag_file_text(filepath, encoding)
    entries = []
    for line in text.split("\n"):
        line = line.rstrip("\r").strip()
        if not line:
            continue
        parts = re.split(r"\s+", line, maxsplit=2)
        if len(parts) >= 3:
            entries.append((parts[0], parts[1], parts[2]))
    return entries


def get_payload_files(bag_dir):
    """Get all payload files (under data/) as paths relative to bag_dir."""
    data_dir = os.path.join(bag_dir, "data")
    if not os.path.isdir(data_dir):
        return set()
    files = set()
    for root, dirs, filenames in os.walk(data_dir):
        for fn in filenames:
            full_path = os.path.join(root, fn)
            rel_path = os.path.relpath(full_path, bag_dir)
            files.add(rel_path)
    return files


def validate_bag(bag_dir):
    """
    Validate a BagIt bag per RFC 8493.

    Returns a list of error strings. Empty list means the bag is valid.
    """
    errors = []

    # ----------------------------------------------------------------
    # 1. bagit.txt: MUST exist, MUST be UTF-8, MUST NOT have BOM
    # ----------------------------------------------------------------
    bagit_path = os.path.join(bag_dir, "bagit.txt")
    if not os.path.isfile(bagit_path):
        return ["Missing required file: bagit.txt"]

    with open(bagit_path, "rb") as f:
        raw_bagit = f.read()

    # BOM check (UTF-8 BOM = EF BB BF)
    if raw_bagit[:3] == b"\xef\xbb\xbf":
        return ["bagit.txt MUST NOT contain a Byte Order Mark (BOM)"]

    try:
        bagit_text = raw_bagit.decode("utf-8")
    except UnicodeDecodeError:
        return ["bagit.txt MUST be encoded in UTF-8"]

    lines = bagit_text.split("\n")
    lines = [l.rstrip("\r") for l in lines]
    while lines and lines[-1] == "":
        lines.pop()

    if len(lines) < 2:
        return [f"bagit.txt must have exactly 2 lines, found {len(lines)}"]

    # ----------------------------------------------------------------
    # 2. Parse BagIt-Version and Tag-File-Character-Encoding
    # ----------------------------------------------------------------
    version = None
    encoding = "UTF-8"
    has_ws_before_colon = False

    v_match = re.match(r"^BagIt-Version:\s*(\d+\.\d+)\s*$", lines[0])
    if v_match:
        version = v_match.group(1)
    else:
        v_match = re.match(r"^BagIt-Version\s+:\s*(\d+\.\d+)\s*$", lines[0])
        if v_match:
            version = v_match.group(1)
            has_ws_before_colon = True
        else:
            return [f"Invalid BagIt-Version line: {lines[0]!r}"]

    e_match = re.match(r"^Tag-File-Character-Encoding:\s*(.+?)\s*$", lines[1])
    if e_match:
        encoding = e_match.group(1)
    else:
        e_match = re.match(
            r"^Tag-File-Character-Encoding\s+:\s*(.+?)\s*$", lines[1]
        )
        if e_match:
            encoding = e_match.group(1)
            has_ws_before_colon = True
        else:
            return [f"Invalid Tag-File-Character-Encoding line: {lines[1]!r}"]

    major_ver, minor_ver = version.split(".")
    major_ver, minor_ver = int(major_ver), int(minor_ver)

    if major_ver >= 1 and has_ws_before_colon:
        return ["v1.0 bagit.txt MUST NOT have whitespace before colon"]

    # ----------------------------------------------------------------
    # 3. data/ directory MUST exist
    # ----------------------------------------------------------------
    data_dir = os.path.join(bag_dir, "data")
    if not os.path.isdir(data_dir):
        errors.append("Missing required payload directory: data/")

    # ----------------------------------------------------------------
    # 4. Discover manifest and tag-manifest files
    # ----------------------------------------------------------------
    manifests = {}
    tag_manifests = {}

    try:
        bag_entries = os.listdir(bag_dir)
    except OSError as e:
        return [f"Cannot list bag directory: {e}"]

    for entry in bag_entries:
        m = re.match(r"^manifest-([a-zA-Z0-9]+)\.txt$", entry)
        if m:
            alg = m.group(1).lower()
            if alg in HASH_ALGORITHMS:
                manifests[entry] = alg
            else:
                errors.append(f"Unsupported hash algorithm in {entry}: {alg}")

        m = re.match(r"^tagmanifest-([a-zA-Z0-9]+)\.txt$", entry)
        if m:
            alg = m.group(1).lower()
            if alg in HASH_ALGORITHMS:
                tag_manifests[entry] = alg
            else:
                errors.append(f"Unsupported hash algorithm in {entry}: {alg}")

    if not manifests:
        errors.append("At least one payload manifest (manifest-*.txt) is required")
        return errors

    if errors:
        return errors

    # ----------------------------------------------------------------
    # 5. Parse all payload manifests
    # ----------------------------------------------------------------
    all_manifest_entries = {}

    for manifest_name, algorithm in manifests.items():
        manifest_path = os.path.join(bag_dir, manifest_name)
        entries = parse_manifest_file(manifest_path, encoding)
        all_manifest_entries[manifest_name] = (algorithm, entries)

    # ----------------------------------------------------------------
    # 6. Security checks on manifest paths
    # ----------------------------------------------------------------
    for manifest_name, (algorithm, entries) in all_manifest_entries.items():
        for checksum, filepath in entries:
            sec_err = check_path_security(filepath)
            if sec_err:
                errors.append(f"{manifest_name}: {sec_err}")

            if not filepath.startswith("data/"):
                errors.append(
                    f"{manifest_name}: references path outside data/: {filepath}"
                )

    if errors:
        return errors

    # ----------------------------------------------------------------
    # 7. Parse fetch.txt (if present) and check security
    # ----------------------------------------------------------------
    fetch_files = set()
    fetch_path = os.path.join(bag_dir, "fetch.txt")
    if os.path.isfile(fetch_path):
        try:
            fetch_entries = parse_fetch_file(fetch_path, encoding)
        except Exception:
            fetch_entries = []

        for url, size, fp in fetch_entries:
            sec_err = check_path_security(fp)
            if sec_err:
                errors.append(f"fetch.txt: {sec_err}")
            else:
                fetch_files.add(fp)

    if errors:
        return errors

    # ----------------------------------------------------------------
    # 8. Duplicate filename detection (version-specific rules)
    # ----------------------------------------------------------------
    for manifest_name, (algorithm, entries) in all_manifest_entries.items():
        seen = {}
        for checksum, filepath in entries:
            if filepath in seen:
                prev_hash = seen[filepath]
                if prev_hash != checksum:
                    errors.append(
                        f"{manifest_name}: {filepath} listed twice with different checksums"
                    )
                else:
                    if major_ver >= 1:
                        errors.append(
                            f"{manifest_name}: {filepath} listed more than once "
                            f"(v1.0 requires exactly once)"
                        )
            else:
                seen[filepath] = checksum

    if errors:
        return errors

    # ----------------------------------------------------------------
    # 9. Completeness checks
    # ----------------------------------------------------------------
    actual_payload = get_payload_files(bag_dir)

    # 9a. All files referenced in manifests must exist on disk or in fetch.txt
    for manifest_name, (algorithm, entries) in all_manifest_entries.items():
        for checksum, filepath in entries:
            full_path = os.path.join(bag_dir, filepath)
            if not os.path.isfile(full_path) and filepath not in fetch_files:
                errors.append(
                    f"File listed in {manifest_name} not found: {filepath}"
                )

    # 9b. All payload files on disk must be in at least one manifest
    listed_in_any = set()
    listed_per_manifest = {}

    for manifest_name, (algorithm, entries) in all_manifest_entries.items():
        manifest_files = set()
        for checksum, filepath in entries:
            listed_in_any.add(filepath)
            manifest_files.add(filepath)
        listed_per_manifest[manifest_name] = manifest_files

    for payload_file in actual_payload:
        if payload_file not in listed_in_any:
            errors.append(f"Payload file not listed in any manifest: {payload_file}")

    # 9c. v1.0: every payload file must be in EVERY manifest
    if major_ver >= 1:
        for manifest_name, manifest_files in listed_per_manifest.items():
            for payload_file in actual_payload:
                if payload_file not in manifest_files:
                    errors.append(
                        f"v1.0 requires {payload_file} in {manifest_name}"
                    )

    if errors:
        return errors

    # ----------------------------------------------------------------
    # 10. Payload checksum verification
    # ----------------------------------------------------------------
    for manifest_name, (algorithm, entries) in all_manifest_entries.items():
        seen_files = set()
        for checksum, filepath in entries:
            if filepath in seen_files:
                continue
            seen_files.add(filepath)

            full_path = os.path.join(bag_dir, filepath)
            if not os.path.isfile(full_path):
                continue

            computed = compute_hash(full_path, algorithm)
            if computed != checksum:
                errors.append(
                    f"Checksum mismatch in {manifest_name} for {filepath}: "
                    f"expected {checksum}, computed {computed}"
                )

    if errors:
        return errors

    # ----------------------------------------------------------------
    # 11. Tag manifest verification
    # ----------------------------------------------------------------
    for tag_name, algorithm in tag_manifests.items():
        tag_path = os.path.join(bag_dir, tag_name)
        entries = parse_manifest_file(tag_path, encoding)

        for checksum, filepath in entries:
            sec_err = check_path_security(filepath)
            if sec_err:
                errors.append(f"{tag_name}: {sec_err}")
                continue

            full_path = os.path.join(bag_dir, filepath)
            if not os.path.isfile(full_path):
                errors.append(
                    f"Tag file listed in {tag_name} not found: {filepath}"
                )
                continue

            computed = compute_hash(full_path, algorithm)
            if computed != checksum:
                errors.append(
                    f"Tag checksum mismatch in {tag_name} for {filepath}: "
                    f"expected {checksum}, computed {computed}"
                )

    return errors


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <bag-directory>", file=sys.stderr)
        sys.exit(2)

    bag_dir = os.path.abspath(sys.argv[1])

    if not os.path.isdir(bag_dir):
        print(f"Not a directory: {bag_dir}", file=sys.stderr)
        sys.exit(2)

    errs = validate_bag(bag_dir)

    if errs:
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
