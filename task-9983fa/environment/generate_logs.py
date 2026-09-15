#!/usr/bin/env python3
"""Generate Nexus API Gateway syslog-formatted logs with embedded attack patterns."""
import random
from datetime import datetime, timedelta

random.seed(42)

base_time = datetime(2024, 6, 10, 9, 0, 0)
logs = []

NORMAL_USERS = [
    ("10.0.1.10", "alice@acme.io"),
    ("10.0.1.11", "bob@acme.io"),
    ("10.0.1.12", "charlie@acme.io"),
    ("10.0.2.20", "diana@acme.io"),
    ("10.0.2.21", "eve@acme.io"),
]

API_PATHS = [
    "/api/v2/users", "/api/v2/orders", "/api/v2/products",
    "/api/v2/inventory", "/api/v2/reports", "/api/v2/config",
    "/api/v2/health", "/api/v2/metrics",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "python-requests/2.31.0",
    "curl/8.4.0",
]


def fmt(t):
    return t.strftime("%b %d %H:%M:%S")


def sid():
    return f"{random.randint(0x1000,0xffff):04x}{random.randint(0x1000,0xffff):04x}"


def auth_log(t, ip, user, result, reason="none"):
    mfa = "totp" if result == "success" else "none"
    return (
        f"{fmt(t)} gw-prod-01 nexus-auth[4521]: "
        f"src_ip={ip} user={user} result={result} "
        f"reason={reason} mfa={mfa} sid={sid()}"
    )


def api_log(t, ip, method, path, status, ua):
    byt = random.randint(200, 50000) if status == 200 else random.randint(50, 200)
    dur = random.randint(5, 500)
    return (
        f'{fmt(t)} gw-prod-01 nexus-api[4522]: '
        f'src_ip={ip} method={method} path={path} status={status} '
        f'ua="{ua}" bytes={byt} duration_ms={dur} sid={sid()}'
    )


# --- Phase 1: Normal traffic 09:00-09:04 ---
for i in range(25):
    t = base_time + timedelta(seconds=random.randint(0, 240))
    ip, user = random.choice(NORMAL_USERS)
    if random.random() < 0.25:
        logs.append((t, auth_log(t, ip, user, "success")))
    else:
        logs.append((t, api_log(t, ip, random.choice(["GET", "POST"]),
                                random.choice(API_PATHS), 200,
                                random.choice(USER_AGENTS))))

# --- ATTACK 1: Brute force from 203.0.113.42 ---
# 20 failed auth attempts on same user within ~80s starting at 09:05
for i in range(20):
    t = base_time + timedelta(minutes=5, seconds=i * 4 + random.randint(0, 2))
    logs.append((t, auth_log(t, "203.0.113.42", "admin@acme.io",
                             "failure", "invalid_password")))

# --- Phase 2: Normal traffic 09:06-09:09 ---
for i in range(20):
    t = base_time + timedelta(minutes=6, seconds=random.randint(0, 180))
    ip, user = random.choice(NORMAL_USERS)
    logs.append((t, api_log(t, ip, "GET", random.choice(API_PATHS), 200,
                            random.choice(USER_AGENTS))))

# --- ATTACK 2: Credential stuffing from 198.51.100.17 ---
# 15 different usernames failing within ~45s starting at 09:10
stuffing_users = [
    "john@acme.io", "jane@acme.io", "mike@acme.io", "sarah@acme.io",
    "tom@acme.io", "lisa@acme.io", "david@acme.io", "emma@acme.io",
    "james@acme.io", "olivia@acme.io", "robert@acme.io", "sophia@acme.io",
    "william@acme.io", "ava@acme.io", "richard@acme.io",
]
for i, user in enumerate(stuffing_users):
    t = base_time + timedelta(minutes=10, seconds=i * 3 + random.randint(0, 1))
    logs.append((t, auth_log(t, "198.51.100.17", user,
                             "failure", "invalid_password")))

# --- Phase 3: Normal traffic 09:11-09:14 ---
for i in range(20):
    t = base_time + timedelta(minutes=11, seconds=random.randint(0, 180))
    ip, user = random.choice(NORMAL_USERS)
    logs.append((t, api_log(t, ip, "GET", random.choice(API_PATHS), 200,
                            random.choice(USER_AGENTS))))

# --- ATTACK 3: API scanning from 192.0.2.99 ---
# 40 requests yielding 403/404 within ~60s starting at 09:15
scan_paths = [
    "/admin", "/wp-admin", "/phpmyadmin", "/.env", "/config.json",
    "/api/v1/debug", "/actuator", "/server-status", "/.git/config",
    "/backup.sql", "/dump.sql", "/api/v2/internal/keys",
    "/api/v2/admin/users", "/api/v2/admin/config", "/.htaccess",
    "/api/v2/debug/vars", "/trace", "/api/v2/internal/tokens",
    "/api/v1/admin", "/console", "/shell", "/cmd", "/exec",
    "/swagger.json", "/graphql", "/introspect",
    "/login.php", "/admin.php", "/test.php", "/info.php",
    "/api/v2/users/1/password", "/api/v2/users/1/token",
    "/robots.txt", "/sitemap.xml", "/crossdomain.xml",
    "/api/v2/internal/metrics", "/api/v2/internal/debug",
    "/wp-login.php", "/xmlrpc.php", "/api/v2/files/etc/passwd",
]
for i in range(40):
    t = base_time + timedelta(minutes=15, seconds=i + random.randint(0, 1))
    status = random.choice([403, 403, 404, 404, 403])
    path = scan_paths[i % len(scan_paths)]
    logs.append((t, api_log(t, "192.0.2.99", "GET", path, status,
                            "Mozilla/5.0 (compatible; Scanner/1.0)")))

# --- Phase 4: Final normal traffic 09:16-09:18 ---
for i in range(15):
    t = base_time + timedelta(minutes=16, seconds=random.randint(0, 120))
    ip, user = random.choice(NORMAL_USERS)
    logs.append((t, api_log(t, ip, "GET", random.choice(API_PATHS), 200,
                            random.choice(USER_AGENTS))))

# Sort by time and output
logs.sort(key=lambda x: x[0])
for _, line in logs:
    print(line)
