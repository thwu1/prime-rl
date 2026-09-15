#!/usr/bin/env python3
"""Tests for DNS exfiltration forensics task."""


import hashlib
import json
import os
import random
import struct
import subprocess
import uuid

import pytest

EXPECTED_SHA256 = "67198482032b4fb1244acd6ce868570bac4baabd374f0fb35942837342772dd0"
EXPECTED_TUNNEL_DOMAIN = "cdn-telemetry.example.net"
EXPECTED_TOTAL_TUNNEL = 72
EXPECTED_UNIQUE_CHUNKS = 60
EXPECTED_ENCODING = "base32"
EXPECTED_QUERY_TYPE = "TXT"
EXPECTED_RETRANSMISSIONS = 12


# ── Validation pcap generator (for testing detector generalization) ──

def _ip_chk(data):
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return ~s & 0xffff


def _enc_dns_name(name):
    enc = b""
    for label in name.encode("ascii").split(b"."):
        enc += bytes([len(label)]) + label
    return enc + b"\x00"


def _make_dns_q(qname, qtype, txid):
    hdr = struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    return hdr + _enc_dns_name(qname) + struct.pack("!HH", qtype, 1)


def _make_pkt(dns, ts, us, rng):
    eth = b'\x00' * 12 + b'\x08\x00'
    udp_l = 8 + len(dns)
    udp = struct.pack("!HHHH", rng.randint(32768, 65535), 53, udp_l, 0)
    ip_t = 20 + udp_l
    ip = struct.pack("!BBHHHBBH4s4s",
                     0x45, 0, ip_t, rng.randint(0, 65535), 0x4000,
                     64, 17, 0, b'\x0a\x00\x02\x0a', b'\x0a\x00\x02\x01')
    chk = _ip_chk(ip)
    ip = ip[:10] + struct.pack("!H", chk) + ip[12:]
    p = eth + ip + udp + dns
    return struct.pack("<IIII", ts, us, len(p), len(p)) + p


def _generate_validation_pcap(path, tunnel_domain, num_legit=60,
                              num_tunnel=25):
    """Generate a minimal pcap with a different tunnel for detector testing."""
    rng = random.Random(int.from_bytes(os.urandom(8), 'big'))

    legit_domains = [
        "www.google.com", "mail.google.com", "api.github.com",
        "www.amazon.com", "cdn.jsdelivr.net", "pypi.org",
        "archive.ubuntu.com", "www.wikipedia.org",
        "outlook.office365.com", "fonts.googleapis.com",
    ]

    pkts = []
    bt = 1710600000

    for _ in range(num_legit):
        d = rng.choice(legit_domains)
        dns = _make_dns_q(d, 1, rng.randint(0, 65535))
        pkts.append((bt + rng.randint(0, 600), rng.randint(0, 999999), dns))

    for seq in range(num_tunnel):
        chunk = bytes(rng.randint(0, 255) for _ in range(16))
        fqdn = f"{seq:04x}.{chunk.hex()}.{tunnel_domain}"
        dns = _make_dns_q(fqdn, 16, rng.randint(0, 65535))
        pkts.append((bt + 100 + seq * 3, rng.randint(0, 999999), dns))

    pkts.sort()
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts, us, dns in pkts:
            f.write(_make_pkt(dns, ts, us, rng))


# ── Test: Data Recovery ──

class TestExfiltration:
    """Verify the exfiltrated binary was correctly reconstructed."""

    def test_file_exists(self):
        assert os.path.isfile("/app/exfiltrated.bin"), \
            "Exfiltrated data file not found at /app/exfiltrated.bin"

    def test_file_not_empty(self):
        size = os.path.getsize("/app/exfiltrated.bin")
        assert size > 0, "exfiltrated.bin is empty"

    def test_sha256(self):
        with open("/app/exfiltrated.bin", "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        assert actual == EXPECTED_SHA256, (
            f"SHA256 mismatch: got {actual}, expected {EXPECTED_SHA256}"
        )


# ── Test: Structured Analysis ──

class TestAnalysis:
    """Verify the tunnel analysis JSON report."""

    @pytest.fixture(autouse=True)
    def load_analysis(self):
        path = "/app/tunnel_analysis.json"
        assert os.path.isfile(path), \
            "Analysis file not found at /app/tunnel_analysis.json"
        with open(path) as f:
            self.data = json.load(f)

    def test_tunnel_domain(self):
        assert self.data["tunnel_domain"] == EXPECTED_TUNNEL_DOMAIN

    def test_total_tunnel_queries(self):
        assert self.data["total_tunnel_queries"] == EXPECTED_TOTAL_TUNNEL

    def test_unique_chunks(self):
        assert self.data["unique_chunks"] == EXPECTED_UNIQUE_CHUNKS

    def test_encoding(self):
        assert self.data["encoding"] == EXPECTED_ENCODING

    def test_query_type(self):
        assert self.data["query_type"] == EXPECTED_QUERY_TYPE

    def test_retransmission_count(self):
        assert self.data["retransmission_count"] == EXPECTED_RETRANSMISSIONS


# ── Test: Detection Engineering ──

class TestDetector:
    """Verify the general-purpose DNS tunnel detector."""

    def test_detector_exists(self):
        assert os.path.isfile("/app/detector.py"), \
            "Detector not found at /app/detector.py"

    def test_detects_main_tunnel(self):
        """Detector must identify the tunnel domain in the original pcap."""
        result = subprocess.run(
            ["python3", "/app/detector.py", "/app/traffic.pcap"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, \
            f"detector.py failed: {result.stderr[:500]}"

        output = json.loads(result.stdout)
        assert "detected_tunnels" in output, \
            "Output missing 'detected_tunnels' key"
        assert isinstance(output["detected_tunnels"], list), \
            "'detected_tunnels' must be a list"
        assert len(output["detected_tunnels"]) > 0, \
            "No tunnels detected in main pcap"

        domains = [
            t["domain"].rstrip(".").lower()
            for t in output["detected_tunnels"]
        ]
        assert any(d == EXPECTED_TUNNEL_DOMAIN for d in domains), (
            f"Expected '{EXPECTED_TUNNEL_DOMAIN}' in detected domains, "
            f"got: {domains}"
        )

    def test_detects_validation_tunnel(self):
        """Detector must identify a tunnel in a never-before-seen pcap
        with a randomly generated tunnel domain."""
        random_suffix = uuid.uuid4().hex[:8]
        validation_domain = f"telemetry-{random_suffix}.example.org"
        pcap_path = f"/tmp/validation_{random_suffix}.pcap"

        _generate_validation_pcap(pcap_path, validation_domain)

        result = subprocess.run(
            ["python3", "/app/detector.py", pcap_path],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, \
            f"detector.py failed on validation pcap: {result.stderr[:500]}"

        output = json.loads(result.stdout)
        assert "detected_tunnels" in output
        assert isinstance(output["detected_tunnels"], list)
        assert len(output["detected_tunnels"]) > 0, \
            "No tunnels detected in validation pcap"

        domains = [
            t["domain"].rstrip(".").lower()
            for t in output["detected_tunnels"]
        ]
        assert any(d == validation_domain for d in domains), (
            f"Expected '{validation_domain}' in detected domains, "
            f"got: {domains}"
        )
