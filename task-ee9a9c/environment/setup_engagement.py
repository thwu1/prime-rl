#!/usr/bin/env python3
"""
Generate engagement artifacts for the credential forensics audit task.
Runs during Docker build (builder stage only). Creates all hash dumps,
encrypted files, wordlists, honeypot captures, and engagement notes.
"""

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import crypt
import struct
import subprocess
import os

import bcrypt as bcrypt_lib

ENGAGEMENT_DIR = "/app/engagement"
os.makedirs(ENGAGEMENT_DIR, exist_ok=True)


# ============================================================
# Pure-Python MD4 for NTLM hash computation
# ============================================================

def _md4(message):
    """Compute MD4 digest of bytes, return hex string."""
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


# ============================================================
# 1. Linux Shadow File (SHA-512 crypt hashes)
# ============================================================

LINUX_ACCOUNTS = [
    ("svc_backup", "Backup2024!", "$6$Kj8mPq2x"),
    ("admin_web", "Webmaster2024#", "$6$Rm4nVt7y"),
    ("dev_ops", "Pipeline2024!", "$6$Hn3kWp9z"),
    ("jorge.m", "Backup2024!", "$6$Xp5wNq3r"),
    ("tina.c", "Pipeline2024!", "$6$Ym7sLk4t"),
]

shadow_lines = [
    "root:*:19500:0:99999:7:::",
    "daemon:*:19500:0:99999:7:::",
    "www-data:*:19500:0:99999:7:::",
]

chgdates = {"svc_backup": 19750, "admin_web": 19845, "dev_ops": 19900,
            "jorge.m": 19880, "tina.c": 19890}

for user, password, salt in LINUX_ACCOUNTS:
    hashed = crypt.crypt(password, salt)
    chg = chgdates.get(user, 19800)
    shadow_lines.append(f"{user}:{hashed}:{chg}:0:99999:7:::")

with open(os.path.join(ENGAGEMENT_DIR, "server_shadow.txt"), "w") as f:
    f.write("\n".join(shadow_lines) + "\n")


# ============================================================
# 2. Domain NTLM Hashes (pwdump format)
# ============================================================

DOMAIN_ACCOUNTS = [
    ("j.martinez", "Backup2024!", "1001"),
    ("svc_sql", "Database2024!", "1002"),
    ("admin.dc", "Control2024#", "1003"),
    ("k.wilson", "Winter2024!", "1004"),
    ("t.chen", "Pipeline2024!", "1005"),
]

domain_lines = [
    "Guest:501:aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0:::",
    "krbtgt:502:aad3b435b51404eeaad3b435b51404ee:f1a93a3face2b9b8e0d6a6bf14a85cf3:::",
]

for user, password, rid in DOMAIN_ACCOUNTS:
    nt = ntlm_hash(password)
    domain_lines.append(f"{user}:{rid}:aad3b435b51404eeaad3b435b51404ee:{nt}:::")

with open(os.path.join(ENGAGEMENT_DIR, "domain_hashes.txt"), "w") as f:
    f.write("\n".join(domain_lines) + "\n")


# ============================================================
# 3. Web Application Database Dump (bcrypt hashes)
# ============================================================

WEBAPP_ACCOUNTS = [
    ("jmartinez", "jorge.martinez@meridian.local", "Backup2024!", "editor", "2023-06-15", "2024-03-10"),
    ("kwilson", "kyle.wilson@meridian.local", "Security2023@", "analyst", "2023-09-22", "2024-03-12"),
    ("tchen", "tina.chen@meridian.local", "Pipeline2024!", "editor", "2023-04-01", "2024-03-11"),
    ("webapp_admin", "admin@meridian.local", "Fortress2023@", "admin", "2022-01-10", "2024-03-14"),
]

webapp_lines = [
    "-- Meridian Technologies Intranet Portal",
    "-- Database: meridian_portal (MySQL 8.0.36)",
    "-- Table: users",
    "-- Extracted: 2024-03-13 during post-exploitation",
    "",
    "id,username,email,password_hash,role,created_at,last_login",
]

for idx, (username, email, password, role, created, last_login) in enumerate(WEBAPP_ACCOUNTS, 1):
    hashed = bcrypt_lib.hashpw(password.encode(), bcrypt_lib.gensalt(rounds=5)).decode('ascii')
    webapp_lines.append(f"{idx},{username},{email},{hashed},{role},{created},{last_login}")

with open(os.path.join(ENGAGEMENT_DIR, "webapp_db_dump.csv"), "w") as f:
    f.write("\n".join(webapp_lines) + "\n")


# ============================================================
# 4. Honeypot Capture Log (reveals password pattern)
# ============================================================

honeypot_content = """\
=== Meridian Technologies Network Honeypot ===
=== Deployment: 2024-03-11 through 2024-03-14 ===
=== Captures: cleartext credentials from authentication attempts ===

2024-03-11 09:15:22 [HONEYPOT-RDP] src=10.0.2.45 dst=10.0.2.200 user=testuser auth=FAIL password=Summer2024!
2024-03-11 09:32:45 [HONEYPOT-SSH] src=10.0.1.22 dst=10.0.1.100 user=admin auth=FAIL password=Network2023#
2024-03-11 10:01:12 [HONEYPOT-HTTP] src=10.0.3.10 dst=10.0.3.50 user=demo auth=FAIL password=Portal2024@
2024-03-11 14:22:33 [HONEYPOT-RDP] src=10.0.2.67 dst=10.0.2.200 user=backup auth=FAIL password=Server2023!
2024-03-11 15:45:01 [HONEYPOT-SSH] src=10.0.1.88 dst=10.0.1.100 user=root auth=FAIL password=Cloud2024#
2024-03-12 08:12:55 [HONEYPOT-HTTP] src=10.0.3.25 dst=10.0.3.50 user=test auth=FAIL password=Diamond2023@
2024-03-12 11:30:44 [HONEYPOT-RDP] src=10.0.2.91 dst=10.0.2.200 user=support auth=FAIL password=Helpdesk2024!
2024-03-13 09:05:17 [HONEYPOT-SSH] src=10.0.1.15 dst=10.0.1.100 user=deploy auth=FAIL password=Release2023#
"""

with open(os.path.join(ENGAGEMENT_DIR, "honeypot_captures.log"), "w") as f:
    f.write(honeypot_content)


# ============================================================
# 5. Password Policy
# ============================================================

policy_content = """\
Meridian Technologies - Password Policy (GPO Extract)
======================================================

Minimum password length: 10 characters
Complexity requirements: Enabled
  - Must contain characters from 3 of 4 categories:
    * Uppercase letters (A-Z)
    * Lowercase letters (a-z)
    * Digits (0-9)
    * Special characters (!@#$%^&*)
Password history: 12 passwords remembered
Maximum password age: 90 days
Minimum password age: 1 day
Account lockout threshold: 5 invalid attempts
Account lockout duration: 30 minutes

NOTE: Policy does not enforce cross-system password uniqueness.
Service accounts are exempt from periodic rotation per IT exception
request #2024-0142.
"""

with open(os.path.join(ENGAGEMENT_DIR, "password_policy.txt"), "w") as f:
    f.write(policy_content)


# ============================================================
# 6. Engagement Notes
# ============================================================

notes_content = """\
ENGAGEMENT NOTES - Internal Penetration Test
Client: Meridian Technologies
Assessment Period: 2024-03-11 through 2024-03-15
Lead Analyst: [REDACTED] (reassigned to IR-2024-031)

== Network Topology ==

Segment 1 - Linux Infrastructure (10.0.1.0/24):
  File server, web server, CI/CD build server.
  Authentication: local accounts, /etc/shadow (SHA-based hashing).

Segment 2 - Windows Domain MERIDIAN.LOCAL (10.0.2.0/24):
  DC01 (Domain Controller), user workstations.
  Authentication: Active Directory, NTDS.dit.

Segment 3 - DMZ (10.0.3.0/24):
  Intranet web portal at intranet.meridian.local.
  Authentication: MySQL database. NOTE - this is a legacy application;
  initial review suggests the password hashing may use a different
  algorithm than the Linux servers.

== Personnel Identified ==

IT Operations Team:
- Jorge Martinez: Senior sysadmin. Linux account "jorge.m", domain account "j.martinez", portal username "jmartinez". Manages backup infrastructure and the svc_backup service account.
- Tina Chen: DevOps lead. Linux account "tina.c", domain account "t.chen", portal username "tchen". Manages CI/CD pipeline and the dev_ops service account.
- Kyle Wilson: Junior security analyst. Domain account "k.wilson", portal username "kwilson". No Linux server access.

Service Accounts:
- svc_backup: Automated backup service on Linux servers
- admin_web: Web server administration (Linux)
- dev_ops: CI/CD pipeline automation (Linux)
- svc_sql: SQL Server service account (Domain)
- admin.dc: Domain Controller administrator - Domain Admin privileges
- webapp_admin: Intranet portal administration

== Credential Observations ==

A network honeypot was deployed across all three segments during the
first two days of the assessment. It captured cleartext credentials
from employees testing connectivity and troubleshooting access. See
honeypot_captures.log for the raw capture data. The captured passwords
exhibit a consistent organizational construction pattern - analyze the
captures to identify the scheme before attempting to crack the extracted
hashes.

A custom engagement wordlist (engagement_wordlist.txt) was compiled from
OSINT sources, email signatures, internal documentation headers, and
infrastructure naming conventions observed during reconnaissance.

== Extracted Artifacts ==

1. server_shadow.txt - /etc/shadow extract from Linux servers. Contains
   3 service accounts and 2 personal accounts with crackable SHA-based
   hashes. System accounts (root, daemon, www-data) are locked.

2. domain_hashes.txt - NTDS.dit extract in standard dump format.
   Contains 5 crackable domain accounts. Guest and krbtgt entries
   should be skipped.

3. webapp_db_dump.csv - User table export from the intranet portal
   database. Contains 4 accounts. Hash format differs from the Linux
   shadow file - determine the hashing algorithm before cracking.

4. locked_archive.zip - Password-protected archive from \\\\DC01\\vault$
   file share. Believed to be secured with the DC administrator's
   credential.

5. classified_data.gpg - GPG symmetrically encrypted file discovered
   alongside the archive. The decryption passphrase is stored within
   the vault.

== Vault Architecture ==

The vault archive contains a manifest file describing its contents and
how each entry is encrypted. Encrypted vault entries use standard
OpenSSL symmetric encryption (AES-256-CBC with PBKDF2 key derivation).
The manifest identifies which assessment credential was used as the
encryption key for each entry.

== Interim Findings (Partial) ==

- Strong suspicion of credential reuse between Linux and Windows
  systems based on timing analysis of authentication logs
- At least one employee is believed to be using their personal password
  as a service account password - a serious policy violation
- Password policy (see password_policy.txt) requires complexity but
  does not enforce uniqueness across systems
"""

with open(os.path.join(ENGAGEMENT_DIR, "notes.txt"), "w") as f:
    f.write(notes_content)


# ============================================================
# 7. Engagement Wordlist (~280 words)
# ============================================================

wordlist_words = [
    # Infrastructure (includes: Backup, Database, Pipeline, Control)
    "Server", "Network", "Firewall", "Router", "Switch", "Gateway", "Proxy",
    "Cloud", "Storage", "Deploy", "Monitor", "Config", "Service", "Cluster",
    "Queue", "Cache", "Load", "Bridge", "Tunnel", "Socket", "Backup", "Database",
    "Pipeline", "Control", "System", "Process", "Release", "Build", "Stage",
    "Production", "Development", "Staging", "Docker", "Container", "Virtual",
    "Machine", "Instance", "Volume", "Registry", "Endpoint",
    # Admin/Roles (includes: Webmaster)
    "Admin", "Root", "Super", "Master", "Manager", "Director", "Lead", "Chief",
    "Head", "Senior", "Junior", "Analyst", "Engineer", "Architect", "Specialist",
    "Operator", "Webmaster", "Developer", "Consultant", "Coordinator",
    # Seasons/Time (includes: Winter)
    "Spring", "Summer", "Autumn", "Winter", "January", "February", "March",
    "April", "June", "July", "August", "September", "October", "November",
    "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    # Security (includes: Security, Fortress)
    "Security", "Encrypt", "Decrypt", "Cipher", "Token", "Access", "Login",
    "Secret", "Private", "Public", "Shield", "Guard", "Protect", "Defend",
    "Scan", "Audit", "Patch", "Exploit", "Breach", "Threat", "Risk", "Alert",
    "Incident", "Response", "Forensic", "Malware", "Phishing", "Ransomware",
    # Corporate
    "Acme", "Corp", "Global", "Tech", "Solutions", "Digital", "Cyber",
    "Enterprise", "Company", "Business", "Finance", "Marketing", "Sales",
    "Legal", "Engineering", "Operations", "Support", "Executive", "Strategy",
    "Innovation", "Meridian", "Horizon", "Apex", "Summit", "Pinnacle",
    # Names
    "Smith", "Johnson", "Williams", "Martinez", "Wilson", "Chen", "Thompson",
    "Davis", "Garcia", "Anderson", "Taylor", "Moore", "Jackson", "White",
    "Harris", "Brown", "Miller", "Thomas", "Robinson", "Clark",
    # Projects/Code names
    "Project", "Mission", "Falcon", "Eagle", "Phoenix", "Dragon", "Thunder",
    "Storm", "Lightning", "Shadow", "Ghost", "Phantom", "Stealth", "Quantum",
    "Flux", "Orbit", "Velocity", "Momentum", "Catalyst", "Fusion", "Nexus",
    "Titan", "Atlas", "Vortex", "Zenith", "Nova", "Pulsar", "Quasar",
    # Common password bases
    "Password", "Welcome", "Change", "Temp", "Default", "Hello", "World",
    "Test", "Demo", "Sample", "Example", "Alpha", "Beta", "Gamma", "Delta",
    "Omega", "Sigma", "Lambda", "Kappa", "Theta", "Epsilon",
    # Animals
    "Tiger", "Lion", "Bear", "Wolf", "Hawk", "Cobra", "Viper", "Raven",
    "Panther", "Jaguar", "Mustang", "Stallion",
    # Colors
    "Red", "Blue", "Green", "Black", "Gold", "Silver", "Purple", "Orange",
    "Crimson", "Azure", "Indigo", "Scarlet",
    # Technology
    "Portal", "Domain", "Hosting", "Frontend", "Backend", "Fullstack",
    "Python", "Java", "Golang", "Rust", "Swift", "Kotlin", "Node",
    # Misc (includes: Fortress)
    "Fortress", "Bastion", "Citadel", "Sentinel", "Warden", "Paladin",
    "Champion", "Legacy", "Heritage", "Sovereign", "Crown", "Kingdom",
    "Empire", "Republic", "Alliance", "Federation", "Coalition", "Dynasty",
    "Harmony", "Liberty", "Victory", "Triumph", "Glory", "Honor",
    "Crystal", "Diamond", "Emerald", "Ruby", "Sapphire", "Topaz",
    "Cobalt", "Titanium", "Carbon", "Silicon", "Platinum", "Uranium",
    "Helpdesk",
]

with open(os.path.join(ENGAGEMENT_DIR, "engagement_wordlist.txt"), "w") as f:
    for word in wordlist_words:
        f.write(word + "\n")


# ============================================================
# 8. Vault contents (encrypted entries inside ZIP)
# ============================================================

vault_staging = "/tmp/vault_staging"
os.makedirs(vault_staging, exist_ok=True)

# Vault manifest
vault_manifest = """\
MERIDIAN TECHNOLOGIES - CREDENTIAL VAULT
=========================================

This vault contains encrypted sensitive credentials used by automated
systems. Each entry is encrypted using OpenSSL AES-256-CBC with PBKDF2
key derivation (10000 iterations).

ENTRIES:

1. vault_gpg_passphrase.enc
   Purpose: Passphrase for classified_data.gpg decryption
   Encrypted with: svc_sql domain service account credential

2. vault_ssh_key.enc
   Purpose: SSH private key for backup server automation
   Encrypted with: dev_ops Linux service account credential
"""

with open(os.path.join(vault_staging, "vault_manifest.txt"), "w") as f:
    f.write(vault_manifest)

# GPG passphrase → encrypt with svc_sql password (Database2024!)
gpg_passphrase = "Qu4ntum_Flux!88"
with open("/tmp/gpg_pp.txt", "w") as f:
    f.write(gpg_passphrase)

subprocess.run([
    "openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "10000",
    "-pass", "pass:Database2024!",
    "-in", "/tmp/gpg_pp.txt",
    "-out", os.path.join(vault_staging, "vault_gpg_passphrase.enc"),
], check=True)

# Decoy: fake SSH key → encrypt with dev_ops password (Pipeline2024!)
fake_ssh = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHIAAAAGY\nmNyeXB0AAAAGAAAABDxIMSNpK0FAKE_KEY_DATA_HERE\n-----END OPENSSH PRIVATE KEY-----\n"
with open("/tmp/ssh_key.txt", "w") as f:
    f.write(fake_ssh)

subprocess.run([
    "openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "10000",
    "-pass", "pass:Pipeline2024!",
    "-in", "/tmp/ssh_key.txt",
    "-out", os.path.join(vault_staging, "vault_ssh_key.enc"),
], check=True)

# Create password-protected ZIP with admin.dc password (Control2024#)
subprocess.run([
    "zip", "-j", "-P", "Control2024#",
    os.path.join(ENGAGEMENT_DIR, "locked_archive.zip"),
    os.path.join(vault_staging, "vault_manifest.txt"),
    os.path.join(vault_staging, "vault_gpg_passphrase.enc"),
    os.path.join(vault_staging, "vault_ssh_key.enc"),
], check=True)


# ============================================================
# 9. GPG-encrypted classified file
# ============================================================

flag_content = "FLAG-7b2c9f4e8a1d3c5b6e0f2a4d8c1b3e5a\n"
with open("/tmp/classified_flag.txt", "w") as f:
    f.write(flag_content)

gpg_home = "/tmp/gpg_home"
os.makedirs(gpg_home, exist_ok=True)
os.chmod(gpg_home, 0o700)
os.environ["GNUPGHOME"] = gpg_home

subprocess.run([
    "gpg", "--batch", "--yes",
    "--passphrase", gpg_passphrase,
    "--pinentry-mode", "loopback",
    "--symmetric", "--cipher-algo", "AES256",
    "--output", os.path.join(ENGAGEMENT_DIR, "classified_data.gpg"),
    "/tmp/classified_flag.txt",
], check=True, env=os.environ)


# ============================================================
# 10. Cleanup temp files
# ============================================================

for f in ["/tmp/gpg_pp.txt", "/tmp/ssh_key.txt", "/tmp/classified_flag.txt"]:
    if os.path.exists(f):
        os.remove(f)
for d in [vault_staging, gpg_home]:
    subprocess.run(["rm", "-rf", d])

print("Engagement artifacts generated successfully.")
print(f"Files in {ENGAGEMENT_DIR}:")
for fname in sorted(os.listdir(ENGAGEMENT_DIR)):
    fpath = os.path.join(ENGAGEMENT_DIR, fname)
    print(f"  {fname} ({os.path.getsize(fpath)} bytes)")
