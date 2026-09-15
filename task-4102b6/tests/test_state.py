
import json
import struct
import sys
import os
import importlib.util
import zlib
import pytest

sys.path.insert(0, "/app")


def crc16_ccitt_false(data):
    """Reference CRC-16/CCITT-FALSE implementation."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


# ---- Test that sidp_layers.py exists and is importable ----

class TestLayerImplementation:
    """Test that the Scapy layer implementation is correct."""

    @pytest.fixture(autouse=True)
    def load_layers(self):
        assert os.path.exists("/app/sidp_layers.py"), \
            "sidp_layers.py must exist at /app/sidp_layers.py"
        spec = importlib.util.spec_from_file_location("sidp_layers", "/app/sidp_layers.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_has_header_class(self):
        """SIDP_Header class must exist."""
        assert hasattr(self.mod, "SIDP_Header"), "Must define SIDP_Header class"

    def test_has_message_class(self):
        """SIDP_Message class must exist."""
        assert hasattr(self.mod, "SIDP_Message"), "Must define SIDP_Message class"

    def test_has_param_class(self):
        """SIDP_Param class must exist."""
        assert hasattr(self.mod, "SIDP_Param"), "Must define SIDP_Param class"

    def test_has_fragment_class(self):
        """SIDP_Fragment class must exist."""
        assert hasattr(self.mod, "SIDP_Fragment"), "Must define SIDP_Fragment class"

    def test_parse_v1_simple_request(self):
        """Parse a v1 request packet (SessionOpen)."""
        # Packet 0: SessionOpen request
        hex_data = "5344010000001234000100130101010001000c44696167436c69656e742d31"
        raw = bytes.fromhex(hex_data)
        pkt = self.mod.SIDP_Header(raw)

        assert pkt.version == 1
        assert pkt.flags == 0x00
        assert pkt.session_id == 0x00001234
        assert pkt.sequence == 1
        assert pkt.payload_length == 19

    def test_parse_v1_response(self):
        """Parse a v1 response packet (DeviceInfo)."""
        hex_data = "53440101000012340004003702010301010012496e647573747269616c504c432d5835303001020006332e31342e3201030010534e2d32303234303831352d30303432"
        raw = bytes.fromhex(hex_data)
        pkt = self.mod.SIDP_Header(raw)

        assert pkt.version == 1
        assert pkt.flags & 0x01 == 1  # is_response

    def test_parse_v2_with_checksum(self):
        """Parse a v2 packet with checksum and verify v2-specific fields."""
        # Packet 14: StartTransfer v2
        hex_data = "5344028000001234000f00130766be4b800501020501000400000200050200041c613576b543"
        raw = bytes.fromhex(hex_data)
        pkt = self.mod.SIDP_Header(raw)

        assert pkt.version == 2
        assert pkt.flags & 0x80 != 0  # checksum_present
        # V2 must have priority and timestamp fields
        assert hasattr(pkt, "priority") or hasattr(pkt, "timestamp"), \
            "V2 packets must have priority/timestamp fields"

    def test_parse_v2_fragment(self):
        """Parse a v2 fragmented packet."""
        # Packet 16: Fragment 0/3
        hex_data = "5344028400001234001100ce0766be4b81000100000003"
        # Just the header + start of fragment, enough to check structure
        raw = bytes.fromhex(hex_data)
        pkt = self.mod.SIDP_Header(raw)
        assert pkt.version == 2
        assert pkt.flags & 0x04 != 0  # is_fragmented

    def test_v1_no_priority_timestamp(self):
        """V1 packets should not consume bytes for priority/timestamp."""
        hex_data = "534401000000123400050003030100"
        raw = bytes.fromhex(hex_data)
        pkt = self.mod.SIDP_Header(raw)
        assert pkt.version == 1
        assert pkt.payload_length == 3

    def test_rebuild_v1_packet(self):
        """Building a v1 packet should produce correct bytes."""
        hex_data = "534401000000123400050003030100"
        raw = bytes.fromhex(hex_data)
        pkt = self.mod.SIDP_Header(raw)
        rebuilt = bytes(pkt)
        # The rebuilt packet should be the same length and decode the same
        reparsed = self.mod.SIDP_Header(rebuilt)
        assert reparsed.version == 1
        assert reparsed.session_id == 0x00001234
        assert reparsed.sequence == 5

    def test_crc16_computation(self):
        """CRC-16/CCITT-FALSE must be correctly computed."""
        # Test with known data
        test_data = b'SD\x02\x80\x00\x00\x12\x34\x00\x0f\x00\x13\x07\x66\xbe\x4b\x80'
        expected_crc = crc16_ccitt_false(test_data)
        # The module should have the CRC function or we verify via packet parsing
        if hasattr(self.mod, "crc16_ccitt_false"):
            assert self.mod.crc16_ccitt_false(test_data) == expected_crc

    def test_craft_response_exists(self):
        """craft_response function must exist."""
        assert hasattr(self.mod, "craft_response"), \
            "Must define craft_response(hex_request) -> str function"

    def test_craft_response_basic(self):
        """craft_response must produce valid response for ReadParam request."""
        # Packet 8: ReadParam temperature request
        request_hex = "534401000000123400090009040101040100020001"
        response_hex = self.mod.craft_response(request_hex)
        assert isinstance(response_hex, str), "craft_response must return hex string"
        resp_bytes = bytes.fromhex(response_hex)
        resp = self.mod.SIDP_Header(resp_bytes)

        # Response flag must be set
        assert resp.flags & 0x01 == 1, "Response flag must be set"
        # Same session_id
        assert resp.session_id == 0x00001234
        # Sequence incremented by 1
        assert resp.sequence == 10  # original was 9, so response is 10


class TestAnalysisOutput:
    """Test that analysis.json is correct."""

    @pytest.fixture(autouse=True)
    def load_analysis(self):
        assert os.path.exists("/app/analysis.json"), \
            "analysis.json must exist at /app/analysis.json"
        with open("/app/analysis.json") as f:
            self.data = json.load(f)

    def test_total_packets(self):
        assert self.data["total_packets"] == 30

    def test_unique_session_ids(self):
        sids = sorted(self.data["unique_session_ids"])
        expected = sorted(["0x00001234", "0x00005678"])
        assert sids == expected, f"Expected {expected}, got {sids}"

    def test_anomaly_indices(self):
        indices = sorted(self.data["anomaly_indices"])
        assert indices == [25, 26, 27], f"Expected [25, 26, 27], got {indices}"

    def test_anomaly_reasons(self):
        reasons = self.data["anomaly_reasons"]
        assert reasons["25"] == "invalid_sync"
        assert reasons["26"] == "bad_checksum"
        assert reasons["27"] == "invalid_fragment_index"

    def test_device_type(self):
        assert self.data["device_type"] == "IndustrialPLC-X500"

    def test_firmware_version(self):
        assert self.data["firmware_version"] == "3.14.2"

    def test_serial_number(self):
        assert self.data["serial_number"] == "SN-20240815-0042"

    def test_parameter_temperature(self):
        params = self.data["parameters"]
        assert "0x0001" in params
        assert abs(params["0x0001"] - 72.5) < 0.01

    def test_parameter_pressure(self):
        params = self.data["parameters"]
        assert "0x0002" in params
        assert abs(params["0x0002"] - 1013.25) < 0.1

    def test_parameter_voltage(self):
        params = self.data["parameters"]
        assert "0x0003" in params
        assert abs(params["0x0003"] - 24.125) < 0.01

    def test_parameter_fw_string(self):
        params = self.data["parameters"]
        assert "0x0010" in params
        assert params["0x0010"] == "PLC-X500-FW-3.14.2-release"

    def test_reassembled_firmware_crc32(self):
        expected_crc = "0x1c613576"
        assert self.data["reassembled_firmware_crc32"] == expected_crc

    def test_reassembled_firmware_size(self):
        assert self.data["reassembled_firmware_size"] == 512
