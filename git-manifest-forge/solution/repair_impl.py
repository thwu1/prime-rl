#!/usr/bin/env python3
"""Repair a corrupted git repository.

Diagnoses and fixes all corruption issues using only Python's standard library.
No git commands or git libraries are used.

Handles:
- Misplaced loose objects (SHA path doesn't match content hash)
- Tree entry sort order (Git's canonical directory-suffix sort)
- Index file SHA-1 trailer checksum
- Working tree files diverged from HEAD blobs
- Cascading fixes: tree SHA changes propagate through commits and refs
- Cleanup of old corrupt objects to satisfy git fsck --strict
"""

import hashlib
import os
import struct
import zlib

REPO = "/app/repo"
GIT = os.path.join(REPO, ".git")
OBJECTS = os.path.join(GIT, "objects")


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def read_obj(sha):
    """Read and decompress a loose git object. Returns (type_str, content_bytes)."""
    path = os.path.join(OBJECTS, sha[:2], sha[2:])
    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())
    nul = raw.index(b"\x00")
    hdr = raw[:nul].decode()
    typ, _ = hdr.split(" ")
    return typ, raw[nul + 1:]


def write_obj(typ, content):
    """Write a git object. Returns the hex SHA."""
    hdr = f"{typ} {len(content)}".encode() + b"\x00"
    raw = hdr + content
    h = sha1(raw)
    d = os.path.join(OBJECTS, h[:2])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, h[2:])
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(zlib.compress(raw))
    return h


def del_obj(sha):
    """Delete a loose object file and clean up empty parent directory."""
    p = os.path.join(OBJECTS, sha[:2], sha[2:])
    if os.path.exists(p):
        os.remove(p)
        d = os.path.dirname(p)
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)


def parse_tree(data):
    """Parse tree binary content into list of (name, mode_int, sha_hex)."""
    entries = []
    i = 0
    while i < len(data):
        sp = data.index(b" ", i)
        mode = int(data[i:sp], 8)
        nul = data.index(b"\x00", sp + 1)
        name = data[sp + 1 : nul].decode()
        entry_sha = data[nul + 1 : nul + 21].hex()
        entries.append((name, mode, entry_sha))
        i = nul + 21
    return entries


def serialize_tree(entries):
    """Serialize tree entries to binary content."""
    buf = b""
    for name, mode, entry_sha in entries:
        buf += format(mode, "o").encode() + b" " + name.encode() + b"\x00"
        buf += bytes.fromhex(entry_sha)
    return buf


def tree_sort_key(entry):
    """Git's canonical tree sort: directories compare as name + '/'."""
    name, mode, _ = entry
    return name + "/" if (mode & 0o170000) == 0o040000 else name


# ── Fix 1: Misplaced loose objects ───────────────────────────────────────


def fix_misplaced_objects():
    """Scan all loose objects; move any whose SHA doesn't match their path."""
    for prefix in sorted(os.listdir(OBJECTS)):
        pdir = os.path.join(OBJECTS, prefix)
        if not os.path.isdir(pdir) or prefix in ("info", "pack"):
            continue
        for fname in list(os.listdir(pdir)):
            fpath = os.path.join(pdir, fname)
            implied_sha = prefix + fname
            with open(fpath, "rb") as f:
                compressed = f.read()
            try:
                raw = zlib.decompress(compressed)
            except zlib.error:
                continue
            actual_sha = sha1(raw)
            if actual_sha != implied_sha:
                correct_dir = os.path.join(OBJECTS, actual_sha[:2])
                os.makedirs(correct_dir, exist_ok=True)
                correct_path = os.path.join(correct_dir, actual_sha[2:])
                if not os.path.exists(correct_path):
                    os.rename(fpath, correct_path)
                else:
                    os.remove(fpath)
                if os.path.isdir(pdir) and not os.listdir(pdir):
                    os.rmdir(pdir)


# ── Fix 2: Tree sort order (bottom-up recursive) ────────────────────────


def fix_tree(sha, remap):
    """Recursively fix tree sort order. Returns (possibly new) SHA.

    Processes sub-trees first so child SHA updates propagate upward.
    Records old_sha -> new_sha in remap dict.
    """
    if sha in remap:
        return remap[sha]

    typ, data = read_obj(sha)
    if typ != "tree":
        return sha

    entries = parse_tree(data)
    new_entries = []
    changed = False

    for name, mode, child_sha in entries:
        if (mode & 0o170000) == 0o040000:
            fixed = fix_tree(child_sha, remap)
            if fixed != child_sha:
                changed = True
            new_entries.append((name, mode, fixed))
        else:
            new_entries.append((name, mode, child_sha))

    correct_order = sorted(new_entries, key=tree_sort_key)
    if correct_order != new_entries:
        changed = True

    if changed:
        new_data = serialize_tree(correct_order)
        new_sha = write_obj("tree", new_data)
        remap[sha] = new_sha
        return new_sha

    return sha


# ── Fix 3: Commit chain ─────────────────────────────────────────────────


def fix_commit_chain(head_sha, tree_remap):
    """Walk commit chain, rewrite any commit whose tree or parent changed.

    Returns mapping of old_commit_sha -> new_commit_sha.
    """
    commit_remap = {}

    # Collect the full commit chain (HEAD -> root)
    chain = []
    cur = head_sha
    while cur:
        typ, data = read_obj(cur)
        text = data.decode("utf-8")
        parents = []
        for line in text.split("\n"):
            if line == "":
                break
            if line.startswith("parent "):
                parents.append(line[7:])
        chain.append((cur, text, parents))
        cur = parents[0] if parents else None

    # Process oldest-to-newest so parent remaps are available
    for commit_sha, text, parents in reversed(chain):
        lines = text.split("\n")
        hdr_end = lines.index("")

        tree_sha = None
        for line in lines[:hdr_end]:
            if line.startswith("tree "):
                tree_sha = line[5:]

        new_tree = tree_remap.get(tree_sha, tree_sha)
        new_parents = [commit_remap.get(p, p) for p in parents]

        if new_tree != tree_sha or new_parents != parents:
            new_hdr = []
            pi = 0
            for line in lines[:hdr_end]:
                if line.startswith("tree "):
                    new_hdr.append(f"tree {new_tree}")
                elif line.startswith("parent "):
                    new_hdr.append(f"parent {new_parents[pi]}")
                    pi += 1
                else:
                    new_hdr.append(line)

            new_text = "\n".join(new_hdr) + "\n" + "\n".join(lines[hdr_end:])
            new_commit = write_obj("commit", new_text.encode("utf-8"))
            commit_remap[commit_sha] = new_commit

    return commit_remap


# ── Fix 4: Index checksum ────────────────────────────────────────────────


def fix_index_checksum():
    """Recompute and overwrite the index file's SHA-1 trailer checksum."""
    idx_path = os.path.join(GIT, "index")
    with open(idx_path, "rb") as f:
        data = f.read()

    stored = data[-20:]
    computed = hashlib.sha1(data[:-20]).digest()
    if stored != computed:
        with open(idx_path, "wb") as f:
            f.write(data[:-20] + computed)


# ── Fix 5: Working tree from blobs ───────────────────────────────────────


def fix_working_tree():
    """Restore any working tree file whose content doesn't match its index blob."""
    idx_path = os.path.join(GIT, "index")
    with open(idx_path, "rb") as f:
        data = f.read()

    count = struct.unpack(">I", data[8:12])[0]
    off = 12

    for _ in range(count):
        blob_sha = data[off + 40 : off + 60].hex()
        flags = struct.unpack(">H", data[off + 60 : off + 62])[0]
        nlen = flags & 0xFFF
        name = data[off + 62 : off + 62 + nlen].decode()

        total = 62 + nlen
        pad = 8 - (total % 8)
        off += total + pad

        wt_path = os.path.join(REPO, name)
        if not os.path.exists(wt_path):
            continue

        with open(wt_path, "rb") as f:
            wt_data = f.read()

        wt_hdr = f"blob {len(wt_data)}".encode() + b"\x00"
        wt_sha = sha1(wt_hdr + wt_data)

        if wt_sha != blob_sha:
            try:
                _, blob_data = read_obj(blob_sha)
                with open(wt_path, "wb") as f:
                    f.write(blob_data)
            except Exception:
                pass


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    # 1. Fix misplaced objects (SHA path != content hash)
    fix_misplaced_objects()

    # 2. Read HEAD ref to find current commit
    with open(os.path.join(GIT, "HEAD")) as f:
        head = f.read().strip()
    ref_name = head[5:] if head.startswith("ref: ") else None
    ref_file = os.path.join(GIT, ref_name) if ref_name else None

    with open(ref_file) as f:
        head_sha = f.read().strip()

    # 3. Fix tree sort order for all reachable trees
    tree_remap = {}
    cur = head_sha
    while cur:
        typ, cdata = read_obj(cur)
        for line in cdata.decode().split("\n"):
            if line.startswith("tree "):
                fix_tree(line[5:], tree_remap)
            elif line == "":
                break
        parents = []
        for line in cdata.decode().split("\n"):
            if line == "":
                break
            if line.startswith("parent "):
                parents.append(line[7:])
        cur = parents[0] if parents else None

    # 4. Rewrite commits if any trees changed
    commit_remap = {}
    if tree_remap:
        commit_remap = fix_commit_chain(head_sha, tree_remap)

    # 5. Update ref to point to new HEAD commit
    if head_sha in commit_remap and ref_file:
        with open(ref_file, "w") as f:
            f.write(commit_remap[head_sha] + "\n")

    # 6. Delete old corrupt objects
    for old_sha in tree_remap:
        del_obj(old_sha)
    for old_sha in commit_remap:
        del_obj(old_sha)

    # 7. Fix index checksum
    fix_index_checksum()

    # 8. Restore working tree files from blobs
    fix_working_tree()


if __name__ == "__main__":
    main()
