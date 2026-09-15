#!/usr/bin/env python3
"""Git repository secret forensics audit solver."""

import binascii
import csv
import hashlib
import hmac
import json
import re
import struct
import subprocess

import yaml

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
REPO = "/app/repo"


def base62_encode(num, length=6):
    if num == 0:
        return BASE62[0] * length
    result = []
    while num > 0:
        result.append(BASE62[num % 62])
        num //= 62
    result.reverse()
    return "".join(result).rjust(length, BASE62[0])


def hkdf_sha256(ikm, salt, info, length):
    """HKDF extract-and-expand with SHA-256."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    t = b""
    okm = b""
    for i in range(1, (length + 31) // 32 + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=REPO,
                       capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


def compute_expected_checksum(algo, cs_config, prefix, body):
    """Compute the expected checksum for a token."""
    data = prefix + body
    if algo == "crc32_base62":
        crc = binascii.crc32(data.encode()) & 0xFFFFFFFF
        return base62_encode(crc, cs_config["length"])
    elif algo == "hmac_sha256_hkdf_trunc":
        mk_hex = open(cs_config["hkdf_master_key_file"]).read().strip()
        mk = bytes.fromhex(mk_hex)
        dk = hkdf_sha256(mk, cs_config["hkdf_salt"].encode(),
                         cs_config["hkdf_info"].encode(),
                         cs_config["hkdf_key_length"])
        h = hmac.new(dk, data.encode(), hashlib.sha256).hexdigest()
        return h[:cs_config["length"]]
    elif algo == "sha256_base62":
        d = hashlib.sha256(data.encode()).digest()
        num = struct.unpack(">I", d[:4])[0]
        return base62_encode(num, cs_config["length"])
    return None


def build_pattern(provider):
    """Build regex for a provider's token format."""
    prefixes = provider["prefixes"]
    chars = provider["body_charset"]
    blen = provider["body_length"]
    algo = provider["checksum"]["algorithm"]
    cslen = provider["checksum"]["length"]

    if algo in ("crc32_base62", "sha256_base62"):
        cs_chars = provider["checksum"].get("base62_charset", BASE62)
    elif algo == "hmac_sha256_hkdf_trunc":
        cs_chars = "0123456789abcdef"
    else:
        cs_chars = chars

    def esc(s):
        return re.sub(r"([\]\-\^\\])", r"\\\1", s)

    pfx = "|".join(re.escape(p) for p in prefixes)
    return re.compile(f"({pfx})([{esc(chars)}]{{{blen}}})([{esc(cs_chars)}]{{{cslen}}})")


def scan_text(text, prov_pats):
    """Find all tokens in text. Returns [(provider, full_token, prefix, body, cs)]."""
    results = []
    for prov, pat in prov_pats:
        for m in pat.finditer(text):
            pfx, body, cs = m.group(1), m.group(2), m.group(3)
            results.append((prov, pfx + body + cs, pfx, body, cs))
    return results


def main():
    # Load providers
    with open("/app/providers.yaml") as f:
        config = yaml.safe_load(f)
    prov_pats = [(p, build_pattern(p)) for p in config["providers"]]

    # Load rotation log
    rotated_set = set()
    with open("/app/rotation_log.csv") as f:
        for row in csv.DictReader(f):
            rotated_set.add(row["token_sha256"])

    # Collect reachable commits
    out, _, _ = git("rev-list", "--all")
    reachable = set(out.strip().split("\n")) if out.strip() else set()

    # Explicitly include stash if present
    sout, _, rc = git("rev-parse", "--verify", "--quiet", "refs/stash")
    if rc == 0 and sout.strip():
        extra, _, _ = git("rev-list", sout.strip())
        if extra.strip():
            reachable.update(extra.strip().split("\n"))

    # Collect dangling commits
    dout, derr, _ = git("fsck", "--dangling", "--no-reflogs", "--no-progress")
    dangling = set()
    for line in (dout + "\n" + derr).split("\n"):
        if "dangling commit" in line:
            dangling.add(line.split()[-1])

    all_commits = reachable | dangling

    # Scan HEAD tree to determine present_at_head tokens
    head_tree_out, _, _ = git("ls-tree", "-r", "HEAD")
    blob_cache = {}
    head_token_ids = set()

    for line in head_tree_out.strip().split("\n"):
        if not line:
            continue
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        blob_hash = parts[2]
        if blob_hash not in blob_cache:
            content, _, _ = git("cat-file", "-p", blob_hash)
            blob_cache[blob_hash] = content
        for _, full_tok, _, _, _ in scan_text(blob_cache[blob_hash], prov_pats):
            head_token_ids.add(hashlib.sha256(full_tok.encode()).hexdigest())

    # Scan all commits
    findings = {}  # token_id -> info dict

    for commit in all_commits:
        date_out, _, _ = git("log", "-1", "--format=%aI", commit)
        commit_date = date_out.strip()
        is_reachable = commit in reachable

        tree_out, _, _ = git("ls-tree", "-r", commit)
        for line in tree_out.strip().split("\n"):
            if not line:
                continue
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            blob_hash = parts[2]

            if blob_hash not in blob_cache:
                content, _, _ = git("cat-file", "-p", blob_hash)
                blob_cache[blob_hash] = content

            for prov, full_tok, pfx, body, cs in scan_text(blob_cache[blob_hash], prov_pats):
                tid = hashlib.sha256(full_tok.encode()).hexdigest()

                if tid not in findings:
                    algo = prov["checksum"]["algorithm"]
                    expected = compute_expected_checksum(algo, prov["checksum"], pfx, body)
                    valid = (expected == cs) if expected else False
                    redacted = pfx + "*" * len(body) + cs

                    findings[tid] = {
                        "token_id": tid,
                        "provider": prov["name"],
                        "token_redacted": redacted,
                        "checksum_valid": valid,
                        "first_seen_commit": commit,
                        "first_seen_date": commit_date,
                        "present_at_head": tid in head_token_ids,
                        "any_reachable": is_reachable,
                        "rotated": tid in rotated_set,
                    }
                else:
                    existing = findings[tid]
                    if commit_date and existing["first_seen_date"]:
                        if commit_date < existing["first_seen_date"]:
                            existing["first_seen_commit"] = commit
                            existing["first_seen_date"] = commit_date
                    if is_reachable:
                        existing["any_reachable"] = True

    # Classify risk and build output
    risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    results = []

    for tid, info in findings.items():
        if not info["checksum_valid"]:
            risk = "low"
        elif info["rotated"]:
            risk = "medium"
        elif info["present_at_head"]:
            risk = "critical"
        elif info["any_reachable"]:
            risk = "high"
        else:
            risk = "medium"

        results.append({
            "token_id": info["token_id"],
            "provider": info["provider"],
            "token_redacted": info["token_redacted"],
            "checksum_valid": info["checksum_valid"],
            "first_seen_commit": info["first_seen_commit"],
            "first_seen_date": info["first_seen_date"],
            "present_at_head": info["present_at_head"],
            "rotated": info["rotated"],
            "risk_level": risk,
        })

    results.sort(key=lambda x: (risk_order[x["risk_level"]], x["first_seen_date"]))

    with open("/app/audit_report.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Audit complete: {len(results)} tokens found")
    for r in results:
        print(f"  [{r['risk_level']}] {r['provider']}: {r['token_redacted'][:30]}...")


if __name__ == "__main__":
    main()
