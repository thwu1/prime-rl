#!/usr/bin/env python3
"""
Reconstruct a git repository from a JSON-based object archive.

Reads structured JSON representations of git objects from /app/archive/,
re-encodes them into git's native binary format, and writes them as loose
objects into a new repository at /app/repo/.

"""
import hashlib
import json
import os
import subprocess
import zlib

ARCHIVE = "/app/archive"
REPO = "/app/repo"


def read_archive():
    """Read the complete archive: types, objects, refs, metadata."""
    with open(os.path.join(ARCHIVE, "types.json")) as f:
        types = json.load(f)

    objects = {}
    for sha in types:
        with open(os.path.join(ARCHIVE, "objects", f"{sha}.json")) as f:
            objects[sha] = json.load(f)

    with open(os.path.join(ARCHIVE, "refs.json")) as f:
        refs = json.load(f)

    with open(os.path.join(ARCHIVE, "metadata.json")) as f:
        metadata = json.load(f)

    return types, objects, refs, metadata


def write_git_object(sha, raw_data):
    """Write a zlib-compressed git object to the repo's object store."""
    obj_dir = os.path.join(REPO, ".git", "objects", sha[:2])
    os.makedirs(obj_dir, exist_ok=True)
    obj_path = os.path.join(obj_dir, sha[2:])
    with open(obj_path, "wb") as f:
        f.write(zlib.compress(raw_data))


def encode_blob(sha, obj):
    """Encode a blob object: 'blob <size>\0<content>'."""
    content = obj["content"].encode()
    full = b"blob " + str(len(content)).encode() + b"\0" + content
    computed = hashlib.sha1(full).hexdigest()
    if computed != sha:
        raise ValueError(f"Blob SHA1 mismatch: expected {sha}, got {computed}")
    write_git_object(sha, full)


def encode_tree(sha, obj):
    """
    Encode a tree object from JSON entries to git's binary tree format.

    Each entry in binary: '<mode> <name>\0<20-byte-sha1>'
    - Mode is ASCII (e.g., '100644' for files, '40000' for directories)
    - Git stores directory mode as '40000', NOT '040000' (no leading zero)
    - Name is the filename/dirname (no path separator)
    - SHA1 is 20 raw bytes, NOT hex
    - Entries are concatenated with no separator
    """
    binary_entries = b""
    for entry in obj["entries"]:
        mode = entry["mode"]
        # Critical: git's internal binary tree format uses '40000' for
        # directories, but git cat-file -p displays '040000'. Must
        # strip the leading zero for the SHA1 to match.
        if mode == "040000":
            mode = "40000"

        name = entry["name"]
        sha_bytes = bytes.fromhex(entry["sha1"])

        binary_entries += mode.encode() + b" " + name.encode() + b"\0" + sha_bytes

    full = b"tree " + str(len(binary_entries)).encode() + b"\0" + binary_entries
    computed = hashlib.sha1(full).hexdigest()
    if computed != sha:
        raise ValueError(f"Tree SHA1 mismatch: expected {sha}, got {computed}")
    write_git_object(sha, full)


def encode_commit(sha, obj):
    """
    Encode a commit object from structured JSON to git's raw format.

    Format:
      tree <tree_sha>\n
      parent <parent_sha>\n    (repeated for each parent)
      author <name> <<email>> <timestamp> <tz>\n
      committer <name> <<email>> <timestamp> <tz>\n
      \n
      <message>\n
    """
    lines = [f"tree {obj['tree']}"]
    for parent in obj.get("parents", []):
        lines.append(f"parent {parent}")
    lines.append(
        f"author {obj['author_name']} <{obj['author_email']}> "
        f"{obj['author_timestamp']} {obj['author_tz']}"
    )
    lines.append(
        f"committer {obj['committer_name']} <{obj['committer_email']}> "
        f"{obj['committer_timestamp']} {obj['committer_tz']}"
    )
    lines.append("")
    lines.append(obj["message"])

    content = ("\n".join(lines) + "\n").encode()
    full = b"commit " + str(len(content)).encode() + b"\0" + content
    computed = hashlib.sha1(full).hexdigest()
    if computed != sha:
        raise ValueError(f"Commit SHA1 mismatch: expected {sha}, got {computed}")
    write_git_object(sha, full)


def encode_tag(sha, obj):
    """
    Encode a tag object from structured JSON to git's raw format.

    Format:
      object <sha>\n
      type <target_type>\n
      tag <tag_name>\n
      tagger <name> <<email>> <timestamp> <tz>\n
      \n
      <message>\n
    """
    lines = [f"object {obj['object']}"]
    lines.append(f"type {obj['target_type']}")
    lines.append(f"tag {obj['tag_name']}")
    lines.append(
        f"tagger {obj['tagger_name']} <{obj['tagger_email']}> "
        f"{obj['tagger_timestamp']} {obj['tagger_tz']}"
    )
    lines.append("")
    lines.append(obj["message"])

    content = ("\n".join(lines) + "\n").encode()
    full = b"tag " + str(len(content)).encode() + b"\0" + content
    computed = hashlib.sha1(full).hexdigest()
    if computed != sha:
        raise ValueError(f"Tag SHA1 mismatch: expected {sha}, got {computed}")
    write_git_object(sha, full)


def find_feature_branch_tip(types, objects, main_sha):
    """
    Determine the tip commit of the feature/streaming branch by
    analyzing the commit graph.

    Strategy:
    1. BFS from main HEAD to find all commits reachable from main
    2. Identify commits NOT reachable from main (the feature branch)
    3. The tip is the commit among those that is not a parent of any
       other non-main commit
    """
    commits = {
        sha: objects[sha]
        for sha, obj_type in types.items()
        if obj_type == "commit"
    }

    # Find all commits reachable from main
    main_reachable = set()
    stack = [main_sha]
    while stack:
        current = stack.pop()
        if current in main_reachable:
            continue
        main_reachable.add(current)
        for parent in commits[current].get("parents", []):
            stack.append(parent)

    # Commits not reachable from main = feature branch commits
    feature_commits = {sha for sha in commits if sha not in main_reachable}

    # Find tips: commits that are not parents of any other feature commit
    parent_set = set()
    for sha in feature_commits:
        for parent in commits[sha].get("parents", []):
            if parent in feature_commits:
                parent_set.add(parent)

    tips = feature_commits - parent_set

    if len(tips) == 1:
        return tips.pop()

    # Disambiguate using metadata if multiple tips exist
    return None


def write_ref(ref_path, sha):
    """Write a git ref file."""
    full_path = os.path.join(REPO, ".git", ref_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(sha + "\n")


def main():
    types, objects, refs, metadata = read_archive()

    # Initialize a bare git repo structure
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=REPO, check=True, capture_output=True, text=True,
    )

    # Encode and write all objects
    for sha, obj_type in types.items():
        obj = objects[sha]
        if obj_type == "blob":
            encode_blob(sha, obj)
        elif obj_type == "tree":
            encode_tree(sha, obj)
        elif obj_type == "commit":
            encode_commit(sha, obj)
        elif obj_type == "tag":
            encode_tag(sha, obj)

    # Set up refs from archive
    main_sha = refs["branches"]["main"]
    write_ref("refs/heads/main", main_sha)

    # HEAD is already correct from git init -b main
    # But ensure it matches the archive
    with open(os.path.join(REPO, ".git", "HEAD"), "w") as f:
        f.write("ref: refs/heads/main\n")

    # Reconstruct the missing feature/streaming branch ref
    feature_sha = find_feature_branch_tip(types, objects, main_sha)
    if feature_sha:
        write_ref("refs/heads/feature/streaming", feature_sha)
        print(f"Reconstructed feature/streaming -> {feature_sha}")
    else:
        print("ERROR: Could not determine feature/streaming branch tip")

    # Set up tags
    for tag_name, tag_sha in refs.get("tags", {}).items():
        write_ref(f"refs/tags/{tag_name}", tag_sha)

    # Checkout main to populate the working tree and index
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=REPO, check=True, capture_output=True, text=True,
    )

    # Verify integrity
    result = subprocess.run(
        ["git", "fsck", "--strict", "--no-dangling"],
        cwd=REPO, capture_output=True, text=True,
    )
    print("fsck stdout:", result.stdout)
    if result.stderr:
        print("fsck stderr:", result.stderr)
    print("fsck exit code:", result.returncode)

    result = subprocess.run(
        ["git", "log", "--all", "--oneline"],
        cwd=REPO, capture_output=True, text=True,
    )
    print("Commit log:")
    print(result.stdout)


if __name__ == "__main__":
    main()
