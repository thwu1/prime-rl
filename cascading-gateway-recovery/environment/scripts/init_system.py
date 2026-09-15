#!/usr/bin/env python3
"""Initialize the system in a broken incident state."""
import sqlite3
import json
import os
import time
from datetime import datetime, timedelta

DB_PATH = "/app/data/config.db"
LOG_DIR = "/app/logs"
CACHE_FILE = "/app/data/health_cache.json"


def init_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS quota_policies (
            policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rules TEXT NOT NULL,
            enforce_mode TEXT DEFAULT 'enforce',
            path_prefix TEXT DEFAULT '*',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS config_versions (
            version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_json TEXT NOT NULL,
            pushed_by TEXT NOT NULL,
            pushed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS service_registry (
            service_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            port INTEGER NOT NULL,
            status TEXT DEFAULT 'unknown',
            last_heartbeat TEXT
        );
    """)

    policies = [
        (
            "global_rate_limit",
            json.dumps([{"path_pattern": "*", "max_rps": 1000, "window_sec": 60}]),
            "enforce",
            "*"
        ),
        (
            "api_v1_quota",
            "null",
            "enforce",
            "/api/v1/"
        ),
        (
            "internal_bypass",
            json.dumps([{"path_pattern": "/internal/*", "bypass": True}]),
            "permissive",
            "/internal/"
        ),
        (
            "analytics_throttle",
            json.dumps([{"path_pattern": "/api/v2/analytics/*", "max_rps": 100, "window_sec": 60}]),
            "enforce",
            "/api/v2/analytics/"
        ),
    ]

    for name, rules, mode, prefix in policies:
        conn.execute(
            "INSERT INTO quota_policies (name, rules, enforce_mode, path_prefix) "
            "VALUES (?, ?, ?, ?)",
            (name, rules, mode, prefix)
        )

    conn.execute(
        "INSERT INTO config_versions (config_json, pushed_by, pushed_at, status) "
        "VALUES (?, ?, ?, ?)",
        (
            json.dumps({"name": "initial_setup", "rules": [{"path_pattern": "*", "max_rps": 1000}]}),
            "deploy-bot@infra.internal",
            "2024-01-14 09:00:00",
            "superseded"
        )
    )
    conn.execute(
        "INSERT INTO config_versions (config_json, pushed_by, pushed_at, status) "
        "VALUES (?, ?, ?, ?)",
        (
            json.dumps({"name": "api_v1_quota", "rules": None, "path_prefix": "/api/v1/"}),
            "oncall-eng@infra.internal",
            "2024-01-15 10:30:00",
            "active"
        )
    )

    for i in range(1, 4):
        status = "crashed" if i != 2 else "running"
        conn.execute(
            "INSERT INTO service_registry (name, port, status, last_heartbeat) "
            "VALUES (?, ?, ?, ?)",
            (f"gateway-worker-{i}", 8080 + i, status, "2024-01-15 10:45:00")
        )

    conn.commit()
    conn.close()


def generate_crash_logs():
    os.makedirs(LOG_DIR, exist_ok=True)

    base_time = datetime(2024, 1, 15, 10, 30, 0)

    with open(os.path.join(LOG_DIR, "worker_1.log"), 'w') as f:
        for i in range(25):
            t = base_time + timedelta(seconds=i * 12)
            ts = t.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts} worker-1 INFO Starting worker 1 on port 8081\n")
            f.write(f"{ts} worker-1 INFO Connected to database\n")
            f.write(f"{ts} worker-1 INFO Loading quota policies for cache warmup...\n")
            f.write(f"{ts} worker-1 INFO Loaded policy: global_rate_limit (enforce)\n")
            f.write(f"{ts} worker-1 ERROR Fatal error during policy cache warmup: 'NoneType' object is not iterable\n")
            f.write(f"{ts} worker-1 ERROR Worker 1 shutting down due to startup failure\n")

    with open(os.path.join(LOG_DIR, "worker_2.log"), 'w') as f:
        t = base_time + timedelta(seconds=5)
        ts = t.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{ts} worker-2 INFO Starting worker 2 on port 8082\n")
        f.write(f"{ts} worker-2 INFO Connected to database\n")
        f.write(f"{ts} worker-2 WARNING HOTFIX_MODE=lenient: skipping policy cache warmup validation\n")
        f.write(f"{ts} worker-2 INFO Policy cache warmup skipped (lenient mode)\n")
        f.write(f"{ts} worker-2 INFO Server started on port 8082\n")
        for i in range(20):
            t = base_time + timedelta(seconds=30 + i * 8)
            ts = t.strftime("%Y-%m-%d %H:%M:%S")
            if i % 4 == 0:
                f.write(f"{ts} worker-2 INFO \"GET /health HTTP/1.1\" 200\n")
            else:
                f.write(f"{ts} worker-2 WARNING Request to /api/v1/users caught by lenient handler, returning empty response\n")
                f.write(f"{ts} worker-2 INFO \"GET /api/v1/users HTTP/1.1\" 200\n")

    with open(os.path.join(LOG_DIR, "worker_3.log"), 'w') as f:
        for i in range(25):
            t = base_time + timedelta(seconds=i * 12 + 2)
            ts = t.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts} worker-3 INFO Starting worker 3 on port 8083\n")
            f.write(f"{ts} worker-3 INFO Connected to database\n")
            f.write(f"{ts} worker-3 INFO Loading quota policies for cache warmup...\n")
            f.write(f"{ts} worker-3 INFO Loaded policy: global_rate_limit (enforce)\n")
            f.write(f"{ts} worker-3 ERROR Fatal error during policy cache warmup: 'NoneType' object is not iterable\n")
            f.write(f"{ts} worker-3 ERROR Worker 3 shutting down due to startup failure\n")

    with open(os.path.join(LOG_DIR, "config_pusher.log"), 'w') as f:
        t = base_time - timedelta(seconds=5)
        ts = t.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{ts} config_pusher INFO Received push request from oncall-eng@infra.internal\n")
        f.write(f"{ts} config_pusher INFO Validating config: api_v1_quota\n")
        f.write(f"{ts} config_pusher INFO Validation passed\n")
        f.write(f"{ts} config_pusher INFO Config pushed successfully: api_v1_quota\n")
        f.write(f"{ts} config_pusher INFO Notified 3 workers to reload configuration\n")

    with open(os.path.join(LOG_DIR, "monitor.log"), 'w') as f:
        t = base_time - timedelta(minutes=45)
        ts = t.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{ts} monitor INFO Health check completed: all workers healthy\n")
        f.write(f"{ts} monitor INFO Health status cached (TTL: 86400s)\n")
        t = base_time + timedelta(minutes=10)
        ts = t.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{ts} monitor INFO Health check: returning cached result (age: 3300s)\n")
        f.write(f"{ts} monitor INFO Cached status: overall_status=healthy\n")

    with open(os.path.join(LOG_DIR, "haproxy.log"), 'w') as f:
        for i in range(8):
            t = base_time + timedelta(seconds=i * 20)
            ts = t.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts} haproxy[1234]: Server gateway_workers/worker-1 is DOWN, reason: Layer4 connection problem, info: \"Connection refused\", check duration: 1ms\n")
            f.write(f"{ts} haproxy[1234]: Server gateway_workers/worker-3 is DOWN, reason: Layer4 connection problem, info: \"Connection refused\", check duration: 1ms\n")
            if i < 3:
                f.write(f"{ts} haproxy[1234]: Server gateway_workers/worker-2 is UP, reason: Layer7 check passed, code: 200, check duration: 5ms\n")


def create_stale_cache():
    """Create a stale health cache from before the incident."""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    cache_data = {
        "timestamp": time.time() - 120,
        "workers": {
            "8081": {"status": "healthy", "worker_id": 1, "port": 8081},
            "8082": {"status": "healthy", "worker_id": 2, "port": 8082},
            "8083": {"status": "healthy", "worker_id": 3, "port": 8083}
        },
        "database": {"status": "healthy"},
        "overall_status": "healthy",
        "from_cache": False,
        "cache_age_seconds": 0
    }
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache_data, f, indent=2)


def create_red_herrings():
    """Create misleading artifacts in the environment."""
    with open("/app/data/.config_push_lock", 'w') as f:
        f.write("locked by pid 4821 at 2024-01-15T10:29:55Z\n")


if __name__ == "__main__":
    init_database()
    generate_crash_logs()
    create_stale_cache()
    create_red_herrings()
    print("System initialized with incident state")
