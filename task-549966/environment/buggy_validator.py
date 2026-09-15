#!/usr/bin/env python3
"""
BagIt bag validator - validates bags per the BagIt specification.

"""
import sys
import os
import hashlib
import re

ALGORITHMS = {
    "md5": hashlib.md5,
    "sha1": hashlib.sha1,
    "sha224": hashlib.sha224,
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}


def file_hash(path, alg):
    """Compute hex digest of a file."""
    h = ALGORITHMS[alg]()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_unsafe_path(p):
    """Check for path traversal and out-of-scope paths."""
    parts = p.replace("\\", "/").split("/")
    if ".." in parts:
        return True
    if p.startswith("/"):
        return True
    if p.startswith("~"):
        return True
    if len(p) >= 2 and p[1] == ":":
        return True
    if p.startswith("\\\\"):
        return True
    return False


def validate(bag):
    """Validate a BagIt bag. Returns list of errors (empty = valid)."""
    errs = []

    # --- bagit.txt must exist ---
    bagit_f = os.path.join(bag, "bagit.txt")
    if not os.path.isfile(bagit_f):
        return ["Missing bagit.txt"]

    raw = open(bagit_f, "rb").read()

    # Decode bagit.txt as UTF-8
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ["bagit.txt not valid UTF-8"]

    lines = [l.rstrip("\r") for l in txt.split("\n")]
    while lines and not lines[-1]:
        lines.pop()

    if not lines:
        return ["Empty bagit.txt"]

    # Parse version line
    vm = re.match(r'^BagIt-Version\s*:\s*(\d+\.\d+)\s*$', lines[0])
    if not vm:
        return [f"Invalid BagIt-Version line: {lines[0]!r}"]

    ver = vm.group(1)
    major = int(ver.split(".")[0])

    # Parse encoding (default to UTF-8 if second line absent)
    enc = "UTF-8"
    if len(lines) >= 2:
        em = re.match(r'^Tag-File-Character-Encoding\s*:\s*(.+?)\s*$', lines[1])
        if em:
            enc = em.group(1)

    # --- data/ directory must exist ---
    data_dir = os.path.join(bag, "data")
    if not os.path.isdir(data_dir):
        return ["Missing data/ directory"]

    # --- Discover manifest and tag-manifest files ---
    manifests = {}
    tag_manifests = {}
    for f in os.listdir(bag):
        m = re.match(r'^manifest-(\w+)\.txt$', f)
        if m and m.group(1).lower() in ALGORITHMS:
            manifests[f] = m.group(1).lower()
        m = re.match(r'^tagmanifest-(\w+)\.txt$', f)
        if m and m.group(1).lower() in ALGORITHMS:
            tag_manifests[f] = m.group(1).lower()

    if not manifests:
        return ["No payload manifest found"]

    # --- Parse all payload manifests ---
    all_entries = {}
    for mname, alg in manifests.items():
        mpath = os.path.join(bag, mname)
        entries = []
        try:
            with open(mpath, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    cs = parts[0].lower()
                    if not re.match(r'^[0-9a-f]+$', cs):
                        continue
                    fp = parts[1]
                    entries.append((cs, fp))
        except UnicodeDecodeError:
            errs.append(f"Cannot decode manifest {mname}")
            continue
        all_entries[mname] = (alg, entries)

    if errs:
        return errs

    # --- Security checks on manifest paths ---
    for mname, (alg, entries) in all_entries.items():
        for cs, fp in entries:
            if is_unsafe_path(fp):
                errs.append(f"Unsafe path in {mname}: {fp}")
            elif not fp.startswith("data/"):
                errs.append(f"Path outside data/ in {mname}: {fp}")

    if errs:
        return errs

    # --- Parse fetch.txt for holey bags ---
    fetch_files = set()
    fetch_f = os.path.join(bag, "fetch.txt")
    if os.path.isfile(fetch_f):
        try:
            with open(fetch_f, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    parts = re.split(r'\s+', line, maxsplit=2)
                    if len(parts) >= 3:
                        fetch_files.add(parts[2])
        except Exception:
            pass

    # --- Duplicate filename detection ---
    for mname, (alg, entries) in all_entries.items():
        seen = {}
        for cs, fp in entries:
            if fp in seen:
                if seen[fp] != cs:
                    errs.append(f"Duplicate with different hash in {mname}: {fp}")
            else:
                seen[fp] = cs

    if errs:
        return errs

    # --- File existence check ---
    for mname, (alg, entries) in all_entries.items():
        for cs, fp in entries:
            full = os.path.join(bag, fp)
            if not os.path.isfile(full) and fp not in fetch_files:
                errs.append(f"Missing file: {fp} (from {mname})")

    if errs:
        return errs

    # --- Payload checksum verification ---
    for mname, (alg, entries) in all_entries.items():
        checked = set()
        for cs, fp in entries:
            if fp in checked:
                continue
            checked.add(fp)
            full = os.path.join(bag, fp)
            if not os.path.isfile(full):
                continue
            actual = file_hash(full, alg)
            if actual != cs:
                errs.append(f"Checksum mismatch for {fp} in {mname}")

    if errs:
        return errs

    # --- Tag manifest verification ---
    for tname, alg in tag_manifests.items():
        tpath = os.path.join(bag, tname)
        try:
            with open(tpath, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    cs = parts[0].lower()
                    fp = parts[1]
                    if is_unsafe_path(fp):
                        errs.append(f"Unsafe tag path in {tname}: {fp}")
                        continue
                    full = os.path.join(bag, fp)
                    if not os.path.isfile(full):
                        errs.append(f"Missing tag file: {fp}")
                        continue
                    actual = file_hash(full, alg)
                    if actual != cs:
                        errs.append(f"Tag checksum mismatch for {fp} in {tname}")
        except UnicodeDecodeError:
            errs.append(f"Cannot decode tag manifest {tname}")

    return errs


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <bag-directory>", file=sys.stderr)
        sys.exit(2)
    bag = os.path.abspath(sys.argv[1])
    if not os.path.isdir(bag):
        print(f"Not a directory: {bag}", file=sys.stderr)
        sys.exit(2)
    errors = validate(bag)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
