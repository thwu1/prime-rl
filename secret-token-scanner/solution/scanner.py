#!/usr/bin/env python3

"""
Comprehensive git repository secret audit scanner.

Searches ALL git objects — reachable (branches, tags, notes, stash) and
unreachable (orphaned by amend/rebase/force-push) — for API tokens matching
the spec at /app/token_spec.yaml, validates integrity checksums, classifies
each token's location in the git object model, and determines reachability
from named refs.
"""

import json
import os
import re
import subprocess
import zlib

REPO = "/app/repo"
BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# ── Token patterns ──────────────────────────────────────────────────────────

PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9_])apx_[A-Za-z0-9]{30}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9_-])nxs-[0-9a-f]{40}-[0-9a-f]{8}(?![0-9a-f])"),
    re.compile(r"(?<![A-Za-z0-9_])vlt_(?:live|test)_[A-Za-z0-9]{28}(?![A-Za-z0-9])"),
]

# ── Checksum helpers ────────────────────────────────────────────────────────


def base62_encode(num, length=6):
    if num == 0:
        return BASE62[0] * length
    chars = []
    while num > 0:
        chars.append(BASE62[num % 62])
        num //= 62
    chars.reverse()
    return "".join(chars).rjust(length, "0")


def fnv1a_32(data):
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


# ── Token validators ───────────────────────────────────────────────────────


def verify_apx(token):
    if not re.fullmatch(r"apx_[A-Za-z0-9]{30}", token):
        return False
    payload, checksum = token[4:28], token[28:]
    crc = zlib.crc32(("apx_" + payload).encode()) & 0xFFFFFFFF
    return checksum == base62_encode(crc, 6)


def verify_nxs(token):
    m = re.fullmatch(r"nxs-([0-9a-f]{40})-([0-9a-f]{8})", token)
    if not m:
        return False
    raw = bytes.fromhex(m.group(1))
    adler = zlib.adler32(raw) & 0xFFFFFFFF
    return m.group(2) == format(adler, "08x")


def verify_vlt(token):
    for prefix in ("vlt_live_", "vlt_test_"):
        if token.startswith(prefix):
            body = token[len(prefix):]
            if not re.fullmatch(r"[A-Za-z0-9]{28}", body):
                return False
            payload, checksum = body[:22], body[22:]
            h = fnv1a_32((prefix + payload).encode())
            return checksum == base62_encode(h, 6)
    return False


def classify_token(token):
    if verify_apx(token):
        return "apx"
    if verify_nxs(token):
        return "nxs"
    if verify_vlt(token):
        return "vlt"
    return None


def find_candidates(text):
    found = set()
    for pat in PATTERNS:
        for m in pat.finditer(text):
            found.add(m.group())
    return found


# ── Git helpers ─────────────────────────────────────────────────────────────


def git_run(*args):
    r = subprocess.run(
        ["git"] + list(args), cwd=REPO,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return r.stdout.decode("utf-8", errors="replace")


def git_merged(*args):
    """Run git command, merging stderr into stdout."""
    r = subprocess.run(
        ["git"] + list(args), cwd=REPO,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return r.stdout.decode("utf-8", errors="replace")


def obj_type(h):
    return git_run("cat-file", "-t", h).strip()


def obj_content(h):
    return git_run("cat-file", "-p", h)


def parse_hashes(output):
    hashes = set()
    for line in output.splitlines():
        parts = line.split()
        if parts:
            hashes.add(parts[0])
    return hashes


# ── Main audit logic ───────────────────────────────────────────────────────


def main():
    findings = {}

    # 1) All objects reachable from named refs (branches, tags, notes, stash)
    reachable = parse_hashes(git_run("rev-list", "--all", "--objects"))

    # Explicitly include stash in case --all doesn't cover refs/stash
    stash_ref = git_run("rev-parse", "refs/stash").strip()
    if stash_ref and len(stash_ref) == 40:
        reachable |= parse_hashes(git_run("rev-list", stash_ref, "--objects"))

    # 2) Tag objects (git rev-list peels tags, so tag objects aren't in the set)
    tag_obj_hashes = set()
    for line in git_run("for-each-ref", "--format=%(objectname) %(objecttype)",
                        "refs/tags/").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "tag":
            tag_obj_hashes.add(parts[0])
            reachable.add(parts[0])

    # 3) Note blob hashes
    note_blob_hashes = set()
    for line in git_run("notes", "list").splitlines():
        parts = line.strip().split()
        if parts:
            note_blob_hashes.add(parts[0])

    # 4) Stash-only objects (for distinguishing stash blobs from branch blobs)
    stash_obj_hashes = set()
    if stash_ref and len(stash_ref) == 40:
        stash_obj_hashes = parse_hashes(
            git_run("rev-list", stash_ref, "--objects")
        )

    branch_obj_hashes = parse_hashes(
        git_run("rev-list", "--branches", "--objects")
    )

    # 5) Unreachable objects (orphaned by amend, rebase, filter-branch, etc.)
    unreachable = set()
    fsck_output = git_merged("fsck", "--unreachable", "--no-reflogs")
    for line in fsck_output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in ("unreachable", "dangling"):
            unreachable.add(parts[2])

    # For unreachable commits, also enumerate their tree blobs
    for h in list(unreachable):
        if obj_type(h) == "commit":
            content = obj_content(h)
            for cline in content.splitlines():
                if cline.startswith("tree "):
                    tree_hash = cline.split()[1]
                    for tline in git_run("ls-tree", "-r", tree_hash).splitlines():
                        tparts = tline.split(None, 3)
                        if len(tparts) >= 3:
                            unreachable.add(tparts[2])
                    break

    all_objects = reachable | unreachable | tag_obj_hashes

    # 6) Scan every blob and tag object for token patterns
    for h in all_objects:
        otype = obj_type(h)
        if otype not in ("blob", "tag"):
            continue

        content = obj_content(h)
        candidates = find_candidates(content)

        for token in candidates:
            if token in findings:
                continue
            provider = classify_token(token)
            if not provider:
                continue

            # Determine location_type
            if otype == "tag":
                loc = "tag_annotation"
            elif h in note_blob_hashes:
                loc = "note"
            elif h in stash_obj_hashes and h not in branch_obj_hashes:
                loc = "stash"
            else:
                loc = "blob"

            findings[token] = {
                "token": token,
                "provider": provider,
                "location_type": loc,
                "reachable": h in reachable,
            }

    # Write output
    result = {"findings": list(findings.values())}
    with open("/app/audit.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Audit complete: {len(findings)} valid token(s) found")
    for f in result["findings"]:
        print(f"  [{f['provider']}] {f['location_type']:16s} "
              f"reachable={str(f['reachable']):5s}  {f['token'][:40]}...")


if __name__ == "__main__":
    main()
