"""Tests verifying full recovery from the cascading API gateway failure."""

import subprocess
import json
import time
import sqlite3
import re
import os


def _curl(url, timeout=5):
    """Helper: run curl and return (returncode, stdout)."""
    result = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 5
    )
    return result.returncode, result.stdout


def _curl_status(url, timeout=5):
    """Helper: run curl and return HTTP status code as string."""
    result = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         "--max-time", str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 5
    )
    return result.stdout.strip()


class TestWorkerHealth:
    """All gateway workers must be running and responding."""

    def test_worker_1_healthy(self):
        status = _curl_status("http://localhost:8081/health")
        assert status == "200", f"Worker 1 health check returned {status}"

    def test_worker_2_healthy(self):
        status = _curl_status("http://localhost:8082/health")
        assert status == "200", f"Worker 2 health check returned {status}"

    def test_worker_3_healthy(self):
        status = _curl_status("http://localhost:8083/health")
        assert status == "200", f"Worker 3 health check returned {status}"


class TestLoadBalancer:
    """HAProxy must distribute traffic across healthy workers."""

    def test_haproxy_serves_requests(self):
        rc, body = _curl("http://localhost:80/api/v1/users")
        assert rc == 0 and body, "HAProxy returned empty or failed"
        data = json.loads(body)
        assert data.get("status") == "ok", f"Unexpected response: {data}"

    def test_haproxy_distributes_to_multiple_workers(self):
        worker_ids = set()
        for _ in range(15):
            rc, body = _curl("http://localhost:80/api/v1/users")
            if rc == 0 and body:
                try:
                    data = json.loads(body)
                    wid = data.get("worker_id")
                    if wid is not None:
                        worker_ids.add(wid)
                except json.JSONDecodeError:
                    pass
        assert len(worker_ids) >= 2, (
            f"Traffic only reached worker(s) {worker_ids}; "
            "expected distribution across at least 2"
        )


class TestAPIResponses:
    """API requests must return valid, non-empty JSON responses."""

    def test_api_v1_returns_valid_response(self):
        """The specific path that was causing crashes must now work."""
        for port in [8081, 8082, 8083]:
            rc, body = _curl(f"http://localhost:{port}/api/v1/users")
            assert rc == 0, f"Worker on port {port} unreachable"
            data = json.loads(body)
            assert data != {}, (
                f"Worker on port {port} returned empty response (silent data loss)"
            )
            assert data.get("status") == "ok", (
                f"Worker on port {port} returned unexpected status: {data}"
            )

    def test_api_v1_via_loadbalancer(self):
        for _ in range(5):
            rc, body = _curl("http://localhost:80/api/v1/quota/check")
            assert rc == 0, "Request through load balancer failed"
            data = json.loads(body)
            assert data.get("status") == "ok", f"Bad response: {data}"
            assert "worker_id" in data, f"Missing worker_id in response: {data}"


class TestDatabaseFix:
    """Corrupted quota policy data must be repaired."""

    def test_no_null_rules_in_active_policies(self):
        conn = sqlite3.connect("/app/data/config.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT name, rules FROM quota_policies WHERE active = 1"
        )
        for row in cursor.fetchall():
            parsed = json.loads(row["rules"])
            assert parsed is not None, (
                f"Policy '{row['name']}' has null rules"
            )
            assert isinstance(parsed, list), (
                f"Policy '{row['name']}' rules is {type(parsed).__name__}, expected list"
            )
        conn.close()


class TestConfigValidation:
    """Config management must reject invalid policy data."""

    def test_rejects_null_rules(self):
        bad_config = '{"name": "test_bad", "rules": null, "path_prefix": "/test/"}'
        result = subprocess.run(
            ["python3", "/app/services/config_pusher.py", "--validate", bad_config],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0, (
            f"Config pusher accepted null rules. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )

    def test_rejects_string_rules(self):
        bad_config = '{"name": "test_bad", "rules": "not_a_list"}'
        result = subprocess.run(
            ["python3", "/app/services/config_pusher.py", "--validate", bad_config],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0, (
            "Config pusher accepted string rules instead of list"
        )

    def test_accepts_valid_rules(self):
        good_config = json.dumps({
            "name": "test_good",
            "rules": [{"path_pattern": "/test/*", "max_rps": 100}],
            "path_prefix": "/test/"
        })
        result = subprocess.run(
            ["python3", "/app/services/config_pusher.py", "--validate", good_config],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Config pusher rejected valid config: {result.stderr}"
        )


class TestWorkerResilience:
    """Workers must handle bad policy data without crashing."""

    def test_survives_null_rules_in_database(self):
        """Insert a bad policy, make a request, verify worker survives."""
        conn = sqlite3.connect("/app/data/config.db")
        conn.execute(
            "INSERT INTO quota_policies (name, rules, enforce_mode, path_prefix, active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("_test_transient_null", "null", "enforce", "/api/v1/_test_null/", 1)
        )
        conn.commit()

        try:
            _curl("http://localhost:8081/api/v1/_test_null/probe")
            time.sleep(1)
            status = _curl_status("http://localhost:8081/health")
            assert status == "200", (
                f"Worker 1 crashed after encountering null rules (health: {status})"
            )
        finally:
            conn.execute(
                "DELETE FROM quota_policies WHERE name = '_test_transient_null'"
            )
            conn.commit()
            conn.close()


class TestReconnectionBackoff:
    """Database reconnection must use backoff to prevent thundering herd."""

    def test_connect_method_has_delay(self):
        with open("/app/services/gateway_worker.py") as f:
            code = f.read()

        connect_start = code.find("def _connect(self)")
        assert connect_start != -1, "Cannot find _connect method in worker code"

        next_def = code.find("\n    def ", connect_start + 20)
        connect_body = code[connect_start:next_def] if next_def != -1 else code[connect_start:]

        assert "time.sleep(0)" not in connect_body, (
            "Reconnection uses time.sleep(0) - no real backoff"
        )

        sleep_calls = re.findall(r'time\.sleep\(([^)]+)\)', connect_body)
        has_positive_sleep = any(
            s.strip() not in ('0', '0.0', '0.00') for s in sleep_calls
        )

        has_backoff_keywords = any(
            kw in connect_body.lower() for kw in
            ['backoff', 'exponential', 'jitter', '2 **', '2**', 'pow(2', 'random']
        )

        assert has_positive_sleep or has_backoff_keywords, (
            "No backoff or meaningful delay found in _connect method. "
            "Reconnection without backoff causes thundering herd."
        )


class TestMonitorAccuracy:
    """Health monitoring must report accurate, current data."""

    def test_monitor_not_stale(self):
        result = subprocess.run(
            ["python3", "/app/services/monitor.py", "--check"],
            capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 0, f"Monitor failed: {result.stderr}"
        data = json.loads(result.stdout)

        if data.get("from_cache"):
            age = data.get("cache_age_seconds", 99999)
            assert age < 120, (
                f"Monitor returning stale cached data (age: {age}s). "
                "Cache TTL may be too high."
            )

    def test_monitor_cache_ttl_reasonable(self):
        with open("/app/services/monitor.py") as f:
            code = f.read()

        ttl_matches = re.findall(r'CACHE_TTL\s*=\s*(\d+)', code)
        for ttl_str in ttl_matches:
            ttl = int(ttl_str)
            assert ttl <= 120, (
                f"Monitor CACHE_TTL is {ttl}s - far too long for health monitoring. "
                "Stale health data masks real failures."
            )


class TestSystemStability:
    """System must remain stable under sustained load."""

    def test_stability_under_load(self):
        for _ in range(20):
            _curl("http://localhost:80/api/v1/users")

        time.sleep(3)

        for port in [8081, 8082, 8083]:
            status = _curl_status(f"http://localhost:{port}/health")
            assert status == "200", (
                f"Worker on port {port} became unhealthy after load test"
            )

    def test_haproxy_still_serving_after_load(self):
        rc, body = _curl("http://localhost:80/api/v1/status")
        assert rc == 0, "HAProxy not serving after load test"
        data = json.loads(body)
        assert data.get("status") == "ok"
