#!/usr/bin/env python3
"""
Git three-way merge — implemented from scratch using only Python stdlib.

Reads/writes Git objects directly (zlib + SHA-1), walks the commit DAG to
find the merge base, performs hunk-based three-way text merge with conflict
detection, and creates a valid merge commit.

"""

import hashlib
import os
import sys
import time
import zlib
from collections import deque
from difflib import SequenceMatcher

# ---- Git object I/O -------------------------------------------------------


def read_object(repo, sha):
    """Read a loose git object.  Returns (obj_type: str, data: bytes)."""
    path = os.path.join(repo, ".git", "objects", sha[:2], sha[2:])
    with open(path, "rb") as fh:
        raw = zlib.decompress(fh.read())
    null = raw.index(b"\x00")
    hdr = raw[:null].decode("ascii")
    obj_type = hdr.split(" ", 1)[0]
    return obj_type, raw[null + 1:]


def write_object(repo, obj_type, data):
    """Write a git object, return its hex SHA-1."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    store = f"{obj_type} {len(data)}".encode("ascii") + b"\x00" + data
    sha = hashlib.sha1(store).hexdigest()
    d = os.path.join(repo, ".git", "objects", sha[:2])
    p = os.path.join(d, sha[2:])
    if not os.path.exists(p):
        os.makedirs(d, exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(zlib.compress(store))
    return sha


# ---- Tree parsing / building ----------------------------------------------


def parse_tree(data):
    """Return [(mode_str, name_str, sha_hex), ...]."""
    entries, i = [], 0
    while i < len(data):
        sp = data.index(b" ", i)
        mode = data[i:sp].decode("ascii")
        null = data.index(b"\x00", sp + 1)
        name = data[sp + 1:null].decode("utf-8")
        sha = data[null + 1:null + 21].hex()
        entries.append((mode, name, sha))
        i = null + 21
    return entries


def _tree_sort_key(entry):
    mode, name, _ = entry
    return (name + "/") if mode == "40000" else name


def make_tree_data(entries):
    """Build the binary payload for a tree object."""
    entries = sorted(entries, key=_tree_sort_key)
    parts = []
    for mode, name, sha in entries:
        parts.append(f"{mode} {name}".encode("utf-8") + b"\x00" + bytes.fromhex(sha))
    return b"".join(parts)


# ---- Commit parsing -------------------------------------------------------


def parse_commit(data):
    """Return dict with keys: tree, parents (list), author, committer, message."""
    text = data.decode("utf-8")
    lines = text.split("\n")
    info = {"parents": []}
    idx = 0
    while idx < len(lines) and lines[idx]:
        key, val = lines[idx].split(" ", 1)
        if key == "parent":
            info["parents"].append(val)
        else:
            info[key] = val
        idx += 1
    info["message"] = "\n".join(lines[idx + 1:]) if idx + 1 < len(lines) else ""
    return info


# ---- Recursive tree ↔ flat file map ---------------------------------------


def tree_to_files(repo, tree_sha, prefix=""):
    """Flatten a tree into {path: (mode, blob_sha)}."""
    _, data = read_object(repo, tree_sha)
    entries = parse_tree(data)
    files = {}
    for mode, name, sha in entries:
        path = name if not prefix else f"{prefix}/{name}"
        if mode == "40000":
            files.update(tree_to_files(repo, sha, path))
        else:
            files[path] = (mode, sha)
    return files


def files_to_tree(repo, files):
    """Build nested tree objects from {path: (mode, sha)}.  Returns root tree SHA."""
    root = {}
    for path, (mode, sha) in files.items():
        parts = path.split("/")
        cur = root
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = (mode, sha)

    def _build(node):
        entries = []
        for name, val in node.items():
            if isinstance(val, dict):
                sub_sha = _build(val)
                entries.append(("40000", name, sub_sha))
            else:
                m, s = val
                entries.append((m, name, s))
        return write_object(repo, "tree", make_tree_data(entries))

    return _build(root)


# ---- Merge-base (LCA) -----------------------------------------------------


def find_merge_base(repo, sha_a, sha_b):
    """BFS-based lowest common ancestor in the commit DAG."""
    ancestors_a = set()
    q = deque([sha_a])
    while q:
        c = q.popleft()
        if c in ancestors_a:
            continue
        ancestors_a.add(c)
        try:
            _, d = read_object(repo, c)
            for p in parse_commit(d)["parents"]:
                q.append(p)
        except Exception:
            pass

    visited = set()
    q = deque([sha_b])
    while q:
        c = q.popleft()
        if c in visited:
            continue
        if c in ancestors_a:
            return c
        visited.add(c)
        try:
            _, d = read_object(repo, c)
            for p in parse_commit(d)["parents"]:
                q.append(p)
        except Exception:
            pass
    return None


# ---- Three-way text merge --------------------------------------------------


def _hunks(base, other):
    """Diff *base* → *other* as list of (base_start, base_end, replacement_lines)."""
    sm = SequenceMatcher(None, base, other, autojunk=False)
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes()
            if tag != "equal"]


def merge_text(base_text, left_text, right_text):
    """Three-way merge.  Returns (merged_text, has_conflict)."""
    if left_text == right_text:
        return left_text, False
    if base_text == left_text:
        return right_text, False
    if base_text == right_text:
        return left_text, False

    base_l = base_text.splitlines(True)
    left_l = left_text.splitlines(True)
    right_l = right_text.splitlines(True)

    lh = _hunks(base_l, left_l)
    rh = _hunks(base_l, right_l)

    result = []
    conflict = False
    base_pos = 0
    li = ri = 0

    while li < len(lh) or ri < len(rh):
        left_cur = lh[li] if li < len(lh) else None
        right_cur = rh[ri] if ri < len(rh) else None

        if left_cur and right_cur:
            ls, le, lr = left_cur
            rs, re, rr = right_cur
            if le <= rs:
                # left hunk entirely before right — apply left
                result.extend(base_l[base_pos:ls])
                result.extend(lr)
                base_pos = le
                li += 1
            elif re <= ls:
                # right hunk entirely before left — apply right
                result.extend(base_l[base_pos:rs])
                result.extend(rr)
                base_pos = re
                ri += 1
            else:
                # overlapping
                start = min(ls, rs)
                end = max(le, re)
                result.extend(base_l[base_pos:start])
                if lr == rr:
                    result.extend(lr)
                else:
                    conflict = True
                    result.append("<<<<<<< HEAD\n")
                    result.extend(lr)
                    result.append("=======\n")
                    result.extend(rr)
                    result.append(">>>>>>> branch\n")
                base_pos = end
                li += 1
                ri += 1
        elif left_cur:
            ls, le, lr = left_cur
            result.extend(base_l[base_pos:ls])
            result.extend(lr)
            base_pos = le
            li += 1
        else:
            rs, re, rr = right_cur
            result.extend(base_l[base_pos:rs])
            result.extend(rr)
            base_pos = re
            ri += 1

    result.extend(base_l[base_pos:])
    return "".join(result), conflict


# ---- Tree-level merge -----------------------------------------------------


def merge_trees(repo, base_tree, left_tree, right_tree):
    """Merge two trees against a common base.

    Returns ({path: (mode, sha)}, has_conflicts).
    """
    base_f = tree_to_files(repo, base_tree) if base_tree else {}
    left_f = tree_to_files(repo, left_tree)
    right_f = tree_to_files(repo, right_tree)

    all_paths = sorted(set(base_f) | set(left_f) | set(right_f))
    merged = {}
    conflicts = False

    for path in all_paths:
        be = base_f.get(path)
        le = left_f.get(path)
        re = right_f.get(path)

        if le == re:
            # Both sides agree (or both deleted)
            if le:
                merged[path] = le
        elif be == le:
            # Only right changed
            if re:
                merged[path] = re
            # else: right deleted, omit
        elif be == re:
            # Only left changed
            if le:
                merged[path] = le
            # else: left deleted, omit
        elif le is None or re is None:
            # One side deleted, the other modified — keep the modified version
            # and flag a conflict
            conflicts = True
            entry = le or re
            if entry:
                merged[path] = entry
        else:
            # Both sides changed — attempt content merge
            base_txt = ""
            if be:
                _, bd = read_object(repo, be[1])
                base_txt = bd.decode("utf-8", errors="replace")

            _, ld = read_object(repo, le[1])
            _, rd = read_object(repo, re[1])
            left_txt = ld.decode("utf-8", errors="replace")
            right_txt = rd.decode("utf-8", errors="replace")

            mtxt, c = merge_text(base_txt, left_txt, right_txt)
            if c:
                conflicts = True

            blob_sha = write_object(repo, "blob", mtxt.encode("utf-8"))
            merged[path] = (le[0], blob_sha)

    return merged, conflicts


# ---- Ref helpers -----------------------------------------------------------


def read_ref(repo, name):
    p = os.path.join(repo, ".git", "refs", "heads", name)
    if os.path.exists(p):
        return open(p).read().strip()
    packed = os.path.join(repo, ".git", "packed-refs")
    if os.path.exists(packed):
        target = f"refs/heads/{name}"
        for line in open(packed):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == target:
                return parts[0]
    return None


def read_head(repo):
    content = open(os.path.join(repo, ".git", "HEAD")).read().strip()
    if content.startswith("ref: "):
        rpath = os.path.join(repo, ".git", content[5:])
        if os.path.exists(rpath):
            return open(rpath).read().strip()
    return content


def head_branch(repo):
    content = open(os.path.join(repo, ".git", "HEAD")).read().strip()
    prefix = "ref: refs/heads/"
    if content.startswith(prefix):
        return content[len(prefix):]
    return None


def write_ref(repo, name, sha):
    p = os.path.join(repo, ".git", "refs", "heads", name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(sha + "\n")


# ---- Main ------------------------------------------------------------------


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <branch>", file=sys.stderr)
        sys.exit(1)

    branch = sys.argv[1]
    repo = os.getcwd()

    our_sha = read_head(repo)
    their_sha = read_ref(repo, branch)
    if not our_sha:
        sys.exit("Cannot read HEAD")
    if not their_sha:
        sys.exit(f"Branch '{branch}' not found")

    base_sha = find_merge_base(repo, our_sha, their_sha)
    if not base_sha:
        sys.exit("No common ancestor")

    # Retrieve tree SHAs
    _, od = read_object(repo, our_sha)
    _, td = read_object(repo, their_sha)
    _, bd = read_object(repo, base_sha)
    our_tree = parse_commit(od)["tree"]
    their_tree = parse_commit(td)["tree"]
    base_tree = parse_commit(bd)["tree"]

    # Merge
    merged_files, _ = merge_trees(repo, base_tree, our_tree, their_tree)
    merged_tree = files_to_tree(repo, merged_files)

    # Build commit
    ts = int(time.time())
    ident = f"Merge Tool <merge@tool.local> {ts} +0000"
    body = (
        f"tree {merged_tree}\n"
        f"parent {our_sha}\n"
        f"parent {their_sha}\n"
        f"author {ident}\n"
        f"committer {ident}\n"
        f"\nMerge branch '{branch}'\n"
    )
    merge_sha = write_object(repo, "commit", body)

    # Update ref
    br = head_branch(repo)
    if br:
        write_ref(repo, br, merge_sha)
    else:
        with open(os.path.join(repo, ".git", "HEAD"), "w") as fh:
            fh.write(merge_sha + "\n")

    print(merge_sha)


if __name__ == "__main__":
    main()
