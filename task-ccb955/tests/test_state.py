"""
Tests for SIP ALG packet boundary exploitation.

Verifies that:
  1. config.json MSS values match those in the PCAP captures
  2. /app/exploit.py generates payloads that trigger ALG pinholes
     on the correct ports and IPs across all four scenarios

"""

import json
import os
import struct
import subprocess
import sys
import importlib.util
import pytest


# ── module loaders ──────────────────────────────────────────────────

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def alg():
    return _load("alg_simulator", "/app/alg_simulator.py")


@pytest.fixture(scope="session")
def tcp():
    return _load("tcp_engine", "/app/tcp_engine.py")


@pytest.fixture(scope="session")
def exploit():
    return _load("exploit", "/app/exploit.py")


@pytest.fixture(scope="session")
def config():
    with open("/app/config.json") as f:
        return json.load(f)


# ── helpers ─────────────────────────────────────────────────────────

def _run_scenario(scenario, exploit_mod, alg_mod, tcp_mod):
    """Execute one scenario; return (expectations, segments)."""
    payload = exploit_mod.generate_payload(scenario)

    boundary = scenario["boundary"]
    headers = scenario["http_headers_template"].replace("{boundary}", boundary)

    body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    headers = headers.replace("{content_length}", str(len(body)))
    full_stream = headers.encode("utf-8") + body

    segmenter = tcp_mod.TCPSegmenter(scenario["mss"])
    segments = segmenter.segment(full_stream)

    tracker = alg_mod.SIPConnectionTracker(
        strict=scenario.get("strict_mode", False)
    )
    expectations = tracker.process_stream(segments, scenario["internal_ip"])
    return expectations, segments


def _get(config, sid):
    return next(s for s in config["scenarios"] if s["id"] == sid)


def _extract_mss_from_pcap(pcap_path):
    """Extract MSS from the SYN-ACK on port 5060 by parsing the PCAP binary."""
    with open(pcap_path, 'rb') as f:
        f.read(24)  # skip global header
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', rec)
            data = f.read(incl_len)
            if len(data) < 54:  # min eth(14)+ip(20)+tcp(20)
                continue
            ethertype = struct.unpack('>H', data[12:14])[0]
            if ethertype != 0x0800:
                continue
            proto = data[14 + 9]
            if proto != 6:
                continue
            ip_ihl = (data[14] & 0x0f) * 4
            tcp_off = 14 + ip_ihl
            sport = struct.unpack('>H', data[tcp_off:tcp_off+2])[0]
            flags = data[tcp_off + 13]
            is_syn = bool(flags & 0x02)
            is_ack = bool(flags & 0x10)
            if sport == 5060 and is_syn and is_ack:
                doff = (data[tcp_off + 12] >> 4) * 4
                i = tcp_off + 20
                end = tcp_off + doff
                while i < end:
                    kind = data[i]
                    if kind == 0:
                        break
                    if kind == 1:
                        i += 1
                        continue
                    opt_len = data[i + 1]
                    if kind == 2 and opt_len == 4:
                        return struct.unpack('>H', data[i+2:i+4])[0]
                    i += opt_len
    raise RuntimeError(f"No SYN-ACK from port 5060 in {pcap_path}")


# ── config completion tests ─────────────────────────────────────────

SCENARIO_IDS = [
    "chrome_standard",
    "firefox_small_mss",
    "safari_strict_alg",
    "edge_jumbo_mss",
]


@pytest.mark.parametrize("sid", SCENARIO_IDS)
class TestConfigCompletion:
    """Verify MSS values were correctly determined from PCAP captures."""

    def test_mss_populated(self, sid, config):
        sc = _get(config, sid)
        assert sc.get("mss") is not None, (
            f"{sid}: MSS is null — must be determined from capture"
        )

    def test_mss_is_integer(self, sid, config):
        sc = _get(config, sid)
        assert isinstance(sc.get("mss"), int), (
            f"{sid}: MSS must be an integer, got {type(sc.get('mss'))}"
        )

    def test_mss_matches_capture(self, sid, config):
        sc = _get(config, sid)
        pcap = sc.get("capture", f"/app/captures/{sid}.pcap")
        expected = _extract_mss_from_pcap(pcap)
        assert sc["mss"] == expected, (
            f"{sid}: config MSS {sc['mss']} != capture MSS {expected}"
        )


# ── basic sanity ────────────────────────────────────────────────────

class TestExploitModule:
    def test_file_exists(self):
        assert os.path.exists("/app/exploit.py"), "exploit.py not found"

    def test_has_generate_payload(self, exploit):
        assert callable(
            getattr(exploit, "generate_payload", None)
        ), "exploit.py must define generate_payload(scenario)"


# ── parametrized scenario tests ─────────────────────────────────────

SCENARIOS = [
    ("chrome_standard", 8080, "192.168.1.105"),
    ("firefox_small_mss", 22, "10.0.0.42"),
    ("safari_strict_alg", 443, "172.16.0.50"),
    ("edge_jumbo_mss", 9090, "192.168.0.1"),
]


@pytest.mark.parametrize("sid,expected_port,expected_ip", SCENARIOS)
class TestPinholeCreation:
    """Verify ALG pinhole is created with the correct port and IP."""

    def test_pinhole_exists(self, sid, expected_port, expected_ip,
                            exploit, alg, tcp, config):
        sc = _get(config, sid)
        exps, _ = _run_scenario(sc, exploit, alg, tcp)
        assert len(exps) >= 1, f"No pinhole created for {sid}"

    def test_correct_port(self, sid, expected_port, expected_ip,
                          exploit, alg, tcp, config):
        sc = _get(config, sid)
        exps, _ = _run_scenario(sc, exploit, alg, tcp)
        assert exps[0]["contact_port"] == expected_port, (
            f"{sid}: got port {exps[0]['contact_port']}, want {expected_port}"
        )

    def test_correct_ip(self, sid, expected_port, expected_ip,
                        exploit, alg, tcp, config):
        sc = _get(config, sid)
        exps, _ = _run_scenario(sc, exploit, alg, tcp)
        assert exps[0]["contact_ip"] == expected_ip, (
            f"{sid}: got ip {exps[0]['contact_ip']}, want {expected_ip}"
        )


@pytest.mark.parametrize("sid,expected_port,expected_ip", SCENARIOS)
class TestSegmentAlignment:
    """Verify the SIP REGISTER truly starts at a TCP segment boundary."""

    def test_register_at_boundary(self, sid, expected_port, expected_ip,
                                  exploit, alg, tcp, config):
        sc = _get(config, sid)
        _, segments = _run_scenario(sc, exploit, alg, tcp)

        found = any(
            seg.decode("utf-8", errors="ignore").startswith("REGISTER ")
            for seg in segments
        )
        assert found, (
            f"{sid}: REGISTER not found at start of any TCP segment"
        )


@pytest.mark.parametrize("sid,expected_port,expected_ip", SCENARIOS)
class TestPayloadStructure:
    """Verify the payload is well-formed multipart/form-data."""

    def test_contains_boundary(self, sid, expected_port, expected_ip,
                               exploit, alg, tcp, config):
        sc = _get(config, sid)
        payload = exploit.generate_payload(sc)
        body = payload if isinstance(payload, str) else payload.decode("utf-8")
        assert sc["boundary"] in body, (
            f"{sid}: boundary not found in payload body"
        )

    def test_contains_sip_register(self, sid, expected_port, expected_ip,
                                    exploit, alg, tcp, config):
        sc = _get(config, sid)
        payload = exploit.generate_payload(sc)
        body = payload if isinstance(payload, str) else payload.decode("utf-8")
        assert "REGISTER sip:" in body, (
            f"{sid}: SIP REGISTER not found in payload body"
        )

    def test_content_length_consistent(self, sid, expected_port, expected_ip,
                                        exploit, alg, tcp, config):
        """Content-Length in headers must equal actual body size."""
        sc = _get(config, sid)
        payload = exploit.generate_payload(sc)
        body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        body_len = len(body)

        boundary = sc["boundary"]
        headers = sc["http_headers_template"].replace("{boundary}", boundary)
        headers = headers.replace("{content_length}", str(body_len))

        assert "{content_length}" not in headers
        assert f"Content-Length: {body_len}" in headers.replace("\r\n", "\n") or \
               f"Content-Length: {body_len}" in headers
