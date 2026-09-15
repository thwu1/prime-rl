#!/usr/bin/env python3
"""
gitforge_impl.py — Creates a fully valid Git repository from a JSON manifest.
Implements all Git binary formats (blob, tree, commit, index v2) from scratch
using only the Python standard library.
"""

import hashlib
import json
import os
import struct
import sys
import zlib


# ── Low-level object helpers ─────────────────────────────────────────────


def _sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _make_object(obj_type: str, content: bytes) -> tuple[str, bytes]:
    """Build a raw git object (header + content).  Returns (sha_hex, raw)."""
    header = f"{obj_type} {len(content)}".encode("ascii") + b"\x00"
    raw = header + content
    return _sha1_hex(raw), raw


def _store_object(git_dir: str, sha: str, raw: bytes) -> None:
    """Zlib-compress *raw* and write to .git/objects/XX/YYY…"""
    d = os.path.join(git_dir, "objects", sha[:2])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, sha[2:])
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(zlib.compress(raw))


# ── Blob ─────────────────────────────────────────────────────────────────


def _create_blob(git_dir: str, content: bytes) -> str:
    sha, raw = _make_object("blob", content)
    _store_object(git_dir, sha, raw)
    return sha


# ── Tree ─────────────────────────────────────────────────────────────────


def _tree_sort_key(entry: tuple[str, int, str]) -> str:
    """Git's canonical tree sort: directories compare as name + '/'."""
    name, mode, _ = entry
    if (mode >> 12) == 4:          # 040000 → directory
        return name + "/"
    return name


def _build_trees(git_dir: str, files: dict) -> str:
    """Recursively create tree objects from a flat {path: info} dict.

    Returns the root tree SHA.
    """
    subtrees: dict[str, dict] = {}
    blobs: dict[str, dict] = {}

    for path, info in files.items():
        parts = path.split("/", 1)
        if len(parts) == 1:
            blobs[parts[0]] = info
        else:
            subtrees.setdefault(parts[0], {})[parts[1]] = info

    entries: list[tuple[str, int, str]] = []       # (name, mode_int, sha)

    for name, info in blobs.items():
        content = info["content"]
        if isinstance(content, str):
            content = content.encode("utf-8")
        sha = _create_blob(git_dir, content)
        entries.append((name, int(info["mode"], 8), sha))

    for dirname, sub in subtrees.items():
        sub_sha = _build_trees(git_dir, sub)
        entries.append((dirname, 0o040000, sub_sha))

    # Sort with Git's canonical ordering
    entries.sort(key=_tree_sort_key)

    # Serialize
    buf = b""
    for name, mode, sha in entries:
        # Git stores modes as octal ASCII without leading zeros
        buf += format(mode, "o").encode("ascii")
        buf += b" "
        buf += name.encode("utf-8")
        buf += b"\x00"
        buf += bytes.fromhex(sha)      # 20-byte binary SHA

    tree_sha, tree_raw = _make_object("tree", buf)
    _store_object(git_dir, tree_sha, tree_raw)
    return tree_sha


# ── Commit ───────────────────────────────────────────────────────────────


def _create_commit(
    git_dir: str,
    tree_sha: str,
    parent_shas: list[str],
    author_name: str,
    author_email: str,
    timestamp: int,
    timezone: str,
    message: str,
) -> str:
    lines: list[str] = [f"tree {tree_sha}"]
    for p in parent_shas:
        lines.append(f"parent {p}")

    ident = f"{author_name} <{author_email}> {timestamp} {timezone}"
    lines.append(f"author {ident}")
    lines.append(f"committer {ident}")
    lines.append("")                   # blank separator
    lines.append(message)

    body = "\n".join(lines)
    if not body.endswith("\n"):
        body += "\n"

    sha, raw = _make_object("commit", body.encode("utf-8"))
    _store_object(git_dir, sha, raw)
    return sha


# ── Index (version 2) ───────────────────────────────────────────────────


def _write_index(
    git_dir: str,
    worktree: str,
    file_info: dict[str, dict],
) -> None:
    """Write a valid .git/index in version-2 format.

    *file_info* maps each path to ``{"mode": "100644", "sha": "<hex>"}``.
    Stat data is read from the actual working-tree files.
    """
    sorted_paths = sorted(file_info.keys())

    entries_buf = b""
    for path in sorted_paths:
        info = file_info[path]
        sha_hex = info["sha"]
        mode_str = info["mode"]

        full = os.path.join(worktree, path)
        st = os.stat(full)

        ctime_s = int(st.st_ctime_ns // 10**9)
        ctime_ns = int(st.st_ctime_ns % 10**9)
        mtime_s = int(st.st_mtime_ns // 10**9)
        mtime_ns = int(st.st_mtime_ns % 10**9)
        dev = st.st_dev & 0xFFFFFFFF
        ino = st.st_ino & 0xFFFFFFFF
        uid = st.st_uid & 0xFFFFFFFF
        gid = st.st_gid & 0xFFFFFFFF
        fsize = st.st_size & 0xFFFFFFFF

        mode_val = int(mode_str, 8)    # e.g. 0o100644 → 0x81A4 (16-bit)

        name_bytes = path.encode("utf-8")
        name_len = min(len(name_bytes), 0xFFF)
        flags = name_len               # assume_valid=0, extended=0, stage=0

        # 62 bytes of fixed-width fields  ──────────────────────────────
        entry = struct.pack(
            ">IIIIII",                  # 6 × uint32 = 24 bytes
            ctime_s, ctime_ns,
            mtime_s, mtime_ns,
            dev, ino,
        )
        entry += struct.pack(">HH", 0, mode_val)   # unused(2) + mode(2) = 4
        entry += struct.pack(">III", uid, gid, fsize)  # 12
        entry += bytes.fromhex(sha_hex)              # 20
        entry += struct.pack(">H", flags)            # 2
        # Total fixed: 24 + 4 + 12 + 20 + 2 = 62 ✓

        # Variable-length name + NUL padding to 8-byte boundary (1-8 NULs)
        entry += name_bytes
        nul_count = 8 - ((62 + len(name_bytes)) % 8)
        entry += b"\x00" * nul_count

        entries_buf += entry

    header = b"DIRC"
    header += struct.pack(">I", 2)                  # version
    header += struct.pack(">I", len(sorted_paths))  # entry count

    body = header + entries_buf
    checksum = hashlib.sha1(body).digest()           # 20-byte trailer

    with open(os.path.join(git_dir, "index"), "wb") as f:
        f.write(body + checksum)


# ── Repository assembly ─────────────────────────────────────────────────


def build_repo(manifest_path: str, output_dir: str) -> None:
    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    git_dir = os.path.join(output_dir, ".git")
    for d in ("objects", "refs/heads", "refs/tags"):
        os.makedirs(os.path.join(git_dir, d), exist_ok=True)

    # Minimal valid config
    with open(os.path.join(git_dir, "config"), "w") as f:
        f.write(
            "[core]\n"
            "\trepositoryformatversion = 0\n"
            "\tfilemode = true\n"
            "\tbare = false\n"
        )

    with open(os.path.join(git_dir, "description"), "w") as f:
        f.write(
            "Unnamed repository; edit this file 'description' "
            "to name the repository.\n"
        )

    # ── Process commits in order ─────────────────────────────────────
    id_to_sha: dict[str, str] = {}

    for ci in manifest["commits"]:
        tree_sha = _build_trees(git_dir, ci["files"])
        parent_shas = [id_to_sha[pid] for pid in ci["parents"]]
        commit_sha = _create_commit(
            git_dir,
            tree_sha,
            parent_shas,
            ci["author_name"],
            ci["author_email"],
            ci["timestamp"],
            ci["timezone"],
            ci["message"],
        )
        id_to_sha[ci["id"]] = commit_sha

    # ── Refs ─────────────────────────────────────────────────────────
    for ref, cid in manifest["branches"].items():
        ref_path = os.path.join(git_dir, ref)
        os.makedirs(os.path.dirname(ref_path), exist_ok=True)
        with open(ref_path, "w") as f:
            f.write(id_to_sha[cid] + "\n")

    with open(os.path.join(git_dir, "HEAD"), "w") as f:
        f.write(f"ref: {manifest['head_ref']}\n")

    # ── Working tree + index ─────────────────────────────────────────
    head_cid = manifest["branches"][manifest["head_ref"]]
    head_commit = next(c for c in manifest["commits"] if c["id"] == head_cid)

    index_info: dict[str, dict] = {}
    for path, info in head_commit["files"].items():
        full = os.path.join(output_dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)

        content = info["content"]
        if isinstance(content, str):
            content = content.encode("utf-8")

        with open(full, "wb") as f:
            f.write(content)

        # chmod BEFORE stat so ctime reflects final metadata
        if info["mode"] == "100755":
            os.chmod(full, 0o755)
        else:
            os.chmod(full, 0o644)

        blob_sha, _ = _make_object("blob", content)
        index_info[path] = {"mode": info["mode"], "sha": blob_sha}

    _write_index(git_dir, output_dir, index_info)


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <manifest.json> <output_dir>")
        sys.exit(1)
    build_repo(sys.argv[1], sys.argv[2])
