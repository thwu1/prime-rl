"""Tests for DNS resolver security hardening and conformance."""

import json
import struct
import sys
import socket
import threading
import importlib
import os
import shutil

import pytest
from unittest.mock import patch

# Ensure /app/resolver.py exists (restore from backup if needed)
if not os.path.exists("/app/resolver.py") and os.path.exists("/opt/task/resolver.py"):
    os.makedirs("/app", exist_ok=True)
    shutil.copy2("/opt/task/resolver.py", "/app/resolver.py")

sys.path.insert(0, "/app")
import resolver


# ---------------------------------------------------------------------------
# Test 1: Compression pointer loop protection
# ---------------------------------------------------------------------------

class TestCompressionLoopProtection:
    """DNS name decoder must not infinite-loop on crafted compression pointers."""

    @staticmethod
    def _craft_loop_packet():
        """Build a DNS response with a self-referencing compression pointer."""
        header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
        qname = b"\x07example\x03com\x00"
        question = qname + struct.pack("!HH", 1, 1)
        answer_offset = len(header) + len(question)
        ptr_hi = 0xC0 | ((answer_offset >> 8) & 0x3F)
        ptr_lo = answer_offset & 0xFF
        answer_name = bytes([ptr_hi, ptr_lo])
        answer_fields = struct.pack("!HHIH", 1, 1, 300, 4) + bytes([1, 2, 3, 4])
        return header + question + answer_name + answer_fields

    def test_does_not_hang(self):
        """Parser must terminate on a compression pointer cycle."""
        packet = self._craft_loop_packet()
        finished = threading.Event()

        def parse():
            try:
                resolver.parse_dns_packet(packet)
            except Exception:
                pass
            finished.set()

        t = threading.Thread(target=parse, daemon=True)
        t.start()
        assert finished.wait(timeout=5), (
            "decode_dns_name entered an infinite loop on a self-referencing "
            "compression pointer"
        )

    def test_raises_error(self):
        """Parser should raise an error on a compression pointer loop."""
        packet = self._craft_loop_packet()
        finished = threading.Event()
        raised = [False]

        def parse():
            try:
                resolver.parse_dns_packet(packet)
            except Exception:
                raised[0] = True
            finished.set()

        t = threading.Thread(target=parse, daemon=True)
        t.start()
        if not finished.wait(timeout=5):
            pytest.fail("Parser hung on compression pointer cycle")
        assert raised[0], (
            "Parser did not raise an error for a compression pointer loop"
        )


# ---------------------------------------------------------------------------
# Helpers for mock-based resolution tests
# ---------------------------------------------------------------------------

def _make_packet(answers=None, authorities=None, additionals=None,
                 question_name="test.example.com", rcode=0):
    """Construct a DNSPacket for use in mocked send_query calls."""
    answers = answers or []
    authorities = authorities or []
    additionals = additionals or []
    header = resolver.DNSHeader(
        id=0xBEEF, flags=(0x8000 | rcode),
        num_questions=1,
        num_answers=len(answers),
        num_authorities=len(authorities),
        num_additionals=len(additionals),
    )
    question = resolver.DNSQuestion(question_name, resolver.TYPE_A, resolver.CLASS_IN)
    return resolver.DNSPacket(header, [question], answers, authorities, additionals)


# ---------------------------------------------------------------------------
# Test 2: CNAME chain following
# ---------------------------------------------------------------------------

class TestCNAMEResolution:
    """The resolver must follow CNAME records to their ultimate A-record target."""

    def test_single_hop(self):
        """Follow a single CNAME redirect to its A record."""
        cname_resp = _make_packet(
            question_name="www.example.com",
            answers=[resolver.DNSRecord(
                "www.example.com", resolver.TYPE_CNAME, resolver.CLASS_IN,
                300, "web.example.com",
            )],
        )
        a_resp = _make_packet(
            question_name="web.example.com",
            answers=[resolver.DNSRecord(
                "web.example.com", resolver.TYPE_A, resolver.CLASS_IN,
                300, "93.184.216.34",
            )],
        )
        call_count = [0]

        def mock_sq(server, name, type_=resolver.TYPE_A, timeout=5.0):
            call_count[0] += 1
            if call_count[0] > 60:
                raise RuntimeError("Too many queries — possible infinite loop")
            if name.lower().rstrip(".") == "www.example.com":
                return cname_resp
            if name.lower().rstrip(".") == "web.example.com":
                return a_resp
            return _make_packet(rcode=3)

        with patch.object(resolver, "send_query", side_effect=mock_sq):
            result = resolver.resolve("www.example.com", resolver.TYPE_A)

        assert result == "93.184.216.34", (
            f"Expected 93.184.216.34 for CNAME www.example.com -> "
            f"web.example.com, got {result}"
        )

    def test_multi_hop(self):
        """Follow a two-hop CNAME chain: alias1 -> alias2 -> real."""
        responses = {
            "alias1.example.com": _make_packet(
                answers=[resolver.DNSRecord(
                    "alias1.example.com", resolver.TYPE_CNAME, resolver.CLASS_IN,
                    300, "alias2.example.com",
                )],
            ),
            "alias2.example.com": _make_packet(
                answers=[resolver.DNSRecord(
                    "alias2.example.com", resolver.TYPE_CNAME, resolver.CLASS_IN,
                    300, "real.example.com",
                )],
            ),
            "real.example.com": _make_packet(
                answers=[resolver.DNSRecord(
                    "real.example.com", resolver.TYPE_A, resolver.CLASS_IN,
                    300, "10.0.0.1",
                )],
            ),
        }
        call_count = [0]

        def mock_sq(server, name, type_=resolver.TYPE_A, timeout=5.0):
            call_count[0] += 1
            if call_count[0] > 90:
                raise RuntimeError("Too many queries")
            key = name.lower().rstrip(".")
            return responses.get(key, _make_packet(rcode=3))

        with patch.object(resolver, "send_query", side_effect=mock_sq):
            result = resolver.resolve("alias1.example.com", resolver.TYPE_A)

        assert result == "10.0.0.1", (
            f"Expected 10.0.0.1 for two-hop CNAME chain, got {result}"
        )


# ---------------------------------------------------------------------------
# Test 3: NS resolution without glue records
# ---------------------------------------------------------------------------

class TestNSWithoutGlue:
    """When a delegation has no glue record, the resolver must recursively
    resolve the NS hostname before continuing."""

    def test_resolves_ns_hostname(self):
        delegation_resp = _make_packet(
            question_name="target.example.com",
            authorities=[resolver.DNSRecord(
                "example.com", resolver.TYPE_NS, resolver.CLASS_IN,
                86400, "ns1.other.com",
            )],
        )
        ns_a_resp = _make_packet(
            question_name="ns1.other.com",
            answers=[resolver.DNSRecord(
                "ns1.other.com", resolver.TYPE_A, resolver.CLASS_IN,
                86400, "10.0.0.53",
            )],
        )
        final_resp = _make_packet(
            question_name="target.example.com",
            answers=[resolver.DNSRecord(
                "target.example.com", resolver.TYPE_A, resolver.CLASS_IN,
                300, "192.168.1.1",
            )],
        )
        call_count = [0]

        def mock_sq(server, name, type_=resolver.TYPE_A, timeout=5.0):
            call_count[0] += 1
            if call_count[0] > 60:
                raise RuntimeError("Too many queries")
            key = name.lower().rstrip(".")
            if key == "target.example.com":
                if server == "10.0.0.53":
                    return final_resp
                return delegation_resp
            if key == "ns1.other.com":
                return ns_a_resp
            return _make_packet(rcode=3)

        with patch.object(resolver, "send_query", side_effect=mock_sq):
            result = resolver.resolve("target.example.com", resolver.TYPE_A)

        assert result == "192.168.1.1", (
            f"Expected 192.168.1.1 when NS has no glue, got {result}"
        )


# ---------------------------------------------------------------------------
# Test 4: EDNS0 support
# ---------------------------------------------------------------------------

class TestEDNS0Support:
    """Queries must include an EDNS0 OPT pseudo-record."""

    def test_query_contains_opt_record(self):
        """build_query output must contain an OPT record (type 41)."""
        query = resolver.build_query("example.com", resolver.TYPE_A)
        packet = resolver.parse_dns_packet(query)
        opt_records = [r for r in packet.additionals if r.type_ == resolver.TYPE_OPT]
        assert len(opt_records) >= 1, (
            "No OPT record found in query — EDNS0 not implemented"
        )

    def test_advertises_adequate_buffer(self):
        """The OPT record's class field (= UDP payload size) should be >= 1232."""
        query = resolver.build_query("example.com", resolver.TYPE_A)
        packet = resolver.parse_dns_packet(query)
        opt_records = [r for r in packet.additionals if r.type_ == resolver.TYPE_OPT]
        if not opt_records:
            pytest.fail("No OPT record found — cannot check buffer size")
        udp_size = opt_records[0].class_
        assert 1232 <= udp_size <= 65535, (
            f"EDNS0 UDP payload size {udp_size} is outside the "
            f"recommended range [1232, 65535]"
        )


# ---------------------------------------------------------------------------
# Test 5: Receive buffer handles EDNS0-sized responses
# ---------------------------------------------------------------------------

class TestReceiveBufferSize:
    """The socket receive buffer must not truncate large DNS responses."""

    @staticmethod
    def _build_large_response():
        """Build a valid DNS response with many A records, exceeding 512 bytes."""
        num_answers = 40
        qname = b"\x03big\x07example\x03com\x00"

        header = struct.pack("!HHHHHH", 0xAAAA, 0x8180, 1, num_answers, 0, 0)
        question = qname + struct.pack("!HH", 1, 1)

        answers = b""
        for i in range(num_answers):
            # Compression pointer to qname at offset 12
            name_ptr = struct.pack("!H", 0xC00C)
            a_record = name_ptr + struct.pack("!HHIH", 1, 1, 300, 4) + bytes([10, 0, i % 256, 1])
            answers += a_record

        response = header + question + answers
        return response, num_answers

    def test_handles_large_response(self):
        """send_query must receive responses larger than 512 bytes intact."""
        large_response, expected_count = self._build_large_response()
        assert len(large_response) > 512, "Test setup error: response not large enough"

        with patch.object(resolver.random, 'randint', return_value=0xAAAA):
            with patch.object(resolver.socket, 'socket') as MockSockCls:
                mock_sock = MockSockCls.return_value

                # Simulate real socket behavior: truncate data to buffer size
                def mock_recvfrom(bufsize):
                    return (large_response[:bufsize], ("198.41.0.4", 53))

                mock_sock.recvfrom.side_effect = mock_recvfrom

                try:
                    result = resolver.send_query("198.41.0.4", "big.example.com")
                    assert len(result.answers) == expected_count, (
                        f"Expected {expected_count} answers but got "
                        f"{len(result.answers)} — receive buffer may be too small "
                        f"for EDNS0-sized responses"
                    )
                except (ValueError, struct.error) as e:
                    pytest.fail(
                        f"Failed to parse response of {len(large_response)} bytes "
                        f"(likely truncated by insufficient recvfrom buffer): {e}"
                    )


# ---------------------------------------------------------------------------
# Test 6: Transaction ID verification
# ---------------------------------------------------------------------------

class TestTransactionIDVerification:
    """send_query must verify response transaction IDs to prevent spoofing."""

    def test_rejects_spoofed_response(self):
        """send_query must not accept a response whose transaction ID
        doesn't match the query."""
        # Build a valid DNS response with WRONG transaction ID (0xBBBB)
        resp_header = struct.pack("!HHHHHH", 0xBBBB, 0x8180, 1, 1, 0, 0)
        qname = b"\x04test\x07example\x03com\x00"
        resp_q = qname + struct.pack("!HH", 1, 1)
        resp_a = qname + struct.pack("!HHIH", 1, 1, 300, 4) + bytes([10, 0, 0, 1])
        wrong_id_response = resp_header + resp_q + resp_a

        accepted_wrong_id = False

        # Force query to use transaction ID 0xAAAA
        with patch.object(resolver.random, 'randint', return_value=0xAAAA):
            with patch.object(resolver.socket, 'socket') as MockSockCls:
                mock_sock = MockSockCls.return_value
                # First recv returns wrong-ID response, second raises timeout
                mock_sock.recvfrom.side_effect = [
                    (wrong_id_response, ("198.41.0.4", 53)),
                    socket.timeout("no more responses"),
                ]

                try:
                    result = resolver.send_query("198.41.0.4", "test.example.com")
                    # If resolver returns without checking ID, it accepted the
                    # spoofed packet
                    if result.header.id == 0xBBBB:
                        accepted_wrong_id = True
                except Exception:
                    pass  # Timeout or ValueError is acceptable — means it rejected

        assert not accepted_wrong_id, (
            "send_query accepted a DNS response with transaction ID 0xBBBB "
            "when the query used 0xAAAA — vulnerable to DNS cache poisoning"
        )


# ---------------------------------------------------------------------------
# Test 7: End-to-end resolution (requires network)
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """Sanity check that the resolver can resolve a real domain after fixes."""

    def test_resolve_example_com(self):
        """Resolve example.com over the real internet."""
        importlib.reload(resolver)
        result = None
        for _attempt in range(3):
            try:
                result = resolver.resolve("example.com", resolver.TYPE_A)
                if result is not None:
                    break
            except Exception:
                continue

        assert result is not None, "Failed to resolve example.com after 3 attempts"
        parts = result.split(".")
        assert len(parts) == 4, f"{result} is not a valid IPv4 address"
        for p in parts:
            assert p.isdigit() and 0 <= int(p) <= 255, (
                f"Invalid octet '{p}' in resolved address {result}"
            )


# ---------------------------------------------------------------------------
# Test 8: Audit report validation
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"vulnerability", "protocol_violation", "missing_feature"}
VALID_SEVERITIES = {"critical", "high", "medium"}


class TestAuditReport:
    """The audit report at /app/audit.json must conform to the specified schema."""

    def test_exists(self):
        assert os.path.exists("/app/audit.json"), "/app/audit.json does not exist"

    def test_valid_json(self):
        with open("/app/audit.json") as f:
            try:
                json.load(f)
            except json.JSONDecodeError as e:
                pytest.fail(f"/app/audit.json is not valid JSON: {e}")

    def test_has_findings(self):
        with open("/app/audit.json") as f:
            data = json.load(f)
        assert "findings" in data, "audit.json missing 'findings' key"
        assert isinstance(data["findings"], list), "'findings' must be an array"

    def test_minimum_findings_count(self):
        """audit.json must contain at least 6 findings."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        findings = data.get("findings", [])
        assert len(findings) >= 6, (
            f"Expected at least 6 findings, got {len(findings)}"
        )

    def test_findings_schema(self):
        """Each finding must have required fields with valid enum values."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        required_keys = {"id", "category", "severity", "description",
                         "rfc_reference", "remediation"}
        for i, finding in enumerate(data.get("findings", [])):
            missing = required_keys - set(finding.keys())
            assert not missing, f"Finding {i} missing keys: {missing}"
            assert finding["category"] in VALID_CATEGORIES, (
                f"Finding {i} has invalid category '{finding['category']}'"
            )
            assert finding["severity"] in VALID_SEVERITIES, (
                f"Finding {i} has invalid severity '{finding['severity']}'"
            )
            assert isinstance(finding["id"], str) and len(finding["id"]) > 0, (
                f"Finding {i} 'id' must be a non-empty string"
            )
            assert isinstance(finding["description"], str) and len(finding["description"]) > 0, (
                f"Finding {i} 'description' must be a non-empty string"
            )

    def test_has_risk_assessment(self):
        """audit.json must have a 'risk_assessment' field."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        assert "risk_assessment" in data, "audit.json missing 'risk_assessment'"
        assert data["risk_assessment"] in {"critical", "high", "medium", "low"}, (
            f"Invalid risk_assessment value: {data['risk_assessment']}"
        )

    def test_has_test_methodology(self):
        """audit.json must have a 'test_methodology' field."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        assert "test_methodology" in data, "audit.json missing 'test_methodology'"
        assert isinstance(data["test_methodology"], str) and len(data["test_methodology"]) > 10, (
            "test_methodology must be a non-trivial description"
        )

    def test_findings_cover_all_categories(self):
        """Findings must span all three category types."""
        with open("/app/audit.json") as f:
            data = json.load(f)
        categories_found = {f["category"] for f in data.get("findings", [])}
        for cat in VALID_CATEGORIES:
            assert cat in categories_found, (
                f"No findings with category '{cat}' — audit should identify "
                f"issues across all categories"
            )
