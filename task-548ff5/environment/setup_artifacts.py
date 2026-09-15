#!/usr/bin/env python3
"""Generate penetration testing artifacts for AD security assessment task."""

import json
import os
import struct
import random
import hmac as hmac_mod

from Crypto.Hash import MD4
from Crypto.Cipher import ARC4, AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.Padding import pad

# Deterministic seed for reproducible builds
SEED = 0x414D435254
random.seed(SEED)

DOMAIN = "ACME"
DOMAIN_FQDN = "acme.corp"
REALM = "ACME.CORP"
DC_NAME = "DC01"


def randbytes(n):
    return bytes([random.randint(0, 255) for _ in range(n)])


def ntlm_hash(password):
    return MD4.new(password.encode('utf-16-le')).digest()


def ntlm_hash_hex(password):
    return ntlm_hash(password).hex()


def generate_ntlmv2_line(password, username, domain):
    nt_hash = ntlm_hash(password)
    identity = (username.upper() + domain.upper()).encode('utf-16-le')
    ntv2_hash = hmac_mod.new(nt_hash, identity, 'md5').digest()

    server_challenge = randbytes(8)
    client_challenge = randbytes(8)

    blob = b'\x01\x01\x00\x00\x00\x00\x00\x00'
    blob += struct.pack('<Q', 133500000000000000)
    blob += client_challenge
    blob += b'\x00\x00\x00\x00'
    dom_bytes = domain.encode('utf-16-le')
    blob += struct.pack('<HH', 2, len(dom_bytes)) + dom_bytes
    comp_bytes = DC_NAME.encode('utf-16-le')
    blob += struct.pack('<HH', 1, len(comp_bytes)) + comp_bytes
    fqdn_bytes = DOMAIN_FQDN.encode('utf-16-le')
    blob += struct.pack('<HH', 4, len(fqdn_bytes)) + fqdn_bytes
    blob += struct.pack('<HH', 0, 0)

    nt_proof_str = hmac_mod.new(ntv2_hash, server_challenge + blob, 'md5').digest()
    return (
        f"{username}::{domain}:"
        f"{server_challenge.hex()}:{nt_proof_str.hex()}:{blob.hex()}"
    )


def generate_krb5tgs_line(password, username, realm, spn):
    key = ntlm_hash(password)
    usage = struct.pack('<I', 2)
    k1 = hmac_mod.new(key, usage, 'md5').digest()

    confounder = randbytes(8)
    plaintext_data = randbytes(240)
    plaintext = confounder + plaintext_data

    checksum = hmac_mod.new(k1, plaintext, 'md5').digest()
    k2 = hmac_mod.new(k1, checksum, 'md5').digest()

    cipher = ARC4.new(k2)
    encrypted = cipher.encrypt(plaintext)

    return (
        f"$krb5tgs$23$*{username}${realm}${spn}*"
        f"${checksum.hex()}${encrypted.hex()}"
    )


def aes_encrypt_file(input_path, output_path, password):
    """Encrypt file with AES-256-GCM using PBKDF2-derived key.

    Format: salt(16) || nonce(12) || tag(16) || ciphertext
    Key derivation: PBKDF2-HMAC-SHA1, 100000 iterations, 32-byte key.
    """
    salt = randbytes(16)
    key = PBKDF2(password, salt, dkLen=32, count=100000)
    nonce = randbytes(12)
    aes_cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    with open(input_path, 'rb') as f:
        plaintext = f.read()
    ciphertext, tag = aes_cipher.encrypt_and_digest(plaintext)
    with open(output_path, 'wb') as f:
        f.write(salt + nonce + tag + ciphertext)


# ============================================================
# Directory setup
# ============================================================
os.makedirs("/app/responder", exist_ok=True)
os.makedirs("/app/loot", exist_ok=True)

# ============================================================
# 1. Responder NTLMv2 captures
# ============================================================
print("[*] Generating Responder captures...")

responder_entries = [
    ("jsmith", "Summer2024!", "SMB"),
    ("bwilson", "Welcome1!", "SMB"),
    ("workstation01$", "K" * 120, "SMB"),
    ("scanner$", "Z" * 120, "HTTP"),
    ("agarcia", "Acme2024Spring", "HTTP"),
]

smb_lines = []
http_lines = []
for user, pwd, proto in responder_entries:
    line = generate_ntlmv2_line(pwd, user, DOMAIN)
    if proto == "SMB":
        smb_lines.append(line)
    else:
        http_lines.append(line)

with open("/app/responder/SMB-NTLMv2-Client-10.10.10.50.txt", "w") as f:
    f.write("\n".join(smb_lines) + "\n")
with open("/app/responder/HTTP-NTLMv2-Client-10.10.10.15.txt", "w") as f:
    f.write("\n".join(http_lines) + "\n")

# ============================================================
# 2. Kerberoast output (mix of valid and corrupted entries)
# ============================================================
print("[*] Generating Kerberoast output...")

tgs_entries = [
    ("svc_backup", "Backup#Service99", "cifs/FILESVR01.acme.corp"),
    ("svc_web", "WebApp2024$ecure", "HTTP/WEBSVR01.acme.corp"),
    ("svc_mssql", "Kj#9x$mP2v!qR7nL8wZ@4bC5dE6fG7hI8jK", "MSSQLSvc/DBSVR01.acme.corp:1433"),
]

valid_tgs_lines = []
for user, pwd, spn in tgs_entries:
    valid_tgs_lines.append(generate_krb5tgs_line(pwd, user, REALM, spn))

corrupted_entries = [
    (
        "$krb5tgs$23$*svc_old$ACME.CORP$LDAP/DC01.acme.corp*$"
        + "a" * 31
        + "$"
        + "b" * 200
    ),
    (
        "$krb5tgs$18$*svc_aes$ACME.CORP$HTTP/intranet.acme.corp*$"
        + randbytes(16).hex()
        + "$"
        + randbytes(200).hex()
    ),
    "$krb5tgs$23$" + randbytes(16).hex() + "$" + randbytes(200).hex(),
]

kerb_output = [
    "# Impacket v0.12.0 - GetUserSPNs.py output",
    "# Target Domain: ACME.CORP",
    "# Timestamp: 2024-11-15 14:23:07 UTC",
    "",
    corrupted_entries[0],
    valid_tgs_lines[0],
    "",
    corrupted_entries[1],
    valid_tgs_lines[1],
    corrupted_entries[2],
    "",
    valid_tgs_lines[2],
    "",
]

with open("/app/loot/kerberoast_raw.txt", "w") as f:
    f.write("\n".join(kerb_output) + "\n")

# ============================================================
# 3. NTDS dump (will be encrypted)
# ============================================================
print("[*] Generating NTDS dump...")

ntds_accounts = [
    ("Administrator", 500, "Adm!n#Pr0tect3d"),
    ("Guest", 501, None),
    ("krbtgt", 502, None),
    ("da_johnson", 1108, "J0hn$on@dmin2024"),
    ("jsmith", 1201, "Summer2024!"),
    ("bwilson", 1202, "Welcome1!"),
    ("agarcia", 1203, "Acme2024Spring"),
    ("mhenderson", 1204, "P@ssw0rd2024"),
    ("tlee", 1205, None),
    ("svc_backup", 1301, "Backup#Service99"),
    ("svc_web", 1302, "WebApp2024$ecure"),
    ("svc_mssql", 1303, None),
    ("svc_exchange", 1304, "Exch@nge$vc2024"),
    ("DC01$", 1000, None),
]

ntds_lines = []
for user, rid, pwd in ntds_accounts:
    lm = "aad3b435b51404eeaad3b435b51404ee"
    nt = ntlm_hash_hex(pwd) if pwd else randbytes(16).hex()
    ntds_lines.append(f"{DOMAIN_FQDN}\\{user}:{rid}:{lm}:{nt}:::")

ntds_content = "\n".join(ntds_lines) + "\n"
with open("/tmp/ntds_dump.txt", "w") as f:
    f.write(ntds_content)

# ============================================================
# 4. Crown jewels (will be encrypted)
# ============================================================
print("[*] Generating crown jewels...")

crown_jewels = """\
ACME CORP - STRICTLY CONFIDENTIAL
Emergency Access Credentials
========================================

Flag: ACME{d0m41n_c0mpr0m1s3d_v14_cr3d_ch41n_2024}

AWS Production Account:
  Access Key ID: AKIAIOSFODNN7EXAMPLE
  Secret Key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

Production Database (PostgreSQL):
  Host: prod-db.internal.acme.corp
  Port: 5432
  Username: prod_admin
  Password: Pr0d-DB-M@ster-2024!

VPN Gateway:
  Pre-Shared Key: AcmeVPN-PSK-7x9mK2pL
  Admin Portal: https://vpn.acme.corp/admin
  Admin Password: VPN@dmin#2024

Internal CA Root Key Password: C@-R00t-K3y-ACME!2024
"""

with open("/tmp/crown_jewels.txt", "w") as f:
    f.write(crown_jewels)

# ============================================================
# 5. Decoy content for red herring encrypted files
# ============================================================
print("[*] Generating decoy content...")

decoy_vulnscan = """\
ACME Corp Quarterly Vulnerability Scan Report - Q2 2024
========================================================
Scanner: Nessus Professional 10.7.4
Scan Date: 2024-06-15
Target Range: 10.10.10.0/24

Executive Summary:
  Critical: 2 (both patched in July maintenance window)
  High: 8
  Medium: 15
  Low: 23

Note: This is the Q2 periodic scan. All critical findings were
addressed in the July 2024 maintenance window. This report has
been superseded by the Q3 scan dated 2024-09-15.
No engagement-relevant credentials or access data in this file.
"""

with open("/tmp/decoy_vulnscan.txt", "w") as f:
    f.write(decoy_vulnscan)

decoy_config = """\
ACME Corp Server Configuration Backup
======================================
Export Date: 2024-08-20
Exported By: IT Operations (routine backup)

DC01 Configuration Summary:
  Role: Active Directory Domain Services
  OS: Windows Server 2022 Standard 21H2
  Last Patched: 2024-08-15
  Disk: C:\\ 120GB, D:\\ 500GB

FILESVR01 Configuration Summary:
  Role: File Server
  OS: Windows Server 2019 Standard
  Last Patched: 2024-08-15
  Shares: dept$, shared$, backup$

Note: This is a routine quarterly configuration export.
No credentials or sensitive engagement data.
"""

with open("/tmp/decoy_config.txt", "w") as f:
    f.write(decoy_config)

# ============================================================
# 6. Encrypt all packages with AES-256-GCM
# ============================================================
print("[*] Encrypting artifact packages with AES-256-GCM...")

# Package Alpha: NTDS dump — encrypted with svc_backup password
aes_encrypt_file("/tmp/ntds_dump.txt", "/app/loot/package_alpha.enc", "Backup#Service99")

# Package Beta: Decoy vuln scan — encrypted with svc_web password
aes_encrypt_file("/tmp/decoy_vulnscan.txt", "/app/loot/package_beta.enc", "WebApp2024$ecure")

# Package Gamma: Crown jewels — encrypted with da_johnson password
aes_encrypt_file("/tmp/crown_jewels.txt", "/app/loot/package_gamma.enc", "J0hn$on@dmin2024")

# Package Delta: Decoy config backup — encrypted with Administrator password
aes_encrypt_file("/tmp/decoy_config.txt", "/app/loot/package_delta.enc", "Adm!n#Pr0tect3d")

os.remove("/tmp/ntds_dump.txt")
os.remove("/tmp/crown_jewels.txt")
os.remove("/tmp/decoy_vulnscan.txt")
os.remove("/tmp/decoy_config.txt")

# ============================================================
# 7. Network map
# ============================================================
print("[*] Writing network map...")

network_map = {
    "engagement": "ACME Corp Internal Penetration Test",
    "domain": "acme.corp",
    "network_range": "10.10.10.0/24",
    "hosts": [
        {
            "hostname": "DC01",
            "ip": "10.10.10.5",
            "os": "Windows Server 2022",
            "role": "Domain Controller",
            "services": ["DNS/53", "LDAP/389", "Kerberos/88", "SMB/445"],
        },
        {
            "hostname": "FILESVR01",
            "ip": "10.10.10.10",
            "os": "Windows Server 2019",
            "role": "File Server",
            "services": ["SMB/445", "CIFS"],
        },
        {
            "hostname": "WEBSVR01",
            "ip": "10.10.10.15",
            "os": "Windows Server 2019",
            "role": "Web Server",
            "services": ["HTTP/80", "HTTPS/443"],
        },
        {
            "hostname": "DBSVR01",
            "ip": "10.10.10.20",
            "os": "Windows Server 2019",
            "role": "Database Server",
            "services": ["MSSQL/1433"],
        },
        {
            "hostname": "WS001",
            "ip": "10.10.10.50",
            "os": "Windows 10 Enterprise",
            "role": "Workstation",
            "services": [],
            "notes": "Initial compromise point — attacker presence confirmed",
        },
    ],
    "domain_groups": {
        "Domain Admins": ["Administrator", "da_johnson"],
        "Backup Operators": ["svc_backup"],
        "Service Accounts": ["svc_backup", "svc_web", "svc_mssql", "svc_exchange"],
        "Domain Users": [
            "jsmith", "bwilson", "agarcia", "mhenderson", "tlee",
        ],
    },
}

with open("/app/network_map.json", "w") as f:
    json.dump(network_map, f, indent=2)

# ============================================================
# 8. AD Configuration Export
# ============================================================
print("[*] Writing AD configuration export...")

ad_config = {
    "domain": "acme.corp",
    "forest": "acme.corp",
    "functional_level": "Windows Server 2016",
    "domain_controllers": ["DC01.acme.corp"],
    "password_policy": {
        "minimum_length": 8,
        "complexity_required": True,
        "max_age_days": 90,
        "min_age_days": 1,
        "lockout_threshold": 5,
        "lockout_duration_minutes": 30,
        "lockout_observation_window_minutes": 30,
        "history_count": 12,
        "reversible_encryption": False,
    },
    "fine_grained_password_policies": [],
    "gpo_security_settings": {
        "Default Domain Policy": {
            "LLMNR": "Not Configured",
            "NetBIOS_over_TCPIP": "Not Configured",
            "mDNS": "Not Configured",
            "WinRM_Service": "Enabled",
            "PowerShell_ScriptBlock_Logging": "Disabled",
            "PowerShell_Module_Logging": "Disabled",
            "Process_Creation_Auditing_CommandLine": "Disabled",
            "Credential_Guard": "Not Configured",
            "LSA_Protection": "Not Configured",
            "WDIGEST_Authentication": "Not Configured",
            "SMB_Signing_Required": False,
            "LDAP_Signing_Required": False,
        },
    },
    "kerberos_policy": {
        "max_ticket_lifetime_hours": 10,
        "max_renewal_lifetime_days": 7,
        "supported_encryption_types": ["AES256-CTS-HMAC-SHA1-96", "AES128-CTS-HMAC-SHA1-96", "RC4-HMAC-MD5"],
        "claims_compound_auth_armor": "Not Supported",
    },
    "delegation_settings": [
        {
            "account": "svc_web",
            "delegation_type": "Unconstrained",
            "spn": ["HTTP/WEBSVR01.acme.corp"],
            "note": "Set during IIS deployment in 2021; change ticket pending since Q1 2024",
        },
        {
            "account": "svc_backup",
            "delegation_type": "Not Delegated",
            "spn": ["cifs/FILESVR01.acme.corp"],
        },
        {
            "account": "svc_mssql",
            "delegation_type": "Constrained",
            "allowed_targets": ["MSSQLSvc/DBSVR01.acme.corp:1433"],
            "spn": ["MSSQLSvc/DBSVR01.acme.corp:1433"],
        },
    ],
    "service_accounts": {
        "svc_backup": {
            "managed_service_account": False,
            "spn": ["cifs/FILESVR01.acme.corp"],
            "member_of": ["Backup Operators", "Domain Users"],
            "password_last_set": "2024-01-15T09:30:00Z",
            "password_never_expires": True,
            "account_enabled": True,
            "logon_hours": "unrestricted",
        },
        "svc_web": {
            "managed_service_account": False,
            "spn": ["HTTP/WEBSVR01.acme.corp"],
            "member_of": ["Domain Users"],
            "password_last_set": "2024-03-22T14:15:00Z",
            "password_never_expires": True,
            "account_enabled": True,
            "logon_hours": "unrestricted",
        },
        "svc_mssql": {
            "managed_service_account": True,
            "spn": ["MSSQLSvc/DBSVR01.acme.corp:1433"],
            "member_of": ["Domain Users"],
            "password_last_set": "2024-11-01T00:00:00Z",
            "password_never_expires": False,
            "account_enabled": True,
        },
        "svc_exchange": {
            "managed_service_account": False,
            "spn": [],
            "member_of": ["Domain Users", "Exchange Servers"],
            "password_last_set": "2023-06-10T11:00:00Z",
            "password_never_expires": True,
            "account_enabled": True,
            "logon_hours": "unrestricted",
        },
    },
    "privileged_accounts": {
        "da_johnson": {
            "member_of": ["Domain Admins", "Administrators", "Enterprise Admins"],
            "last_logon": "2024-11-14T16:45:00Z",
            "allowed_logon_workstations": "unrestricted",
            "admin_count": 1,
            "protected_users_member": False,
            "smart_card_required": False,
            "password_last_set": "2024-09-01T08:00:00Z",
        },
        "Administrator": {
            "member_of": ["Domain Admins", "Administrators", "Schema Admins", "Enterprise Admins"],
            "last_logon": "2024-11-15T07:30:00Z",
            "allowed_logon_workstations": "unrestricted",
            "admin_count": 1,
            "protected_users_member": False,
            "smart_card_required": False,
            "password_last_set": "2024-06-15T10:00:00Z",
        },
    },
    "audit_policy": {
        "Account_Logon": {"success": True, "failure": True},
        "Account_Management": {"success": True, "failure": False},
        "Directory_Service_Access": {"success": True, "failure": False},
        "Logon_Logoff": {"success": True, "failure": True},
        "Object_Access": {"success": False, "failure": False},
        "Policy_Change": {"success": True, "failure": False},
        "Privilege_Use": {"success": False, "failure": False},
        "Detailed_Tracking": {"success": False, "failure": False},
    },
    "protected_users_group_members": [],
    "tiered_administration": {
        "implemented": False,
        "paw_deployed": False,
        "admin_tier_separation": "None",
    },
}

with open("/app/ad_config.json", "w") as f:
    json.dump(ad_config, f, indent=2)

# ============================================================
# 9. Security Event Logs
# ============================================================
print("[*] Generating security event logs...")

events = [
    # --- Red herring: vulnerability scanner activity from 10.10.10.100 ---
    {
        "TimeCreated": "2024-11-15T08:45:00.123Z",
        "EventID": 4625,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "admin",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.100",
            "IpPort": "49152",
            "Status": "0xC000006D",
            "SubStatus": "0xC000006A",
            "FailureReason": "Unknown user name or bad password.",
        },
    },
    {
        "TimeCreated": "2024-11-15T08:45:01.456Z",
        "EventID": 4625,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "sa",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.100",
            "IpPort": "49153",
            "Status": "0xC000006D",
            "SubStatus": "0xC000006A",
            "FailureReason": "Unknown user name or bad password.",
        },
    },
    {
        "TimeCreated": "2024-11-15T08:45:02.789Z",
        "EventID": 4625,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "root",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.100",
            "IpPort": "49154",
            "Status": "0xC000006D",
            "SubStatus": "0xC000006A",
            "FailureReason": "Unknown user name or bad password.",
        },
    },
    {
        "TimeCreated": "2024-11-15T08:45:03.012Z",
        "EventID": 4625,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "test",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.100",
            "IpPort": "49155",
            "Status": "0xC000006D",
            "SubStatus": "0xC000006A",
            "FailureReason": "Unknown user name or bad password.",
        },
    },

    # --- Actual attack: NTLM validation events from Responder on 10.10.10.50 ---
    {
        "TimeCreated": "2024-11-15T09:15:23.100Z",
        "EventID": 4776,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "jsmith",
            "Workstation": "WS001",
            "Status": "0x0",
            "PackageName": "MICROSOFT_AUTHENTICATION_PACKAGE_V1_0",
        },
    },
    {
        "TimeCreated": "2024-11-15T09:15:24.200Z",
        "EventID": 4776,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "bwilson",
            "Workstation": "WS001",
            "Status": "0x0",
            "PackageName": "MICROSOFT_AUTHENTICATION_PACKAGE_V1_0",
        },
    },
    {
        "TimeCreated": "2024-11-15T09:15:45.300Z",
        "EventID": 4776,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "agarcia",
            "Workstation": "WEBSVR01",
            "Status": "0x0",
            "PackageName": "MICROSOFT_AUTHENTICATION_PACKAGE_V1_0",
        },
    },

    # --- Attacker authenticates as jsmith after cracking NTLMv2 ---
    {
        "TimeCreated": "2024-11-15T10:30:12.500Z",
        "EventID": 4624,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "jsmith",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.50",
            "IpPort": "51234",
            "AuthenticationPackageName": "Kerberos",
            "LogonProcessName": "Kerberos",
            "KeyLength": 0,
        },
    },

    # --- Kerberoasting: rapid TGS requests with RC4 (etype 0x17 = 23) ---
    {
        "TimeCreated": "2024-11-15T10:32:07.100Z",
        "EventID": 4769,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "jsmith@ACME.CORP",
            "ServiceName": "svc_backup",
            "ServiceSid": "S-1-5-21-ACME-1301",
            "TicketOptions": "0x40810010",
            "TicketEncryptionType": "0x17",
            "IpAddress": "10.10.10.50",
            "IpPort": "51235",
            "Status": "0x0",
        },
    },
    {
        "TimeCreated": "2024-11-15T10:32:07.300Z",
        "EventID": 4769,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "jsmith@ACME.CORP",
            "ServiceName": "svc_web",
            "ServiceSid": "S-1-5-21-ACME-1302",
            "TicketOptions": "0x40810010",
            "TicketEncryptionType": "0x17",
            "IpAddress": "10.10.10.50",
            "IpPort": "51236",
            "Status": "0x0",
        },
    },
    {
        "TimeCreated": "2024-11-15T10:32:07.500Z",
        "EventID": 4769,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "jsmith@ACME.CORP",
            "ServiceName": "svc_mssql",
            "ServiceSid": "S-1-5-21-ACME-1303",
            "TicketOptions": "0x40810010",
            "TicketEncryptionType": "0x17",
            "IpAddress": "10.10.10.50",
            "IpPort": "51237",
            "Status": "0x0",
        },
    },

    # --- More red herring: scanner continues periodic probing ---
    {
        "TimeCreated": "2024-11-15T11:00:00.000Z",
        "EventID": 4625,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "backup",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.100",
            "IpPort": "49200",
            "Status": "0xC000006D",
            "SubStatus": "0xC000006A",
            "FailureReason": "Unknown user name or bad password.",
        },
    },
    {
        "TimeCreated": "2024-11-15T11:00:01.000Z",
        "EventID": 4625,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "sysadmin",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.100",
            "IpPort": "49201",
            "Status": "0xC000006D",
            "SubStatus": "0xC000006A",
            "FailureReason": "Unknown user name or bad password.",
        },
    },

    # --- Attacker uses cracked svc_backup to access DC ---
    {
        "TimeCreated": "2024-11-15T14:20:33.700Z",
        "EventID": 4624,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "svc_backup",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.50",
            "IpPort": "52100",
            "AuthenticationPackageName": "NTLM",
            "LogonProcessName": "NtLmSsp",
            "LmPackageName": "NTLM V2",
            "KeyLength": 128,
        },
    },

    # --- DCSync / NTDS extraction via replication rights ---
    {
        "TimeCreated": "2024-11-15T14:22:15.200Z",
        "EventID": 4662,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "SubjectUserName": "svc_backup",
            "SubjectDomainName": "ACME",
            "ObjectType": "{19195a5b-6da0-11d0-afd3-00c04fd930c9}",
            "ObjectName": "DC=acme,DC=corp",
            "OperationType": "Object Access",
            "AccessMask": "0x100",
            "Properties": "DS-Replication-Get-Changes;DS-Replication-Get-Changes-All;DS-Replication-Get-Changes-In-Filtered-Set",
        },
    },
    {
        "TimeCreated": "2024-11-15T14:22:16.100Z",
        "EventID": 4662,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "SubjectUserName": "svc_backup",
            "SubjectDomainName": "ACME",
            "ObjectType": "{19195a5b-6da0-11d0-afd3-00c04fd930c9}",
            "ObjectName": "DC=acme,DC=corp",
            "OperationType": "Object Access",
            "AccessMask": "0x100",
            "Properties": "DS-Replication-Get-Changes;DS-Replication-Get-Changes-All",
        },
    },

    # --- Attacker authenticates as da_johnson after cracking from NTDS ---
    {
        "TimeCreated": "2024-11-15T15:45:10.400Z",
        "EventID": 4624,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "TargetUserName": "da_johnson",
            "TargetDomainName": "ACME",
            "LogonType": 3,
            "IpAddress": "10.10.10.50",
            "IpPort": "53001",
            "AuthenticationPackageName": "NTLM",
            "LogonProcessName": "NtLmSsp",
            "LmPackageName": "NTLM V2",
            "KeyLength": 128,
        },
    },

    # --- DA performs privileged operations ---
    {
        "TimeCreated": "2024-11-15T15:47:30.600Z",
        "EventID": 4672,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "SubjectUserName": "da_johnson",
            "SubjectDomainName": "ACME",
            "PrivilegeList": "SeDebugPrivilege\n\tSeBackupPrivilege\n\tSeRestorePrivilege\n\tSeTakeOwnershipPrivilege",
        },
    },

    # --- Additional file access events to show DA accessing sensitive shares ---
    {
        "TimeCreated": "2024-11-15T15:48:05.800Z",
        "EventID": 5145,
        "Channel": "Security",
        "Computer": "DC01.acme.corp",
        "EventData": {
            "SubjectUserName": "da_johnson",
            "SubjectDomainName": "ACME",
            "ShareName": "\\\\*\\SYSVOL",
            "ShareLocalPath": "\\??\\C:\\Windows\\SYSVOL\\sysvol",
            "RelativeTargetName": "acme.corp\\scripts\\emergency-creds.ps1",
            "AccessMask": "0x12019F",
            "IpAddress": "10.10.10.50",
        },
    },
]

with open("/app/security_events.json", "w") as f:
    json.dump(events, f, indent=2)

# ============================================================
# 10. Engagement notes (with competing hypotheses)
# ============================================================
print("[*] Writing engagement notes...")

notes = """\
ACME Corp Internal Penetration Test - Artifact Handoff
=======================================================
Tester: [REDACTED] | Date: 2024-11-15 | Status: INCOMPLETE HANDOFF

BACKGROUND
----------
The original tester was pulled off this engagement before completing
the report. Two team members reviewed the artifacts and reached
different conclusions about the attack path used. Your job is to
complete the analysis: crack all credentials, determine which attack
path is supported by the evidence, decrypt all relevant packages,
and produce a full security assessment.

COMPETING ATTACK PATH HYPOTHESES
---------------------------------

  HYPOTHESIS A — "LLMNR Poisoning Chain"
    The attacker positioned on WS001 (10.10.10.50), deployed Responder
    to poison LLMNR/NBT-NS queries on the corporate VLAN, captured
    NTLMv2 challenge-response hashes, cracked them offline, used
    resulting domain user credentials for Kerberoasting against service
    accounts, compromised a privileged service account, leveraged its
    group membership to perform DCSync/NTDS extraction, then cracked
    domain admin credentials from the dump.

  HYPOTHESIS B — "Phishing & Credential Harvest"
    The attacker delivered a phishing email to a user workstation
    (10.10.10.100), gained execution via macro, used Mimikatz to
    harvest plaintext credentials from LSASS memory, performed
    credential stuffing against the domain controller, then used
    direct volume shadow copy to extract NTDS.dit from the DC.

Review the security event logs (security_events.json) and correlate
them with the captured artifacts to determine which hypothesis is
correct. The event logs were exported from DC01 prior to handoff.

COLLECTED ARTIFACTS
-------------------

  responder/            Captured NTLMv2 challenge-response hashes.

  loot/kerberoast_raw.txt
                        Kerberoasting output against domain SPNs.
                        WARNING: the extraction tool encountered errors
                        mid-run. Some entries may be malformed or use
                        unsupported encryption types. Filter carefully.

  loot/package_alpha.enc
  loot/package_beta.enc
  loot/package_gamma.enc
  loot/package_delta.enc
                        Four encrypted packages collected at various
                        stages of the engagement. Each was encrypted
                        with AES-256-GCM (PBKDF2 key derivation,
                        100000 iterations, 32-byte key) using a
                        credential obtained during testing. Binary
                        format: salt(16) || nonce(12) || tag(16) ||
                        ciphertext. Contents and encryption keys are
                        not documented — you must determine which
                        credential decrypts each package and assess
                        which contain engagement-relevant data vs.
                        decoys.

  network_map.json      Discovered hosts, services, and domain group info.

  ad_config.json        Active Directory configuration export: GPOs,
                        Kerberos settings, delegation, service accounts,
                        password policies, audit configuration. Use this
                        to identify security misconfigurations that enabled
                        the attack.

  security_events.json  Windows Security event log export from DC01.
                        Contains authentication, Kerberos, replication,
                        and file access events around the attack window.

  wordlist.txt          Organization-specific wordlist from OSINT phase.
"""

with open("/app/engagement_notes.txt", "w") as f:
    f.write(notes)

# ============================================================
# 11. Wordlist
# ============================================================
print("[*] Generating wordlist...")

passwords = set()

bases = [
    "Password", "Welcome", "Admin", "Summer", "Winter", "Spring", "Fall",
    "Monday", "Friday", "Backup", "Service", "Server", "Domain", "Exchange",
    "WebApp", "Security", "Network", "Corp", "Acme", "Company", "Access",
    "Login", "Change", "Reset", "Temp", "Test", "User", "Master", "Secret",
    "Oracle", "Manage", "Cloud", "System", "Global", "Portal", "Enter",
]
suffixes = [
    "!", "#", "$", "@", "1", "1!", "123", "123!", "2023", "2024",
    "2023!", "2024!", "2024#", "2024$", "Pass", "Pass!", "#1",
    "99", "#99", "$1", "2025",
]
for base in bases:
    for suf in suffixes:
        passwords.add(f"{base}{suf}")

targets = [
    "Summer2024!", "Welcome1!", "Acme2024Spring",
    "Backup#Service99", "WebApp2024$ecure",
    "Adm!n#Pr0tect3d", "J0hn$on@dmin2024",
    "P@ssw0rd2024", "Exch@nge$vc2024",
]
passwords.update(targets)

extras = [
    "P@ssword1", "Ch@ngeme1", "Letmein!", "Tr0ub4dor&3",
    "qwerty123", "abc123!", "trustno1", "football1!",
    "baseball2024", "dragon123", "monkey123", "shadow2024",
    "jennifer1!", "robert2024", "michael123!", "charlie#1",
    "P@ssw0rd!", "Passw0rd1", "p@ssw0rd", "PASSWORD1!",
    "Spr!ng2024", "W!nter2024", "Autumn2024!", "F@ll2024",
    "C0rp0rate!", "Enterpr!se1", "Pr0duct!on1", "Stag!ng2024",
    "D3v3l0p!", "T3st1ng!", "Qual!ty1", "R3lease2024",
    "C0mpany2024", "0ff!ce365", "Micr0soft!", "W!ndows2024",
    "L!nux2024", "Ubunt#2024", "R3dhat!", "D3bian2024",
]
passwords.update(extras)

for i in range(150):
    b = random.choice(["Key", "Auth", "Cred", "Token", "Hash", "Cert", "Sig"])
    n = random.randint(100, 999)
    s = random.choice(["!", "#", "@", "$"])
    passwords.add(f"{b}{s}{n}")

pw_list = sorted(passwords)
random.shuffle(pw_list)

with open("/app/wordlist.txt", "w") as f:
    f.write("\n".join(pw_list) + "\n")

print(f"[*] Wordlist: {len(pw_list)} entries")
print("[*] Artifact generation complete!")
