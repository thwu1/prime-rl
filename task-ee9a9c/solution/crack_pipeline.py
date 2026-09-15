#!/usr/bin/env python3

"""
Credential forensics pipeline: infer password pattern from honeypot data,
crack multi-format hashes across three systems, correlate identities,
follow multi-stage credential chain, produce structured report.
"""

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import crypt
import struct
import subprocess
import json
import os
import re

import bcrypt as bcrypt_lib

ENGAGEMENT_DIR = "/app/engagement"
RESULTS_DIR = "/app/results"

SKIP_SHADOW = {"root", "daemon", "www-data"}
SKIP_NTLM = {"Guest", "krbtgt"}


# ---------------------------------------------------------------------------
# Pure-Python MD4 (for NTLM hash verification without OpenSSL legacy)
# ---------------------------------------------------------------------------

def _md4(message):
    def F(x, y, z):
        return (x & y) | ((~x) & z)
    def G(x, y, z):
        return (x & y) | (x & z) | (y & z)
    def H(x, y, z):
        return x ^ y ^ z
    def LR(n, b):
        return ((n << b) | (n >> (32 - b))) & 0xFFFFFFFF

    msg = bytearray(message)
    orig_bits = len(msg) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += struct.pack('<Q', orig_bits)

    A, B, C, D = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476

    for i in range(0, len(msg), 64):
        M = struct.unpack('<16I', bytes(msg[i:i + 64]))
        a, b, c, d = A, B, C, D

        for j in range(16):
            if j % 4 == 0:
                a = LR((a + F(b, c, d) + M[j]) & 0xFFFFFFFF, 3)
            elif j % 4 == 1:
                d = LR((d + F(a, b, c) + M[j]) & 0xFFFFFFFF, 7)
            elif j % 4 == 2:
                c = LR((c + F(d, a, b) + M[j]) & 0xFFFFFFFF, 11)
            else:
                b = LR((b + F(c, d, a) + M[j]) & 0xFFFFFFFF, 19)

        for j, k in enumerate([0,4,8,12,1,5,9,13,2,6,10,14,3,7,11,15]):
            if j % 4 == 0:
                a = LR((a + G(b, c, d) + M[k] + 0x5A827999) & 0xFFFFFFFF, 3)
            elif j % 4 == 1:
                d = LR((d + G(a, b, c) + M[k] + 0x5A827999) & 0xFFFFFFFF, 5)
            elif j % 4 == 2:
                c = LR((c + G(d, a, b) + M[k] + 0x5A827999) & 0xFFFFFFFF, 9)
            else:
                b = LR((b + G(c, d, a) + M[k] + 0x5A827999) & 0xFFFFFFFF, 13)

        for j, k in enumerate([0,8,4,12,2,10,6,14,1,9,5,13,3,11,7,15]):
            if j % 4 == 0:
                a = LR((a + H(b, c, d) + M[k] + 0x6ED9EBA1) & 0xFFFFFFFF, 3)
            elif j % 4 == 1:
                d = LR((d + H(a, b, c) + M[k] + 0x6ED9EBA1) & 0xFFFFFFFF, 9)
            elif j % 4 == 2:
                c = LR((c + H(d, a, b) + M[k] + 0x6ED9EBA1) & 0xFFFFFFFF, 11)
            else:
                b = LR((b + H(c, d, a) + M[k] + 0x6ED9EBA1) & 0xFFFFFFFF, 15)

        A = (A + a) & 0xFFFFFFFF
        B = (B + b) & 0xFFFFFFFF
        C = (C + c) & 0xFFFFFFFF
        D = (D + d) & 0xFFFFFFFF

    return struct.pack('<4I', A, B, C, D).hex()


def ntlm_hash(password):
    return _md4(password.encode('utf-16-le'))


# ---------------------------------------------------------------------------
# Step 1: Infer password pattern from honeypot captures
# ---------------------------------------------------------------------------

def infer_pattern(honeypot_path):
    years = set()
    symbols = set()
    with open(honeypot_path) as f:
        for line in f:
            m = re.search(r'password=(\S+)', line)
            if m:
                pw = m.group(1)
                # Pattern: CapitalizedWord + 4-digit year + 1 special char
                match = re.match(r'^[A-Z][a-z]+(\d{4})([^a-zA-Z0-9])$', pw)
                if match:
                    years.add(match.group(1))
                    symbols.add(match.group(2))
    return sorted(years), sorted(symbols)


# ---------------------------------------------------------------------------
# Step 2: Generate candidates from wordlist + inferred pattern
# ---------------------------------------------------------------------------

def generate_candidates(wordlist_path, years, symbols):
    candidates = []
    with open(wordlist_path) as f:
        for line in f:
            word = line.strip()
            if word:
                for year in years:
                    for symbol in symbols:
                        candidates.append(word + year + symbol)
    return candidates


# ---------------------------------------------------------------------------
# Step 3: Parse hash files
# ---------------------------------------------------------------------------

def parse_shadow(path):
    entries = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split(":")
            if len(parts) >= 2:
                user, hval = parts[0], parts[1]
                if user not in SKIP_SHADOW and hval.startswith("$6$"):
                    entries[user] = hval
    return entries


def parse_ntlm(path):
    empty_nt = "31d6cfe0d16ae931b73c59d7e0c089c0"
    entries = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split(":")
            if len(parts) >= 4:
                user, nt = parts[0], parts[3]
                if user not in SKIP_NTLM and nt != empty_nt:
                    entries[user] = nt
    return entries


def parse_webapp(path):
    entries = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("--") or line.startswith("id,") or not line:
                continue
            parts = line.split(",")
            if len(parts) >= 4:
                username = parts[1]
                password_hash = parts[3]
                if password_hash.startswith("$2b$") or password_hash.startswith("$2a$"):
                    entries[username] = password_hash
    return entries


# ---------------------------------------------------------------------------
# Step 4: Crack hashes
# ---------------------------------------------------------------------------

def crack_shadow(entries, candidates):
    cracked = {}
    for user, full_hash in entries.items():
        parts = full_hash.split("$")
        setting = "$".join(parts[:3]) + "$"
        for candidate in candidates:
            if crypt.crypt(candidate, setting) == full_hash:
                cracked[user] = candidate
                print(f"[+] SHA-512 cracked  {user}: {candidate}")
                break
    return cracked


def crack_ntlm(entries, candidates):
    hash_to_pw = {}
    for c in candidates:
        hash_to_pw[ntlm_hash(c)] = c

    cracked = {}
    for user, target in entries.items():
        if target in hash_to_pw:
            cracked[user] = hash_to_pw[target]
            print(f"[+] NTLM   cracked  {user}: {hash_to_pw[target]}")
    return cracked


def crack_webapp(entries, candidates):
    cracked = {}
    for user, stored_hash in entries.items():
        stored_bytes = stored_hash.encode('ascii')
        for candidate in candidates:
            if bcrypt_lib.checkpw(candidate.encode(), stored_bytes):
                cracked[user] = candidate
                print(f"[+] bcrypt cracked  {user}: {candidate}")
                break
    return cracked


# ---------------------------------------------------------------------------
# Step 5: Parse personnel identity mapping from engagement notes
# ---------------------------------------------------------------------------

def parse_personnel(notes_path):
    with open(notes_path) as f:
        notes = f.read()

    groups = []
    for line in notes.split("\n"):
        m = re.match(r'^- ([\w ]+?):\s+', line)
        if not m:
            continue
        name = m.group(1).strip()
        # Only process personnel entries (contain account references)
        if '"' not in line:
            continue

        accounts = []
        linux_m = re.search(r'Linux account "(\w[\w.]*)"', line, re.IGNORECASE)
        domain_m = re.search(r'domain account "(\w[\w.]*)"', line, re.IGNORECASE)
        portal_m = re.search(r'portal username "(\w+)"', line, re.IGNORECASE)

        if linux_m:
            accounts.append(f"linux:{linux_m.group(1)}")
        if domain_m:
            accounts.append(f"domain:{domain_m.group(1)}")
        if portal_m:
            accounts.append(f"webapp:{portal_m.group(1)}")

        if accounts:
            groups.append({"person": name, "accounts": sorted(accounts)})

    return groups


# ---------------------------------------------------------------------------
# Step 6: Cross-system password reuse analysis
# ---------------------------------------------------------------------------

def find_reuse(linux_creds, domain_creds, webapp_creds):
    pw_to_accounts = {}
    for user, pw in linux_creds.items():
        pw_to_accounts.setdefault(pw, []).append(f"linux:{user}")
    for user, pw in domain_creds.items():
        pw_to_accounts.setdefault(pw, []).append(f"domain:{user}")
    for user, pw in webapp_creds.items():
        pw_to_accounts.setdefault(pw, []).append(f"webapp:{user}")

    reuse = []
    for pw in sorted(pw_to_accounts):
        accounts = pw_to_accounts[pw]
        systems = {a.split(":")[0] for a in accounts}
        if len(systems) < 2:
            continue

        # Classify service vs personal accounts
        service_prefixes = ("svc_", "admin_", "dev_", "webapp_admin")
        has_service = any(
            any(a.split(":")[1].startswith(p) or a.split(":")[1] == p.rstrip("_")
                for p in service_prefixes)
            for a in accounts
        )
        has_personal = any(
            not any(a.split(":")[1].startswith(p) or a.split(":")[1] == p.rstrip("_")
                    for p in service_prefixes)
            for a in accounts
        )

        if len(systems) >= 3 or (has_service and has_personal):
            risk = "critical"
        else:
            risk = "high"

        reuse.append({
            "password": pw,
            "accounts": sorted(accounts),
            "risk_level": risk,
        })

    return reuse


# ---------------------------------------------------------------------------
# Step 7: Credential chain — vault unlock → GPG decrypt
# ---------------------------------------------------------------------------

def unlock_vault(all_creds):
    extract_dir = "/tmp/vault_extract"
    os.makedirs(extract_dir, exist_ok=True)

    # Unlock ZIP with admin.dc password
    zip_pw = all_creds.get("domain:admin.dc", "")
    r = subprocess.run(
        ["unzip", "-o", "-P", zip_pw,
         os.path.join(ENGAGEMENT_DIR, "locked_archive.zip"),
         "-d", extract_dir],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[-] ZIP unlock failed: {r.stderr}")
        return ""

    print(f"[+] ZIP unlocked with admin.dc credential: {zip_pw}")

    # Read vault manifest
    manifest_path = os.path.join(extract_dir, "vault_manifest.txt")
    with open(manifest_path) as f:
        manifest = f.read()
    print(f"[*] Vault manifest loaded")

    # Decrypt vault_gpg_passphrase.enc with svc_sql credential
    svc_sql_pw = all_creds.get("domain:svc_sql", "")
    if not svc_sql_pw:
        print("[-] svc_sql credential not available")
        return ""

    enc_path = os.path.join(extract_dir, "vault_gpg_passphrase.enc")
    r = subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-d", "-salt", "-pbkdf2",
         "-iter", "10000", "-pass", f"pass:{svc_sql_pw}", "-in", enc_path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[-] Vault decryption failed: {r.stderr}")
        return ""

    gpg_passphrase = r.stdout.strip()
    print(f"[+] GPG passphrase recovered: {gpg_passphrase}")

    # Decrypt classified GPG file
    gpg_home = "/tmp/solve_gpg"
    os.makedirs(gpg_home, exist_ok=True)
    os.chmod(gpg_home, 0o700)
    env = os.environ.copy()
    env["GNUPGHOME"] = gpg_home

    agent_conf = os.path.join(gpg_home, "gpg-agent.conf")
    with open(agent_conf, "w") as f:
        f.write("allow-loopback-pinentry\n")
    subprocess.run(["gpgconf", "--kill", "gpg-agent"],
                   capture_output=True, env=env)

    r = subprocess.run(
        ["gpg", "--batch", "--yes",
         "--passphrase", gpg_passphrase,
         "--pinentry-mode", "loopback",
         "--decrypt", os.path.join(ENGAGEMENT_DIR, "classified_data.gpg")],
        capture_output=True, text=True, env=env,
    )
    if r.returncode == 0:
        flag = r.stdout.strip()
        print(f"[+] Flag recovered: {flag}")
        return flag

    print(f"[-] GPG decryption failed: {r.stderr}")
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # 1. Infer password pattern from honeypot captures
    print("[*] Analyzing honeypot captures to infer password pattern...")
    years, symbols = infer_pattern(
        os.path.join(ENGAGEMENT_DIR, "honeypot_captures.log"))
    print(f"[+] Inferred years: {years}, symbols: {symbols}")

    # 2. Generate candidates
    print("[*] Generating candidates from wordlist + inferred pattern...")
    candidates = generate_candidates(
        os.path.join(ENGAGEMENT_DIR, "engagement_wordlist.txt"), years, symbols)
    print(f"[+] {len(candidates)} candidates generated")

    # 3. Parse hash files
    shadow_entries = parse_shadow(
        os.path.join(ENGAGEMENT_DIR, "server_shadow.txt"))
    ntlm_entries = parse_ntlm(
        os.path.join(ENGAGEMENT_DIR, "domain_hashes.txt"))
    webapp_entries = parse_webapp(
        os.path.join(ENGAGEMENT_DIR, "webapp_db_dump.csv"))
    print(f"[*] Hash files: {len(shadow_entries)} Linux, "
          f"{len(ntlm_entries)} domain, {len(webapp_entries)} webapp")

    # 4. Crack all hash types
    print("\n[*] Cracking SHA-512 crypt hashes (Linux)...")
    linux_creds = crack_shadow(shadow_entries, candidates)
    print(f"[+] {len(linux_creds)}/{len(shadow_entries)} Linux cracked")

    print("\n[*] Cracking NTLM hashes (Domain)...")
    domain_creds = crack_ntlm(ntlm_entries, candidates)
    print(f"[+] {len(domain_creds)}/{len(ntlm_entries)} domain cracked")

    print("\n[*] Cracking bcrypt hashes (Web app)...")
    webapp_creds = crack_webapp(webapp_entries, candidates)
    print(f"[+] {len(webapp_creds)}/{len(webapp_entries)} webapp cracked")

    # 5. Build combined credential map
    all_creds = {}
    for user, pw in linux_creds.items():
        all_creds[f"linux:{user}"] = pw
    for user, pw in domain_creds.items():
        all_creds[f"domain:{user}"] = pw
    for user, pw in webapp_creds.items():
        all_creds[f"webapp:{user}"] = pw

    # 6. Parse personnel identity mapping
    print("\n[*] Mapping personnel identities across systems...")
    identity_groups = parse_personnel(
        os.path.join(ENGAGEMENT_DIR, "notes.txt"))
    print(f"[+] {len(identity_groups)} identity groups identified")

    # 7. Cross-system reuse analysis
    print("\n[*] Analyzing cross-system password reuse...")
    reuse = find_reuse(linux_creds, domain_creds, webapp_creds)
    print(f"[+] {len(reuse)} cross-system reuse instances found")

    # 8. Credential chain: vault → GPG
    print("\n[*] Following credential chain through vault...")
    flag = unlock_vault(all_creds)

    # 9. Build report
    report = {
        "cracked_credentials": all_creds,
        "password_pattern": {
            "years": years,
            "symbols": symbols,
            "description": ("Organizational passwords follow the pattern: "
                            "CapitalizedWord + 4-digit year (2023 or 2024) "
                            "+ trailing special character (!, #, or @)"),
        },
        "identity_groups": identity_groups,
        "cross_system_reuse": reuse,
        "decrypted_flag": flag if flag else "",
    }

    report_path = os.path.join(RESULTS_DIR, "report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[+] Report written to {report_path}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
