#!/usr/bin/env python3
"""Generate synthesized forensic log data for incident analysis challenge."""
import random
import hashlib
import base64
import os
import subprocess
from datetime import datetime, timedelta
from urllib.parse import quote

random.seed(42)

LOG_DIR = "/app/logs"
os.makedirs(LOG_DIR, exist_ok=True)

# =================== GROUND TRUTH ===================
ATTACKER_IP = "198.51.100.73"
CONTRACTOR_IP = "203.0.113.42"
SERVER_IP = "10.0.1.50"
ADMIN_IPS = ["10.0.1.5", "10.0.1.12", "10.0.1.30"]
HOSTNAME = "webserver"
COMPROMISED_ACCOUNT = "deploy"

BF_START = datetime(2024, 3, 15, 2, 14, 7)
BF_SUCCESS = datetime(2024, 3, 15, 2, 47, 33)
WS_FIRST = datetime(2024, 3, 15, 3, 2, 15)
DNS_START = datetime(2024, 3, 15, 3, 14, 30)

WEBSHELL_PATH = "/uploads/.sys_cache.php"
C2_DOMAIN = "cdn-telemetry.analytics-pool.net"
EXFIL_FILE = "/etc/shadow"

AES_KEY = hashlib.sha256(b"forensic-challenge-key-2024").digest()
IV = hashlib.md5(b"forensic-challenge-iv").digest()

EXFIL_PLAINTEXT = (
    "root:$6$xK9Zp3mL$4jmPwRqLhVbN3yF8dGtUoE2sAiWcX7kBnMvHfJgDqRlYpCzT1wOaS0uI6eKx:19431:0:99999:7:::\n"
    "daemon:*:19431:0:99999:7:::\n"
    "deploy:$6$mN3RwQ7L$7hFkLpVtY9xBjC5eQsUaI0wDgXrMnZ8oKcHlJfAyEdT4bGvF2iRuWzXsNpMq:19431:0:99999:7:::\n"
    "postgres:$6$pQ7LdK4R$2bGwKxNrF4cAjH9eYtV0sI3uMzXoJlDqWfBnCg5mRyTvE8hPaS6iUoLwZxNd:19431:0:99999:7:::\n"
    "admin:$6$tR4KvJ8N$8nFyJxLqP3bGhW5dMeUoA1sIcXkZrV9wDlHfBjCgEyTmQa6iS2uRpOvLxWzF:19431:0:99999:7:::"
)

WS_COMMANDS = [
    "id", "uname -a", "cat /etc/passwd", "ls -la /var/www/html/",
    "cat /etc/shadow", "netstat -tlnp",
    "find / -writable -type f 2>/dev/null | head",
    "cat /var/lib/app/db.conf",
]
WS_TIMES = [
    WS_FIRST,
    WS_FIRST + timedelta(seconds=33),
    WS_FIRST + timedelta(seconds=67),
    WS_FIRST + timedelta(seconds=106),
    WS_FIRST + timedelta(seconds=182),
    WS_FIRST + timedelta(seconds=258),
    WS_FIRST + timedelta(seconds=330),
    WS_FIRST + timedelta(seconds=407),
]
WS_SIZES = [52, 95, 1823, 445, 612, 380, 1205, 284]


# =================== HELPERS ===================
def syslog_ts(dt):
    return dt.strftime("%b %d %H:%M:%S")


def apache_ts(dt):
    return dt.strftime("%d/%b/%Y:%H:%M:%S +0000")


def dns_ts(dt):
    ms = random.randint(0, 999)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def random_external_ip():
    while True:
        a = random.randint(1, 223)
        b = random.randint(0, 255)
        c = random.randint(0, 255)
        d = random.randint(1, 254)
        ip = f"{a}.{b}.{c}.{d}"
        if not any(ip.startswith(p) for p in ("10.", "127.", "192.168.", "0.")):
            if not (a == 172 and 16 <= b <= 31):
                if ip not in (ATTACKER_IP, CONTRACTOR_IP):
                    return ip


def encrypt_data():
    pt_file = "/tmp/_gen_pt"
    ct_file = "/tmp/_gen_ct"
    with open(pt_file, "wb") as f:
        f.write(EXFIL_PLAINTEXT.encode("utf-8"))
    subprocess.run([
        "openssl", "enc", "-aes-256-cbc",
        "-K", AES_KEY.hex(), "-iv", IV.hex(),
        "-nosalt", "-in", pt_file, "-out", ct_file
    ], check=True)
    with open(ct_file, "rb") as f:
        ct = f.read()
    os.remove(pt_file)
    os.remove(ct_file)
    return ct


# =================== AUTH.LOG ===================
def gen_auth_log():
    events = []
    pid = [1000]

    def np():
        pid[0] += 1
        return pid[0]

    base = datetime(2024, 3, 14, 0, 0, 0)

    # Cron sessions every 15 minutes for 3 days
    for i in range(192):
        t = base + timedelta(minutes=15 * i)
        p = np()
        events.append((t, f"CRON[{p}]: pam_unix(cron:session): session opened for user root(uid=0) by root(uid=0)"))
        events.append((t + timedelta(seconds=random.randint(1, 3)),
                        f"CRON[{p}]: pam_unix(cron:session): session closed for user root"))

    # Systemd / kernel noise
    for i in range(600):
        t = base + timedelta(seconds=random.randint(0, 259200))
        templates = [
            "systemd[1]: Started Session {} of user root.",
            "systemd-logind[380]: New session {} of user root.",
            "systemd-logind[380]: Removed session {}.",
            "systemd[1]: session-{}.scope: Deactivated successfully.",
        ]
        msg = random.choice(templates).format(random.randint(1, 9999))
        events.append((t, msg))

    # Legitimate admin SSH sessions (publickey auth)
    admin_times = [
        (datetime(2024, 3, 14, 8, 30, 15), "10.0.1.5", "admin", 900),
        (datetime(2024, 3, 14, 10, 15, 42), "10.0.1.12", "root", 1800),
        (datetime(2024, 3, 14, 14, 22, 8), "10.0.1.30", "deploy", 600),
        (datetime(2024, 3, 14, 16, 0, 0), "10.0.1.5", "admin", 1200),
        (datetime(2024, 3, 14, 21, 45, 30), "10.0.1.12", "root", 300),
        (datetime(2024, 3, 15, 8, 0, 5), "10.0.1.12", "root", 7200),
        (datetime(2024, 3, 15, 9, 15, 22), "10.0.1.30", "deploy", 1200),
        (datetime(2024, 3, 15, 11, 30, 0), "10.0.1.5", "admin", 600),
        (datetime(2024, 3, 15, 14, 45, 10), "10.0.1.12", "root", 3600),
        (datetime(2024, 3, 15, 18, 20, 0), "10.0.1.30", "deploy", 900),
        (datetime(2024, 3, 16, 8, 10, 0), "10.0.1.5", "admin", 1800),
        (datetime(2024, 3, 16, 10, 0, 0), "10.0.1.30", "deploy", 600),
        (datetime(2024, 3, 16, 15, 30, 0), "10.0.1.12", "root", 1200),
    ]
    for t, ip, user, dur in admin_times:
        p = np()
        port = random.randint(40000, 65000)
        fp = ''.join(random.choices("abcdef0123456789", k=43))
        events.append((t, f"sshd[{p}]: Accepted publickey for {user} from {ip} port {port} ssh2: RSA SHA256:{fp}"))
        events.append((t + timedelta(seconds=1),
                        f"sshd[{p}]: pam_unix(sshd:session): session opened for user {user}(uid=0) by (uid=0)"))
        events.append((t + timedelta(seconds=dur),
                        f"sshd[{p}]: pam_unix(sshd:session): session closed for user {user}"))

    # Contractor SSH session (red herring - password auth, no prior failures)
    ct = datetime(2024, 3, 15, 1, 30, 22)
    p = np()
    port = random.randint(40000, 65000)
    events.append((ct, f"sshd[{p}]: Accepted password for contractor from {CONTRACTOR_IP} port {port} ssh2"))
    events.append((ct + timedelta(seconds=1),
                    f"sshd[{p}]: pam_unix(sshd:session): session opened for user contractor(uid=1002) by (uid=0)"))
    events.append((ct + timedelta(seconds=300),
                    f"sshd[{p}]: pam_unix(sshd:session): session closed for user contractor"))

    # Brute force from 80 random external IPs (all fail)
    bf_ips = [random_external_ip() for _ in range(80)]
    usernames = ["root", "admin", "deploy", "test", "user", "ubuntu",
                 "guest", "ftpuser", "postgres", "mysql", "www-data", "backup"]

    for ip in bf_ips:
        n = random.randint(20, 200)
        start = base + timedelta(seconds=random.randint(0, 259200))
        for j in range(n):
            t = start + timedelta(seconds=j * random.uniform(1, 5))
            p = np()
            user = random.choice(usernames)
            port = random.randint(32000, 65000)
            is_invalid = random.random() < 0.15
            if is_invalid:
                events.append((t, f"sshd[{p}]: Invalid user {user} from {ip} port {port} ssh2"))
            pfx = "invalid user " if is_invalid else ""
            events.append((t + timedelta(seconds=0.1),
                            f"sshd[{p}]: Failed password for {pfx}{user} from {ip} port {port} ssh2"))

    # THE ATTACKER brute force (500 failures then success)
    bf_dur = (BF_SUCCESS - BF_START).total_seconds() - 3
    attacker_usernames = ["root", "admin", "deploy", "ubuntu", "test", "user"]
    for j in range(500):
        base_offset = (j / 500) * bf_dur
        jitter = random.uniform(0, 0.9)
        t = BF_START + timedelta(seconds=base_offset + jitter)
        p = np()
        user = random.choice(attacker_usernames)
        port = random.randint(40000, 65000)
        events.append((t, f"sshd[{p}]: Failed password for {user} from {ATTACKER_IP} port {port} ssh2"))

    # Attacker success
    p = np()
    port = random.randint(40000, 65000)
    events.append((BF_SUCCESS,
                    f"sshd[{p}]: Accepted password for {COMPROMISED_ACCOUNT} from {ATTACKER_IP} port {port} ssh2"))
    events.append((BF_SUCCESS + timedelta(seconds=1),
                    f"sshd[{p}]: pam_unix(sshd:session): session opened for user {COMPROMISED_ACCOUNT}(uid=1001) by (uid=0)"))

    events.sort(key=lambda x: x[0])
    with open(os.path.join(LOG_DIR, "auth.log"), "w") as f:
        for dt, msg in events:
            f.write(f"{syslog_ts(dt)} {HOSTNAME} {msg}\n")
    print(f"auth.log: {len(events)} lines")


# =================== ACCESS.LOG ===================
def gen_access_log():
    events = []
    base = datetime(2024, 3, 14, 0, 0, 0)

    normal_paths = [
        "/", "/index.html", "/about", "/contact", "/products", "/services",
        "/api/v1/status", "/api/v1/health", "/api/v1/users", "/api/v1/products",
        "/static/css/main.css", "/static/js/app.js", "/static/js/vendor.js",
        "/images/logo.png", "/images/banner.jpg", "/favicon.ico", "/robots.txt",
        "/sitemap.xml", "/blog", "/blog/post-1", "/blog/post-2", "/blog/post-3",
        "/admin/login", "/admin/dashboard", "/docs", "/pricing",
    ]
    methods = ["GET"] * 9 + ["POST"]
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15",
    ]

    # Normal traffic from 200 IPs
    normal_ips = [random_external_ip() for _ in range(200)]
    for i in range(25000):
        t = base + timedelta(seconds=random.randint(0, 259200))
        ip = random.choice(normal_ips)
        method = random.choice(methods)
        path = random.choice(normal_paths)
        status = random.choices([200, 301, 304, 404, 500], weights=[70, 5, 10, 10, 5])[0]
        size = random.randint(200, 50000) if status == 200 else random.randint(0, 500)
        ua = random.choice(uas)
        events.append((t, f'{ip} - - [{apache_ts(t)}] "{method} {path} HTTP/1.1" {status} {size} "-" "{ua}"'))

    # Web scanning noise from 10 IPs
    scan_ips = [random_external_ip() for _ in range(10)]
    scan_paths = [
        "/../../etc/passwd", "/admin/config.php", "/wp-login.php", "/phpmyadmin/",
        "/.env", "/backup.zip", "/wp-admin/", "/xmlrpc.php",
        "/cgi-bin/test-cgi", "/.git/config", "/server-status",
        "/api/v1/users?id=1%20OR%201%3D1", "/shell.php", "/cmd.asp",
        "/.aws/credentials", "/debug/vars", "/actuator/env",
    ]
    for ip in scan_ips:
        n = random.randint(30, 120)
        t_start = base + timedelta(seconds=random.randint(0, 259200))
        for j in range(n):
            t = t_start + timedelta(seconds=j * random.uniform(0.5, 3))
            path = random.choice(scan_paths)
            events.append((t, f'{ip} - - [{apache_ts(t)}] "GET {path} HTTP/1.1" 404 0 "-" "Mozilla/5.0"'))

    # Contractor legitimate web access (red herring)
    for j in range(5):
        t = datetime(2024, 3, 15, 1, 31, 0) + timedelta(seconds=j * 30)
        events.append((t, f'{CONTRACTOR_IP} - - [{apache_ts(t)}] "GET /admin/dashboard HTTP/1.1" 200 4521 "-" "{uas[0]}"'))

    # Normal-looking requests from attacker IP (before web shell)
    attacker_ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    for j in range(15):
        t = datetime(2024, 3, 15, 2, 50, 0) + timedelta(seconds=j * random.randint(30, 90))
        path = random.choice(["/", "/about", "/products", "/api/v1/status"])
        events.append((t, f'{ATTACKER_IP} - - [{apache_ts(t)}] "GET {path} HTTP/1.1" 200 {random.randint(1000, 5000)} "-" "{attacker_ua}"'))

    # ATTACKER WEB SHELL ACCESS
    key_frags = [AES_KEY[i:i + 4].hex() for i in range(0, 32, 4)]
    for idx in range(len(WS_COMMANDS)):
        t = WS_TIMES[idx]
        cmd = WS_COMMANDS[idx]
        size = WS_SIZES[idx]
        b64cmd = quote(base64.b64encode(cmd.encode()).decode(), safe='')
        token = f"{idx:02x}{key_frags[idx]}"
        path = f"{WEBSHELL_PATH}?c={b64cmd}&t={token}"
        events.append((t, f'{ATTACKER_IP} - - [{apache_ts(t)}] "GET {path} HTTP/1.1" 200 {size} "-" "{attacker_ua}"'))

    events.sort(key=lambda x: x[0])
    with open(os.path.join(LOG_DIR, "access.log"), "w") as f:
        for _, line in events:
            f.write(line + "\n")
    print(f"access.log: {len(events)} lines")


# =================== DNS_QUERIES.LOG ===================
def gen_dns_log():
    events = []
    base = datetime(2024, 3, 14, 0, 0, 0)

    normal_domains = [
        "google.com", "www.google.com", "accounts.google.com",
        "facebook.com", "cdn.facebook.com", "amazon.com", "aws.amazon.com",
        "github.com", "api.github.com", "cloudflare.com",
        "stackoverflow.com", "cdn.jsdelivr.net", "fonts.googleapis.com",
        "ajax.googleapis.com", "analytics.google.com",
        "update.ubuntu.com", "archive.ubuntu.com", "security.ubuntu.com",
        "ntp.ubuntu.com", "time.google.com", "smtp.gmail.com", "imap.gmail.com",
        "pypi.org", "registry.npmjs.org", "rubygems.org",
    ]
    internal_ips = ["10.0.1.10", "10.0.1.20", "10.0.1.30",
                    "10.0.1.40", SERVER_IP, "10.0.1.60"]
    query_types = ["A", "AAAA", "A", "A", "A", "MX", "TXT"]

    # Normal DNS traffic
    for i in range(12000):
        t = base + timedelta(seconds=random.randint(0, 259200))
        client = random.choice(internal_ips)
        domain = random.choice(normal_domains)
        qtype = random.choice(query_types)
        events.append((t, f"{dns_ts(t)} query[{qtype}] {domain} from {client}"))

    # Legitimate analytics/CDN queries
    legit_analytics = [
        "telemetry.microsoft.com", "cdn-settings.segment.io",
        "analytics.amplitude.com", "cdn.optimizely.com",
        "tracking.mixpanel.com", "api.segment.io",
        "stats.g.doubleclick.net", "cdn-analytics.pinpoint.com",
    ]
    for i in range(800):
        t = base + timedelta(seconds=random.randint(0, 259200))
        client = random.choice(internal_ips)
        domain = random.choice(legit_analytics)
        events.append((t, f"{dns_ts(t)} query[A] {domain} from {client}"))

    # DNS EXFILTRATION
    ciphertext = encrypt_data()
    transmission = IV + ciphertext
    chunk_size = 30
    chunks = []
    for i in range(0, len(transmission), chunk_size):
        chunks.append(transmission[i:i + chunk_size])

    for seq, chunk in enumerate(chunks):
        t = DNS_START + timedelta(seconds=seq * random.uniform(2, 5))
        seq_hex = f"{seq:02x}"
        data_hex = chunk.hex()
        domain = f"{seq_hex}.{data_hex}.exfil.{C2_DOMAIN}"
        events.append((t, f"{dns_ts(t)} query[A] {domain} from {SERVER_IP}"))

    events.sort(key=lambda x: x[0])
    with open(os.path.join(LOG_DIR, "dns_queries.log"), "w") as f:
        for _, line in events:
            f.write(line + "\n")
    print(f"dns_queries.log: {len(events)} lines (exfil: {len(chunks)})")
    return len(chunks)


# =================== APP_AUDIT.LOG ===================
def gen_audit_log():
    events = []
    base = datetime(2024, 3, 14, 0, 0, 0)

    normal_users = ["www-data", "postgres", "admin", "deploy"]
    normal_actions = ["DB_QUERY", "FILE_READ", "CONFIG_LOAD",
                      "SESSION_START", "SESSION_END", "API_CALL"]
    normal_paths = ["/var/www/html/index.html", "/var/lib/app/app.db",
                    "/etc/app/config.yml", "/var/log/app/app.log",
                    "/tmp/cache/session_data", "/var/www/html/static/app.js"]

    for i in range(2500):
        t = base + timedelta(seconds=random.randint(0, 259200))
        user = random.choice(normal_users)
        action = random.choice(normal_actions)
        path = random.choice(normal_paths)
        result = random.choices(["SUCCESS", "DENIED"], weights=[95, 5])[0]
        events.append((t, f'{t.strftime("%Y-%m-%dT%H:%M:%S")} [AUDIT] user={user} action={action} path={path} result={result}'))

    # Attacker audit trail
    attacker_events = [
        (datetime(2024, 3, 15, 3, 5, 20), "deploy", "FILE_READ", "/etc/shadow", "SUCCESS"),
        (datetime(2024, 3, 15, 3, 5, 45), "deploy", "FILE_READ", "/etc/passwd", "SUCCESS"),
        (datetime(2024, 3, 15, 3, 6, 10), "deploy", "DB_QUERY", "SELECT * FROM pg_shadow", "SUCCESS"),
        (datetime(2024, 3, 15, 3, 8, 30), "deploy", "FILE_READ", "/var/lib/app/db.conf", "SUCCESS"),
        (datetime(2024, 3, 15, 3, 10, 0), "deploy", "PROCESS_EXEC", "/usr/bin/python3 /tmp/.exfil.py", "SUCCESS"),
        (datetime(2024, 3, 15, 3, 12, 0), "deploy", "NET_CONNECT", f"dns://{C2_DOMAIN}", "SUCCESS"),
    ]
    for t, user, action, path, result in attacker_events:
        events.append((t, f'{t.strftime("%Y-%m-%dT%H:%M:%S")} [AUDIT] user={user} action={action} path={path} result={result}'))

    events.sort(key=lambda x: x[0])
    with open(os.path.join(LOG_DIR, "app_audit.log"), "w") as f:
        for _, line in events:
            f.write(line + "\n")
    print(f"app_audit.log: {len(events)} lines")


# =================== MAIN ===================
if __name__ == "__main__":
    gen_auth_log()
    gen_access_log()
    num_exfil = gen_dns_log()
    gen_audit_log()

    sha256 = hashlib.sha256(EXFIL_PLAINTEXT.encode("utf-8")).hexdigest()
    print(f"\n=== Generation complete ===")
    print(f"  Exfil queries: {num_exfil}")
    print(f"  Exfil SHA256:  {sha256}")
