#!/usr/bin/env python3
"""Repair the damaged git repository at /app/repo.

Diagnoses and fixes:
1. Corrupted pack header (version field)
2. Missing pack index
3. Displaced loose objects in .git/salvaged/
4. Dangling refs (loose and packed)
"""

import os
import struct
import shutil
import subprocess
import sys

REPO = "/app/repo"
GIT_DIR = os.path.join(REPO, ".git")


def run(cmd, check=True):
    r = subprocess.run(cmd, shell=True, cwd=REPO,
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"WARN: {cmd} -> rc={r.returncode}", file=sys.stderr)
        print(r.stderr, file=sys.stderr)
    return r


# ── Step 1: Fix pack header ──────────────────────────────────────

pack_dir = os.path.join(GIT_DIR, "objects", "pack")
for fn in os.listdir(pack_dir):
    if not fn.endswith(".pack"):
        continue
    pack_path = os.path.join(pack_dir, fn)
    with open(pack_path, "rb") as f:
        data = bytearray(f.read())

    magic = data[:4]
    if magic != b"PACK":
        print(f"WARNING: {fn} does not start with PACK magic", file=sys.stderr)
        continue

    version = struct.unpack(">I", data[4:8])[0]
    if version != 2:
        print(f"Fixing pack version: {version} -> 2")
        data[4:8] = struct.pack(">I", 2)
        with open(pack_path, "wb") as f:
            f.write(data)

    # ── Step 2: Regenerate index if absent ──
    basename = fn[:-5]  # strip .pack
    idx_path = os.path.join(pack_dir, basename + ".idx")
    if not os.path.exists(idx_path):
        print(f"Regenerating pack index for {fn}")
        r = run(f"git index-pack {pack_path}")
        if r.returncode != 0:
            print(f"ERROR: git index-pack failed: {r.stderr}", file=sys.stderr)
            sys.exit(1)

# ── Step 3: Restore displaced loose objects ──────────────────────

salvaged = os.path.join(GIT_DIR, "salvaged")
if os.path.isdir(salvaged):
    objects_dir = os.path.join(GIT_DIR, "objects")
    restored = 0
    for name in os.listdir(salvaged):
        if len(name) != 40:
            continue
        try:
            int(name, 16)
        except ValueError:
            continue
        prefix, suffix = name[:2], name[2:]
        dest_dir = os.path.join(objects_dir, prefix)
        os.makedirs(dest_dir, exist_ok=True)
        src = os.path.join(salvaged, name)
        dst = os.path.join(dest_dir, suffix)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            restored += 1
    shutil.rmtree(salvaged)
    print(f"Restored {restored} loose objects from salvaged/")

# ── Step 4: Remove dangling loose refs ───────────────────────────

refs_dir = os.path.join(GIT_DIR, "refs")
for root, dirs, files in os.walk(refs_dir):
    for fn in files:
        ref_path = os.path.join(root, fn)
        try:
            with open(ref_path) as f:
                sha = f.read().strip()
        except Exception:
            continue
        if len(sha) != 40:
            continue
        r = run(f"git cat-file -e {sha}", check=False)
        if r.returncode != 0:
            rel = os.path.relpath(ref_path, GIT_DIR)
            print(f"Removing dangling ref: {rel} -> {sha}")
            os.remove(ref_path)

# ── Step 5: Clean packed-refs ────────────────────────────────────

packed_refs_path = os.path.join(GIT_DIR, "packed-refs")
if os.path.exists(packed_refs_path):
    with open(packed_refs_path) as f:
        lines = f.readlines()

    clean = []
    skip_peel = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            clean.append(line)
            skip_peel = False
            continue
        if stripped.startswith("^"):
            if not skip_peel:
                clean.append(line)
            skip_peel = False
            continue
        parts = stripped.split()
        if len(parts) >= 2 and len(parts[0]) == 40:
            sha = parts[0]
            r = run(f"git cat-file -e {sha}", check=False)
            if r.returncode == 0:
                clean.append(line)
                skip_peel = False
            else:
                print(f"Removing bad packed-ref: {stripped}")
                skip_peel = True
        else:
            clean.append(line)
            skip_peel = False

    with open(packed_refs_path, "w") as f:
        f.writelines(clean)

# ── Step 6: Verify ───────────────────────────────────────────────

print("\n=== Verification ===")
r = run("git fsck --full 2>&1", check=False)
print(r.stdout)
if r.returncode != 0:
    print(f"WARNING: git fsck exited {r.returncode}", file=sys.stderr)
    if r.stderr:
        print(r.stderr, file=sys.stderr)

r = run("git log --oneline --all --graph", check=False)
print(r.stdout)

r = run("git branch -a", check=False)
print("Branches:", r.stdout.strip())

r = run("git tag", check=False)
print("Tags:", r.stdout.strip())

print("\nRepair complete.")
