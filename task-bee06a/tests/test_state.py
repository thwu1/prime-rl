"""
Tests for DNS tunnel forensics & detection engineering task.
"""

import os
import sys
import json
import random as _random
import importlib.util
import pytest

RESULTS_DIR = "/app/results"

EXPECTED_TUNNEL_DOMAIN = "cdn-telemetry.analytics-cdn.net"
EXPECTED_PACKET_COUNT = 21
EXPECTED_CHECKSUM = "0a56b613334948e33711bea518527a78fbd547e602434afc135daf19666be2b0"


def read_result(filename):
    path = os.path.join(RESULTS_DIR, filename)
    assert os.path.isfile(path), f"Result file not found: {path}"
    with open(path, "r") as f:
        return f.read().strip()


# --- Recovery tests ---


class TestTunnelDomain:
    def test_tunnel_domain_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "tunnel_domain.txt"))

    def test_tunnel_domain_correct(self):
        domain = read_result("tunnel_domain.txt")
        assert domain == EXPECTED_TUNNEL_DOMAIN, (
            f"Expected tunnel domain '{EXPECTED_TUNNEL_DOMAIN}', got '{domain}'"
        )


class TestPacketCount:
    def test_packet_count_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "packet_count.txt"))

    def test_packet_count_correct(self):
        count = read_result("packet_count.txt")
        assert count == str(EXPECTED_PACKET_COUNT), (
            f"Expected {EXPECTED_PACKET_COUNT} tunnel packets, got {count}"
        )


class TestExfiltratedData:
    def test_exfiltrated_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "exfiltrated.txt"))

    def test_exfiltrated_is_valid_json(self):
        data = read_result("exfiltrated.txt")
        parsed = json.loads(data)
        assert isinstance(parsed, dict), "Exfiltrated data should be a JSON object"

    def test_exfiltrated_has_classification(self):
        parsed = json.loads(read_result("exfiltrated.txt"))
        assert "classification" in parsed, "Missing 'classification' field"
        assert "COMINT" in parsed["classification"]

    def test_exfiltrated_has_project(self):
        parsed = json.loads(read_result("exfiltrated.txt"))
        assert "project" in parsed, "Missing 'project' field"
        assert parsed["project"] == "AUTUMN TEMPEST"

    def test_exfiltrated_has_access_key(self):
        parsed = json.loads(read_result("exfiltrated.txt"))
        assert "key" in parsed, "Missing 'key' field"
        assert parsed["key"] == "c7f3e2d1-4a8b-9c0e-5f6d-1234abcd5678"

    def test_exfiltrated_has_handler(self):
        parsed = json.loads(read_result("exfiltrated.txt"))
        assert "handler" in parsed, "Missing 'handler' field"

    def test_exfiltrated_has_notes(self):
        parsed = json.loads(read_result("exfiltrated.txt"))
        assert "notes" in parsed, "Missing 'notes' field"
        assert "compromised" in parsed["notes"].lower()


class TestChecksum:
    def test_checksum_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "checksum.txt"))

    def test_checksum_correct(self):
        checksum = read_result("checksum.txt")
        assert checksum == EXPECTED_CHECKSUM, (
            f"Expected checksum '{EXPECTED_CHECKSUM}', got '{checksum}'"
        )

    def test_checksum_matches_exfiltrated(self):
        """Verify checksum is consistent with the exfiltrated data file."""
        import hashlib
        data = read_result("exfiltrated.txt")
        computed = hashlib.sha256(data.encode("utf-8")).hexdigest()
        checksum = read_result("checksum.txt")
        assert computed == checksum, (
            f"Checksum '{checksum}' does not match SHA256 of exfiltrated.txt ('{computed}')"
        )


# --- Assessment tests ---


class TestAssessment:
    def test_assessment_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "assessment.txt"))

    def test_assessment_substantive(self):
        text = read_result("assessment.txt")
        assert len(text) >= 300, (
            f"Assessment too brief ({len(text)} chars, need >= 300)"
        )

    def test_assessment_identifies_weaknesses(self):
        """Assessment must identify at least 4 of 5 OPSEC weakness categories."""
        text = read_result("assessment.txt").lower()
        categories = {
            "history_exposure": any(k in text for k in [
                "bash_history", ".bash_history", "shell history",
                "command history", "history file", "passphrase in",
                "password in", "plaintext passphrase", "plaintext password",
            ]),
            "weak_crypto": any(k in text for k in [
                "xor", "weak cipher", "weak encryption",
                "simple cipher", "trivial cipher", "not aes",
                "inadequate encryption", "insecure cipher",
            ]),
            "key_derivation": any(k in text for k in [
                "key derivat", "derived from domain", "domain name as",
                "key from the domain", "sha256 of the domain",
                "tunnel domain", "domain.*key", "key.*domain",
                "observable key",
            ]),
            "artifact_persistence": any(k in text for k in [
                "binary", "artifact", "left on disk", "remained on",
                "not deleted", "not removed", "cleanup fail",
                "forensic artifact", "exfiltool", "incomplete cleanup",
                "incomplete removal",
            ]),
            "pattern_predictability": any(k in text for k in [
                "sequential", "sequence number", "predictable",
                "deterministic", "incrementing", "hex counter",
                "easily identif", "trivially detect", "pattern",
            ]),
        }
        identified = sum(v for v in categories.values())
        assert identified >= 4, (
            f"Assessment must identify >= 4 of 5 weakness categories, found {identified}. "
            f"Detected: {[k for k, v in categories.items() if v]}. "
            f"Missing: {[k for k, v in categories.items() if not v]}."
        )


# --- Detector tests ---


class TestDetector:
    @pytest.fixture(autouse=True)
    def load_detector(self):
        path = os.path.join(RESULTS_DIR, "detector.py")
        assert os.path.isfile(path), "detector.py not found at /app/results/detector.py"
        spec = importlib.util.spec_from_file_location("detector", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "detect"), (
            "detector.py must define a function: detect(query: str) -> bool"
        )
        self.detect = mod.detect

    def _tunnel_queries(self):
        """Generate diverse tunnel queries for held-out testing."""
        rng = _random.Random(42)
        b32_alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        configs = [
            ("evil-cdn.example.net", "x", 20),
            ("data.badserver.org", "t", 15),
            ("metrics.c2host.io", "d", 25),
            ("api.shadowrelay.com", "x", 18),
            ("cdn.darkpipe.net", "z", 20),
        ]
        queries = []
        for domain, marker, csz in configs:
            payload = "".join(rng.choices(b32_alphabet, k=csz * 5))
            for seq in range(5):
                chunk = payload[seq * csz:(seq + 1) * csz]
                queries.append(f"{chunk}.{seq:02x}.{marker}.{domain}")
        return queries

    def _benign_queries(self):
        """Realistic benign DNS queries including tricky long subdomains."""
        return [
            "www.google.com",
            "mail.google.com",
            "api.github.com",
            "fonts.googleapis.com",
            "cdn.jsdelivr.net",
            "static.cloudflareinsights.com",
            "analytics.google.com",
            "mx1.mail.protection.outlook.com",
            "ns1.dns.example.com",
            "outlook.office365.com",
            "login.microsoftonline.com",
            "pool.ntp.org",
            "time.windows.com",
            "20230601._domainkey.gmail.com",
            "selector1._domainkey.outlook.com",
            "_acme-challenge.example.com",
            "_dmarc.example.com",
            "_sip._tcp.voip.example.com",
            "d1ab23cd45ef.cloudfront.net",
            "ec2-54-123-45-67.compute-1.amazonaws.com",
            "very-long-subdomain-for-loadbalancer.us-east-1.elb.amazonaws.com",
            "v1234567890.assets.example.com",
            "wpad.example.com",
            "updates.example.com",
            "tracker.example.com",
        ]

    def test_detector_returns_bool(self):
        result = self.detect("www.google.com")
        assert isinstance(result, bool), (
            f"detect() must return bool, got {type(result).__name__}"
        )

    def test_detector_recall(self):
        """Detector must catch >= 85% of tunnel queries across varied configs."""
        tunnels = self._tunnel_queries()
        tp = sum(1 for q in tunnels if self.detect(q))
        recall = tp / len(tunnels)
        assert recall >= 0.85, (
            f"Recall {recall:.2f} < 0.85 ({tp}/{len(tunnels)} detected)"
        )

    def test_detector_precision(self):
        """Detector must not flag > 10% false positives on realistic benign queries."""
        tunnels = self._tunnel_queries()
        benign = self._benign_queries()
        tp = sum(1 for q in tunnels if self.detect(q))
        fp = sum(1 for q in benign if self.detect(q))
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        assert precision >= 0.90, (
            f"Precision {precision:.2f} < 0.90 (TP={tp}, FP={fp})"
        )

    def test_detector_handles_edge_cases(self):
        """Detector must not crash on edge-case inputs."""
        edge_cases = ["", ".", "com", "a.b", "x" * 200 + ".com"]
        for q in edge_cases:
            result = self.detect(q)
            assert isinstance(result, bool), (
                f"detect('{q[:30]}...') returned {type(result).__name__}, expected bool"
            )
