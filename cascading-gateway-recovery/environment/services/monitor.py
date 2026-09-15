#!/usr/bin/env python3
"""Health monitoring service for the API gateway system."""

import json
import time
import sys
import os
import urllib.request

WORKER_PORTS = [8081, 8082, 8083]
DB_PATH = "/app/data/config.db"
CACHE_FILE = "/app/data/health_cache.json"
CACHE_TTL = 86400


def check_worker_health(port):
    """Check health of a single worker."""
    try:
        req = urllib.request.Request(f"http://localhost:{port}/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


def check_db_health():
    """Check database connectivity."""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=2)
        conn.execute("SELECT COUNT(*) FROM quota_policies")
        conn.close()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


def get_cached_status():
    """Return cached health status if cache file exists and TTL hasn't expired."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                cached = json.load(f)
            age = time.time() - cached.get("timestamp", 0)
            if age < CACHE_TTL:
                cached["from_cache"] = True
                cached["cache_age_seconds"] = int(age)
                return cached
        except (json.JSONDecodeError, IOError):
            pass
    return None


def perform_health_check():
    """Perform a live health check of all components."""
    health = {
        "timestamp": time.time(),
        "workers": {},
        "database": check_db_health(),
        "from_cache": False,
        "cache_age_seconds": 0
    }

    for port in WORKER_PORTS:
        health["workers"][str(port)] = check_worker_health(port)

    all_healthy = all(
        w.get("status") == "healthy" for w in health["workers"].values()
    ) and health["database"].get("status") == "healthy"

    health["overall_status"] = "healthy" if all_healthy else "degraded"

    with open(CACHE_FILE, 'w') as f:
        json.dump(health, f)

    return health


def main():
    if "--check" in sys.argv:
        cached = get_cached_status()
        if cached is not None:
            print(json.dumps(cached))
            return

        health = perform_health_check()
        print(json.dumps(health))
    elif "--live" in sys.argv:
        health = perform_health_check()
        print(json.dumps(health))
    else:
        while True:
            health = perform_health_check()
            status_line = f"[{time.strftime('%H:%M:%S')}] {health['overall_status']}"
            for port, info in health["workers"].items():
                status_line += f" | worker-{port}: {info.get('status', 'unknown')}"
            print(status_line, flush=True)
            time.sleep(30)


if __name__ == "__main__":
    main()
