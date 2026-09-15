#!/usr/bin/env python3
"""Generate a corrupted git repository for the repair benchmark task.

Corruptions introduced:
1. Tree sort order: HEAD commit's root tree and src/ subtree use alphabetical
   sort instead of Git's canonical directory-suffix sort.
2. Index checksum: last 20 bytes of .git/index are zeroed.
3. Working tree: src/lib0.py is truncated.
4. Blob path: data/config.json blob stored at wrong SHA path.
"""

import hashlib
import os
import shutil
import struct
import sys
import zlib


def sha1_hex(data):
    return hashlib.sha1(data).hexdigest()


def make_object(obj_type, content):
    header = f"{obj_type} {len(content)}".encode("ascii") + b"\x00"
    raw = header + content
    return sha1_hex(raw), raw


def store_object(objects_dir, sha, raw):
    d = os.path.join(objects_dir, sha[:2])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, sha[2:])
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(zlib.compress(raw))


def create_blob(objects_dir, content):
    data = content.encode("utf-8") if isinstance(content, str) else content
    sha, raw = make_object("blob", data)
    store_object(objects_dir, sha, raw)
    return sha


def create_tree(objects_dir, entries, use_git_sort=True):
    if use_git_sort:
        entries = sorted(entries, key=lambda e: e[0] + "/" if (e[1] & 0o170000) == 0o040000 else e[0])
    else:
        entries = sorted(entries, key=lambda e: e[0])

    buf = b""
    for name, mode, sha in entries:
        buf += format(mode, "o").encode("ascii")
        buf += b" " + name.encode("utf-8") + b"\x00"
        buf += bytes.fromhex(sha)

    tree_sha, tree_raw = make_object("tree", buf)
    store_object(objects_dir, tree_sha, tree_raw)
    return tree_sha


def create_commit(objects_dir, tree_sha, parents, author_name, author_email, ts, tz, message):
    lines = [f"tree {tree_sha}"]
    for p in parents:
        lines.append(f"parent {p}")
    ident = f"{author_name} <{author_email}> {ts} {tz}"
    lines.append(f"author {ident}")
    lines.append(f"committer {ident}")
    lines.append("")
    lines.append(message)
    body = "\n".join(lines)
    if not body.endswith("\n"):
        body += "\n"
    sha, raw = make_object("commit", body.encode("utf-8"))
    store_object(objects_dir, sha, raw)
    return sha


def write_index(git_dir, worktree, entries_info, zero_checksum=False):
    sorted_paths = sorted(entries_info.keys())
    entries_buf = b""

    for path in sorted_paths:
        info = entries_info[path]
        sha_hex = info["sha"]
        mode_val = info["mode"]

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

        name_bytes = path.encode("utf-8")
        name_len = min(len(name_bytes), 0xFFF)
        flags = name_len

        entry = struct.pack(">IIIIII", ctime_s, ctime_ns, mtime_s, mtime_ns, dev, ino)
        entry += struct.pack(">I", mode_val)
        entry += struct.pack(">III", uid, gid, fsize)
        entry += bytes.fromhex(sha_hex)
        entry += struct.pack(">H", flags)
        entry += name_bytes
        padding = 8 - ((62 + len(name_bytes)) % 8)
        entry += b"\x00" * padding
        entries_buf += entry

    header = b"DIRC" + struct.pack(">II", 2, len(sorted_paths))
    body = header + entries_buf

    if zero_checksum:
        checksum = b"\x00" * 20
    else:
        checksum = hashlib.sha1(body).digest()

    with open(os.path.join(git_dir, "index"), "wb") as f:
        f.write(body + checksum)


def main():
    repo_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "repo")

    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir)

    git_dir = os.path.join(repo_dir, ".git")
    objects_dir = os.path.join(git_dir, "objects")

    for d in ("objects", "refs/heads", "refs/tags"):
        os.makedirs(os.path.join(git_dir, d), exist_ok=True)

    with open(os.path.join(git_dir, "config"), "w") as f:
        f.write("[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n")

    with open(os.path.join(git_dir, "description"), "w") as f:
        f.write("Unnamed repository; edit this file 'description' to name the repository.\n")

    # ─── File contents ───────────────────────────────────────

    c1 = {
        "README.md": ("100644", "# Forge Project\n\nA demonstration repository.\n"),
        "LICENSE": ("100644", "MIT License\n\nCopyright (c) 2024\n"),
        "src/main.py": ("100755", "#!/usr/bin/env python3\nprint('Hello, World!')\n"),
        "src/lib/utils.py": ("100644", "def helper():\n    return 42\n"),
        "src/lib/io.py": ("100644", "import sys\n\ndef read_input():\n    return sys.stdin.read()\n"),
        "data/config.json": ("100644", '{"version": 1}\n'),
    }

    c2 = {
        "README.md": ("100644", "# Forge Project\n\nA demonstration repository.\n\nUpdated with new modules.\n"),
        "LICENSE": ("100644", "MIT License\n\nCopyright (c) 2024\n"),
        "src/main.py": ("100755", "#!/usr/bin/env python3\nfrom lib import utils\nprint(utils.helper())\n"),
        "src/lib.py": ("100644", "# Namespace package marker\n"),
        "src/lib/utils.py": ("100644", "def helper():\n    return 42\n"),
        "src/lib/io.py": ("100644", "import sys\n\ndef read_input():\n    return sys.stdin.read()\n"),
        "src/lib0.py": ("100644", "# Additional module\nVERSION = '0.1'\n"),
        "data/config.json": ("100644", '{"version": 2}\n'),
        "data.txt": ("100644", "Flat data file at root level.\n"),
    }

    # ─── Create blobs ────────────────────────────────────────

    blobs = {}
    for path, (mode, content) in c1.items():
        blobs[(path, content)] = create_blob(objects_dir, content)
    for path, (mode, content) in c2.items():
        if (path, content) not in blobs:
            blobs[(path, content)] = create_blob(objects_dir, content)

    def blob(path, files):
        return blobs[(path, files[path][1])]

    # ─── Commit 1 trees (correct sort) ───────────────────────

    c1_lib_tree = create_tree(objects_dir, [
        ("io.py", 0o100644, blob("src/lib/io.py", c1)),
        ("utils.py", 0o100644, blob("src/lib/utils.py", c1)),
    ], use_git_sort=True)

    c1_src_tree = create_tree(objects_dir, [
        ("lib", 0o040000, c1_lib_tree),
        ("main.py", 0o100755, blob("src/main.py", c1)),
    ], use_git_sort=True)

    c1_data_tree = create_tree(objects_dir, [
        ("config.json", 0o100644, blob("data/config.json", c1)),
    ], use_git_sort=True)

    c1_root_tree = create_tree(objects_dir, [
        ("LICENSE", 0o100644, blob("LICENSE", c1)),
        ("README.md", 0o100644, blob("README.md", c1)),
        ("data", 0o040000, c1_data_tree),
        ("src", 0o040000, c1_src_tree),
    ], use_git_sort=True)

    commit1 = create_commit(
        objects_dir, c1_root_tree, [],
        "Ada Lovelace", "ada@example.com", 1700000000, "+0100",
        "Initial project setup\n\nEstablish the basic project structure with\nsource code and configuration files."
    )

    # ─── Commit 2 trees (WRONG sort for root and src/) ───────

    c2_lib_tree = create_tree(objects_dir, [
        ("io.py", 0o100644, blob("src/lib/io.py", c2)),
        ("utils.py", 0o100644, blob("src/lib/utils.py", c2)),
    ], use_git_sort=True)

    # BUG: alphabetical sort instead of dir-suffix
    c2_src_tree = create_tree(objects_dir, [
        ("lib", 0o040000, c2_lib_tree),
        ("lib.py", 0o100644, blob("src/lib.py", c2)),
        ("lib0.py", 0o100644, blob("src/lib0.py", c2)),
        ("main.py", 0o100755, blob("src/main.py", c2)),
    ], use_git_sort=False)

    c2_data_tree = create_tree(objects_dir, [
        ("config.json", 0o100644, blob("data/config.json", c2)),
    ], use_git_sort=True)

    # BUG: alphabetical sort instead of dir-suffix
    c2_root_tree = create_tree(objects_dir, [
        ("LICENSE", 0o100644, blob("LICENSE", c2)),
        ("README.md", 0o100644, blob("README.md", c2)),
        ("data", 0o040000, c2_data_tree),
        ("data.txt", 0o100644, blob("data.txt", c2)),
        ("src", 0o040000, c2_src_tree),
    ], use_git_sort=False)

    commit2 = create_commit(
        objects_dir, c2_root_tree, [commit1],
        "Charles Babbage", "charles@example.com", 1700100000, "+0000",
        "Add sorting edge cases and expand modules"
    )

    # ─── Refs ────────────────────────────────────────────────

    with open(os.path.join(git_dir, "refs", "heads", "main"), "w") as f:
        f.write(commit2 + "\n")

    with open(os.path.join(git_dir, "HEAD"), "w") as f:
        f.write("ref: refs/heads/main\n")

    # ─── Working tree ────────────────────────────────────────

    for path, (mode, content) in c2.items():
        full = os.path.join(repo_dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        if mode == "100755":
            os.chmod(full, 0o755)
        else:
            os.chmod(full, 0o644)

    # ─── Index ───────────────────────────────────────────────
    # Write index BEFORE truncation so stat data (fsize) matches blob sizes.
    # The zeroed checksum is the only index corruption.

    index_entries = {}
    for path, (mode, content) in c2.items():
        index_entries[path] = {"sha": blobs[(path, content)], "mode": int(mode, 8)}

    # CORRUPTION 2: Zero the checksum
    write_index(git_dir, repo_dir, index_entries, zero_checksum=True)

    # CORRUPTION 3: Truncate src/lib0.py (AFTER index so stat data is consistent)
    with open(os.path.join(repo_dir, "src", "lib0.py"), "w") as f:
        f.write("# Additio")

    # CORRUPTION 4: Move data/config.json blob to wrong path
    config_sha = blob("data/config.json", c2)
    obj_dir = os.path.join(objects_dir, config_sha[:2])
    correct_path = os.path.join(obj_dir, config_sha[2:])

    last = config_sha[-1]
    new_last = hex((int(last, 16) + 1) % 16)[2:]
    wrong_tail = config_sha[2:-1] + new_last
    wrong_path = os.path.join(obj_dir, wrong_tail)

    os.rename(correct_path, wrong_path)

    print(f"Created corrupted repo at: {repo_dir}")
    print(f"Commit 1: {commit1}")
    print(f"Commit 2: {commit2}")
    print(f"Corruptions applied:")
    print(f"  1. Tree sort: root={c2_root_tree}, src={c2_src_tree}")
    print(f"  2. Index checksum: zeroed")
    print(f"  3. Working tree: src/lib0.py truncated")
    print(f"  4. Blob path: {config_sha} -> ...{wrong_tail[-8:]}")


if __name__ == "__main__":
    main()
