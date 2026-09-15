#!/usr/bin/env python3

"""
Solve the AD breach response task.
Produces two deliverables:
  1. /app/answers/attack_analysis.json   — Attack chain reconstruction
  2. /app/answers/security_assessment.json — Posture assessment + hardening
"""

import json
import os
import hmac
import hashlib
import struct


# ================================================================
# Crypto helpers for krb5tgs hash cracking
# ================================================================
def ntlm(pw):
    try:
        from Crypto.Hash import MD4
        h = MD4.new()
        h.update(pw.encode('utf-16le'))
        return h.digest()
    except ImportError:
        return hashlib.new('md4', pw.encode('utf-16le'), usedforsecurity=False).digest()


def rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) % 256])
    return bytes(out)


def parse_krb5tgs_header(hash_line):
    star1 = hash_line.index("*")
    star2 = hash_line.index("*", star1 + 1)
    inner = hash_line[star1 + 1:star2]
    parts = inner.split("$")
    return parts[0], parts[1], parts[2]


def verify_krb5tgs(hash_line, password):
    idx_check = hash_line.rindex("*$") + 2
    rest = hash_line[idx_check:]
    check_hex, edata_hex = rest.split("$", 1)
    checksum = bytes.fromhex(check_hex)
    edata = bytes.fromhex(edata_hex)
    nt = ntlm(password)
    k1 = hmac.new(nt, struct.pack('<I', 2), hashlib.md5).digest()
    k3 = hmac.new(k1, checksum, hashlib.md5).digest()
    decrypted = rc4(k3, edata)
    expected = hmac.new(k1, decrypted, hashlib.md5).digest()
    return expected == checksum


# ================================================================
# Part 1: Attack Reconstruction
# ================================================================
def reconstruct_attack(ad, events, wordlist, hash_lines):
    # Find Kerberoasting: TGS (4769) with RC4 (0x17)
    rc4_tgs = [
        e for e in events
        if e.get("EventID") == 4769 and e.get("TicketEncryptionType") == "0x17"
    ]
    rc4_tgs.sort(key=lambda e: e["TimeCreated"])
    attacker_ip = rc4_tgs[0]["IpAddress"]

    # Initial compromise: first TGT from attacker IP
    tgts = sorted(
        [e for e in events if e.get("EventID") == 4768 and e.get("IpAddress") == attacker_ip],
        key=lambda e: e["TimeCreated"]
    )
    initial_user = tgts[0]["TargetUserName"]

    # Crack hashes
    cracked_info = None
    for h in hash_lines:
        user, realm, spn = parse_krb5tgs_header(h)
        for pw in wordlist:
            if verify_krb5tgs(h, pw):
                cracked_info = (user, realm, spn, pw)
                break
        if cracked_info:
            break

    compromised_service_account = cracked_info[0]
    compromised_spn = cracked_info[2]
    recovered_password = cracked_info[3]

    # Find ESC1 template
    exploited_template = None
    for t in ad.get("certificate_templates", []):
        flags = t.get("flags", {})
        ekus = t.get("pKIExtendedKeyUsage_names", [])
        if (flags.get("ENROLLEE_SUPPLIES_SUBJECT", False)
                and "Client Authentication" in ekus
                and t.get("msPKI-RA-Signature", 1) == 0):
            exploited_template = t["name"]
            break

    # Extract target user from recovered certificate
    from cryptography import x509 as cx509
    with open("/app/evidence/certificates/recovered_cert.pem", "rb") as f:
        cert = cx509.load_pem_x509_certificate(f.read())

    impersonated_user = None
    try:
        san_ext = cert.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for name in san_ext.value:
            if isinstance(name, cx509.OtherName):
                if name.type_id.dotted_string == "1.3.6.1.4.1.311.20.2.3":
                    raw = name.value
                    if raw[0] == 0x0C:
                        upn = raw[2:2 + raw[1]].decode('utf-8')
                        impersonated_user = upn.split("@")[0]
    except Exception:
        pass

    if not impersonated_user:
        pkinit = [
            e for e in events
            if e.get("EventID") == 4768 and e.get("PreAuthType") == "16"
            and e.get("IpAddress") == attacker_ip
        ]
        if pkinit:
            impersonated_user = pkinit[0]["TargetUserName"]

    summary = (
        f"The attacker initially compromised '{initial_user}' on workstation WS-MKTG04 "
        f"({attacker_ip}). From this foothold, they performed Kerberoasting by requesting "
        f"TGS tickets with RC4 encryption (etype 0x17) for multiple service SPNs. They "
        f"cracked the password for service account '{compromised_service_account}' "
        f"(SPN: {compromised_spn}). This account is a member of 'VPN Users', which has "
        f"enrollment rights on the '{exploited_template}' certificate template. The template is "
        f"vulnerable to ESC1 (AD CS misconfiguration): ENROLLEE_SUPPLIES_SUBJECT flag set, "
        f"Client Authentication EKU, and zero authorized signatures required. The attacker "
        f"exploited ESC1 by requesting a certificate with a Subject Alternative Name (UPN) "
        f"of '{impersonated_user}@meridian.local', a Domain Admin. Using this certificate, they "
        f"performed PKINIT authentication (PreAuthType 16) to obtain a TGT as "
        f"'{impersonated_user}', achieving Domain Admin and Enterprise Admin access."
    )

    return {
        "initial_compromise": initial_user,
        "compromised_service_account": compromised_service_account,
        "compromised_spn": compromised_spn,
        "recovered_password": recovered_password,
        "exploited_template": exploited_template,
        "vulnerability_class": "ESC1",
        "impersonated_user": impersonated_user,
        "attack_chain_summary": summary
    }


# ================================================================
# Part 2: Security Posture Assessment
# ================================================================
def assess_security_posture(ad):
    # --- Evaluate alternative attack paths ---
    alternative_paths = []

    # 1. Constrained delegation: svc_sqlprod has TRUSTED_TO_AUTH_FOR_DELEGATION
    #    and msDS-AllowedToDelegateTo DB-ANALYTICS
    for user in ad.get("users", []):
        allowed = user.get("msDS-AllowedToDelegateTo", [])
        if allowed and user.get("TRUSTED_TO_AUTH_FOR_DELEGATION"):
            targets = ", ".join(allowed)
            alternative_paths.append({
                "path_name": "Constrained Delegation with Protocol Transition (S4U2Self+S4U2Proxy)",
                "technique": "With the cracked svc_sqlprod credentials and TRUSTED_TO_AUTH_FOR_DELEGATION "
                             "flag, an attacker can use S4U2Self to obtain a forwardable service ticket "
                             "for any user, then S4U2Proxy to impersonate that user to the delegated "
                             f"services ({targets}). This bypasses the need for the target user to "
                             "authenticate.",
                "entry_account_or_object": user["sAMAccountName"],
                "target": targets,
                "risk_level": "high",
                "justification": "Constrained delegation with protocol transition allows impersonation "
                                 "of any non-Protected Users domain user to the target services. "
                                 "Risk is high but scoped to specific SPNs, unlike ESC1 which grants "
                                 "full domain admin."
            })

    # 2. Unconstrained delegation: BACKUP01 and DC01 have TRUSTED_FOR_DELEGATION
    for comp in ad.get("computers", []):
        if comp.get("TRUSTED_FOR_DELEGATION") and "Domain Controllers" not in comp.get("dn", ""):
            alternative_paths.append({
                "path_name": f"Unconstrained Delegation on {comp['sAMAccountName'].rstrip('$')}",
                "technique": f"{comp['sAMAccountName']} has unconstrained delegation enabled. "
                             "If a privileged user (e.g., Domain Admin) authenticates to this host "
                             "via Kerberos, their TGT is cached in memory and can be extracted with "
                             "Mimikatz/Rubeus. An attacker with local admin on this host could also "
                             "use the SpoolService/PrinterBug or PetitPotam to coerce DC authentication.",
                "entry_account_or_object": comp["sAMAccountName"],
                "target": "Any user whose TGT is captured (potential Domain Admin)",
                "risk_level": "high",
                "justification": "Non-DC servers with unconstrained delegation are high risk because "
                                 "coercion techniques (SpoolService, PetitPotam) can force DC machine "
                                 "account authentication, leading to full domain compromise."
            })

    # 3. DnsAdmins abuse
    for group in ad.get("groups", []):
        if group.get("sAMAccountName") == "DnsAdmins":
            members = group.get("members", [])
            for member in members:
                alternative_paths.append({
                    "path_name": "DnsAdmins DLL Injection",
                    "technique": f"User '{member}' is a member of the DnsAdmins group. DnsAdmins "
                                 "members can configure the DNS service to load an arbitrary DLL "
                                 "using dnscmd /config /serverlevelplugindll. When the DNS service "
                                 "restarts, the DLL executes as SYSTEM on the Domain Controller, "
                                 "granting full DC compromise.",
                    "entry_account_or_object": member,
                    "target": "DC01 (SYSTEM-level access on Domain Controller)",
                    "risk_level": "critical",
                    "justification": "DnsAdmins to DC SYSTEM is a well-known escalation path that "
                                     "requires only compromising a single non-admin user account. "
                                     "Rated critical because it provides SYSTEM on a DC with no "
                                     "additional prerequisites beyond the group membership."
                })

    # 4. Backup Operators
    for group in ad.get("groups", []):
        if group.get("sAMAccountName") == "Backup Operators":
            members = group.get("members", [])
            for member in members:
                alternative_paths.append({
                    "path_name": "Backup Operators Credential Extraction",
                    "technique": f"Service account '{member}' is in the Backup Operators group, "
                                 "which has SeBackupPrivilege. This allows backing up the SAM, "
                                 "SYSTEM, and SECURITY registry hives, or shadow-copying NTDS.dit "
                                 "from a Domain Controller. The extracted database contains all "
                                 "domain password hashes.",
                    "entry_account_or_object": member,
                    "target": "All domain credentials via NTDS.dit extraction",
                    "risk_level": "high",
                    "justification": "Backup Operators can extract all domain hashes but requires "
                                     "the attacker to first compromise the service account and "
                                     "obtain interactive access to a DC."
                })

    # --- Evaluate highest risk misconfiguration ---
    highest_risk = (
        "The VPNAccess AD CS certificate template is the highest risk misconfiguration. "
        "It is vulnerable to ESC1: the ENROLLEE_SUPPLIES_SUBJECT flag allows the requester "
        "to specify an arbitrary Subject Alternative Name (SAN), the template includes "
        "Client Authentication EKU (enabling Kerberos PKINIT authentication), "
        "msPKI-RA-Signature is 0 (no manager approval required), and 'VPN Users' group "
        "members can enroll. This combination allows any member of 'VPN Users' to "
        "immediately impersonate any domain user — including Domain Admins — by requesting "
        "a certificate with the target's UPN in the SAN. Unlike delegation attacks which "
        "are scoped to specific SPNs, or DnsAdmins which requires a DNS restart, ESC1 "
        "provides instant, unrestricted identity impersonation across the entire domain."
    )

    # --- Create Sigma detection rules ---
    sigma_kerberoasting = """title: Kerberoasting - RC4 Encrypted TGS Request from User Account
id: 3a8d0c2e-7f1b-4e9a-b5c3-d82f6e1a9b47
status: experimental
description: >
    Detects potential Kerberoasting by identifying TGS ticket requests using RC4
    encryption (0x17) which is anomalous in environments enforcing AES. Filters
    out machine accounts (ending in $) which legitimately use RC4 in some configurations.
references:
    - https://attack.mitre.org/techniques/T1558/003/
logsource:
    product: windows
    service: security
detection:
    selection:
        EventID: 4769
        TicketEncryptionType: '0x17'
        Status: '0x0'
    filter_machine_accounts:
        TargetUserName|endswith: '$'
    filter_service_names:
        ServiceName: 'krbtgt'
    condition: selection and not filter_machine_accounts and not filter_service_names
falsepositives:
    - Legacy applications requiring RC4 Kerberos encryption
    - Misconfigured service accounts without AES keys
level: high
tags:
    - attack.credential_access
    - attack.t1558.003"""

    sigma_adcs_esc1 = """title: AD CS Certificate Request with Subject Alternative Name Manipulation
id: 9c4e7b3a-2d1f-4a8c-b6e5-f73d2c9a1e84
status: experimental
description: >
    Detects certificate requests where the requester specifies a Subject Alternative
    Name containing a UPN different from their own identity, indicating potential
    ESC1 exploitation for identity impersonation.
references:
    - https://posts.specterops.io/certified-pre-owned-d95910965cd2
logsource:
    product: windows
    service: security
detection:
    selection_request:
        EventID: 4886
    selection_san:
        Attributes|contains: 'SAN:'
    filter_self_enrollment:
        Attributes|contains: ''
    condition: selection_request and selection_san
falsepositives:
    - Legitimate certificate requests with SANs for web servers
    - Automated certificate enrollment with approved SAN extensions
level: high
tags:
    - attack.privilege_escalation
    - attack.t1649"""

    sigma_pkinit = """title: Suspicious PKINIT Authentication from Non-Smartcard User
id: b7e2d4f1-8c3a-4b9e-a1d6-c95f3e2b7a48
status: experimental
description: >
    Detects Kerberos TGT requests using PKINIT (PreAuthType 16) certificate-based
    authentication, which may indicate the use of a stolen or forged certificate
    for impersonation if the account does not normally use smartcard logon.
references:
    - https://attack.mitre.org/techniques/T1649/
logsource:
    product: windows
    service: security
detection:
    selection:
        EventID: 4768
        PreAuthType: '16'
        Status: '0x0'
    filter_machine_accounts:
        TargetUserName|endswith: '$'
    condition: selection and not filter_machine_accounts
falsepositives:
    - Users with smartcard or certificate-based logon configured
    - ADFS service accounts using certificate authentication
level: medium
tags:
    - attack.credential_access
    - attack.t1649"""

    sigma_rules = [sigma_kerberoasting, sigma_adcs_esc1, sigma_pkinit]

    # --- Create remediation plan ---
    remediation_plan = [
        {
            "priority": 1,
            "action": "Harden VPNAccess certificate template to eliminate ESC1",
            "target_object": "VPNAccess certificate template (CN=VPNAccess,CN=Certificate Templates,CN=Public Key Services,CN=Services,CN=Configuration)",
            "specific_change": "Set msPKI-Certificate-Name-Flag to remove CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT (clear bit 0x1). "
                               "Set msPKI-RA-Signature to 1 or higher to require Certificate Manager approval. "
                               "Alternatively, if the template is not business-critical, disable it on the CA entirely.",
            "rationale": "This is the vulnerability the attacker exploited. ESC1 allows any enrollee to "
                         "impersonate any user in the domain. Removing ENROLLEE_SUPPLIES_SUBJECT prevents "
                         "arbitrary SAN specification, and requiring RA signatures adds human approval."
        },
        {
            "priority": 2,
            "action": "Rotate svc_sqlprod password and enforce managed service accounts",
            "target_object": "svc_sqlprod service account",
            "specific_change": "Reset password to a 128+ character random string via Set-ADAccountPassword. "
                               "Convert to a Group Managed Service Account (gMSA) with automatic password rotation. "
                               "Update SQL Server service configuration to use the gMSA.",
            "rationale": "The attacker cracked this account's weak password via Kerberoasting. "
                         "A gMSA with automatic 120-char password rotation eliminates Kerberoasting risk entirely."
        },
        {
            "priority": 3,
            "action": "Enforce AES-only Kerberos encryption and disable RC4",
            "target_object": "All service accounts (svc_sqlprod, svc_backup, svc_web, svc_adfs) and domain policy",
            "specific_change": "Set msDS-SupportedEncryptionTypes to 0x18 (AES128 + AES256) on each service account. "
                               "Configure domain GPO: Computer Configuration > Policies > Windows Settings > "
                               "Security Settings > Local Policies > Security Options > 'Network security: "
                               "Configure encryption types allowed for Kerberos' — enable only AES128 and AES256.",
            "rationale": "Kerberoasting relies on requesting RC4-encrypted TGS tickets which use the NTLM hash "
                         "as the key, making offline cracking feasible. Enforcing AES-only makes Kerberoasting "
                         "significantly harder as AES keys are derived with 4096 PBKDF2 iterations."
        },
        {
            "priority": 4,
            "action": "Remove svc_sqlprod from VPN Users group (least privilege)",
            "target_object": "VPN Users group membership",
            "specific_change": "Remove-ADGroupMember -Identity 'VPN Users' -Members 'svc_sqlprod'. "
                               "The SQL Server service account has no legitimate need for VPN certificate "
                               "enrollment.",
            "rationale": "The attacker leveraged VPN Users membership to enroll in the VPNAccess template. "
                         "Service accounts should only be in groups strictly required for their function."
        },
        {
            "priority": 5,
            "action": "Remove unconstrained delegation from BACKUP01",
            "target_object": "BACKUP01$ computer account",
            "specific_change": "Clear the TRUSTED_FOR_DELEGATION flag (bit 0x80000) in userAccountControl. "
                               "If delegation is needed, configure constrained delegation with specific SPNs.",
            "rationale": "Unconstrained delegation on non-DC servers allows TGT capture of any authenticating "
                         "principal. Combined with coercion attacks (SpoolService, PetitPotam), this could be "
                         "used to capture the DC machine account TGT."
        },
        {
            "priority": 6,
            "action": "Restrict DnsAdmins group membership",
            "target_object": "DnsAdmins group and m.oconnor account",
            "specific_change": "Remove m.oconnor from DnsAdmins unless DNS administration is a core duty. "
                               "Implement Just-In-Time access via PAM or a tiered admin model where DNS "
                               "changes require approval.",
            "rationale": "DnsAdmins members can load arbitrary DLLs into the DNS service running as SYSTEM "
                         "on the DC. This is a direct path to DC compromise that should be restricted to "
                         "dedicated Tier 0 admin accounts."
        },
        {
            "priority": 7,
            "action": "Remove constrained delegation with protocol transition from svc_sqlprod",
            "target_object": "svc_sqlprod service account",
            "specific_change": "Clear TRUSTED_TO_AUTH_FOR_DELEGATION flag. Remove msDS-AllowedToDelegateTo entries. "
                               "If cross-server SQL delegation is needed, use Resource-Based Constrained Delegation "
                               "with explicit principal restrictions instead.",
            "rationale": "Protocol transition (S4U2Self + S4U2Proxy) allows svc_sqlprod to impersonate any "
                         "non-Protected user to the delegated MSSQL services without that user authenticating. "
                         "RBCD with specific allowed principals is a safer alternative."
        }
    ]

    return {
        "alternative_attack_paths": alternative_paths,
        "highest_risk_misconfiguration": highest_risk,
        "sigma_rules": sigma_rules,
        "remediation_plan": remediation_plan
    }


# ================================================================
# Main
# ================================================================
def main():
    with open("/app/evidence/ad_snapshot.json") as f:
        ad = json.load(f)
    with open("/app/evidence/security_events.json") as f:
        events = json.load(f)
    with open("/app/evidence/wordlist.txt") as f:
        wordlist = [line.strip() for line in f if line.strip()]
    with open("/app/evidence/kerberoast_hashes.txt") as f:
        hash_lines = [line.strip() for line in f if line.strip()]

    # Part 1: Attack reconstruction
    attack_analysis = reconstruct_attack(ad, events, wordlist, hash_lines)

    # Part 2: Security posture assessment
    security_assessment = assess_security_posture(ad)

    # Write outputs
    os.makedirs("/app/answers", exist_ok=True)

    with open("/app/answers/attack_analysis.json", "w") as f:
        json.dump(attack_analysis, f, indent=2)

    with open("/app/answers/security_assessment.json", "w") as f:
        json.dump(security_assessment, f, indent=2)

    print("=== Attack Analysis ===")
    print(json.dumps(attack_analysis, indent=2))
    print("\n=== Security Assessment ===")
    print(json.dumps(security_assessment, indent=2))


if __name__ == "__main__":
    main()
