#!/usr/bin/env python3
"""Generate synthetic DNS query log with embedded exfiltration channels."""
import random
import base64
import hashlib
import json
from datetime import datetime, timedelta

random.seed(0xDEADCAFE)

LOG_PATH = "/tmp/dns_queries.log"

SSH_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA2a2rwplBQLzOHEP6VDnNkEJaGxFNaFzQ09lD3Fp8aKM6R5Nk
VmyGPBSI6MhRkP7PnU1s2EQF8TtL7LMdGkhVjz2nNRMAxEfOrYUJHwK9fQJxhWn0
qGpNMXBPf0yJKLcj2H5NU2OXlNKXnREQCTNbZNrJ4MUDReM5j9bKMgJfj7fCPJ5H
Qw4j2cR5kBNGFSwExVWXoKlNUh7yClgjR1lKf3NJm5oYGC6sPKd0xhi7gAe0RBjv
NSqPS0IDKOP3Mn1cPYhbeLrkXQkNBtfS9JGrFJM0IjjWnI7ECkW8v0pfbxHB4XOlR
qXxnJLCb3GJDnCakrg3FhvNnxUJHQKCA42JpQIDAQABAoIBAC3qvbJ9xPLak5AiLr
qN9gxfHGEQ5ZEOG2Ng0TJxPNjjKzRQb0V4QYP5WDMLI4m9lRwifXjOiKJLqMNrTiv
B7JgYnTKRL5Rf3p5Kt1XxJJ7E5zzLXAteQhMP7JxQUTKAwhMf0rSTIqrfGT9FflRS
P5bfL3HkRfirftQQmQExRXfAGxB6tgGTP5ad2lLjzBMPRWMOcmSP4QN4eq2TEmFBw
x0o15Gqfj7GXlP4mjLx4P5MWapXbij5PKQWV8jGr8xY0oWkN4Y3FfCQknKW4rShB9
CxIWPNagHjVEP0KHKfPKixj8qMFpk2exJb5jvqGAI3mMQKjLl0lBT50mGNPER53IK
xFECgYEA7z2OqLPMIy5ny4kFT7RWJVr0RXApmGD5a34eqGIoR0Rl3tozFiDMzLzGm
S+9apGQkMfMlgIQN2Cch3tJ7iRqJx3MxGOHY1bPb0IRioPjp6PsMi6pJr4fNVJP2d
QgY1s7rIr6GxJm0+7i1HBqfNebk7P8iGmafn7J5FI2JMa6l9SMsCgYEA6F2nChY9e
E7hyJKxbmLOCrmkGd2D5xd4fOvz1zBDFT98UtJRPH5Fjqtj7P1FdSfNLaFM7FKZZM
ZqtHf1xtZMQpfMs4IuacNqVHNdYLqH7D5MJAV9G9HaIrSvGUQHiS6SH5ptf0+fxMF
k1CGINVlS7xIa0vFhQVHVbS5UPkjH4u6Y/sCgYEArBqwJ8fhJxNBFY1Y8KFmHnWF
cLP8bMb8eAamGIisSwT21Nh8DjmPKLKaPxhb5eSXUMFJ7dXz2sGQfGBHCml3lkIkF
r1JMeY9LKdCjPINVPR8J4I6a6Qms7MWGOpYSXiU8t2EcX4z8Ic3XPNZLMJ0Y3Qs6X
BqjC4RPJmeJTd1rsCgYB9UQT2pCel1bP4kIHpFxk4eR7R3afI8dU8ylk2A7GZ3j7fc
phXjkHyDrog9d1s7eMxhiNwDVLhyDC9a1J4hHGl3oEd6QUKLpbE8bBqjjjKTKP5Tf
STHNv8GCqYWH5a6g8S4a1bPMFspPhT7qLDCrZjf1CmEXInO8pjJroNdrwKBgQCd6L
Yk1d7LSr7EWF2tyYi4qCa7qNQH0j8fHH1FNUCkvJJLEkDm9EcrNG8T52rGAlHbR5B
s2lpXbMpJ6EDhFn6AoGWTxJLqNtJr5X6q6mA4unkIQIh3hLpdV9LJ1vCCrUQqJ5p9
r3eJ7S7cRCqLNJ0F2V8rj5L5NxT9apF8cJLA==
-----END RSA PRIVATE KEY-----"""

SHADOW_CONTENT = """root:$6$rounds=656000$rGjLTsfOd7ACJm3i$xZQ3LRq4XjfK8vG1bP9wNrcTe8FDPlIWHPSVOvSdKxJNJnWCbNH2pAzVhKx7WFfDqjVk6Xts2oQjqJ7l1a5/:19722:0:99999:7:::
daemon:*:19722:0:99999:7:::
bin:*:19722:0:99999:7:::
sys:*:19722:0:99999:7:::
sysadmin:$6$rounds=656000$mKP1dP5ycVj3E2nz$JgsFVtM3NY7Q8SxbF1ihEwqj1mVCt4xLGUfVFHHvXRm8FQ5KqG0vtSrj2L0YRb5p2gXK9jF1kAbdCJr7q/:19722:0:99999:7:::
dbadmin:$6$rounds=656000$9XnPq4Bk1vDZfhMJ$R0VCFFhmQEBfnihKP7qJH5sD2YG3CjLbPqKe3hBxS2JDmA9VUfGOUTjTqJiK9MKl5qXpH2hCqE8dN3Rdi50:19723:0:99999:7:::
backup:$6$rounds=656000$WnC2mLxP8bJHfG5k$Vt9aQRl3PxKJEm5PqFdJh8y2D0nEf1iM3cROAGmWx8qAVe5P6HJirSNm2B0oQy4fKH3A9nX7vJ1Lc6wk8R1:19723:0:99999:7:::
www-data:*:19722:0:99999:7:::
nobody:*:19722:0:99999:7:::
deploy:$6$rounds=656000$kR5mD3vJ7wPxYqZt$H8dFjK2QlA3nP9rBwM4xY7eC5gT1iU6oS0fVdN8jW2kX3hG4lR7mQ5tI9yE0pU8bZ1nL6cD3wK4vF7jJ5sO/:19724:0:99999:7:::"""

DB_CREDS = json.dumps({
    "production": {
        "host": "db-prod-master.internal.corp",
        "port": 5432,
        "database": "app_production",
        "username": "prod_admin",
        "password": "kH7$mNq2!pX9vR4&wL8jB5"
    },
    "staging": {
        "host": "db-staging.internal.corp",
        "port": 5432,
        "database": "app_staging",
        "username": "staging_admin",
        "password": "tY3@fG6#cD1%nQ8*bE5"
    },
    "analytics": {
        "host": "clickhouse-prod.internal.corp",
        "port": 9440,
        "database": "analytics",
        "username": "etl_service",
        "password": "zW2^jR9&mK4!hV6$pL3"
    },
    "redis": {
        "host": "redis-cluster.internal.corp",
        "port": 6379,
        "password": "xN8#qT5&vB2!gF7$kM1",
        "database": 0,
        "cluster_mode": True
    }
}, indent=2)

XOR_KEY = b'\x5a\x3c\x7f'

EXFIL_DOMAIN_1 = "cdn-telemetry.dataflows.net"
EXFIL_DOMAIN_2 = "api-metrics.cloudstats.io"
EXFIL_DOMAIN_3 = "health.svc-monitor.cloud"

LEGIT_DOMAINS = [
    "www.google.com", "mail.google.com", "dns.google.com",
    "accounts.google.com", "fonts.googleapis.com", "ajax.googleapis.com",
    "docs.google.com", "drive.google.com", "calendar.google.com",
    "www.microsoft.com", "login.microsoftonline.com", "outlook.office365.com",
    "update.microsoft.com", "download.windowsupdate.com",
    "s3.amazonaws.com", "ec2.us-east-1.amazonaws.com", "sqs.us-west-2.amazonaws.com",
    "api.github.com", "raw.githubusercontent.com", "github.githubassets.com",
    "cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
    "registry.npmjs.org", "pypi.org", "rubygems.org",
    "stackoverflow.com", "www.reddit.com", "news.ycombinator.com",
    "slack-imgs.com", "app.slack.com", "edgeapi.slack.com",
    "zoom.us", "us02web.zoom.us",
    "www.facebook.com", "graph.facebook.com", "connect.facebook.net",
    "api.twitter.com", "abs.twimg.com",
    "www.linkedin.com", "static.licdn.com",
    "ocsp.digicert.com", "crl.microsoft.com", "ocsp.pki.goog",
    "time.windows.com", "ntp.ubuntu.com",
    "security.ubuntu.com", "archive.ubuntu.com", "ppa.launchpadcontent.net",
    "www.wikipedia.org", "en.wikipedia.org", "upload.wikimedia.org",
    "api.stripe.com", "checkout.stripe.com",
    "sentry.io", "o123456.ingest.sentry.io",
    "api.segment.io", "cdn.segment.com",
    "api.datadog.com", "app.datadoghq.com",
    "grafana.internal.corp", "prometheus.internal.corp",
    "jenkins.internal.corp", "gitlab.internal.corp",
    "nexus.internal.corp", "sonar.internal.corp",
    "vault.internal.corp", "consul.internal.corp",
    "k8s-api.internal.corp", "registry.internal.corp",
]

DISTRACTOR_DOMAINS = [
    "vpce-0a1b2c3d4e5f67890.s3.us-east-1.vpce.amazonaws.com",
    "i-0abcdef1234567890.ec2.internal",
    "d-9a8b7c6d5e.execute-api.us-west-2.amazonaws.com",
    "a3f4b2c1-d5e6-7890-abcd-ef1234567890.api.segment.io",
    "f47ac10b-58cc-4372-a567-0e02b2c3d479.webhook.site",
    "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d.runs.app.cloud",
    "dGVzdGluZw.cdn.example-analytics.com",
    "YWJjZGVmZw.static.tracking-pixel.net",
    "aHR0cHM6Ly93d3cuZ29vZ2xlLmNvbQ.r.cloudfront.net",
    "bG9uZy1lbmNvZGVkLXN1YmRvbWFpbi1kYXRh.cache.fastly.net",
]

CLIENT_IPS = [
    "10.0.1.15", "10.0.1.22", "10.0.1.37", "10.0.1.45",
    "10.0.2.11", "10.0.2.18", "10.0.2.33", "10.0.2.56",
    "10.0.3.7", "10.0.3.19", "10.0.3.42", "10.0.3.61",
    "10.0.4.5", "10.0.4.29", "10.0.4.50",
]

EXFIL_CLIENT = "10.0.2.33"

QUERY_TYPES = ["A", "AAAA", "CNAME", "MX", "TXT", "SRV", "PTR", "SOA", "NS"]
QUERY_TYPE_WEIGHTS = [50, 15, 10, 5, 8, 3, 4, 3, 2]


def encode_base32_chunks(data, label_max=52):
    encoded = base64.b32encode(data).decode('ascii').rstrip('=').lower()
    chunks = []
    for i in range(0, len(encoded), label_max):
        chunks.append(encoded[i:i+label_max])
    return chunks


def encode_hex_chunks(data, label_max=56):
    encoded = data.hex()
    chunks = []
    for i in range(0, len(encoded), label_max):
        chunks.append(encoded[i:i+label_max])
    return chunks


def xor_encrypt(data, key):
    result = bytearray(len(data))
    for i, b in enumerate(data):
        result[i] = b ^ key[i % len(key)]
    return bytes(result)


def encode_xor_hex_chunks(data, key, label_max=56):
    encrypted = xor_encrypt(data, key)
    encoded = encrypted.hex()
    chunks = []
    for i in range(0, len(encoded), label_max):
        chunks.append(encoded[i:i+label_max])
    return chunks


def generate_log():
    entries = []
    base_time = datetime(2024, 11, 15, 8, 0, 0)

    for i in range(5500):
        ts = base_time + timedelta(seconds=random.uniform(0, 7200))
        client = random.choice(CLIENT_IPS)
        domain = random.choice(LEGIT_DOMAINS)
        qtype = random.choices(QUERY_TYPES, weights=QUERY_TYPE_WEIGHTS, k=1)[0]
        rcode = random.choices(["NOERROR", "NXDOMAIN", "SERVFAIL"], weights=[95, 4, 1], k=1)[0]
        resp_time_ms = random.uniform(1, 200)
        entries.append((ts, client, domain, qtype, rcode, resp_time_ms))

    for i in range(150):
        ts = base_time + timedelta(seconds=random.uniform(0, 7200))
        client = random.choice(CLIENT_IPS)
        domain = random.choice(DISTRACTOR_DOMAINS)
        qtype = random.choices(["A", "AAAA", "CNAME"], weights=[60, 25, 15], k=1)[0]
        rcode = "NOERROR"
        resp_time_ms = random.uniform(5, 150)
        entries.append((ts, client, domain, qtype, rcode, resp_time_ms))

    ssh_data = SSH_KEY.encode('utf-8')
    ch1_chunks = encode_base32_chunks(ssh_data)
    for seq, chunk in enumerate(ch1_chunks):
        qname = "{}.{:04x}.{}".format(chunk, seq, EXFIL_DOMAIN_1)
        ts = base_time + timedelta(seconds=random.uniform(600, 6600))
        resp_time_ms = random.uniform(30, 120)
        entries.append((ts, EXFIL_CLIENT, qname, "A", "NOERROR", resp_time_ms))

    shadow_data = SHADOW_CONTENT.encode('utf-8')
    ch2_chunks = encode_hex_chunks(shadow_data)
    for seq, chunk in enumerate(ch2_chunks):
        qname = "{}.{:04x}.{}".format(chunk, seq, EXFIL_DOMAIN_2)
        ts = base_time + timedelta(seconds=random.uniform(1200, 6000))
        resp_time_ms = random.uniform(25, 100)
        entries.append((ts, EXFIL_CLIENT, qname, "A", "NOERROR", resp_time_ms))

    creds_data = DB_CREDS.encode('utf-8')
    ch3_chunks = encode_xor_hex_chunks(creds_data, XOR_KEY)
    for seq, chunk in enumerate(ch3_chunks):
        qname = "{}.{:04x}.{}".format(chunk, seq, EXFIL_DOMAIN_3)
        ts = base_time + timedelta(seconds=random.uniform(1800, 5400))
        resp_time_ms = random.uniform(40, 150)
        entries.append((ts, EXFIL_CLIENT, qname, "A", "NOERROR", resp_time_ms))

    entries.sort(key=lambda x: x[0])

    with open(LOG_PATH, 'w') as f:
        f.write("# DNS Resolver Query Log\n")
        f.write("# Format: timestamp client_ip query_name query_type response_code response_time_ms\n")
        f.write("# Period: {} to {}\n".format(base_time.isoformat(), (base_time + timedelta(hours=2)).isoformat()))
        f.write("# Resolver: ns1.internal.corp (10.0.0.2)\n")
        f.write("#\n")
        for ts, client, qname, qtype, rcode, rtime in entries:
            f.write("{}Z {} {} {} {} {:.1f}ms\n".format(
                ts.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3],
                client, qname, qtype, rcode, rtime))


if __name__ == "__main__":
    generate_log()
