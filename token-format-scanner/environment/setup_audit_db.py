#!/usr/bin/env python3
"""Create the HTTP request audit log SQLite database."""
import sqlite3
import json
import base64

db_path = "/app/audit/http_requests.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("""
CREATE TABLE http_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    client_ip TEXT NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    headers TEXT NOT NULL,
    body TEXT,
    status_code INTEGER NOT NULL,
    response_size INTEGER NOT NULL
)
""")

c.execute("""
CREATE TABLE request_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    FOREIGN KEY (request_id) REFERENCES http_requests(id)
)
""")

c.execute("""
CREATE TABLE response_headers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    header_name TEXT NOT NULL,
    header_value TEXT NOT NULL,
    FOREIGN KEY (request_id) REFERENCES http_requests(id)
)
""")

requests = [
    # 1. Health check (no token)
    ("2024-03-15T09:00:01Z", "10.0.0.50", "GET", "/health",
     json.dumps({"User-Agent": "kube-probe/1.28", "Accept": "*/*"}),
     None, 200, 2),

    # 2. Authenticated request with token in Authorization header
    ("2024-03-15T09:12:07Z", "192.168.1.42", "GET", "/api/v2/repos",
     json.dumps({"Authorization": "token gho_j7MxP4sKqL8wYhTg6BeLpR0cHiA5fZ4ccSFC",
                 "User-Agent": "python-requests/2.31.0",
                 "Accept": "application/json"}),
     None, 200, 8492),

    # 3. Prometheus metrics scrape (no token)
    ("2024-03-15T09:15:00Z", "10.0.0.1", "GET", "/metrics",
     json.dumps({"User-Agent": "Prometheus/2.48.0", "Accept": "text/plain"}),
     None, 200, 14523),

    # 4. Deploy request with token in POST body
    ("2024-03-15T09:23:45Z", "192.168.1.100", "POST", "/api/v2/deploy",
     json.dumps({"Content-Type": "application/json", "User-Agent": "curl/8.4.0"}),
     json.dumps({"environment": "staging", "ref": "main",
                 "token": "ghr_q3RtY9vHuN5wXkSf8CdMpU0bFjA7gE30M4HM",
                 "force": False}),
     201, 156),

    # 5. Request with invalid-checksum token in URL query parameter
    ("2024-03-15T09:25:12Z", "192.168.1.200", "GET",
     "/api/v2/users?token=ghp_L8mNvJ6xYbHf2QdKpS0cGiA5eZw9TkZZZZZZ&page=1",
     json.dumps({"User-Agent": "python-requests/2.31.0",
                 "Accept": "application/json"}),
     None, 401, 89),

    # 6. Stripe webhook (decoy - not a GitHub token)
    ("2024-03-15T09:30:00Z", "192.168.1.55", "POST", "/webhooks/stripe",
     json.dumps({"Content-Type": "application/json",
                 "Stripe-Signature": "t=1234567890,v1=abc123"}),
     json.dumps({"api_key": "sk_live_4eC39HqLyjWDarjtT1zdp7dc",
                 "event": "charge.succeeded"}),
     200, 45),

    # 7. Internal API call with JWT bearer token (decoy)
    ("2024-03-15T09:45:33Z", "192.168.1.42", "PUT", "/api/v2/config",
     json.dumps({"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
                 "Content-Type": "application/json",
                 "User-Agent": "Go-http-client/2.0"}),
     json.dumps({"key": "max_connections", "value": 100}),
     204, 0),

    # 8. Another health check (no token)
    ("2024-03-15T10:00:01Z", "10.0.0.50", "GET", "/health",
     json.dumps({"User-Agent": "kube-probe/1.28", "Accept": "*/*"}),
     None, 200, 2),

    # 9. GraphQL request (no GitHub token, just normal auth)
    ("2024-03-15T10:05:22Z", "192.168.1.75", "POST", "/graphql",
     json.dumps({"Content-Type": "application/json",
                 "X-Request-ID": "req-abc123"}),
     json.dumps({"query": "{ viewer { login } }"}),
     200, 340),

    # 10. Slack notification (decoy)
    ("2024-03-15T10:10:00Z", "10.0.0.20", "POST", "/webhooks/slack",
     json.dumps({"Content-Type": "application/json",
                 "Authorization": "Bearer xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"}),
     json.dumps({"channel": "#alerts", "text": "Deploy completed"}),
     200, 12),

    # 11. OAuth callback with token in base64-encoded Set-Cookie response
    ("2024-03-15T09:28:30Z", "192.168.1.150", "GET",
     "/api/v2/oauth/callback?code=abc123&state=xyz789",
     json.dumps({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
                 "Accept": "text/html",
                 "Referer": "https://github.com/login/oauth/authorize"}),
     None, 302, 0),
]

for req in requests:
    c.execute(
        "INSERT INTO http_requests (timestamp, client_ip, method, path, headers, body, status_code, response_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        req
    )

# Add some metadata entries
metadata = [
    (2, "correlation_id", "corr-7f8a9b"),
    (2, "trace_id", "trace-abc123def456"),
    (4, "correlation_id", "corr-2c3d4e"),
    (4, "deploy_id", "deploy-20240315-001"),
    (5, "error_reason", "invalid_token"),
]

for meta in metadata:
    c.execute(
        "INSERT INTO request_metadata (request_id, key, value) VALUES (?, ?, ?)",
        meta
    )

# Response headers — the OAuth callback (request 11) sets a cookie
# containing a base64-encoded GitHub user-to-server token
token_b64 = "Z2h1X244WHpXM3lKdlI1dFlrU2g2RGdOcVUxZkhsQjRlQzFiRDk5MA=="
response_headers = [
    (2, "X-RateLimit-Remaining", "4998"),
    (2, "X-Request-Id", "req-def789"),
    (11, "Location", "https://app.acme.com/dashboard"),
    (11, "Set-Cookie", f"gh_session={token_b64}; Path=/; HttpOnly; Secure; SameSite=Lax"),
    (11, "X-Request-Id", "req-oauth-001"),
]

for rh in response_headers:
    c.execute(
        "INSERT INTO response_headers (request_id, header_name, header_value) VALUES (?, ?, ?)",
        rh
    )

conn.commit()
conn.close()
