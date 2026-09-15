#!/usr/bin/env python3
"""Tests for C2 redirector hardening and detection engineering task."""


import pytest
import subprocess
import time
import json
import os
import socket
import threading
import http.client
from http.server import HTTPServer, BaseHTTPRequestHandler


# ===================================================================
# Fixtures — teamserver stub + Apache
# ===================================================================

class TeamserverHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that mimics a C2 teamserver response."""

    def do_GET(self):
        self._respond()

    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        if cl > 0:
            self.rfile.read(cl)
        self._respond()

    def _respond(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('X-Teamserver', 'true')
        self.end_headers()
        self.wfile.write(b'TEAMSERVER_OK')

    def log_message(self, fmt, *args):
        pass


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


@pytest.fixture(scope='session', autouse=True)
def servers():
    """Start a mock teamserver on 50050 and (re)start Apache on 80."""
    # Start teamserver stub if port is free
    if not _port_in_use(50050):
        srv = HTTPServer(('127.0.0.1', 50050), TeamserverHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        time.sleep(0.5)
    else:
        srv = None

    # (Re)start Apache — try both methods for container compatibility
    subprocess.run(['service', 'apache2', 'stop'], capture_output=True)
    subprocess.run(['apache2ctl', 'stop'], capture_output=True)
    time.sleep(1)

    result = subprocess.run(['service', 'apache2', 'start'], capture_output=True)
    if result.returncode != 0:
        result = subprocess.run(['apache2ctl', 'start'], capture_output=True)
    assert result.returncode == 0, f"Apache failed to start: {result.stderr.decode()}"

    # Health check — wait for Apache to accept connections (up to 15 seconds)
    for attempt in range(15):
        time.sleep(1)
        try:
            conn = http.client.HTTPConnection('127.0.0.1', 80, timeout=3)
            conn.request('HEAD', '/')
            resp = conn.getresponse()
            resp.read()
            conn.close()
            break  # Apache is responding
        except Exception:
            continue
    else:
        pytest.fail("Apache did not respond within 15 seconds")

    yield

    subprocess.run(['service', 'apache2', 'stop'], capture_output=True)
    if srv:
        srv.shutdown()


def http_req(method, path, headers=None, timeout=10):
    """Send an HTTP request to Apache (localhost:80).
    Uses http.client (stdlib) — no redirect following, no external deps."""
    conn = http.client.HTTPConnection('127.0.0.1', 80, timeout=timeout)
    conn.request(method, path, headers=headers or {})
    resp = conn.getresponse()
    body = resp.read().decode('utf-8', errors='replace')
    hdrs = {}
    for name, val in resp.getheaders():
        hdrs[name] = val
    conn.close()
    return resp.status, body, hdrs


# ===================================================================
# Apache Redirector — Alpha profile
# ===================================================================

class TestAlphaProfile:
    HDRS = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/119.0.0.0 Safari/537.36'),
        'X-Request-ID': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        'Accept': 'application/json, text/plain, */*',
        'Cookie': 'session=dGVzdHNlc3Npb25kYXRhMTIzNA==',
    }

    def test_get_proxied(self):
        status, body, _ = http_req('GET',
            '/api/v2/status?id=abcdef01&token=1234567890abcdef',
            headers=self.HDRS)
        assert status == 200 and 'TEAMSERVER_OK' in body, \
            f"Expected 200+TEAMSERVER_OK, got {status}: {body[:200]}"

    def test_post_proxied(self):
        h = dict(self.HDRS)
        h['Content-Type'] = 'application/json'
        status, body, _ = http_req('POST', '/api/v2/submit', headers=h)
        assert status == 200 and 'TEAMSERVER_OK' in body, \
            f"Expected 200+TEAMSERVER_OK, got {status}: {body[:200]}"

    def test_wrong_ua_rejected(self):
        h = dict(self.HDRS); h['User-Agent'] = 'curl/8.4.0'
        status, _, _ = http_req('GET',
            '/api/v2/status?id=abcdef01&token=1234567890abcdef', headers=h)
        assert status == 302, f"Expected 302, got {status}"

    def test_no_cookie_rejected(self):
        h = dict(self.HDRS); del h['Cookie']
        status, _, _ = http_req('GET',
            '/api/v2/status?id=abcdef01&token=1234567890abcdef', headers=h)
        assert status == 302, f"Expected 302, got {status}"

    def test_bad_query_rejected(self):
        status, _, _ = http_req('GET',
            '/api/v2/status?id=ZZZZZZZZ&token=bad',
            headers=self.HDRS)
        assert status == 302, f"Expected 302, got {status}"

    def test_no_xrequestid_rejected(self):
        h = dict(self.HDRS); del h['X-Request-ID']
        status, _, _ = http_req('GET',
            '/api/v2/status?id=abcdef01&token=1234567890abcdef', headers=h)
        assert status == 302, f"Expected 302, got {status}"


# ===================================================================
# Apache Redirector — Bravo profile
# ===================================================================

class TestBravoProfile:
    HDRS = {
        'User-Agent': ('Mozilla/5.0 (compatible; MSIE 11.0; '
                       'Windows NT 10.0; Trident/7.0)'),
        'X-CDN-Node': 'edge-us-east-1',
        'X-Trace-Id': 'abcdef0123456789',
        'Cookie': '__cfduid=abcdef0123456789abcdef0123456789',
    }

    def test_get_proxied(self):
        status, body, _ = http_req('GET',
            '/static/assets/analytics.gif?v=1234&cb=abcdef012345',
            headers=self.HDRS)
        assert status == 200 and 'TEAMSERVER_OK' in body, \
            f"Expected 200+TEAMSERVER_OK, got {status}: {body[:200]}"

    def test_post_proxied(self):
        h = dict(self.HDRS); h['Content-Type'] = 'application/octet-stream'
        status, body, _ = http_req('POST',
            '/static/assets/telemetry', headers=h)
        assert status == 200 and 'TEAMSERVER_OK' in body, \
            f"Expected 200+TEAMSERVER_OK, got {status}: {body[:200]}"

    def test_wrong_ua_rejected(self):
        h = dict(self.HDRS)
        h['User-Agent'] = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/119.0.0.0 Safari/537.36')
        status, _, _ = http_req('GET',
            '/static/assets/analytics.gif?v=1234&cb=abcdef012345', headers=h)
        assert status == 302, f"Expected 302, got {status}"

    def test_no_cookie_rejected(self):
        h = dict(self.HDRS); del h['Cookie']
        status, _, _ = http_req('GET',
            '/static/assets/analytics.gif?v=1234&cb=abcdef012345', headers=h)
        assert status == 302, f"Expected 302, got {status}"


# ===================================================================
# Apache Redirector — Charlie profile
# ===================================================================

class TestCharlieProfile:
    HDRS = {
        'User-Agent': 'FeedParser/6.0.11 (+https://feedparser.org/)',
        'Accept': 'application/rss+xml, application/xml;q=0.9',
        'Cookie': 'FEEDSESSID=abcdefghijklmnopqrstuvwx',
    }

    def test_get_proxied(self):
        status, body, _ = http_req('GET',
            '/feeds/global/rss.xml?t=1700000000&src=news',
            headers=self.HDRS)
        assert status == 200 and 'TEAMSERVER_OK' in body, \
            f"Expected 200+TEAMSERVER_OK, got {status}: {body[:200]}"

    def test_post_proxied(self):
        h = dict(self.HDRS)
        h['Content-Type'] = 'application/x-www-form-urlencoded'
        status, body, _ = http_req('POST',
            '/feeds/global/subscribe', headers=h)
        assert status == 200 and 'TEAMSERVER_OK' in body, \
            f"Expected 200+TEAMSERVER_OK, got {status}: {body[:200]}"

    def test_wrong_ua_rejected(self):
        h = dict(self.HDRS); h['User-Agent'] = 'curl/8.4.0'
        status, _, _ = http_req('GET',
            '/feeds/global/rss.xml?t=1700000000&src=news', headers=h)
        assert status == 302, f"Expected 302, got {status}"

    def test_no_cookie_rejected(self):
        h = dict(self.HDRS); del h['Cookie']
        status, _, _ = http_req('GET',
            '/feeds/global/rss.xml?t=1700000000&src=news', headers=h)
        assert status == 302, f"Expected 302, got {status}"


# ===================================================================
# Apache Redirector — Catch-all
# ===================================================================

class TestCatchAll:
    def test_unknown_uri_redirected(self):
        status, _, hdrs = http_req('GET', '/some/random/page')
        assert status == 302, f"Expected 302, got {status}"
        assert 'example.com' in hdrs.get('Location', ''), \
            f"Expected redirect to example.com, got Location: {hdrs.get('Location', '')}"

    def test_probe_rejected(self):
        status, _, _ = http_req('GET', '/api/v2/status?id=test',
                            headers={'User-Agent': 'curl/8.4.0'})
        assert status == 302, f"Expected 302, got {status}"


# ===================================================================
# YARA Detection Rules
# ===================================================================

class TestYaraRules:
    def _yara_match(self, rule_file, target):
        r = subprocess.run(['yara', rule_file, target],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and len(r.stdout.strip()) > 0

    # Alpha rule
    def test_alpha_detects_payload001(self):
        assert self._yara_match('/app/detection/alpha.yar',
                                '/app/samples/payload_001.bin')

    def test_alpha_no_fp_payload002(self):
        assert not self._yara_match('/app/detection/alpha.yar',
                                    '/app/samples/payload_002.bin')

    def test_alpha_no_fp_payload003(self):
        assert not self._yara_match('/app/detection/alpha.yar',
                                    '/app/samples/payload_003.bin')

    def test_alpha_no_fp_clean001(self):
        assert not self._yara_match('/app/detection/alpha.yar',
                                    '/app/samples/clean_001.bin')

    def test_alpha_no_fp_clean002(self):
        assert not self._yara_match('/app/detection/alpha.yar',
                                    '/app/samples/clean_002.bin')

    # Bravo rule
    def test_bravo_detects_payload002(self):
        assert self._yara_match('/app/detection/bravo.yar',
                                '/app/samples/payload_002.bin')

    def test_bravo_no_fp_payload001(self):
        assert not self._yara_match('/app/detection/bravo.yar',
                                    '/app/samples/payload_001.bin')

    def test_bravo_no_fp_clean001(self):
        assert not self._yara_match('/app/detection/bravo.yar',
                                    '/app/samples/clean_001.bin')

    # Charlie rule
    def test_charlie_detects_payload003(self):
        assert self._yara_match('/app/detection/charlie.yar',
                                '/app/samples/payload_003.bin')

    def test_charlie_no_fp_payload001(self):
        assert not self._yara_match('/app/detection/charlie.yar',
                                    '/app/samples/payload_001.bin')

    def test_charlie_no_fp_clean002(self):
        assert not self._yara_match('/app/detection/charlie.yar',
                                    '/app/samples/clean_002.bin')


# ===================================================================
# Traffic Analysis
# ===================================================================

class TestTrafficAnalysis:
    @pytest.fixture(autouse=True)
    def load(self):
        with open('/app/analysis/c2_sessions.json') as f:
            self.data = json.load(f)

    def test_c2_alpha(self):
        assert self.data['c2_hosts'].get('10.0.0.50') == 'alpha'

    def test_c2_bravo(self):
        assert self.data['c2_hosts'].get('10.0.0.75') == 'bravo'

    def test_c2_charlie(self):
        assert self.data['c2_hosts'].get('10.0.0.120') == 'charlie'

    def test_c2_count(self):
        assert len(self.data['c2_hosts']) == 3

    def test_total_c2_requests(self):
        assert self.data['total_c2_requests'] == 40

    def test_analyst_ip(self):
        assert '172.16.0.10' in self.data['analyst_ips']
