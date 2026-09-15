#!/usr/bin/env python3
"""
Generate post-compromise evidence artifacts for the breach assessment challenge.
Runs during Docker build (builder stage only) - not present in final image.
All cryptographic values are computed at build time for correctness.
"""
import os
import sys
import subprocess
import random
import shutil
import base64
import hashlib
import struct
import json

from Crypto.Cipher import AES
from Crypto.Hash import MD4

random.seed(42)

# ============================================================
# Passwords used in the credential chain
# ============================================================

SVC_BACKUP_PASS = "Fallback#2024"
GPP_PASS = "Gpp@Admin2024"
SVC_DBADMIN_PASS = "D0ma!nRuler#2024"   # Effective DA via ACL chain
DECOY_ADMIN_PASS = "DomainAdmin2024!"    # Disabled administrator (decoy)

DECOY_SVC_WEB_PASS = "Xq9mK7pLw2nR5vB8jF4hC0sY6tD3aZQ"
DECOY_SVC_MONITOR_PASS = "Zb1nM3xPq5wL7vR9jH2kF6sC8tD4aYP"

CLASSIFIED = (
    "CLASSIFIED: Project Nightfall - Bridge infrastructure deployment "
    "coordinates: 47.6062N 122.3321W. Authorization code: ALPHA-SEVEN-"
    "NINER-DELTA. Facility access PIN: 7429-ECHO-3851."
)


# ============================================================
# Cryptographic computation functions
# ============================================================

def compute_sha512_hash(password, salt):
    result = subprocess.run(
        ["openssl", "passwd", "-6", "-salt", salt, password],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def compute_ntlm_hash(password):
    h = MD4.new()
    h.update(password.encode("utf-16-le"))
    return h.hexdigest()


def compute_gpp_cpassword(password):
    ms_gpp_key = bytes.fromhex(
        "4e9906e8fcb66cc9faf49310620ffee8"
        "f496e806cc057990209b09a433b66c1b"
    )
    iv = b"\x00" * 16
    data = password.encode("utf-16-le")
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len]) * pad_len
    cipher = AES.new(ms_gpp_key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(data)
    return base64.b64encode(encrypted).decode()


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "w" if isinstance(content, str) else "wb"
    with open(path, mode) as f:
        f.write(content)


def encrypt_openssl(plaintext, password, outpath):
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()
    subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "10000",
         "-pass", "pass:" + password, "-out", outpath],
        input=plaintext, check=True
    )


def custom_vault_encrypt(plaintext_bytes, password, salt, nonce,
                          iterations=100000, key_len=32):
    """Encrypt using the InlaneFreight Secure Vault Tool v2.3 format."""
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=key_len
    )
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext_bytes)

    magic = b"IFVT"
    version = struct.pack(">H", 0x0203)
    salt_len_bytes = struct.pack(">H", len(salt))
    return magic + version + salt_len_bytes + salt + nonce + ciphertext + tag


# ============================================================
# Compute all cryptographic values at build time
# ============================================================

print("[+] Computing SHA-512 crypt hashes...")
SVC_BACKUP_HASH = compute_sha512_hash(SVC_BACKUP_PASS, "Xt4qM9kR7vLp")
SVC_WEB_HASH = compute_sha512_hash(DECOY_SVC_WEB_PASS, "Rj7KmW2xPq9Y")
SVC_MONITOR_HASH = compute_sha512_hash(DECOY_SVC_MONITOR_PASS, "Np3FhD8cLw5X")
print(f"[+] svc_backup hash: {SVC_BACKUP_HASH}")

print("[+] Computing NTLM hashes...")
NTLM = {
    "administrator": compute_ntlm_hash(DECOY_ADMIN_PASS),
    "krbtgt":        compute_ntlm_hash("KrbtgtR@ndomKey2024!"),
    "svc_dbadmin":   compute_ntlm_hash(SVC_DBADMIN_PASS),
    "svc_sql":       compute_ntlm_hash("SqlService!2024"),
    "svc_exchange":  compute_ntlm_hash("Ex4ch@ng3SvcV3ryL0ngP@ssw0rd!!2024xK"),
    "svc_backup":    compute_ntlm_hash(SVC_BACKUP_PASS),
    "svc_deploy":    compute_ntlm_hash(GPP_PASS),
    "jsmith":        compute_ntlm_hash("Winter2024!John"),
    "mjones":        compute_ntlm_hash("Summer2024$Mary"),
}
print(f"[+] svc_dbadmin NTLM: {NTLM['svc_dbadmin']}")
print(f"[+] administrator NTLM (decoy): {NTLM['administrator']}")

print("[+] Computing GPP cpassword...")
GPP_CPASSWORD = compute_gpp_cpassword(GPP_PASS)
print(f"[+] GPP cpassword: {GPP_CPASSWORD}")


# ============================================================
# Directory structure
# ============================================================

for d in [
    "/app/enterprise/dmz-web01",
    "/app/enterprise/internal-app01/Policies",
    "/app/enterprise/internal-app01/logs",
    "/app/enterprise/internal-app01/custom_vault",
    "/app/enterprise/dc01",
    "/app/results",
]:
    os.makedirs(d, exist_ok=True)


# ============================================================
# Stage 1: DMZ Web Server - Shadow file + wordlist
# ============================================================

write_file("/app/enterprise/dmz-web01/etc_shadow",
    "root:!:19900:0:99999:7:::\n"
    "daemon:*:19900:0:99999:7:::\n"
    "www-data:*:19900:0:99999:7:::\n"
    f"svc_web:{SVC_WEB_HASH}:19900:0:99999:7:::\n"
    f"svc_backup:{SVC_BACKUP_HASH}:19900:0:99999:7:::\n"
    f"svc_monitor:{SVC_MONITOR_HASH}:19900:0:99999:7:::\n"
    "mysql:!:19900:::::\n"
)

write_file("/app/enterprise/dmz-web01/etc_passwd",
    "root:x:0:0:root:/root:/bin/bash\n"
    "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
    "www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin\n"
    "svc_web:x:1001:1001:Web Service Account:/home/svc_web:/bin/bash\n"
    "svc_backup:x:1002:1002:Backup Service Account:/home/svc_backup:/bin/bash\n"
    "svc_monitor:x:1003:1003:Monitoring Service Account:/home/svc_monitor:/bin/bash\n"
    "mysql:x:27:27:MySQL Server:/var/lib/mysql:/bin/false\n"
)

# Generate wordlist with the password hidden among ~2500 entries
base_words = [
    "server", "network", "cloud", "system", "admin", "backup", "service",
    "monitor", "deploy", "config", "manage", "secure", "access", "control",
    "data", "storage", "cluster", "proxy", "gateway", "firewall", "router",
    "switch", "vpn", "ssl", "http", "ftp", "smtp", "ldap", "oracle",
    "mysql", "postgres", "redis", "mongo", "docker", "ansible", "jenkins",
    "spring", "summer", "autumn", "winter", "fallback", "primary", "delta",
    "alpha", "bravo", "charlie", "echo", "foxtrot", "gamma", "hotel",
    "india", "juliet", "kilo", "lima", "november", "oscar", "papa",
    "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
    "xray", "yankee", "zulu", "password", "secret", "master", "domain",
    "enterprise", "corporate", "global", "intern", "remote", "local",
]

suffixes = [
    "!", "#", "@", "$", "2023", "2024", "!2023", "!2024", "#2023",
    "#2024", "@2023", "@2024", "123", "456", "789", "!123", "#456",
    "2025", "!2025", "#2025",
]

words = set()
for w in base_words:
    for s in suffixes:
        words.add(w.capitalize() + s)
        words.add(w.upper() + s)

common = [
    "P@ssw0rd", "Passw0rd!", "Changeme1", "Welcome123", "Qwerty123!",
    "Admin@123", "Test1234!", "User2024#", "Letmein!", "Trustno1",
    "Password1!", "Iloveyou2024", "Monkey123!", "Dragon2024#",
    "Master2024!", "Shadow2024#", "Sunshine!", "Princess2024",
    "Football2024!", "Baseball#2024", "Shadow!", "Michael2024",
    "Backup2024", "FallBack2024", "FALLBACK#2024", "fallback#2024",
    "Fallback2024!", "Fallback@2024", "Fallback$2024",
]
words.update(common)
words.add(SVC_BACKUP_PASS)

wordlist = sorted(words)
random.shuffle(wordlist)
write_file("/app/enterprise/dmz-web01/wordlist.txt", "\n".join(wordlist) + "\n")

write_file("/app/enterprise/dmz-web01/access.log",
    '10.10.10.5 - - [15/Mar/2024:08:22:31 +0000] "GET / HTTP/1.1" 200 3421\n'
    '10.10.10.5 - - [15/Mar/2024:08:22:32 +0000] "GET /admin HTTP/1.1" 302 0\n'
    '10.10.10.5 - - [15/Mar/2024:08:22:33 +0000] "POST /admin/login HTTP/1.1" 200 1847\n'
    '10.10.10.12 - - [15/Mar/2024:09:15:01 +0000] "GET /api/status HTTP/1.1" 200 89\n'
    '10.10.10.12 - - [15/Mar/2024:09:15:44 +0000] "GET /api/backup/trigger HTTP/1.1" 403 42\n'
    '10.10.10.20 - svc_backup [15/Mar/2024:10:30:00 +0000] "POST /api/backup/trigger HTTP/1.1" 200 156\n'
    '10.10.10.20 - svc_backup [15/Mar/2024:10:30:05 +0000] "GET /api/backup/status HTTP/1.1" 200 94\n'
)

write_file("/app/enterprise/dmz-web01/nginx.conf",
    "server {\n"
    "    listen 80;\n"
    "    server_name dmz-web01.inlanefreight.local;\n"
    "\n"
    "    location / {\n"
    "        proxy_pass http://127.0.0.1:8080;\n"
    "    }\n"
    "\n"
    "    location /api/backup {\n"
    '        auth_basic "Backup API";\n'
    "        auth_basic_user_file /etc/nginx/.htpasswd;\n"
    "        proxy_pass http://127.0.0.1:8080;\n"
    "    }\n"
    "}\n"
)


# ============================================================
# Stage 2: Encrypted backup archive
# ============================================================

os.makedirs("/tmp/backup_content", exist_ok=True)

write_file("/tmp/backup_content/ssh_config",
    "# SSH Configuration for Internal Infrastructure\n"
    "# Last updated: 2024-03-10 by svc_backup\n"
    "\n"
    "Host internal-app01\n"
    "    HostName 10.20.30.15\n"
    "    User svc_deploy\n"
    "    IdentityFile ~/.ssh/id_rsa_deploy\n"
    "    Port 22\n"
    "    StrictHostKeyChecking no\n"
    "\n"
    "Host dc01\n"
    "    HostName 10.20.30.5\n"
    "    User svc_admin\n"
    "    Port 22\n"
    "    ProxyJump internal-app01\n"
    "\n"
    "Host db-cluster\n"
    "    HostName 10.20.30.50\n"
    "    User svc_sql\n"
    "    Port 22\n"
    "    ProxyJump internal-app01\n"
)

write_file("/tmp/backup_content/service_notes.txt",
    "=== Service Account Documentation ===\n"
    "Date: 2024-03-15\n"
    "Author: IT Operations Team\n"
    "\n"
    "Infrastructure Notes:\n"
    "- DMZ web servers use local authentication via /etc/shadow\n"
    "- Internal application servers manage credentials via Group Policy\n"
    "- Group Policy credentials are stored in standard XML format under\n"
    "  the Policies/ directory on each managed host\n"
    "- The domain controller NTDS.dit was extracted during the last\n"
    "  quarterly audit and stored locally for emergency recovery\n"
    "- Domain admin credentials should be rotated quarterly per policy\n"
    "\n"
    "IMPORTANT: The svc_deploy account password was last set via Group\n"
    "Policy Preferences (GPP). Check the Groups.xml file on internal-app01\n"
    "for the current cpassword value.\n"
    "\n"
    "NOTE: The IT Security team deployed a custom vault encryption tool\n"
    "on internal-app01 (see custom_vault/ directory). All sensitive files\n"
    "on dc01 are now encrypted using this tool instead of standard OpenSSL.\n"
    "The tool configuration is in vault_config.ini alongside the tool.\n"
    "\n"
    "WARNING: Several service accounts are using legacy password policies.\n"
    "Ensure compliance before the Q4 security audit.\n"
)

subprocess.run(
    ["tar", "czf", "/tmp/backup.tar.gz", "-C", "/tmp/backup_content", "."],
    check=True,
)
encrypt_openssl(
    open("/tmp/backup.tar.gz", "rb").read(),
    SVC_BACKUP_PASS,
    "/app/enterprise/dmz-web01/backup.enc",
)


# ============================================================
# Stage 3: GPP Groups.xml with cpassword
# ============================================================

write_file("/app/enterprise/internal-app01/Policies/Groups.xml",
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Groups clsid="{3125E937-EB16-4b4c-9934-544FC6D24D26}">\n'
    '  <User clsid="{DF5F1855-51E5-4d24-8B1A-D9BDE98BA1D1}"\n'
    '        name="svc_deploy"\n'
    '        image="2"\n'
    '        changed="2024-03-10 14:22:31"\n'
    '        uid="{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}">\n'
    '    <Properties action="U"\n'
    '                newName=""\n'
    '                fullName="Service Deployment Account"\n'
    '                description="Automated deployment service - internal-app01"\n'
    f'                cpassword="{GPP_CPASSWORD}"\n'
    '                changeLogon="0"\n'
    '                noChange="1"\n'
    '                neverExpires="1"\n'
    '                acctDisabled="0"\n'
    '                userName="INLANEFREIGHT\\svc_deploy"/>\n'
    '  </User>\n'
    '</Groups>\n'
)

write_file("/app/enterprise/internal-app01/logs/deploy.log",
    "2024-03-14 08:00:01 [INFO] Deployment started - build #4521\n"
    "2024-03-14 08:00:15 [INFO] Pulling artifacts from nexus.inlanefreight.local\n"
    "2024-03-14 08:02:33 [INFO] Deploying to app-pool-01\n"
    "2024-03-14 08:03:10 [WARN] Health check timeout on node app-pool-01-c\n"
    "2024-03-14 08:04:22 [INFO] Retry successful - all nodes healthy\n"
    "2024-03-14 08:04:23 [INFO] Deployment complete - build #4521\n"
    "2024-03-15 08:00:01 [INFO] Deployment started - build #4522\n"
    "2024-03-15 08:00:14 [INFO] Pulling artifacts from nexus.inlanefreight.local\n"
    "2024-03-15 08:01:45 [ERROR] Connection refused to nexus.inlanefreight.local:8443\n"
    "2024-03-15 08:02:00 [INFO] Retrying artifact pull...\n"
    "2024-03-15 08:02:30 [INFO] Pull successful on retry\n"
    "2024-03-15 08:04:00 [INFO] Deployment complete - build #4522\n"
)

write_file("/app/enterprise/internal-app01/app.config",
    "[database]\n"
    "host = db-cluster.inlanefreight.local\n"
    "port = 5432\n"
    "name = appdb\n"
    "ssl_mode = require\n"
    "\n"
    "[auth]\n"
    "provider = ldap\n"
    "ldap_server = dc01.inlanefreight.local\n"
    "base_dn = DC=INLANEFREIGHT,DC=LOCAL\n"
    "bind_dn = CN=svc_deploy,OU=Service Accounts,DC=INLANEFREIGHT,DC=LOCAL\n"
    "\n"
    "[logging]\n"
    "level = INFO\n"
    "path = /var/log/app/\n"
    "rotate = daily\n"
    "keep = 30\n"
)


# ============================================================
# Custom Vault Tool (evidence the solver must reverse-engineer)
# ============================================================

ENCRYPT_TOOL_SOURCE = r'''#!/usr/bin/env python3
"""
InlaneFreight Secure Vault Tool v2.3
Internal credential storage encryption utility.

Uses PBKDF2-HMAC-SHA256 for key derivation and AES-256-GCM for
authenticated encryption. Parameters are loaded from a config file.

File format:
  [4B magic "IFVT"][2B version][2B salt_len][salt][nonce][ciphertext][16B GCM tag]

Contact: itsec@inlanefreight.local
Last updated: 2024-02-15
"""
import os
import sys
import struct
import hashlib
from configparser import ConfigParser

MAGIC = b"IFVT"
VERSION = 0x0203


def load_params(config_path):
    c = ConfigParser()
    c.read(config_path)
    return {
        "iterations": c.getint("kdf", "pbkdf2_iterations"),
        "hash_algo": c.get("kdf", "hash_algorithm"),
        "key_len": c.getint("cipher", "key_length"),
        "nonce_len": c.getint("cipher", "nonce_length"),
        "salt_len": c.getint("kdf", "salt_length"),
    }


def derive_key(password, salt, params):
    return hashlib.pbkdf2_hmac(
        params["hash_algo"],
        password.encode("utf-8"),
        salt,
        params["iterations"],
        dklen=params["key_len"],
    )


def encrypt_file(input_path, output_path, password, config_path):
    params = load_params(config_path)

    with open(input_path, "rb") as f:
        plaintext = f.read()

    salt = os.urandom(params["salt_len"])
    nonce = os.urandom(params["nonce_len"])
    key = derive_key(password, salt, params)

    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)

    with open(output_path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack(">H", VERSION))
        f.write(struct.pack(">H", len(salt)))
        f.write(salt)
        f.write(nonce)
        f.write(ciphertext)
        f.write(tag)

    print(f"[+] Encrypted {input_path} -> {output_path}")


def decrypt_file(input_path, output_path, password, config_path):
    params = load_params(config_path)

    with open(input_path, "rb") as f:
        data = f.read()

    if data[:4] != MAGIC:
        raise ValueError(f"Invalid file magic: {data[:4]}")

    ver = struct.unpack(">H", data[4:6])[0]
    if ver != VERSION:
        raise ValueError(f"Unsupported version: {ver:#06x}")

    salt_len = struct.unpack(">H", data[6:8])[0]
    salt = data[8:8 + salt_len]
    nonce = data[8 + salt_len:8 + salt_len + params["nonce_len"]]
    tag = data[-16:]
    ciphertext = data[8 + salt_len + params["nonce_len"]:-16]

    key = derive_key(password, salt, params)

    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)

    with open(output_path, "wb") as f:
        f.write(plaintext)

    print(f"[+] Decrypted {input_path} -> {output_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="InlaneFreight Secure Vault Tool v2.3")
    p.add_argument("action", choices=["encrypt", "decrypt"])
    p.add_argument("input", help="Input file")
    p.add_argument("output", help="Output file")
    p.add_argument("-p", "--password", required=True, help="Passphrase")
    p.add_argument("-c", "--config", default="/etc/ifvault/vault.ini",
                   help="Config file path (default: /etc/ifvault/vault.ini)")
    args = p.parse_args()

    if args.action == "encrypt":
        encrypt_file(args.input, args.output, args.password, args.config)
    else:
        decrypt_file(args.input, args.output, args.password, args.config)
'''

VAULT_CONFIG_INI = """[kdf]
pbkdf2_iterations = 100000
hash_algorithm = sha256
salt_length = 32

[cipher]
algorithm = AES-256-GCM
key_length = 32
nonce_length = 12
"""

write_file(
    "/app/enterprise/internal-app01/custom_vault/encrypt_tool.py",
    ENCRYPT_TOOL_SOURCE,
)
write_file(
    "/app/enterprise/internal-app01/custom_vault/vault_config.ini",
    VAULT_CONFIG_INI,
)


# ============================================================
# Stage 4: Encrypted credential vault (OpenSSL, keyed by GPP pass)
# ============================================================

vault_content = (
    "=== INLANEFREIGHT Domain Credential Vault ===\n"
    "Extracted: 2024-03-12\n"
    "Source: Internal credential management system (Thycotic Secret Server)\n"
    "Authorized by: IT Security Team for quarterly audit\n"
    "\n"
    "Service Accounts (NTLM hashes):\n"
    f"  INLANEFREIGHT\\svc_sql       : {NTLM['svc_sql']}\n"
    f"  INLANEFREIGHT\\svc_exchange  : {NTLM['svc_exchange']}\n"
    f"  INLANEFREIGHT\\svc_deploy    : {NTLM['svc_deploy']}\n"
    f"  INLANEFREIGHT\\svc_dbadmin   : {NTLM['svc_dbadmin']}\n"
    "\n"
    "Privileged Accounts (NTLM hashes):\n"
    f"  INLANEFREIGHT\\administrator : {NTLM['administrator']}\n"
    f"  INLANEFREIGHT\\krbtgt        : {NTLM['krbtgt']}\n"
    "\n"
    "NOTE: The built-in administrator account was disabled on 2024-03-13\n"
    "following breach detection. Multiple accounts have been locked as a\n"
    "containment measure. Refer to the AD security graph export on dc01\n"
    "(ad_graph.json) for current account status and ACL relationships.\n"
    "\n"
    "The classified document on dc01 was encrypted using the custom vault\n"
    "tool (see internal-app01/custom_vault/). The encryption passphrase\n"
    "is the cleartext password of the account that holds effective Domain\n"
    "Admin access through the surviving ACL delegation chain.\n"
)

encrypt_openssl(vault_content, GPP_PASS, "/app/enterprise/internal-app01/vault.enc")


# ============================================================
# Stage 5: AD Security Graph on DC01
# ============================================================

ad_graph = {
    "domain": "INLANEFREIGHT.LOCAL",
    "extracted_date": "2024-03-14",
    "description": "AD security graph export - post-incident ACL snapshot",
    "nodes": [
        {
            "id": "administrator",
            "type": "user",
            "enabled": False,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-500",
            "description": "Built-in administrator - disabled 2024-03-13 post-breach",
        },
        {
            "id": "krbtgt",
            "type": "user",
            "enabled": True,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-502",
            "description": "Kerberos TGT service account",
        },
        {
            "id": "svc_dbadmin",
            "type": "user",
            "enabled": True,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1107",
            "description": "Database administration service account",
        },
        {
            "id": "svc_sql",
            "type": "user",
            "enabled": False,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1103",
            "description": "SQL service - locked after excessive failed auth attempts",
        },
        {
            "id": "svc_exchange",
            "type": "user",
            "enabled": True,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1104",
            "description": "Exchange service account",
        },
        {
            "id": "svc_deploy",
            "type": "user",
            "enabled": True,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1106",
            "description": "Deployment service account",
        },
        {
            "id": "svc_backup",
            "type": "user",
            "enabled": True,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1105",
            "description": "Backup service account",
        },
        {
            "id": "jsmith",
            "type": "user",
            "enabled": True,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1201",
            "description": "John Smith - IT Support",
        },
        {
            "id": "mjones",
            "type": "user",
            "enabled": True,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1202",
            "description": "Mary Jones - IT Administration",
        },
        {
            "id": "db_admins",
            "type": "group",
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1301",
            "description": "Database Administrators",
        },
        {
            "id": "server_operators",
            "type": "group",
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-549",
            "description": "Server Operators - delegated server management",
        },
        {
            "id": "helpdesk",
            "type": "group",
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1302",
            "description": "Help Desk Tier 1",
        },
        {
            "id": "it_admins",
            "type": "group",
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1303",
            "description": "IT Administrators",
        },
        {
            "id": "exchange_admins",
            "type": "group",
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1304",
            "description": "Exchange Administrators",
        },
        {
            "id": "domain_admins",
            "type": "group",
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-512",
            "description": "Domain Admins",
        },
        {
            "id": "backup_operators",
            "type": "group",
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-551",
            "description": "Backup Operators",
        },
        {
            "id": "dc01",
            "type": "computer",
            "enabled": True,
            "sid": "S-1-5-21-3842939050-3880317879-2865463114-1000",
            "description": "Primary domain controller",
        },
    ],
    "edges": [
        {
            "from": "administrator",
            "to": "domain_admins",
            "relation": "MemberOf",
            "active": True,
            "note": "Built-in membership (account itself is disabled)",
        },
        {
            "from": "svc_dbadmin",
            "to": "db_admins",
            "relation": "MemberOf",
            "active": True,
        },
        {
            "from": "db_admins",
            "to": "server_operators",
            "relation": "GenericAll",
            "active": True,
            "note": "Delegated for database server management",
        },
        {
            "from": "server_operators",
            "to": "dc01",
            "relation": "GenericAll",
            "active": True,
            "note": "Server Operators have full control on DC01",
        },
        {
            "from": "dc01",
            "to": "domain_admins",
            "relation": "DCSync",
            "active": True,
            "note": "DS-Replication-Get-Changes + DS-Replication-Get-Changes-All granted to DC01$",
        },
        {
            "from": "svc_deploy",
            "to": "helpdesk",
            "relation": "MemberOf",
            "active": True,
        },
        {
            "from": "helpdesk",
            "to": "it_admins",
            "relation": "GenericAll",
            "active": False,
            "note": "Revoked 2024-02-28 - excessive privilege identified in security review",
        },
        {
            "from": "helpdesk",
            "to": "svc_sql",
            "relation": "ForceChangePassword",
            "active": True,
            "note": "Help Desk can reset svc_sql password (account currently locked)",
        },
        {
            "from": "svc_exchange",
            "to": "exchange_admins",
            "relation": "MemberOf",
            "active": True,
        },
        {
            "from": "exchange_admins",
            "to": "domain_admins",
            "relation": "WriteDACL",
            "active": False,
            "note": "Mitigated 2024-01-15 - CVE-2019-1040 remediation",
        },
        {
            "from": "exchange_admins",
            "to": "server_operators",
            "relation": "GenericWrite",
            "active": False,
            "note": "Removed during security hardening 2024-02-01",
        },
        {
            "from": "svc_sql",
            "to": "db_admins",
            "relation": "MemberOf",
            "active": True,
            "note": "Active membership (account itself is locked)",
        },
        {
            "from": "it_admins",
            "to": "server_operators",
            "relation": "WriteDACL",
            "active": False,
            "note": "Delegation suspended 2024-03-01 during incident investigation",
        },
        {
            "from": "it_admins",
            "to": "backup_operators",
            "relation": "AddMember",
            "active": False,
            "note": "Delegation removed 2024-02-15",
        },
        {
            "from": "backup_operators",
            "to": "dc01",
            "relation": "BackupPrivilege",
            "active": True,
            "note": "SE_BACKUP_NAME privilege on DC01",
        },
        {
            "from": "jsmith",
            "to": "helpdesk",
            "relation": "MemberOf",
            "active": True,
        },
        {
            "from": "mjones",
            "to": "it_admins",
            "relation": "MemberOf",
            "active": True,
        },
        {
            "from": "server_operators",
            "to": "domain_admins",
            "relation": "GenericAll",
            "active": False,
            "note": "Emergency lockdown 2024-03-01 - direct DA escalation path removed",
        },
    ],
}

write_file(
    "/app/enterprise/dc01/ad_graph.json",
    json.dumps(ad_graph, indent=2) + "\n",
)


# ============================================================
# Stage 6: NTDS extract on DC01
# ============================================================

LM_EMPTY = "aad3b435b51404eeaad3b435b51404ee"

write_file("/app/enterprise/dc01/ntds_extract.txt",
    "# NTDS.dit Hash Extract - INLANEFREIGHT.LOCAL\n"
    "# Extracted: 2024-03-12 via secretsdump.py (DCSync)\n"
    "# Format: domain\\user:RID:LM_HASH:NT_HASH:::\n"
    f"INLANEFREIGHT\\administrator:500:{LM_EMPTY}:{NTLM['administrator']}:::\n"
    f"INLANEFREIGHT\\Guest:501:{LM_EMPTY}:31d6cfe0d16ae931b73c59d7e0c089c0:::\n"
    f"INLANEFREIGHT\\krbtgt:502:{LM_EMPTY}:{NTLM['krbtgt']}:::\n"
    f"INLANEFREIGHT\\svc_sql:1103:{LM_EMPTY}:{NTLM['svc_sql']}:::\n"
    f"INLANEFREIGHT\\svc_exchange:1104:{LM_EMPTY}:{NTLM['svc_exchange']}:::\n"
    f"INLANEFREIGHT\\svc_backup:1105:{LM_EMPTY}:{NTLM['svc_backup']}:::\n"
    f"INLANEFREIGHT\\svc_deploy:1106:{LM_EMPTY}:{NTLM['svc_deploy']}:::\n"
    f"INLANEFREIGHT\\svc_dbadmin:1107:{LM_EMPTY}:{NTLM['svc_dbadmin']}:::\n"
    f"INLANEFREIGHT\\jsmith:1201:{LM_EMPTY}:{NTLM['jsmith']}:::\n"
    f"INLANEFREIGHT\\mjones:1202:{LM_EMPTY}:{NTLM['mjones']}:::\n"
)

# Generate NTLM cracking wordlist
ntlm_base = [
    "domain", "ruler", "admin", "enterprise", "corporate", "master",
    "control", "power", "super", "root", "system", "network", "server",
    "infra", "global", "manage", "direct", "chief", "prime", "elite",
    "apex", "crown", "reign", "throne", "sovereign", "command", "lead",
    "database", "vault", "secure", "trust", "guard", "shield", "fort",
]

ntlm_suffixes = [
    "!", "#", "@", "$", "2023", "2024", "2025", "!2024", "#2024",
    "@2024", "$2024", "123", "!123", "#123", "456", "789",
]

ntlm_special = [
    "D0mainAdmin!", "Dom@inRuler2024", "D0ma!nRuler2024",
    "DomainRuler#2024", "D0ma!nRuler#2024",
    "Domain!Ruler#2024", "D0main#Ruler2024", "Doma!nRuler#2024",
    "D0MA!NRULER#2024", "d0ma!nruler#2024",
    "DomainAdmin2024!", "DomainAdmin#2024", "Dom@inAdmin2024",
    "P@ssw0rd", "Passw0rd!", "Welcome1!", "Changeme1!",
    "Admin@2024", "Enterprise!2024", "Corporate#2024",
    "SqlService!2024", "Exchange$Svc99", "Winter2024!",
    "P@ssw0rd2024", "Qwerty!789", "KrbtgtR@ndom!",
    "Gpp@Admin2024", "Fallback#2024",
    "Winter2024!John", "Summer2024$Mary",
    "DbAdmin2024!", "Database#2024", "Db@dmin!2024",
]

ntlm_words = set()
for w in ntlm_base:
    for s in ntlm_suffixes:
        ntlm_words.add(w.capitalize() + s)
        ntlm_words.add(w.upper() + s)
        l33t = w.replace("o", "0").replace("a", "@").replace("i", "!")
        ntlm_words.add(l33t.capitalize() + s)

ntlm_words.update(ntlm_special)

ntlm_wordlist = sorted(ntlm_words)
random.shuffle(ntlm_wordlist)
write_file(
    "/app/enterprise/dc01/cracking_wordlist.txt",
    "\n".join(ntlm_wordlist) + "\n",
)

write_file("/app/enterprise/dc01/audit_notes.txt",
    "=== Post-Incident Security Assessment - 2024-03-14 ===\n"
    "Auditor: External Red Team / Incident Response Team\n"
    "\n"
    "Incident Timeline:\n"
    "  2024-03-12 - Breach detected, NTDS.dit extracted for analysis\n"
    "  2024-03-13 - Built-in administrator account DISABLED\n"
    "  2024-03-13 - svc_sql account LOCKED (excessive failed auth)\n"
    "  2024-03-14 - AD security graph exported for ACL review\n"
    "\n"
    "Post-Incident Hardening Actions:\n"
    "  1. Disabled built-in administrator account\n"
    "  2. Locked svc_sql pending investigation\n"
    "  3. Revoked helpdesk -> it_admins GenericAll delegation\n"
    "  4. Removed exchange_admins -> server_operators GenericWrite\n"
    "  5. Removed exchange_admins -> domain_admins WriteDACL (CVE-2019-1040)\n"
    "  6. Suspended it_admins -> server_operators WriteDACL\n"
    "  7. Removed server_operators -> domain_admins GenericAll\n"
    "\n"
    "CRITICAL FINDING: Despite hardening, at least one indirect privilege\n"
    "escalation path to Domain Admin may still exist through surviving ACL\n"
    "delegations. The security graph must be analyzed to identify and\n"
    "remediate any remaining attack paths.\n"
    "\n"
    "Classified documents on DC01 are encrypted using the custom vault tool\n"
    "deployed on internal-app01. The encryption passphrase is the cleartext\n"
    "password of the account with effective DA access.\n"
    "\n"
    "Remediation deadline: 2024-04-30\n"
)


# ============================================================
# Stage 7: Encrypted classified document (custom vault format)
# ============================================================

# Use deterministic salt and nonce for reproducible builds
classified_salt = hashlib.sha256(b"inlanefreight_classified_2024_salt").digest()
classified_nonce = hashlib.sha256(b"inlanefreight_classified_2024_nonce").digest()[:12]

encrypted_classified = custom_vault_encrypt(
    CLASSIFIED.encode("utf-8"),
    SVC_DBADMIN_PASS,
    classified_salt,
    classified_nonce,
)
write_file("/app/enterprise/dc01/classified.enc", encrypted_classified)


# ============================================================
# README for context
# ============================================================

write_file("/app/enterprise/README.txt",
    "=== Penetration Test Evidence Collection ===\n"
    "Engagement: INLANEFREIGHT Corp - Post-Breach Assessment\n"
    "Date: 2024-03-15\n"
    "Classification: CONFIDENTIAL\n"
    "\n"
    "Evidence collected from three hosts spanning multiple network segments.\n"
    "Post-incident hardening has disabled or locked several accounts and\n"
    "revoked multiple ACL delegations. However, residual attack paths may\n"
    "remain.\n"
    "\n"
    "1. dmz-web01 (10.10.10.20) - DMZ Web Server\n"
    "   - Local credential stores (passwd/shadow)\n"
    "   - Encrypted backup archive\n"
    "   - Web server logs and configuration\n"
    "\n"
    "2. internal-app01 (10.20.30.15) - Internal Application Server\n"
    "   - Group Policy artifacts\n"
    "   - Custom vault encryption tool + config\n"
    "   - Encrypted credential vault\n"
    "   - Application configuration and logs\n"
    "\n"
    "3. dc01 (10.20.30.5) - Domain Controller\n"
    "   - NTDS.dit hash extract (via DCSync)\n"
    "   - AD security graph export (post-hardening ACL snapshot)\n"
    "   - Encrypted classified document (custom vault format)\n"
    "   - Security audit notes\n"
    "\n"
    "Objective: Identify the account with effective Domain Admin access\n"
    "through surviving ACL delegations, recover its cleartext password,\n"
    "and decrypt the classified intelligence document on dc01.\n"
)


# ============================================================
# Cleanup temp files
# ============================================================

shutil.rmtree("/tmp/backup_content", ignore_errors=True)
for f in ["/tmp/backup.tar.gz"]:
    try:
        os.remove(f)
    except OSError:
        pass

print("[+] Environment setup complete.")
print(f"[+] Wordlist entries (shadow): {len(wordlist)}")
print(f"[+] Wordlist entries (NTLM): {len(ntlm_wordlist)}")
print(f"[+] Verified svc_dbadmin NTLM hash: {NTLM['svc_dbadmin']}")
print(f"[+] Verified decoy administrator NTLM hash: {NTLM['administrator']}")

# ============================================================
# Verification: ensure ALL expected files exist
# ============================================================

expected_files = [
    "/app/enterprise/dmz-web01/etc_shadow",
    "/app/enterprise/dmz-web01/etc_passwd",
    "/app/enterprise/dmz-web01/wordlist.txt",
    "/app/enterprise/dmz-web01/backup.enc",
    "/app/enterprise/dmz-web01/access.log",
    "/app/enterprise/dmz-web01/nginx.conf",
    "/app/enterprise/internal-app01/Policies/Groups.xml",
    "/app/enterprise/internal-app01/custom_vault/encrypt_tool.py",
    "/app/enterprise/internal-app01/custom_vault/vault_config.ini",
    "/app/enterprise/internal-app01/vault.enc",
    "/app/enterprise/internal-app01/app.config",
    "/app/enterprise/dc01/ad_graph.json",
    "/app/enterprise/dc01/ntds_extract.txt",
    "/app/enterprise/dc01/cracking_wordlist.txt",
    "/app/enterprise/dc01/classified.enc",
    "/app/enterprise/dc01/audit_notes.txt",
    "/app/enterprise/README.txt",
]

print("\n[*] Verifying all expected files...")
all_ok = True
for f in expected_files:
    if not os.path.exists(f):
        print(f"[FATAL] Missing expected file: {f}")
        all_ok = False
    else:
        print(f"[OK] {f} ({os.path.getsize(f)} bytes)")

if not all_ok:
    print("[FATAL] Some files are missing! Aborting.")
    sys.exit(1)

print("\n[+] All files verified successfully.")
