#!/usr/bin/env python3
"""Generate incident forensics artifacts for the adversarial forensics task.

This script runs during Docker build (builder stage) and creates all artifacts
in /app/incident/. It is NOT present in the final Docker image.

Generates both genuine attack artifacts and honeypot/decoy artifacts,
intentionally mixed together. The solver must discriminate between them.
"""

import sqlite3
import hashlib
import base64
import struct
import os
import subprocess
import random
import shutil

INCIDENT_DIR = "/app/incident"

# ══════════════════════════════════════════════════════════════════════════════
# CREDENTIALS
# ══════════════════════════════════════════════════════════════════════════════

# --- Genuine credentials (real attack path) ---
GENUINE_PCAP_USER = "operator"
GENUINE_PCAP_PASS = "Tr@ns1tK3y!"
GENUINE_PCAP_SRC_IP = "172.16.5.30"

GENUINE_DB_ACCOUNTS = [
    {"id": 1, "account_name": "svc_deploy",  "password": "D3pl0y#2024!",
     "salt": "x9k2m7p4", "service_type": "deployment", "host": "prod-web01.internal",
     "last_rotation": "2024-01-10", "active": 1},
    {"id": 2, "account_name": "svc_archive", "password": "V@ultKe3per!",
     "salt": "q3w8e1r5", "service_type": "backup", "host": "prod-web01.internal",
     "last_rotation": "2024-01-08", "active": 1},
    {"id": 3, "account_name": "svc_monitor", "password": "W@tchd0g#7",
     "salt": "t6y2u9i3", "service_type": "monitoring", "host": "prod-web01.internal",
     "last_rotation": "2024-01-12", "active": 1},
    {"id": 4, "account_name": "svc_backup",  "password": "B@ckupR0t8!",
     "salt": "a5s7d2f4", "service_type": "backup", "host": "prod-db01.internal",
     "last_rotation": "2024-01-05", "active": 1},
]

GENUINE_SHADOW_HOST = "prod-web01.internal"
GENUINE_SHADOW_USERS = {
    "root":     "Quar7zN0d3!",
    "webadmin": "Pr0dServ3r!",
    "dbadmin":  "D@t@Eng1ne!",
}

# --- Honeypot credentials (decoy path) ---
HONEYPOT_PCAP_USER = "recon"
HONEYPOT_PCAP_PASS = "Sc0ut1ng!"
HONEYPOT_PCAP_SRC_IP = "192.168.1.105"

HONEYPOT_DB_USERS = [
    {"id": 1, "username": "admin",           "email": "admin@acme-corp.local",
     "password": "Welcome2024",   "salt": "a1b2c3d4e5f6", "role": "administrator",
     "last_login": "2024-01-15 09:23:11", "active": 1},
    {"id": 2, "username": "jdoe",            "email": "jdoe@acme-corp.local",
     "password": "J0hnD0e!2023",  "salt": "f6e5d4c3b2a1", "role": "user",
     "last_login": "2024-01-14 14:05:33", "active": 1},
    {"id": 3, "username": "backup_operator", "email": "backup@acme-corp.local",
     "password": "ArchiveK3y#9",  "salt": "7a8b9c0d1e2f", "role": "service",
     "last_login": "2024-01-15 02:00:00", "active": 1},
    {"id": 4, "username": "svc_monitor",     "email": "monitor@acme-corp.local",
     "password": "S3rviceD@emon", "salt": "3f4e5d6c7b8a", "role": "service",
     "last_login": "2024-01-15 08:00:00", "active": 1},
]

HONEYPOT_SHADOW_HOST = "dmz-public01.internal"
HONEYPOT_SHADOW_USERS = {
    "root":     "Pumpk1nPatch",
    "webadmin": "LinuxR0cks",
    "sysadmin": "Netw0rkN1nja",
}

ZIP_PASSWORD = "V@ultKe3per!"

GENUINE_GPG_PASSPHRASE = f"{GENUINE_PCAP_PASS}:{GENUINE_SHADOW_USERS['root']}"
HONEYPOT_GPG_PASSPHRASE = f"{HONEYPOT_PCAP_PASS}:{HONEYPOT_SHADOW_USERS['root']}"

GENUINE_FLAG = "ACME-REDTEAM-FLAG{d4f82e1a-9b37-4c65-a801-7f2e3d5c9b16}"
HONEYPOT_FLAG = "ACME-REDTEAM-FLAG{00000000-0000-0000-0000-000000000000}"


def create_directories():
    os.makedirs(INCIDENT_DIR, exist_ok=True)


def create_pcap():
    """Create PCAP with two HTTP Basic Auth sessions: genuine and honeypot."""
    def build_packet(src_ip, dst_ip, sport, dport, payload_bytes,
                     src_mac=b'\x11\x22\x33\x44\x55\x66',
                     dst_mac=b'\xaa\xbb\xcc\xdd\xee\xff'):
        eth = struct.pack('!6s6sH', dst_mac, src_mac, 0x0800)
        ip_total = 20 + 20 + len(payload_bytes)
        ip = struct.pack('!BBHHHBBH4s4s',
            0x45, 0, ip_total,
            random.randint(0x1000, 0xFFFF), 0x4000,
            64, 6, 0,
            bytes(int(x) for x in src_ip.split('.')),
            bytes(int(x) for x in dst_ip.split('.')))
        tcp = struct.pack('!HHIIBBHHH',
            sport, dport,
            random.randint(1000, 99999), random.randint(1, 99999),
            0x50, 0x18, 65535, 0, 0)
        return eth + ip + tcp + payload_bytes

    random.seed(1337)
    server_ip = "10.10.14.20"
    client_mac_a = b'\x11\x22\x33\x44\x55\x66'
    client_mac_b = b'\xde\xad\xbe\xef\x01\x02'
    server_mac = b'\xaa\xbb\xcc\xdd\xee\xff'

    packets = []

    # --- Honeypot session: 192.168.1.105 -> :80, Basic Auth ---
    hp_cred = base64.b64encode(
        f"{HONEYPOT_PCAP_USER}:{HONEYPOT_PCAP_PASS}".encode()).decode()

    hp_req1 = (
        "GET /admin/panel HTTP/1.1\r\n"
        "Host: 10.10.14.20\r\n"
        "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:109.0)\r\n"
        "Accept: */*\r\n"
        "\r\n"
    ).encode()
    packets.append(build_packet(HONEYPOT_PCAP_SRC_IP, server_ip, 49152, 80,
                                hp_req1, client_mac_a, server_mac))

    hp_resp1 = (
        "HTTP/1.1 401 Unauthorized\r\n"
        "WWW-Authenticate: Basic realm=\"ACME Admin Panel\"\r\n"
        "Content-Type: text/html\r\n"
        "Content-Length: 47\r\n"
        "\r\n"
        "<html><body>Authentication required</body></html>"
    ).encode()
    packets.append(build_packet(server_ip, HONEYPOT_PCAP_SRC_IP, 80, 49152,
                                hp_resp1, server_mac, client_mac_a))

    hp_req2 = (
        f"GET /admin/panel/dashboard HTTP/1.1\r\n"
        f"Host: 10.10.14.20\r\n"
        f"Authorization: Basic {hp_cred}\r\n"
        f"User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:109.0)\r\n"
        f"Accept: text/html,application/xhtml+xml\r\n"
        f"\r\n"
    ).encode()
    packets.append(build_packet(HONEYPOT_PCAP_SRC_IP, server_ip, 49152, 80,
                                hp_req2, client_mac_a, server_mac))

    hp_resp2 = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html\r\n"
        "Content-Length: 82\r\n"
        "\r\n"
        "<html><head><title>Admin Panel</title></head>"
        "<body><h1>Dashboard</h1></body></html>"
    ).encode()
    packets.append(build_packet(server_ip, HONEYPOT_PCAP_SRC_IP, 80, 49152,
                                hp_resp2, server_mac, client_mac_a))

    # --- Noise: DNS query ---
    dns_payload = (b'\x00\x01\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00'
                   b'\x04acme\x04corp\x03com\x00\x00\x01\x00\x01')
    packets.append(build_packet("192.168.1.1", "8.8.8.8", 55555, 53,
                                dns_payload))

    # --- Genuine session: 172.16.5.30 -> :8443, Basic Auth ---
    gn_cred = base64.b64encode(
        f"{GENUINE_PCAP_USER}:{GENUINE_PCAP_PASS}".encode()).decode()

    gn_req1 = (
        f"POST /api/v2/service/auth HTTP/1.1\r\n"
        f"Host: 10.10.14.20:8443\r\n"
        f"Authorization: Basic {gn_cred}\r\n"
        f"User-Agent: python-requests/2.28.1\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: 2\r\n"
        f"\r\n"
        f"{{}}"
    ).encode()
    packets.append(build_packet(GENUINE_PCAP_SRC_IP, server_ip, 58320, 8443,
                                gn_req1, client_mac_b, server_mac))

    gn_resp1 = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: 45\r\n"
        "\r\n"
        '{"status":"authenticated","token":"svc-98a3f"}'
    ).encode()
    packets.append(build_packet(server_ip, GENUINE_PCAP_SRC_IP, 8443, 58320,
                                gn_resp1, server_mac, client_mac_b))

    # --- More noise: health check ---
    noise_req = (
        "GET /health HTTP/1.1\r\n"
        "Host: 10.10.14.20\r\n"
        "User-Agent: monitoring/1.0\r\n"
        "\r\n"
    ).encode()
    packets.append(build_packet("10.10.14.5", server_ip, 40000, 80,
                                noise_req))

    noise_resp = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: 15\r\n"
        "\r\n"
        '{"status":"ok"}'
    ).encode()
    packets.append(build_packet(server_ip, "10.10.14.5", 80, 40000,
                                noise_resp))

    # --- Noise: honeypot POST to login ---
    hp_login = (
        "POST /admin/panel/login HTTP/1.1\r\n"
        "Host: 10.10.14.20\r\n"
        "Content-Type: application/x-www-form-urlencoded\r\n"
        "Content-Length: 29\r\n"
        "\r\n"
        "username=admin&password=admin"
    ).encode()
    packets.append(build_packet(HONEYPOT_PCAP_SRC_IP, server_ip, 49153, 80,
                                hp_login, client_mac_a, server_mac))

    # Write PCAP
    pcap_path = os.path.join(INCIDENT_DIR, "capture.pcap")
    with open(pcap_path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        base_ts = 1705305600
        for i, pkt_data in enumerate(packets):
            f.write(struct.pack('<IIII',
                base_ts + i * 2,
                i * 123456 % 1000000,
                len(pkt_data),
                len(pkt_data)))
            f.write(pkt_data)


def create_database():
    """Create SQLite database with genuine and honeypot credential tables."""
    db_path = os.path.join(INCIDENT_DIR, "app_database.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Honeypot table: 'users' (obvious name, simple sha256(salt||password))
    c.execute('''CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        email TEXT,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        last_login TEXT,
        is_active INTEGER DEFAULT 1
    )''')
    for u in HONEYPOT_DB_USERS:
        pw_hash = hashlib.sha256(
            (u["salt"] + u["password"]).encode()).hexdigest()
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
                  (u["id"], u["username"], u["email"], pw_hash,
                   u["salt"], u["role"], u["last_login"], u["active"]))

    # Genuine table: 'service_accounts' (different hash: sha256(password||':'||salt))
    c.execute('''CREATE TABLE service_accounts (
        id INTEGER PRIMARY KEY,
        account_name TEXT NOT NULL UNIQUE,
        credential_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        service_type TEXT,
        host TEXT,
        last_rotation TEXT,
        active INTEGER DEFAULT 1
    )''')
    for a in GENUINE_DB_ACCOUNTS:
        pw_hash = hashlib.sha256(
            (a["password"] + ":" + a["salt"]).encode()).hexdigest()
        c.execute("INSERT INTO service_accounts VALUES (?,?,?,?,?,?,?,?)",
                  (a["id"], a["account_name"], pw_hash,
                   a["salt"], a["service_type"], a["host"],
                   a["last_rotation"], a["active"]))

    # Metadata table documenting table purposes and hash methods
    c.execute('''CREATE TABLE schema_metadata (
        table_name TEXT PRIMARY KEY,
        environment TEXT NOT NULL,
        created_date TEXT NOT NULL,
        hash_algorithm TEXT NOT NULL
    )''')
    c.execute("INSERT INTO schema_metadata VALUES (?, ?, ?, ?)",
              ("users", "staging-honeypot-v2", "2024-01-10",
               "sha256(salt||password)"))
    c.execute("INSERT INTO schema_metadata VALUES (?, ?, ?, ?)",
              ("service_accounts", "production-auth", "2024-01-12",
               "sha256(password||':'||salt)"))

    # Audit log (cross-referencing clue)
    c.execute('''CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        source_table TEXT,
        action TEXT NOT NULL,
        detail TEXT,
        src_ip TEXT
    )''')
    c.execute("INSERT INTO audit_log VALUES (1,'2024-01-15 02:00:01',"
              "'service_accounts','AUTH','svc_archive automated backup',"
              "'10.10.14.20')")
    c.execute("INSERT INTO audit_log VALUES (2,'2024-01-15 09:23:11',"
              "'users','AUTH','admin dashboard login','192.168.1.105')")
    c.execute("INSERT INTO audit_log VALUES (3,'2024-01-15 08:23:45',"
              "'service_accounts','AUTH','operator service auth',"
              "'172.16.5.30')")

    conn.commit()
    conn.close()


def create_shadow():
    """Create shadow file with entries from two hosts (genuine + honeypot)."""
    shadow_path = os.path.join(INCIDENT_DIR, "shadow_dump.txt")
    lines = []

    # Genuine host entries
    lines.append(f"# === Host: {GENUINE_SHADOW_HOST} ===")
    lines.append("# Extracted: 2024-01-15T08:30:00Z")
    for user, password in GENUINE_SHADOW_USERS.items():
        salt = hashlib.md5(
            (GENUINE_SHADOW_HOST + user).encode()).hexdigest()[:8]
        result = subprocess.run(
            ["openssl", "passwd", "-6", "-salt", salt, password],
            capture_output=True, text=True, check=True)
        h = result.stdout.strip()
        lines.append(f"{user}:{h}:19722:0:99999:7:::")

    lines.append("")

    # Honeypot host entries
    lines.append(f"# === Host: {HONEYPOT_SHADOW_HOST} ===")
    lines.append("# Extracted: 2024-01-15T09:15:00Z")
    for user, password in HONEYPOT_SHADOW_USERS.items():
        salt = hashlib.md5(
            (HONEYPOT_SHADOW_HOST + user).encode()).hexdigest()[:8]
        result = subprocess.run(
            ["openssl", "passwd", "-6", "-salt", salt, password],
            capture_output=True, text=True, check=True)
        h = result.stdout.strip()
        lines.append(f"{user}:{h}:19722:0:99999:7:::")

    with open(shadow_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def create_server_log():
    """Create server access log with honeypot markers (THPot tags)."""
    log_path = os.path.join(INCIDENT_DIR, "server_access.log")

    entries = [
        '2024-01-15T08:20:05.112Z src=10.10.14.5 method=GET path=/health '
        'status=200 ua="monitoring/1.0" bytes=15 tag=infra-healthcheck '
        'sid=h001',

        '2024-01-15T08:21:33.445Z src=192.168.1.105 method=GET '
        'path=/admin/panel status=401 ua="Mozilla/5.0 (X11; Linux x86_64; '
        'rv:109.0)" bytes=47 tag=THPot-f7a2 sid=s001',

        '2024-01-15T08:21:34.891Z src=192.168.1.105 method=GET '
        'path=/admin/panel/dashboard status=200 ua="Mozilla/5.0 (X11; '
        'Linux x86_64; rv:109.0)" bytes=82 tag=THPot-f7a2 sid=s001',

        '2024-01-15T08:22:01.203Z src=10.10.14.5 method=GET path=/health '
        'status=200 ua="monitoring/1.0" bytes=15 tag=infra-healthcheck '
        'sid=h002',

        '2024-01-15T08:23:45.667Z src=172.16.5.30 method=POST '
        'path=/api/v2/service/auth status=200 ua="python-requests/2.28.1" '
        'bytes=45 tag=prod-api sid=s002',

        '2024-01-15T08:24:12.334Z src=172.16.5.30 method=POST '
        'path=/api/v2/service/deploy status=201 ua="python-requests/2.28.1"'
        ' bytes=1203 tag=prod-api sid=s002',

        '2024-01-15T08:24:55.778Z src=192.168.1.105 method=POST '
        'path=/admin/panel/users status=200 ua="Mozilla/5.0 (X11; Linux '
        'x86_64; rv:109.0)" bytes=4521 tag=THPot-f7a2 sid=s001',

        '2024-01-15T08:25:10.112Z src=172.16.5.30 method=GET '
        'path=/api/v2/service/status status=200 ua="python-requests/2.28.1"'
        ' bytes=89 tag=prod-api sid=s002',

        '2024-01-15T08:26:00.556Z src=10.10.14.5 method=GET path=/health '
        'status=200 ua="monitoring/1.0" bytes=15 tag=infra-healthcheck '
        'sid=h003',

        '2024-01-15T08:27:33.223Z src=192.168.1.105 method=GET '
        'path=/admin/panel/export status=200 ua="Mozilla/5.0 (X11; Linux '
        'x86_64; rv:109.0)" bytes=15680 tag=THPot-f7a2 sid=s001',

        '2024-01-15T08:28:45.890Z src=172.16.5.30 method=POST '
        'path=/api/v2/service/deploy status=201 ua="python-requests/2.28.1"'
        ' bytes=2048 tag=prod-api sid=s002',

        '2024-01-15T08:30:00.001Z src=10.10.14.20 method=GET '
        'path=/api/v2/backup/archive status=200 ua="svc_archive/1.0" '
        'bytes=52428800 tag=prod-api sid=s003',

        '2024-01-15T08:31:15.445Z src=192.168.1.105 method=POST '
        'path=/admin/panel/settings status=200 ua="Mozilla/5.0 (X11; '
        'Linux x86_64; rv:109.0)" bytes=892 tag=THPot-f7a2 sid=s001',
    ]

    with open(log_path, 'w') as f:
        f.write('\n'.join(entries) + '\n')


def create_wordlist():
    """Custom recon wordlist with all target passwords among decoys."""
    targets = [
        "D3pl0y#2024!", "V@ultKe3per!", "W@tchd0g#7", "B@ckupR0t8!",
        "Quar7zN0d3!", "Pr0dServ3r!", "D@t@Eng1ne!",
        "Tr@ns1tK3y!",
        "Welcome2024", "J0hnD0e!2023", "ArchiveK3y#9", "S3rviceD@emon",
        "Pumpk1nPatch", "LinuxR0cks", "Netw0rkN1nja",
        "Sc0ut1ng!",
    ]

    decoys = [
        "password", "123456", "admin", "letmein", "welcome",
        "monkey", "dragon", "master", "qwerty", "login",
        "Password1", "Password123", "Admin123", "Welcome1", "Changeme1",
        "Summer2023", "Winter2023", "Spring2024", "Fall2023",
        "Company1!", "Corporate!", "Security1", "Passw0rd!", "P@ssword1",
        "Server2024", "Desktop2024", "Network2024", "Database1",
        "Backup2024", "Archive2024", "Storage2024", "Cloud2024",
        "Jenkins1!", "Docker2024", "Kubernetes!", "Ansible2024",
        "Linux2024!", "Windows2024", "Ubuntu2024", "MySQL2024",
        "PostgreSQL1", "Redis2024!", "AWS2024!!!", "Azure2024!!",
        "Cisco2024", "Juniper2024", "Fortinet24", "PaloAlto24",
        "Pentest24!", "BugBounty01", "RedTeam24!!", "BlueTeam24",
        "Exploit24!", "Payload24!!", "Shellcode01", "Backdoor24",
        "Incident24", "Response24!", "Forensics01", "Analysis24",
        "P@ssw0rd!!", "Tr0ub4dor&!", "C0rrectH0rse", "B@tteryStapl",
        "R00tAccess!", "Adm1nP@nel!", "S3cureL0g1n!", "M@sterKey01",
        "PumpkinSpice", "PumpkinLatte", "PumpkinPie22",
        "ArchiveKey10", "ArchiveFile!", "ArchiveDump!",
        "Tr@nsf3r!!!", "Tr@nsit1on!", "K3yMast3r!!",
        "V@ult2024!!", "V@ultDoor!!", "K3ep3r2024!",
        "Quar7z2024!", "N0d3Serv3r!", "Qu@rtzR0ck!",
        "D3pl0yM3nt!", "S3rv1c3Key!", "Pr0dAccess!",
        "W@tchT0wer!", "M0n1t0r1ng!", "B@ckupN0w!!",
    ]

    words = targets + decoys
    random.seed(42)
    random.shuffle(words)

    wl_path = os.path.join(INCIDENT_DIR, "recon_wordlist.txt")
    with open(wl_path, 'w') as f:
        f.write('\n'.join(words) + '\n')


def create_cipher_fragment():
    """Create XOR-encoded cipher fragment revealing genuine report identity."""
    plaintext = (
        "RED TEAM ASSESSMENT - CIPHER MEMO\n"
        "==================================\n"
        "Report identification:\n"
        "  GENUINE REPORT -> engagement_report_alpha.gpg\n"
        "  DECOY REPORT   -> engagement_report_beta.gpg\n"
        "\n"
        "The genuine report contains the valid proof flag.\n"
        "The decoy report contains a honeypot flag.\n"
    ).encode()

    # XOR key: first 16 bytes of SHA-256(genuine_pcap_password)
    key = hashlib.sha256(GENUINE_PCAP_PASS.encode()).digest()[:16]
    encrypted = bytes(
        plaintext[i] ^ key[i % len(key)] for i in range(len(plaintext)))

    frag_path = os.path.join(INCIDENT_DIR, "cipher_fragment.bin")
    with open(frag_path, 'wb') as f:
        f.write(encrypted)


def create_zip():
    """Create password-protected ZIP with engagement notes."""
    tmp_dir = os.path.join(INCIDENT_DIR, "_zip_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    notes = (
        "ACME Corp Red Team Exercise - Engagement Notes\n"
        "================================================\n\n"
        "Engagement: ACME-2024-RT-007\n"
        "Classification: CONFIDENTIAL\n\n"
        "1. This engagement involved both genuine attack operations and\n"
        "   interactions with the blue team's honeypot infrastructure.\n"
        "   All artifacts have been collected but are intentionally mixed.\n\n"
        "2. The cipher_fragment.bin file uses XOR encryption with a\n"
        "   16-byte key. The key is the first 16 bytes of the SHA-256\n"
        "   hash of the genuine network operator's password (extracted\n"
        "   from the traffic capture). The genuine session accessed the\n"
        "   production service API, NOT the honeypot admin panel.\n"
        "   Server access logs can help distinguish genuine sessions\n"
        "   from honeypot interactions.\n\n"
        "3. The final assessment report is GPG symmetrically encrypted.\n"
        "   The passphrase follows this format:\n\n"
        "       <operator_password>:<production_host_root_password>\n\n"
        "   Where:\n"
        "     operator_password       = from the genuine PCAP auth session\n"
        "     production_host_root_password = root's cracked password from\n"
        "       the production host shadow entries (not the honeypot host)\n\n"
        "4. Two encrypted reports exist. Use cipher_fragment.bin (after\n"
        "   decryption) to determine which report is genuine.\n\n"
        "--- END OF NOTES ---\n"
    )
    with open(os.path.join(tmp_dir, "engagement_notes.txt"), 'w') as f:
        f.write(notes)

    scan = (
        "Network Scan Results Summary\n"
        "============================\n"
        "Target: 10.10.14.0/24\n"
        "Date: 2024-01-15\n\n"
        "Host: 10.10.14.20 (acme-app01)\n"
        "  22/tcp    open  ssh        OpenSSH 8.9p1\n"
        "  80/tcp    open  http       Apache/2.4.52\n"
        "  443/tcp   open  https      Apache/2.4.52\n"
        "  8443/tcp  open  https-alt  Nginx/1.22\n\n"
        "Host: 10.10.14.30 (acme-dc01)\n"
        "  53/tcp    open  domain     ISC BIND 9.18.12\n"
        "  88/tcp    open  kerberos   Microsoft Windows Kerberos\n"
        "  389/tcp   open  ldap       Microsoft Windows AD LDAP\n"
        "  445/tcp   open  microsoft-ds\n"
    )
    with open(os.path.join(tmp_dir, "scan_results.txt"), 'w') as f:
        f.write(scan)

    zip_path = os.path.join(INCIDENT_DIR, "loot_archive.zip")
    subprocess.run([
        "zip", "-j", "-P", ZIP_PASSWORD, zip_path,
        os.path.join(tmp_dir, "engagement_notes.txt"),
        os.path.join(tmp_dir, "scan_results.txt"),
    ], check=True)

    shutil.rmtree(tmp_dir)


def create_gpg_reports():
    """Create two GPG-encrypted reports: genuine and decoy."""
    gnupg_home = "/tmp/_gnupg_setup"
    os.makedirs(gnupg_home, mode=0o700, exist_ok=True)
    env = dict(os.environ, GNUPGHOME=gnupg_home)

    genuine_report = (
        "ACME Corp Red Team Exercise - Final Assessment Report\n"
        "======================================================\n\n"
        "Engagement ID:  ACME-2024-RT-007\n"
        "Assessor:       Senior Red Team Operator\n"
        "Date:           January 15, 2024\n"
        "Classification: CONFIDENTIAL\n\n"
        "EXECUTIVE SUMMARY\n"
        "-----------------\n"
        "Critical vulnerabilities were identified across ACME Corp's\n"
        "production infrastructure. The red team achieved full system\n"
        "compromise through credential reuse and privilege escalation.\n\n"
        "ATTACK CHAIN\n"
        "------------\n"
        "1. Service API authentication via captured network credentials\n"
        "2. Database credential extraction and hash cracking\n"
        "3. Backup archive access using service account credentials\n"
        "4. Root-level privilege escalation via weak system password\n"
        "5. Full infrastructure compromise\n\n"
        "PROOF OF ASSESSMENT COMPLETION\n"
        "------------------------------\n"
        f"{GENUINE_FLAG}\n\n"
        "RECOMMENDATIONS\n"
        "---------------\n"
        "1. Enforce mutual TLS on all internal service APIs\n"
        "2. Rotate all service account credentials immediately\n"
        "3. Implement hardware security keys for privileged access\n"
        "4. Deploy network segmentation between production tiers\n"
        "5. Review and harden honeypot infrastructure isolation\n\n"
        "--- END OF REPORT ---\n"
    )

    decoy_report = (
        "ACME Corp Penetration Test - Assessment Report\n"
        "===============================================\n\n"
        "Engagement ID:  ACME-2024-PT-003\n"
        "Assessor:       Penetration Tester\n"
        "Date:           January 15, 2024\n"
        "Classification: CONFIDENTIAL\n\n"
        "EXECUTIVE SUMMARY\n"
        "-----------------\n"
        "Assessment of the ACME Corp admin panel infrastructure.\n"
        "Standard web application vulnerabilities were identified.\n\n"
        "PROOF OF COMPLETION\n"
        "-------------------\n"
        f"{HONEYPOT_FLAG}\n\n"
        "--- END OF REPORT ---\n"
    )

    for name, content, passphrase in [
        ("engagement_report_alpha.gpg", genuine_report,
         GENUINE_GPG_PASSPHRASE),
        ("engagement_report_beta.gpg", decoy_report,
         HONEYPOT_GPG_PASSPHRASE),
    ]:
        tmp_path = f"/tmp/_report_{name}.txt"
        with open(tmp_path, 'w') as f:
            f.write(content)
        out_path = os.path.join(INCIDENT_DIR, name)
        subprocess.run([
            "gpg", "--batch", "--yes",
            "--passphrase", passphrase,
            "--pinentry-mode", "loopback",
            "--symmetric", "--cipher-algo", "AES256",
            "--s2k-mode", "3", "--s2k-digest-algo", "SHA512",
            "--s2k-count", "65536",
            "-o", out_path, tmp_path,
        ], env=env, check=True)
        os.remove(tmp_path)

    shutil.rmtree(gnupg_home, ignore_errors=True)


def main():
    create_directories()
    create_pcap()
    print("[+] capture.pcap created")
    create_database()
    print("[+] app_database.db created")
    create_shadow()
    print("[+] shadow_dump.txt created")
    create_server_log()
    print("[+] server_access.log created")
    create_wordlist()
    print("[+] recon_wordlist.txt created")
    create_cipher_fragment()
    print("[+] cipher_fragment.bin created")
    create_zip()
    print("[+] loot_archive.zip created")
    create_gpg_reports()
    print("[+] engagement_report_alpha.gpg created")
    print("[+] engagement_report_beta.gpg created")
    print("[+] All incident artifacts generated successfully.")


if __name__ == "__main__":
    main()
