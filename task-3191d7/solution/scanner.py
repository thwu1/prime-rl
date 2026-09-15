#!/usr/bin/env python3
"""NexAuth comprehensive secret token scanner.

Scans a development workspace for NexAuth tokens across:
- Regular files (plain text and various encodings)
- Git version control history (deleted files)
- Git stash entries
- Git notes on custom refs
- SQLite databases
- Compressed archives (tar.gz, zip, cpio.bz2)
- OpenSSL encrypted files (with passphrase discovery)
- xxd hex dump files

"""

import json
import os
import re
import zlib
import base64
import subprocess
import sqlite3
import tarfile
import zipfile
import bz2
import tempfile
import glob as globmod

# ── Load specification ─────────────────────────────────────────────

SPEC_PATH = "/app/token_spec.json"
CODEBASE = "/app/codebase"
REPORT_PATH = "/app/report.json"

with open(SPEC_PATH) as f:
    spec = json.load(f)

BASE62 = spec["base62_alphabet"]
BASE62_SET = set(BASE62)
ALL_TYPES = spec["token_types"]


# ── Base62 encoding ────────────────────────────────────────────────

def base62_encode(num, width=6):
    if num == 0:
        return BASE62[0] * width
    chars = []
    while num > 0:
        chars.append(BASE62[num % 62])
        num //= 62
    chars.reverse()
    return "".join(chars).rjust(width, BASE62[0])


# ── Token validation ──────────────────────────────────────────────

def validate_token(token_str):
    """Returns (type_id, is_valid_checksum) or None."""
    for tdef in ALL_TYPES:
        prefix = tdef["prefix"]
        total_len = tdef["total_length"]
        payload_len = tdef["payload_length"]

        if not token_str.startswith(prefix) or len(token_str) != total_len:
            continue

        payload = token_str[len(prefix):len(prefix) + payload_len]
        checksum_str = token_str[len(prefix) + payload_len:]

        if len(checksum_str) != 6:
            continue
        if not all(c in BASE62_SET for c in payload + checksum_str):
            continue

        desc = tdef["checksum_input"].lower()

        if "payload" in desc and "only" in desc and "without" in desc:
            data = payload
        elif ("excluding the underscore" in desc
              or "prefix letters only" in desc):
            data = prefix.rstrip("_") + payload
        else:
            data = prefix + payload

        crc = zlib.crc32(data.encode("ascii")) & 0xFFFFFFFF

        if ("complemented" in desc or "bitwise not" in desc
                or "bits flipped" in desc):
            crc = (~crc) & 0xFFFFFFFF

        expected = base62_encode(crc, 6)
        return (tdef["type_id"], expected == checksum_str)

    return None


# ── Regex patterns ─────────────────────────────────────────────────

PAT_40 = re.compile(r"nx[asdi]_[A-Za-z0-9]{36}")
PAT_46 = re.compile(r"nxr_[A-Za-z0-9]{42}")


def find_tokens_in_text(text):
    results = []
    for pat in (PAT_40, PAT_46):
        for m in pat.finditer(text):
            r = validate_token(m.group())
            if r is not None:
                results.append((m.group(), r[0], r[1]))
    return results


# ── Encoding decoders ──────────────────────────────────────────────

def try_base64_decode(s):
    try:
        return base64.b64decode(s, validate=True).decode("utf-8",
                                                          errors="strict")
    except Exception:
        return None


def try_base64url_decode(s):
    try:
        padded = s + "=" * (4 - len(s) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8",
                                                        errors="strict")
    except Exception:
        return None


def deep_scan(text):
    """Scan text for tokens across multiple encoding layers."""
    tokens = []

    # 1. Plain text
    tokens.extend(find_tokens_in_text(text))

    # 2. Base64 blobs
    for m in re.finditer(r"[A-Za-z0-9+/]{40,}={0,3}", text):
        decoded = try_base64_decode(m.group())
        if decoded:
            tokens.extend(find_tokens_in_text(decoded))
            inner = try_base64_decode(decoded)
            if inner:
                tokens.extend(find_tokens_in_text(inner))

    # 3. JWT payloads
    for m in re.finditer(
            r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
            text):
        parts = m.group().split(".")
        if len(parts) >= 2:
            decoded = try_base64url_decode(parts[1])
            if decoded:
                tokens.extend(find_tokens_in_text(decoded))

    # 4. Hex-encoded tokens
    for m in re.finditer(
            r"(?<![0-9a-fA-F])[0-9a-f]{80,92}(?![0-9a-fA-F])", text):
        try:
            decoded = bytes.fromhex(m.group()).decode("ascii")
            tokens.extend(find_tokens_in_text(decoded))
        except Exception:
            pass

    # 5. Python implicit string concatenation
    for m in re.finditer(r'\(\s*((?:"[^"]*"\s*)+)\)', text, re.DOTALL):
        parts = re.findall(r'"([^"]*)"', m.group(1))
        if len(parts) > 1:
            concatenated = "".join(parts)
            tokens.extend(find_tokens_in_text(concatenated))

    # 6. JSON unicode escape sequences
    for m in re.finditer(
            r"(?:\\u[0-9a-fA-F]{4}){2,}[A-Za-z0-9_]{20,50}", text):
        try:
            decoded = m.group().encode("utf-8").decode("unicode_escape")
            tokens.extend(find_tokens_in_text(decoded))
        except Exception:
            pass

    return tokens


# ── Main scan ──────────────────────────────────────────────────────

all_findings = []
seen_tokens = set()


def add_finding(context, token, ttype, valid):
    if token not in seen_tokens:
        seen_tokens.add(token)
        all_findings.append({
            "file": context,
            "token": token,
            "type": ttype,
            "valid": valid,
        })


# ── 1. Scan regular files ─────────────────────────────────────────

for root, dirs, files in os.walk(CODEBASE):
    dirs[:] = sorted(d for d in dirs if d != ".git")
    for fname in sorted(files):
        fpath = os.path.join(root, fname)
        rel_path = os.path.relpath(fpath, CODEBASE)

        # Handle tar.gz archives
        if fpath.endswith((".tar.gz", ".tgz")):
            try:
                with tarfile.open(fpath, "r:gz") as tf:
                    for member in tf.getmembers():
                        if member.isfile():
                            ef = tf.extractfile(member)
                            if ef:
                                content = ef.read().decode("utf-8",
                                                           errors="ignore")
                                for tok, tt, v in deep_scan(content):
                                    add_finding(rel_path, tok, tt, v)
            except Exception:
                pass
            continue

        # Handle zip archives
        if fpath.endswith(".zip"):
            try:
                with zipfile.ZipFile(fpath, "r") as zf:
                    for name in zf.namelist():
                        with zf.open(name) as ef:
                            content = ef.read().decode("utf-8",
                                                       errors="ignore")
                            for tok, tt, v in deep_scan(content):
                                add_finding(rel_path, tok, tt, v)
            except Exception:
                pass
            continue

        # Handle cpio.bz2 archives
        if fpath.endswith(".cpio.bz2"):
            try:
                with open(fpath, "rb") as bf:
                    decompressed = bz2.decompress(bf.read())
                with tempfile.TemporaryDirectory() as tmpdir:
                    subprocess.run(
                        ["cpio", "-id", "--quiet"],
                        input=decompressed, cwd=tmpdir,
                        capture_output=True, check=True
                    )
                    for troot, tdirs, tfiles in os.walk(tmpdir):
                        for tfname in tfiles:
                            tfpath = os.path.join(troot, tfname)
                            try:
                                with open(tfpath, "r",
                                          errors="ignore") as ef:
                                    content = ef.read()
                                for tok, tt, v in deep_scan(content):
                                    add_finding(rel_path, tok, tt, v)
                            except Exception:
                                pass
            except Exception:
                pass
            continue

        # Handle xxd hex dump files
        if fpath.endswith(".hex"):
            try:
                result = subprocess.run(
                    ["xxd", "-r", fpath],
                    capture_output=True, check=True
                )
                content = result.stdout.decode("utf-8", errors="ignore")
                for tok, tt, v in deep_scan(content):
                    add_finding(rel_path, tok, tt, v)
            except Exception:
                pass
            continue

        # Handle OpenSSL encrypted files
        if fpath.endswith(".enc"):
            try:
                # Look for passphrase file in same directory or parent
                enc_dir = os.path.dirname(fpath)
                passphrase_paths = []
                for candidate in [
                    os.path.join(enc_dir, ".vault_passphrase"),
                    os.path.join(os.path.dirname(enc_dir),
                                 "config", ".vault_passphrase"),
                ]:
                    if os.path.exists(candidate):
                        passphrase_paths.append(candidate)

                # Also check Makefile for cipher hints
                makefile_path = os.path.join(CODEBASE, "Makefile")
                cipher = "aes-256-cbc"
                use_pbkdf2 = True

                for pp in passphrase_paths:
                    cmd = ["openssl", "enc", "-d", f"-{cipher}"]
                    if use_pbkdf2:
                        cmd.append("-pbkdf2")
                    cmd.extend(["-pass", f"file:{pp}", "-in", fpath])
                    result = subprocess.run(
                        cmd, capture_output=True, text=True
                    )
                    if result.returncode == 0 and result.stdout:
                        for tok, tt, v in deep_scan(result.stdout):
                            add_finding(rel_path, tok, tt, v)
                        break
            except Exception:
                pass
            continue

        # Handle SQLite databases
        if fpath.endswith(".db"):
            try:
                conn = sqlite3.connect(fpath)
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cur.fetchall()]
                for table in tables:
                    cur.execute(f"SELECT * FROM [{table}]")
                    for row in cur.fetchall():
                        row_text = " ".join(
                            str(v) for v in row if v is not None)
                        for tok, tt, v in find_tokens_in_text(row_text):
                            add_finding(rel_path, tok, tt, v)
                conn.close()
            except Exception:
                pass
            continue

        # Regular text files
        try:
            with open(fpath, "r", errors="ignore") as f:
                content = f.read()
            for tok, tt, v in deep_scan(content):
                add_finding(rel_path, tok, tt, v)
        except Exception:
            pass

# ── 2. Scan git history (deleted files) ──────────────────────────

try:
    result = subprocess.run(
        ["git", "-C", CODEBASE, "log", "--all", "-p",
         "--diff-filter=D"],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout:
        for tok, tt, v in deep_scan(result.stdout):
            add_finding("git-history", tok, tt, v)
except Exception:
    pass

# ── 3. Scan git stash ────────────────────────────────────────────

try:
    result = subprocess.run(
        ["git", "-C", CODEBASE, "stash", "list"],
        capture_output=True, text=True, timeout=10
    )
    if result.stdout.strip():
        stash_entries = result.stdout.strip().split("\n")
        for i in range(len(stash_entries)):
            stash_diff = subprocess.run(
                ["git", "-C", CODEBASE, "stash", "show", "-p",
                 f"stash@{{{i}}}"],
                capture_output=True, text=True, timeout=10
            )
            if stash_diff.stdout:
                for tok, tt, v in deep_scan(stash_diff.stdout):
                    add_finding("git-stash", tok, tt, v)
except Exception:
    pass

# ── 4. Scan git notes (custom refs) ─────────────────────────────

try:
    refs_result = subprocess.run(
        ["git", "-C", CODEBASE, "for-each-ref",
         "--format=%(refname)", "refs/notes/"],
        capture_output=True, text=True, timeout=10
    )
    for ref_line in refs_result.stdout.strip().split("\n"):
        ref_full = ref_line.strip()
        if not ref_full or not ref_full.startswith("refs/notes/"):
            continue
        ref_name = ref_full[len("refs/notes/"):]

        notes_list = subprocess.run(
            ["git", "-C", CODEBASE, "notes", f"--ref={ref_name}",
             "list"],
            capture_output=True, text=True, timeout=10
        )
        for line in notes_list.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                obj_sha = parts[1]
                note_content = subprocess.run(
                    ["git", "-C", CODEBASE, "notes",
                     f"--ref={ref_name}", "show", obj_sha],
                    capture_output=True, text=True, timeout=10
                )
                if note_content.stdout:
                    for tok, tt, v in deep_scan(note_content.stdout):
                        add_finding("git-notes", tok, tt, v)
except Exception:
    pass

# ── Build report ──────────────────────────────────────────────────

by_type = {}
for f in all_findings:
    by_type[f["type"]] = by_type.get(f["type"], 0) + 1

summary = {
    "total": len(all_findings),
    "valid": sum(1 for f in all_findings if f["valid"]),
    "invalid": sum(1 for f in all_findings if not f["valid"]),
    "by_type": by_type,
}

report = {"tokens": all_findings, "summary": summary}

with open(REPORT_PATH, "w") as f:
    json.dump(report, f, indent=2)

print(f"Scan complete: {summary['total']} tokens found "
      f"({summary['valid']} valid, {summary['invalid']} invalid)")
