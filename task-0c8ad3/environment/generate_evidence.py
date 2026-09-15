#!/usr/bin/env python3
"""Generate forensic evidence data for multi-channel C2 protocol analysis task.

Creates realistic Zeek-format network logs with embedded C2 traffic
(DNS tunneling + HTTP POST data exfiltration + HTTP beaconing) mixed
into legitimate network activity.  Includes decoy suspicious DNS
patterns and an authorized red team DNS tunneling exercise that the
analyst must evaluate and correctly classify.
"""


import hashlib
import hmac
import base64
import json
import random
import os

random.seed(42)  # Deterministic generation

# === C2 Infrastructure ===
C2_DNS_DOMAIN = "cdn-telemetry.analytics-data.net"
C2_HTTP_DOMAIN = "api.webstats-collector.com"
C2_HTTP_IP = "198.51.100.23"
C2_DNS_IP = "198.51.100.47"
COMPROMISED_IP = "10.0.1.42"
DNS_SERVER_IP = "10.0.1.1"
CAMPAIGN_ID = "OP-THUNDERSTRIKE-2024"
BEACON_INTERVAL = 30
FIRST_CONTACT_EPOCH = 1709251200  # 2024-03-01 00:00:00 UTC
WINDOW_HOURS = 2

# === Decoy suspicious domains ===
DECOY_DNS_1 = "probe.netcheck-monitoring.io"   # Network monitoring tool
DECOY_DNS_2 = "resolve.dev-sandbox-testing.org"  # Developer testing DNS

# === Authorized Red Team Exercise ===
REDTEAM_DNS_DOMAIN = "tunnel.redteam-ops.net"
REDTEAM_DNS_IP = "198.51.100.55"
REDTEAM_IP = "10.0.1.35"
REDTEAM_CAMPAIGN = "RT-EXERCISE-Q1-2024"

# === Exfiltrated Data ===
EXFIL_DATA = """# Exfiltrated Configuration - Production Environment
# Last modified: 2024-02-28

[database]
primary_host = prod-db-primary.internal.corp
replica_host = prod-db-replica-01.internal.corp
port = 5432
database = customer_records
username = svc_reporting
password = kJ#9mPx$2vL!qR8n
ssl_mode = require
max_connections = 50

[redis]
host = cache-prod-01.internal.corp
port = 6379
password = r3d1s_pr0d_s3cr3t_2024!

[api_keys]
stripe_live = sk_live_7f3a9b2c4d5e6f1a8b9c0d1e2f3a4b5c
sendgrid = SG.abc123def456.xyz789
aws_access_key = AKIAIOSFODNN7EXAMPLE
aws_secret_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

[internal_services]
auth_service = http://auth-api.internal.corp:8080
payment_gateway = http://payments.internal.corp:9090
admin_panel_key = adm1n_p4n3l_m4st3r_k3y_2024""".strip()

# === Crypto ===
HMAC_MSG = b"c2-exfil-key"
STREAM_KEY = hmac.new(CAMPAIGN_ID.encode(), HMAC_MSG, hashlib.sha256).digest()[:16]

# === Data split ===
DATA_BYTES = EXFIL_DATA.encode()
SPLIT_POINT = len(DATA_BYTES) // 2
PART1 = DATA_BYTES[:SPLIT_POINT]   # DNS channel
PART2 = DATA_BYTES[SPLIT_POINT:]   # HTTP channel


def xor_encrypt(data, key, offset=0):
    return bytes(d ^ key[(offset + i) % len(key)] for i, d in enumerate(data))


def b32_encode(data):
    return base64.b32encode(data).decode().lower().rstrip("=")


# === Legitimate Traffic Pools ===
LEGIT_DOMAINS = [
    "www.google.com", "mail.google.com", "drive.google.com",
    "www.facebook.com", "api.facebook.com",
    "www.microsoft.com", "login.microsoftonline.com", "outlook.office365.com",
    "github.com", "api.github.com",
    "aws.amazon.com", "s3.amazonaws.com", "ec2.amazonaws.com",
    "cdn.cloudflare.com", "api.cloudflare.com",
    "www.linkedin.com", "slack-msgs.com", "slack.com",
    "zoom.us", "api.zoom.us",
    "updates.ubuntu.com", "security.ubuntu.com",
    "pypi.org", "files.pythonhosted.org",
    "registry.npmjs.org",
    "fonts.googleapis.com", "fonts.gstatic.com",
    "analytics.google.com", "api.stripe.com",
    "hooks.slack.com", "sentry.io",
    "o123456.ingest.sentry.io",
    "app.datadoghq.com", "newrelic.com",
    "grafana.internal.corp", "prometheus.internal.corp",
    "jenkins.internal.corp", "gitlab.internal.corp",
    "jira.internal.corp", "confluence.internal.corp",
]

RED_HERRING_DOMAINS = [
    "telemetry.vscode-unpkg.net",
    "dc.services.visualstudio.com",
    "update.code.visualstudio.com",
    "az764295.vo.msecnd.net",
    "cdn-patch.swtor.com",
    "stats.wp.com",
    "pixel.quantserve.com",
    "sb.scorecardresearch.com",
]

INTERNAL_IPS = [
    "10.0.1.10", "10.0.1.11", "10.0.1.12", "10.0.1.15",
    "10.0.1.20", "10.0.1.21", "10.0.1.25", "10.0.1.30",
    "10.0.1.35", "10.0.1.40", "10.0.1.42",
    "10.0.1.45", "10.0.1.50", "10.0.1.55", "10.0.1.60",
]

EXTERNAL_IPS = [
    "142.250.80.46", "142.250.80.100",
    "157.240.1.35", "157.240.1.36",
    "13.107.42.14", "52.96.110.30",
    "140.82.121.3", "140.82.121.4",
    "104.16.132.229", "104.16.133.229",
    "151.101.1.69", "151.101.65.69",
]


def generate_zeek_uid():
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return "C" + "".join(random.choice(chars) for _ in range(17))


# -----------------------------------------------------------------
# DNS exfiltration queries (real C2)
# -----------------------------------------------------------------
def generate_exfil_queries():
    """Generate the DNS exfiltration query list (part 1 only)."""
    encrypted = xor_encrypt(PART1, STREAM_KEY, offset=0)
    encoded = b32_encode(encrypted)

    chunk_size = 50
    chunks = [encoded[i:i + chunk_size] for i in range(0, len(encoded), chunk_size)]

    queries = []
    # Init query with campaign ID
    init_encoded = b32_encode(CAMPAIGN_ID.encode())
    queries.append(f"init.{init_encoded}.d.{C2_DNS_DOMAIN}")

    # Data queries
    for seq, chunk in enumerate(chunks):
        queries.append(f"{seq:04x}.{chunk}.d.{C2_DNS_DOMAIN}")

    # End marker
    queries.append(f"fini.00.d.{C2_DNS_DOMAIN}")
    return queries


# -----------------------------------------------------------------
# HTTP exfiltration POST data (part 2)
# -----------------------------------------------------------------
HTTP_EXFIL_CHUNK_SIZE = 200  # base64 chars per POST

def generate_http_exfil_chunks():
    """Generate HTTP POST exfiltration chunks for part 2."""
    encrypted = xor_encrypt(PART2, STREAM_KEY, offset=SPLIT_POINT)
    encoded = base64.b64encode(encrypted).decode()
    chunks = [encoded[i:i + HTTP_EXFIL_CHUNK_SIZE]
              for i in range(0, len(encoded), HTTP_EXFIL_CHUNK_SIZE)]
    return chunks


# -----------------------------------------------------------------
# Decoy DNS patterns
# -----------------------------------------------------------------
def generate_decoy1_queries():
    """Decoy 1: network monitoring tool -- A queries from multiple hosts."""
    queries = []
    for _ in range(80):
        probe_id = ''.join(random.choice('abcdef0123456789') for _ in range(12))
        query = f"probe-{probe_id}.{DECOY_DNS_1}"
        src_ip = random.choice(INTERNAL_IPS)
        queries.append((query, src_ip, "A", "1"))
    return queries


def generate_decoy2_queries():
    """Decoy 2: developer testing DNS records -- A queries with NXDOMAIN."""
    queries = []
    dev_ip = "10.0.1.25"
    for _ in range(45):
        rand_label = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(20))
        query = f"test-{rand_label}.{DECOY_DNS_2}"
        queries.append((query, dev_ip, "A", "1"))
    return queries


# -----------------------------------------------------------------
# Red team exercise DNS tunneling
# -----------------------------------------------------------------
def generate_redteam_queries():
    """Red team exercise: DNS tunneling via TXT queries with base64url
    encoding and .r. separator.  Structurally similar to the real C2
    but uses different encoding (base64url vs base32), different
    separator (.r. vs .d.), different init marker (start vs init),
    and originates from a different source IP."""
    rt_data = (
        b"RT-EXERCISE-Q1-2024: Testing data loss prevention controls "
        b"per engagement SOW-2024-0087. This is authorized penetration "
        b"testing activity. Contact CISO if detected. END-OF-TEST."
    ) * 3
    rt_key = hashlib.sha256(REDTEAM_CAMPAIGN.encode()).digest()[:16]
    encrypted = xor_encrypt(rt_data, rt_key, offset=0)
    encoded = base64.urlsafe_b64encode(encrypted).decode().rstrip("=")

    chunk_size = 40
    chunks = [encoded[i:i + chunk_size] for i in range(0, len(encoded), chunk_size)]

    queries = []
    start_encoded = base64.urlsafe_b64encode(
        REDTEAM_CAMPAIGN.encode()
    ).decode().rstrip("=")
    queries.append(f"start.{start_encoded}.r.{REDTEAM_DNS_DOMAIN}")

    for seq, chunk in enumerate(chunks):
        queries.append(f"{seq:04x}.{chunk}.r.{REDTEAM_DNS_DOMAIN}")

    queries.append(f"end.00.r.{REDTEAM_DNS_DOMAIN}")
    return queries


# -----------------------------------------------------------------
# DNS log generation
# -----------------------------------------------------------------
def generate_dns_log():
    """Generate Zeek-format DNS log with C2 tunneling + red team + decoys."""
    exfil_queries = generate_exfil_queries()
    decoy1_queries = generate_decoy1_queries()
    decoy2_queries = generate_decoy2_queries()
    redteam_queries = generate_redteam_queries()

    lines = [
        "#separator \\x09",
        "#set_separator\t,",
        "#empty_field\t(empty)",
        "#unset_field\t-",
        "#path\tdns",
        "#open\t2024-03-01-00-00-00",
        "#fields\tts\tuid\tid.orig_h\tid.orig_p\tid.resp_h\tid.resp_p\tproto\ttrans_id\trtt\tquery\tqclass\tqclass_name\tqtype\tqtype_name\trcode\trcode_name\tAA\tTC\tRD\tRA\tZ\tanswers\tTTLs\trejected",
        "#types\ttime\tstring\taddr\tport\taddr\tport\tenum\tcount\tinterval\tstring\tcount\tstring\tcount\tstring\tcount\tstring\tbool\tbool\tbool\tbool\tcount\tvector[string]\tvector[interval]\tbool",
    ]

    all_entries = []

    # Legitimate DNS traffic
    ts_start = FIRST_CONTACT_EPOCH - 300
    ts_end = FIRST_CONTACT_EPOCH + WINDOW_HOURS * 3600
    current_ts = ts_start

    while current_ts < ts_end:
        src_ip = random.choice(INTERNAL_IPS)
        domain = random.choice(LEGIT_DOMAINS + RED_HERRING_DOMAINS)
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        trans_id = random.randint(1, 65535)
        rtt = round(random.uniform(0.001, 0.1), 6)

        if "internal.corp" in domain:
            answer_ip = f"10.0.1.{random.randint(100, 200)}"
        else:
            answer_ip = random.choice(EXTERNAL_IPS[:10])

        ttl = random.choice([60, 120, 300, 600, 3600])
        entry_ts = current_ts + random.uniform(0, 0.999)

        line = (
            f"{entry_ts:.6f}\t{uid}\t{src_ip}\t{src_port}\t{DNS_SERVER_IP}\t53\t"
            f"udp\t{trans_id}\t{rtt}\t{domain}\t1\tC_INTERNET\t1\tA\t"
            f"0\tNOERROR\tF\tF\tT\tT\t0\t{answer_ip}\t{ttl}.000000\tF"
        )
        all_entries.append((entry_ts, line))
        current_ts += random.uniform(0.1, 5.0)

    # C2 DNS exfiltration queries (from compromised host, TXT queries)
    exfil_start = FIRST_CONTACT_EPOCH + 600
    for i, query in enumerate(exfil_queries):
        ts_exfil = exfil_start + i * random.uniform(2.0, 8.0)
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        trans_id = random.randint(1, 65535)
        rtt = round(random.uniform(0.05, 0.3), 6)

        line = (
            f"{ts_exfil:.6f}\t{uid}\t{COMPROMISED_IP}\t{src_port}\t{DNS_SERVER_IP}\t53\t"
            f"udp\t{trans_id}\t{rtt}\t{query}\t1\tC_INTERNET\t16\tTXT\t"
            f"0\tNOERROR\tF\tF\tT\tT\t0\t\"v=ok\"\t300.000000\tF"
        )
        all_entries.append((ts_exfil, line))

    # Red team DNS tunneling (TXT queries from red team IP, .r. separator)
    rt_start = FIRST_CONTACT_EPOCH + 400
    for i, query in enumerate(redteam_queries):
        ts_rt = rt_start + i * random.uniform(3.0, 10.0)
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        trans_id = random.randint(1, 65535)
        rtt = round(random.uniform(0.05, 0.25), 6)

        line = (
            f"{ts_rt:.6f}\t{uid}\t{REDTEAM_IP}\t{src_port}\t{DNS_SERVER_IP}\t53\t"
            f"udp\t{trans_id}\t{rtt}\t{query}\t1\tC_INTERNET\t16\tTXT\t"
            f"0\tNOERROR\tF\tF\tT\tT\t0\t\"v=ok\"\t300.000000\tF"
        )
        all_entries.append((ts_rt, line))

    # Decoy 1: network monitoring probes (A queries, multiple sources)
    for j, (query, src_ip, qtype, qtype_num) in enumerate(decoy1_queries):
        ts_decoy = FIRST_CONTACT_EPOCH + random.uniform(100, WINDOW_HOURS * 3600 - 100)
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        trans_id = random.randint(1, 65535)
        rtt = round(random.uniform(0.001, 0.05), 6)
        answer_ip = random.choice(EXTERNAL_IPS)
        line = (
            f"{ts_decoy:.6f}\t{uid}\t{src_ip}\t{src_port}\t{DNS_SERVER_IP}\t53\t"
            f"udp\t{trans_id}\t{rtt}\t{query}\t1\tC_INTERNET\t{qtype_num}\t{qtype}\t"
            f"0\tNOERROR\tF\tF\tT\tT\t0\t{answer_ip}\t60.000000\tF"
        )
        all_entries.append((ts_decoy, line))

    # Decoy 2: developer testing (A queries, mostly NXDOMAIN, single source)
    for j, (query, src_ip, qtype, qtype_num) in enumerate(decoy2_queries):
        ts_decoy = FIRST_CONTACT_EPOCH + random.uniform(200, WINDOW_HOURS * 3600 - 200)
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        trans_id = random.randint(1, 65535)
        rtt = round(random.uniform(0.01, 0.08), 6)
        line = (
            f"{ts_decoy:.6f}\t{uid}\t{src_ip}\t{src_port}\t{DNS_SERVER_IP}\t53\t"
            f"udp\t{trans_id}\t{rtt}\t{query}\t1\tC_INTERNET\t{qtype_num}\t{qtype}\t"
            f"3\tNXDOMAIN\tF\tF\tT\tT\t0\t-\t0.000000\tF"
        )
        all_entries.append((ts_decoy, line))

    # Normal DNS from compromised host (blending)
    for _ in range(150):
        domain = random.choice(LEGIT_DOMAINS)
        ts_normal = FIRST_CONTACT_EPOCH + random.uniform(-300, WINDOW_HOURS * 3600)
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        trans_id = random.randint(1, 65535)
        rtt = round(random.uniform(0.001, 0.1), 6)
        answer_ip = random.choice(EXTERNAL_IPS[:10])
        ttl = random.choice([60, 120, 300, 600])

        line = (
            f"{ts_normal:.6f}\t{uid}\t{COMPROMISED_IP}\t{src_port}\t{DNS_SERVER_IP}\t53\t"
            f"udp\t{trans_id}\t{rtt}\t{domain}\t1\tC_INTERNET\t1\tA\t"
            f"0\tNOERROR\tF\tF\tT\tT\t0\t{answer_ip}\t{ttl}.000000\tF"
        )
        all_entries.append((ts_normal, line))

    all_entries.sort(key=lambda x: x[0])
    for _, line in all_entries:
        lines.append(line)

    lines.append("#close\t2024-03-01-02-30-00")
    return "\n".join(lines)


# -----------------------------------------------------------------
# HTTP log generation
# -----------------------------------------------------------------
def generate_http_log():
    """Generate Zeek-format HTTP log with beacons + exfil POSTs."""
    http_exfil_chunks = generate_http_exfil_chunks()

    lines = [
        "#separator \\x09",
        "#set_separator\t,",
        "#empty_field\t(empty)",
        "#unset_field\t-",
        "#path\thttp",
        "#open\t2024-03-01-00-00-00",
        "#fields\tts\tuid\tid.orig_h\tid.orig_p\tid.resp_h\tid.resp_p\ttrans_depth\tmethod\thost\turi\treferrer\tversion\tuser_agent\torigin\trequest_body_len\tresponse_body_len\tstatus_code\tstatus_msg\tinfo_code\tinfo_msg\ttags\tusername\tpassword\tproxied\torig_fuids\torig_filenames\torig_mime_types\tresp_fuids\tresp_filenames\tresp_mime_types",
        "#types\ttime\tstring\taddr\tport\taddr\tport\tcount\tstring\tstring\tstring\tstring\tstring\tstring\tstring\tcount\tcount\tcount\tstring\tcount\tstring\tset[enum]\tstring\tstring\tset[string]\tvector[string]\tvector[string]\tvector[string]\tvector[string]\tvector[string]\tvector[string]",
    ]

    all_entries = []

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "python-requests/2.31.0",
        "curl/8.4.0",
    ]

    C2_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.85 Safari/537.36"

    LEGIT_URIS = [
        "/", "/api/v1/status", "/index.html", "/login", "/dashboard",
        "/api/v1/users", "/api/v1/metrics", "/assets/main.css",
        "/assets/app.js", "/favicon.ico", "/robots.txt",
        "/api/v2/telemetry", "/health", "/api/status",
    ]

    LEGIT_HTTP_HOSTS = [
        "www.google.com", "github.com", "api.github.com",
        "cdn.cloudflare.com", "analytics.google.com",
        "jenkins.internal.corp", "gitlab.internal.corp",
        "grafana.internal.corp",
    ]

    ts_start = FIRST_CONTACT_EPOCH - 300
    ts_end = FIRST_CONTACT_EPOCH + WINDOW_HOURS * 3600
    current_ts = ts_start

    while current_ts < ts_end:
        src_ip = random.choice(INTERNAL_IPS)
        host = random.choice(LEGIT_HTTP_HOSTS)
        uri = random.choice(LEGIT_URIS)
        ua = random.choice(USER_AGENTS)
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)

        if "internal.corp" in host:
            dst_ip = f"10.0.1.{random.randint(100, 200)}"
            dst_port = random.choice([80, 8080, 3000])
        else:
            dst_ip = random.choice(EXTERNAL_IPS[:10])
            dst_port = 443

        method = "GET" if random.random() < 0.8 else "POST"
        req_len = 0 if method == "GET" else random.randint(50, 5000)
        resp_len = random.randint(200, 50000)
        status = random.choice([200, 200, 200, 200, 301, 304, 404])
        status_msg = {200: "OK", 301: "Moved Permanently", 304: "Not Modified", 404: "Not Found"}[status]
        entry_ts = current_ts + random.uniform(0, 0.999)

        line = (
            f"{entry_ts:.6f}\t{uid}\t{src_ip}\t{src_port}\t{dst_ip}\t{dst_port}\t"
            f"1\t{method}\t{host}\t{uri}\t-\t1.1\t{ua}\t-\t"
            f"{req_len}\t{resp_len}\t{status}\t{status_msg}\t-\t-\t"
            f"(empty)\t-\t-\t-\t-\t-\t-\t-\t-\t-"
        )
        all_entries.append((entry_ts, line))
        current_ts += random.uniform(0.5, 10.0)

    # C2 HTTP beacons (heartbeat GETs, every BEACON_INTERVAL seconds)
    beacon_ts = float(FIRST_CONTACT_EPOCH)
    beacon_count = 0

    while beacon_ts < ts_end:
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        jitter = random.uniform(-2.0, 2.0)
        entry_ts = beacon_ts + jitter

        line = (
            f"{entry_ts:.6f}\t{uid}\t{COMPROMISED_IP}\t{src_port}\t{C2_HTTP_IP}\t443\t"
            f"1\tGET\t{C2_HTTP_DOMAIN}\t/api/v2/heartbeat\t-\t1.1\t{C2_USER_AGENT}\t-\t"
            f"0\t{random.randint(50, 200)}\t200\tOK\t-\t-\t"
            f"(empty)\t-\t-\t-\t-\t-\t-\t-\t-\t-"
        )
        all_entries.append((entry_ts, line))
        beacon_count += 1
        beacon_ts += BEACON_INTERVAL

    # C2 HTTP exfil POSTs (data exfiltration, after DNS exfil completes)
    exfil_http_start = FIRST_CONTACT_EPOCH + 900  # starts after DNS exfil
    exfil_post_count = 0

    for seq, chunk in enumerate(http_exfil_chunks):
        ts_exfil = exfil_http_start + seq * random.uniform(15.0, 25.0)
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        # Encode data in URI query params (visible in Zeek HTTP log)
        uri = f"/api/v2/events?sid=a1b2c3&seq={seq}&d={chunk}"
        req_len = random.randint(200, 600)
        resp_len = random.randint(50, 150)

        line = (
            f"{ts_exfil:.6f}\t{uid}\t{COMPROMISED_IP}\t{src_port}\t{C2_HTTP_IP}\t443\t"
            f"1\tPOST\t{C2_HTTP_DOMAIN}\t{uri}\t-\t1.1\t{C2_USER_AGENT}\t-\t"
            f"{req_len}\t{resp_len}\t200\tOK\t-\t-\t"
            f"(empty)\t-\t-\t-\t-\t-\t-\t-\t-\t-"
        )
        all_entries.append((ts_exfil, line))
        exfil_post_count += 1

    all_entries.sort(key=lambda x: x[0])
    for _, line in all_entries:
        lines.append(line)

    lines.append("#close\t2024-03-01-02-30-00")
    return "\n".join(lines), beacon_count, exfil_post_count


# -----------------------------------------------------------------
# Connection log
# -----------------------------------------------------------------
def generate_conn_log():
    """Generate Zeek-format connection log."""
    lines = [
        "#separator \\x09",
        "#set_separator\t,",
        "#empty_field\t(empty)",
        "#unset_field\t-",
        "#path\tconn",
        "#open\t2024-03-01-00-00-00",
        "#fields\tts\tuid\tid.orig_h\tid.orig_p\tid.resp_h\tid.resp_p\tproto\tservice\tduration\torig_bytes\tresp_bytes\tconn_state\tlocal_orig\tlocal_resp\tmissed_bytes\thistory\torig_pkts\torig_ip_bytes\tresp_pkts\tresp_ip_bytes\ttunnel_parents",
        "#types\ttime\tstring\taddr\tport\taddr\tport\tenum\tstring\tinterval\tcount\tcount\tstring\tbool\tbool\tcount\tstring\tcount\tcount\tcount\tcount\tset[string]",
    ]

    entries = []
    ts_start = FIRST_CONTACT_EPOCH - 300
    ts_end = FIRST_CONTACT_EPOCH + WINDOW_HOURS * 3600
    current_ts = ts_start

    while current_ts < ts_end:
        src_ip = random.choice(INTERNAL_IPS)
        dst_ip = random.choice(EXTERNAL_IPS + [f"10.0.1.{random.randint(100, 200)}"])
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        dst_port = random.choice([53, 80, 443, 443, 443, 8080])
        proto = "udp" if dst_port == 53 else "tcp"
        service = "dns" if dst_port == 53 else "http" if dst_port == 80 else "ssl"
        duration = round(random.uniform(0.01, 30.0), 6)
        orig_bytes = random.randint(100, 10000)
        resp_bytes = random.randint(100, 50000)

        line = (
            f"{current_ts:.6f}\t{uid}\t{src_ip}\t{src_port}\t{dst_ip}\t{dst_port}\t"
            f"{proto}\t{service}\t{duration}\t{orig_bytes}\t{resp_bytes}\tSF\t"
            f"T\tF\t0\tShAdDaf\t{random.randint(5, 50)}\t{orig_bytes + random.randint(100, 500)}\t"
            f"{random.randint(5, 50)}\t{resp_bytes + random.randint(100, 500)}\t(empty)"
        )
        entries.append((current_ts, line))
        current_ts += random.uniform(0.1, 5.0)

    # C2-specific connections
    beacon_ts = float(FIRST_CONTACT_EPOCH)
    while beacon_ts < ts_end:
        uid = generate_zeek_uid()
        src_port = random.randint(32768, 65535)
        line = (
            f"{beacon_ts:.6f}\t{uid}\t{COMPROMISED_IP}\t{src_port}\t{C2_HTTP_IP}\t443\t"
            f"tcp\tssl\t{round(random.uniform(0.5, 2.0), 6)}\t{random.randint(200, 600)}\t"
            f"{random.randint(100, 300)}\tSF\tT\tF\t0\tShAdDaf\t"
            f"{random.randint(5, 15)}\t{random.randint(300, 800)}\t"
            f"{random.randint(5, 15)}\t{random.randint(200, 500)}\t(empty)"
        )
        entries.append((beacon_ts, line))
        beacon_ts += BEACON_INTERVAL

    entries.sort(key=lambda x: x[0])
    for _, line in entries:
        lines.append(line)

    lines.append("#close\t2024-03-01-02-30-00")
    return "\n".join(lines)


# -----------------------------------------------------------------
# Malware fragment (partially recovered)
# -----------------------------------------------------------------
def generate_agent_fragment():
    """Generate a partial C2 agent source code fragment."""
    return '''#!/usr/bin/env python3
"""
Recovered fragment from /tmp/.cache/svc_update.py
File was partially overwritten - some sections corrupted
Recovered by: IR Team
Date: 2024-03-01
SHA-256 (partial file): computed at recovery time
"""

import hashlib
import hmac
import base64
import socket
import time
import os
import random
# [CORRUPTED - 14 bytes missing]

class Config:
    # C2 configuration - values were loaded from encrypted config at runtime
    DNS_SUFFIX = None  # populated at runtime from C2 bootstrap
    HTTP_ENDPOINT = None  # populated at runtime from C2 bootstrap
    BEACON_SEC = None  # populated at runtime from C2 bootstrap

    @staticmethod
    def derive_key(campaign_id):
        """Derive stream cipher key from campaign identifier.
        Uses HMAC-SHA256 with a fixed derivation context to produce
        a 16-byte key for the XOR stream cipher."""
        return hmac.new(
            campaign_id.encode(),
            b"c2-exfil-key",
            hashlib.sha256
        ).digest()[:16]

# [CORRUPTED - approximately 200 bytes missing]

class StreamCipher:
    """XOR-based stream cipher with offset tracking."""

    def __init__(self, key):
        self.key = key
        self.stream_offset = 0  # tracks cumulative byte position

    def encrypt(self, data):
        """Encrypt data continuing from current stream position.
        The stream_offset ensures that data encrypted across multiple
        calls forms a single continuous keystream."""
        if isinstance(data, str):
            data = data.encode()
        result = bytes(
            d ^ self.key[(self.stream_offset + i) % len(self.key)]
            for i, d in enumerate(data)
        )
        self.stream_offset += len(data)
        return result

# [CORRUPTED - 150 bytes missing]

class DNSExfil:
    """DNS-based data exfiltration module."""

    CHUNK_SIZE = 50  # max chars per DNS label

    def __init__(self, cipher, domain):
        self.cipher = cipher
        self.domain = domain

    def _encode(self, data):
        """Encode binary data for DNS transport via base32."""
        return base64.b32encode(data).decode().lower().rstrip('=')

    def send_init(self, campaign_id):
        """Send initialization beacon with campaign ID."""
        encoded_cid = self._encode(campaign_id.encode())
        query = f"init.{encoded_cid}.d.{self.domain}"
        self._dns_query(query, "TXT")

    def exfiltrate(self, data):
        """Exfiltrate data chunk via DNS TXT queries.
        Data is encrypted using the stream cipher (which tracks offset)
        then base32-encoded and split into DNS-safe label chunks."""
        encrypted = self.cipher.encrypt(data)
        encoded = self._encode(encrypted)

        # Split into chunks fitting DNS label size limits
        chunks = [encoded[i:i+self.CHUNK_SIZE]
                  for i in range(0, len(encoded), self.CHUNK_SIZE)]

        for seq, chunk in enumerate(chunks):
            query = f"{seq:04x}.{chunk}.d.{self.domain}"
            self._dns_query(query, "TXT")
            time.sleep(random.uniform(2.0, 8.0))

        # Send completion marker
        self._dns_query(f"fini.00.d.{self.domain}", "TXT")

    def _dns_query(self, query, qtype):
        # [CORRUPTED - DNS query implementation missing]
        pass

class HTTPExfil:
    """HTTP-based data exfiltration module."""

    CHUNK_SIZE = 200  # base64 chars per request

    def __init__(self, cipher, endpoint):
        self.cipher = cipher
        self.endpoint = endpoint

    def exfiltrate(self, data):
        """Exfiltrate data via HTTP POST requests.
        Data is encrypted using the SAME stream cipher instance
        (continuing from whatever offset the DNS module left off),
        then base64-encoded and sent as URI parameters."""
        encrypted = self.cipher.encrypt(data)
        encoded = base64.b64encode(encrypted).decode()

        chunks = [encoded[i:i+self.CHUNK_SIZE]
                  for i in range(0, len(encoded), self.CHUNK_SIZE)]

        for seq, chunk in enumerate(chunks):
            # [CORRUPTED - HTTP POST implementation ~80 bytes missing]
            pass

# [CORRUPTED - orchestrator module missing]
# [CORRUPTED - target data collection missing]
# [CORRUPTED - main() entry point missing]

# Fragment ends here - remaining ~3KB of file was zeroed out
'''


# -----------------------------------------------------------------
# Clean Python sample (for YARA false-positive testing)
# -----------------------------------------------------------------
def generate_clean_sample():
    """Generate a benign Python script for YARA false-positive testing."""
    return '''#!/usr/bin/env python3
"""Simple HTTP health check monitor.

Periodically checks configured endpoints and logs status.
"""

import urllib.request
import time
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("healthcheck")

ENDPOINTS = [
    "http://localhost:8080/health",
    "http://localhost:3000/api/status",
]

INTERVAL = 60  # seconds between checks

def check_endpoint(url):
    """Send GET request to endpoint and return status."""
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        return {"url": url, "status": resp.status, "ok": True}
    except Exception as e:
        return {"url": url, "status": 0, "ok": False, "error": str(e)}

def run_checks():
    results = []
    for ep in ENDPOINTS:
        result = check_endpoint(ep)
        results.append(result)
        logger.info("Check %s: %s", ep, "OK" if result["ok"] else "FAIL")
    return results

def main():
    logger.info("Starting health check monitor (interval=%ds)", INTERVAL)
    while True:
        results = run_checks()
        with open("/tmp/healthcheck.json", "w") as f:
            json.dump(results, f)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
'''


# -----------------------------------------------------------------
# Incident report
# -----------------------------------------------------------------
def generate_incident_report():
    return """INCIDENT REPORT - IR-2024-0301
================================
Date: 2024-03-01
Analyst: J. Chen (SOC Tier 2)
Status: ESCALATED

Summary:
--------
Anomalous DNS and HTTP traffic detected from multiple internal hosts during
routine network monitoring. EDR agent on one affected host went offline at
approximately 2024-02-29 23:45 UTC. A partial malware artifact was recovered
from /tmp before the host was isolated from the network.

Key Observations:
-----------------
1. Four distinct suspicious DNS query patterns were identified during the
   capture window. All exhibit high-entropy subdomain labels but differ in
   query type, encoding scheme, source distribution, and response codes.

2. Two of the four patterns use TXT queries with structured subdomain
   encoding, making them particularly concerning. They appear to be DNS
   tunneling from different source hosts with different encoding schemes
   and subdomain separator conventions.

3. One pattern correlates with outbound HTTP traffic to an external host,
   suggesting a multi-channel C2 framework.

4. The recovered malware fragment indicates a dual-channel exfiltration
   scheme with specific encoding and protocol markers that should help
   attribute one of the tunneling patterns to the actual threat.

IT Security Advisory (received 2024-03-01 01:15 UTC):
------------------------------------------------------
An authorized red team penetration test (engagement SOW-2024-0087) is
currently active on the internal network. The red team is expected to
conduct exfiltration testing using DNS-based techniques. Their specific
infrastructure details (domains, IPs, tools) were intentionally withheld
from the SOC to validate detection capabilities. Any DNS tunneling pattern
that does NOT match the recovered malware's protocol implementation should
be evaluated as potentially authorized testing activity.

Evidence Collected:
-------------------
1. Zeek logs from border sensor (2-hour window): /app/evidence/logs/
   - dns.log: DNS query/response log
   - http.log: HTTP request/response log
   - conn.log: Connection summary log

2. Recovered malware fragment: /app/evidence/recovered/svc_update.py.fragment
   - Partial Python script found in /tmp/.cache/ on compromised host
   - File was partially overwritten (suspected anti-forensics)
   - Contains C2 communication and encryption code fragments

3. Clean baseline: /app/evidence/clean_sample.py
   - Known-good Python script from the same host for comparison

Initial Assessment:
-------------------
- The recovered code fragment reveals the malware's specific protocol:
  base32 encoding, ".d." subdomain separators, "init"/"fini" markers,
  and TXT query types. Cross-reference this against the DNS patterns.
- A stream cipher key derived via HMAC-SHA256 is shared across DNS and
  HTTP exfiltration channels.
- The analyst must evaluate each suspicious DNS pattern against the
  malware's protocol implementation to distinguish the real threat from
  the authorized red team exercise and from legitimate tools.

Tasks for Analyst:
------------------
1. Evaluate ALL four suspicious DNS patterns - classify each as the real
   C2 channel, the authorized red team exercise, or benign/legitimate
   activity. Cross-reference traffic characteristics against the malware
   code to justify your classification.
2. Identify all C2 infrastructure (domains, IPs, protocols)
3. Reconstruct the full exfiltrated data from both channels
4. Characterize the beacon and exfiltration patterns
5. Create detection artifacts:
   a. YARA rule for the malware binary
   b. Sigma detection rule for the DNS C2 channel that would NOT
      false-positive on the authorized red team exercise

Write structured findings to /app/answers.json
Write YARA detection rule to /app/detection/implant.yar
Write Sigma detection rule to /app/detection/c2_dns_tunnel.yml
"""


# -----------------------------------------------------------------
# Main
# -----------------------------------------------------------------
def main():
    os.makedirs("/app/evidence/logs", exist_ok=True)
    os.makedirs("/app/evidence/recovered", exist_ok=True)
    os.makedirs("/app/detection", exist_ok=True)

    dns_log = generate_dns_log()
    with open("/app/evidence/logs/dns.log", "w") as f:
        f.write(dns_log)

    http_log, beacon_count, exfil_post_count = generate_http_log()
    with open("/app/evidence/logs/http.log", "w") as f:
        f.write(http_log)

    conn_log = generate_conn_log()
    with open("/app/evidence/logs/conn.log", "w") as f:
        f.write(conn_log)

    with open("/app/evidence/recovered/svc_update.py.fragment", "w") as f:
        f.write(generate_agent_fragment())

    with open("/app/evidence/clean_sample.py", "w") as f:
        f.write(generate_clean_sample())

    with open("/app/evidence/incident_report.txt", "w") as f:
        f.write(generate_incident_report())

    exfil_queries = generate_exfil_queries()
    redteam_queries = generate_redteam_queries()
    http_chunks = generate_http_exfil_chunks()
    dns_count = sum(1 for line in dns_log.split("\n")
                    if not line.startswith("#") and line.strip())
    http_count = sum(1 for line in http_log.split("\n")
                     if not line.startswith("#") and line.strip())
    print(f"Evidence generated:")
    print(f"  DNS log entries: {dns_count}")
    print(f"  DNS exfil queries: {len(exfil_queries)}")
    print(f"  Red team queries: {len(redteam_queries)}")
    print(f"  HTTP log entries: {http_count}")
    print(f"  HTTP beacons: {beacon_count}")
    print(f"  HTTP exfil POSTs: {exfil_post_count}")
    print(f"  HTTP exfil chunks: {len(http_chunks)}")
    print(f"  Decoy 1 queries: 80 (netcheck-monitoring.io)")
    print(f"  Decoy 2 queries: 45 (dev-sandbox-testing.org)")


if __name__ == "__main__":
    main()
