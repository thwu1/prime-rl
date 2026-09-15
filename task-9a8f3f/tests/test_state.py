
import pytest
import sys
import json
import struct

sys.path.insert(0, '/app')
from postcard_codec import (
    varint_encode, varint_decode,
    zigzag_encode, zigzag_decode,
    cobs_encode, cobs_decode,
    serialize, deserialize,
    frame_messages, unframe_messages,
    is_canonical_varint, max_varint_len,
)


@pytest.fixture
def schema():
    with open('/app/schema.json') as f:
        return json.load(f)


# === Varint Tests ===

class TestVarintEncode:
    """Test varint encoding against Postcard specification vectors."""

    def test_zero(self):
        assert varint_encode(0, 16) == bytes([0x00])

    def test_127(self):
        assert varint_encode(127, 16) == bytes([0x7F])

    def test_128(self):
        assert varint_encode(128, 16) == bytes([0x80, 0x01])

    def test_16383(self):
        assert varint_encode(16383, 16) == bytes([0xFF, 0x7F])

    def test_16384(self):
        assert varint_encode(16384, 16) == bytes([0x80, 0x80, 0x01])

    def test_16385(self):
        assert varint_encode(16385, 16) == bytes([0x81, 0x80, 0x01])

    def test_65535(self):
        assert varint_encode(65535, 16) == bytes([0xFF, 0xFF, 0x03])

    def test_u32_300(self):
        assert varint_encode(300, 32) == bytes([0xAC, 0x02])

    def test_u32_1000(self):
        assert varint_encode(1000, 32) == bytes([0xE8, 0x07])

    def test_u32_large(self):
        # 2^32 - 1 = 4294967295
        result = varint_encode(4294967295, 32)
        assert len(result) == 5
        # Verify by decoding
        val, consumed = varint_decode(result, 32)
        assert val == 4294967295


class TestVarintDecode:
    """Test varint decoding."""

    def test_zero(self):
        assert varint_decode(bytes([0x00]), 16) == (0, 1)

    def test_127(self):
        assert varint_decode(bytes([0x7F]), 16) == (127, 1)

    def test_128(self):
        assert varint_decode(bytes([0x80, 0x01]), 16) == (128, 2)

    def test_65535(self):
        assert varint_decode(bytes([0xFF, 0xFF, 0x03]), 16) == (65535, 3)

    def test_u32_300(self):
        assert varint_decode(bytes([0xAC, 0x02]), 32) == (300, 2)

    def test_overlong_rejected(self):
        """Varint exceeding max encoded length for type should be rejected."""
        with pytest.raises(ValueError):
            varint_decode(bytes([0x80, 0x80, 0x80, 0x00]), 16)

    def test_value_overflow_rejected(self):
        """Decoded value exceeding type range should be rejected."""
        with pytest.raises(ValueError):
            varint_decode(bytes([0xFF, 0xFF, 0x07]), 16)

    def test_trailing_data_ignored(self):
        """Extra bytes after varint should not affect decoding."""
        val, consumed = varint_decode(bytes([0x80, 0x01, 0xFF, 0xFF]), 16)
        assert val == 128
        assert consumed == 2


# === Zigzag Tests ===

class TestZigzagEncode:
    """Test zigzag encoding against Postcard specification vectors."""

    def test_zero(self):
        assert zigzag_encode(0) == 0

    def test_neg1(self):
        assert zigzag_encode(-1) == 1

    def test_pos1(self):
        assert zigzag_encode(1) == 2

    def test_pos63(self):
        assert zigzag_encode(63) == 126

    def test_neg64(self):
        assert zigzag_encode(-64) == 127

    def test_pos64(self):
        assert zigzag_encode(64) == 128

    def test_neg65(self):
        assert zigzag_encode(-65) == 129

    def test_i16_max(self):
        assert zigzag_encode(32767) == 65534

    def test_i16_min(self):
        assert zigzag_encode(-32768) == 65535


class TestZigzagDecode:
    """Test zigzag decoding."""

    def test_zero(self):
        assert zigzag_decode(0) == 0

    def test_one_to_neg1(self):
        assert zigzag_decode(1) == -1

    def test_two_to_pos1(self):
        assert zigzag_decode(2) == 1

    def test_roundtrip_range(self):
        for val in [-100, -1, 0, 1, 100, 32767, -32768, 2147483647, -2147483648]:
            assert zigzag_decode(zigzag_encode(val)) == val


# === COBS Tests ===

class TestCobsEncode:
    """Test COBS encoding against Wikipedia and cobs.rs test vectors."""

    def test_empty(self):
        assert cobs_encode(b'') == bytes([0x01])

    def test_single_zero(self):
        assert cobs_encode(bytes([0x00])) == bytes([0x01, 0x01])

    def test_double_zero(self):
        assert cobs_encode(bytes([0x00, 0x00])) == bytes([0x01, 0x01, 0x01])

    def test_nonzero_only(self):
        assert cobs_encode(bytes([0x11, 0x22, 0x33, 0x44])) == bytes([0x05, 0x11, 0x22, 0x33, 0x44])

    def test_mixed_data(self):
        assert cobs_encode(bytes([0x11, 0x22, 0x00, 0x33])) == bytes([0x03, 0x11, 0x22, 0x02, 0x33])

    def test_trailing_zeros(self):
        assert cobs_encode(bytes([0x11, 0x00, 0x00, 0x00])) == bytes([0x02, 0x11, 0x01, 0x01, 0x01])

    def test_wikipedia_ex6(self):
        """Bytes 0x01 through 0xFE (254 non-zero bytes)."""
        data = bytes(range(1, 255))
        expected = bytes([0xFF]) + data + bytes([0x01])
        assert cobs_encode(data) == expected

    def test_wikipedia_ex7(self):
        """Bytes 0x00 through 0xFE (starts with zero, then 254 non-zero)."""
        data = bytes(range(0, 255))
        expected = bytes([0x01, 0xFF]) + bytes(range(1, 255)) + bytes([0x01])
        assert cobs_encode(data) == expected

    def test_wikipedia_ex8(self):
        """Bytes 0x01 through 0xFF (255 non-zero bytes, crosses 254-byte boundary)."""
        data = bytes(range(1, 256))
        expected = bytes([0xFF]) + bytes(range(1, 255)) + bytes([0x02, 0xFF])
        assert cobs_encode(data) == expected

    def test_wikipedia_ex9(self):
        """Bytes 0x02..0xFF then 0x00 (254 non-zero then zero)."""
        data = bytes(range(2, 256)) + bytes([0x00])
        expected = bytes([0xFF]) + bytes(range(2, 256)) + bytes([0x01, 0x01])
        assert cobs_encode(data) == expected

    def test_wikipedia_ex10(self):
        """Bytes 0x03..0xFF then 0x00, 0x01 (253 non-zero, zero, non-zero)."""
        data = bytes(range(3, 256)) + bytes([0x00, 0x01])
        expected = bytes([0xFE]) + bytes(range(3, 256)) + bytes([0x02, 0x01])
        assert cobs_encode(data) == expected

    def test_254_nonzero_bytes_exact(self):
        """Exactly 254 non-zero bytes uses single 0xFF code, plus trailing code byte."""
        data = bytes([0x01] * 254)
        encoded = cobs_encode(data)
        assert encoded[0] == 0xFF
        assert len(encoded) == 256

    def test_no_zeros_in_output(self):
        """COBS encoded output must never contain 0x00."""
        import random
        random.seed(42)
        for _ in range(100):
            length = random.randint(0, 500)
            data = bytes(random.randint(0, 255) for _ in range(length))
            encoded = cobs_encode(data)
            assert 0x00 not in encoded, f"Zero found in COBS encoding of {length}-byte message"


class TestCobsDecode:
    """Test COBS decoding."""

    def test_empty(self):
        assert cobs_decode(bytes([0x01])) == b''

    def test_single_zero(self):
        assert cobs_decode(bytes([0x01, 0x01])) == bytes([0x00])

    def test_nonzero(self):
        assert cobs_decode(bytes([0x05, 0x11, 0x22, 0x33, 0x44])) == bytes([0x11, 0x22, 0x33, 0x44])

    def test_mixed(self):
        assert cobs_decode(bytes([0x03, 0x11, 0x22, 0x02, 0x33])) == bytes([0x11, 0x22, 0x00, 0x33])

    def test_roundtrip_random(self):
        """COBS encode then decode returns original data for random inputs."""
        import random
        random.seed(123)
        for _ in range(200):
            length = random.randint(0, 600)
            data = bytes(random.randint(0, 255) for _ in range(length))
            assert cobs_decode(cobs_encode(data)) == data

    def test_roundtrip_boundary(self):
        """Roundtrip at the 254-byte boundary."""
        for length in [253, 254, 255, 256, 508, 509]:
            data = bytes([0x01] * length)
            assert cobs_decode(cobs_encode(data)) == data

    def test_roundtrip_all_zeros(self):
        """Roundtrip for all-zero data."""
        for length in [0, 1, 2, 10, 100]:
            data = bytes([0x00] * length)
            assert cobs_decode(cobs_encode(data)) == data


# === Serialization Tests ===

class TestSerialize:
    """Test Postcard serialization with hand-computed expected byte sequences."""

    def test_point(self, schema):
        data = {"x": 1.5, "y": -2.0}
        expected = bytes([0x00, 0x00, 0xC0, 0x3F, 0x00, 0x00, 0x00, 0xC0])
        assert serialize(schema, "Point", data) == expected

    def test_sensor_reading(self, schema):
        data = {"timestamp": 300, "sensor_id": 5, "value": 1.5, "flags": 1}
        expected = bytes([0xAC, 0x02, 0x05, 0x00, 0x00, 0xC0, 0x3F, 0x01])
        assert serialize(schema, "SensorReading", data) == expected

    def test_enum_unit_variant(self, schema):
        assert serialize(schema, "DeviceStatus", "Idle") == bytes([0x00])

    def test_enum_newtype_variant(self, schema):
        data = {"Active": 7}
        assert serialize(schema, "DeviceStatus", data) == bytes([0x01, 0x07])

    def test_enum_struct_variant(self, schema):
        data = {"Error": {"code": 256, "message": "timeout"}}
        expected = bytes([0x02, 0x80, 0x02, 0x07]) + b"timeout"
        assert serialize(schema, "DeviceStatus", data) == expected

    def test_enum_tuple_variant(self, schema):
        data = {"Custom": [255, 128, 0]}
        expected = bytes([0x03, 0xFF, 0x80, 0x00])
        assert serialize(schema, "Color", data) == expected

    def test_command_ping(self, schema):
        assert serialize(schema, "Command", "Ping") == bytes([0x00])

    def test_command_set_config(self, schema):
        data = {"SetConfig": {
            "interval_ms": 1000,
            "sensors": [1, 2, 3],
            "threshold": 0.5,
            "label": None,
        }}
        expected = bytes([
            0x01,
            0xE8, 0x07,
            0x03,
            0x01, 0x02, 0x03,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE0, 0x3F,
            0x00,
        ])
        assert serialize(schema, "Command", data) == expected

    def test_command_get_readings(self, schema):
        data = {"GetReadings": [1, 2, 1000]}
        expected = bytes([0x02, 0x03, 0x01, 0x02, 0xE8, 0x07])
        assert serialize(schema, "Command", data) == expected

    def test_command_batch_update(self, schema):
        data = {"BatchUpdate": [42, [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}], True]}
        expected = bytes([
            0x03,
            0x2A,
            0x02,
            0x00, 0x00, 0x80, 0x3F,
            0x00, 0x00, 0x00, 0x40,
            0x00, 0x00, 0x40, 0x40,
            0x00, 0x00, 0x80, 0x40,
            0x01,
        ])
        assert serialize(schema, "Command", data) == expected

    def test_metadata_map(self, schema):
        data = {"entries": [["alpha", -1], ["beta", 100]], "version": 3}
        expected = (
            bytes([0x02, 0x05]) + b"alpha" + bytes([0x01, 0x04]) + b"beta"
            + bytes([0xC8, 0x01, 0x03])
        )
        assert serialize(schema, "MetadataMap", data) == expected

    def test_nested_tuple_some(self, schema):
        data = [42, 1000, True]
        expected = bytes([0x2A, 0xE8, 0x07, 0x01, 0x01])
        assert serialize(schema, "NestedTuple", data) == expected

    def test_nested_tuple_none(self, schema):
        data = [0, 0, None]
        expected = bytes([0x00, 0x00, 0x00])
        assert serialize(schema, "NestedTuple", data) == expected

    def test_telemetry_packet(self, schema):
        data = {
            "sequence": 42,
            "readings": [{"timestamp": 300, "sensor_id": 5, "value": 1.5, "flags": 1}],
            "status": "Idle",
            "label": "test",
            "raw_data": b'\x01\x02\x03',
        }
        expected = bytes([
            0x2A,
            0x01,
            0xAC, 0x02,
            0x05,
            0x00, 0x00, 0xC0, 0x3F,
            0x01,
            0x00,
            0x01, 0x04,
        ]) + b"test" + bytes([0x03, 0x01, 0x02, 0x03])
        assert serialize(schema, "TelemetryPacket", data) == expected


# === Deserialization Tests ===

class TestDeserialize:
    """Test Postcard deserialization."""

    def test_point(self, schema):
        data = bytes([0x00, 0x00, 0xC0, 0x3F, 0x00, 0x00, 0x00, 0xC0])
        result, consumed = deserialize(schema, "Point", data)
        assert consumed == 8
        assert abs(result["x"] - 1.5) < 1e-6
        assert abs(result["y"] - (-2.0)) < 1e-6

    def test_sensor_reading(self, schema):
        data = bytes([0xAC, 0x02, 0x05, 0x00, 0x00, 0xC0, 0x3F, 0x01])
        result, consumed = deserialize(schema, "SensorReading", data)
        assert consumed == 8
        assert result["timestamp"] == 300
        assert result["sensor_id"] == 5
        assert abs(result["value"] - 1.5) < 1e-6
        assert result["flags"] == 1

    def test_enum_unit(self, schema):
        result, consumed = deserialize(schema, "DeviceStatus", bytes([0x00]))
        assert result == "Idle"
        assert consumed == 1

    def test_enum_newtype(self, schema):
        result, consumed = deserialize(schema, "DeviceStatus", bytes([0x01, 0x07]))
        assert result == {"Active": 7}
        assert consumed == 2

    def test_enum_struct(self, schema):
        data = bytes([0x02, 0x80, 0x02, 0x07]) + b"timeout"
        result, consumed = deserialize(schema, "DeviceStatus", data)
        assert result == {"Error": {"code": 256, "message": "timeout"}}

    def test_telemetry_packet(self, schema):
        data = bytes([
            0x2A, 0x01, 0xAC, 0x02, 0x05, 0x00, 0x00, 0xC0, 0x3F, 0x01,
            0x00, 0x01, 0x04,
        ]) + b"test" + bytes([0x03, 0x01, 0x02, 0x03])
        result, consumed = deserialize(schema, "TelemetryPacket", data)
        assert result["sequence"] == 42
        assert len(result["readings"]) == 1
        assert result["readings"][0]["timestamp"] == 300
        assert result["status"] == "Idle"
        assert result["label"] == "test"
        assert result["raw_data"] == b'\x01\x02\x03'

    def test_metadata_map(self, schema):
        data = (
            bytes([0x02, 0x05]) + b"alpha" + bytes([0x01, 0x04]) + b"beta"
            + bytes([0xC8, 0x01, 0x03])
        )
        result, consumed = deserialize(schema, "MetadataMap", data)
        assert result["entries"] == [["alpha", -1], ["beta", 100]]
        assert result["version"] == 3


# === Roundtrip Tests ===

class TestRoundtrip:
    """Test serialize then deserialize returns the original data."""

    def _roundtrip(self, schema, type_name, data):
        encoded = serialize(schema, type_name, data)
        decoded, consumed = deserialize(schema, type_name, encoded)
        assert consumed == len(encoded), f"Not all bytes consumed: {consumed} vs {len(encoded)}"
        return decoded

    def test_point(self, schema):
        data = {"x": 1.5, "y": -2.0}
        result = self._roundtrip(schema, "Point", data)
        assert abs(result["x"] - data["x"]) < 1e-6
        assert abs(result["y"] - data["y"]) < 1e-6

    def test_all_color_variants(self, schema):
        for variant in ["Red", "Green", "Blue"]:
            assert self._roundtrip(schema, "Color", variant) == variant
        data = {"Custom": [255, 128, 0]}
        assert self._roundtrip(schema, "Color", data) == data

    def test_all_device_status_variants(self, schema):
        assert self._roundtrip(schema, "DeviceStatus", "Idle") == "Idle"
        assert self._roundtrip(schema, "DeviceStatus", {"Active": 42}) == {"Active": 42}
        error = {"Error": {"code": 1000, "message": "critical failure"}}
        assert self._roundtrip(schema, "DeviceStatus", error) == error

    def test_command_ping(self, schema):
        assert self._roundtrip(schema, "Command", "Ping") == "Ping"

    def test_command_set_config_with_label(self, schema):
        data = {"SetConfig": {
            "interval_ms": 5000,
            "sensors": [10, 20, 30, 40],
            "threshold": 3.14,
            "label": "temperature",
        }}
        result = self._roundtrip(schema, "Command", data)
        assert result["SetConfig"]["interval_ms"] == 5000
        assert result["SetConfig"]["sensors"] == [10, 20, 30, 40]
        assert abs(result["SetConfig"]["threshold"] - 3.14) < 1e-10
        assert result["SetConfig"]["label"] == "temperature"

    def test_command_set_config_no_label(self, schema):
        data = {"SetConfig": {
            "interval_ms": 100,
            "sensors": [],
            "threshold": 0.0,
            "label": None,
        }}
        result = self._roundtrip(schema, "Command", data)
        assert result["SetConfig"]["label"] is None
        assert result["SetConfig"]["sensors"] == []

    def test_metadata_map(self, schema):
        data = {"entries": [["x", 42], ["y", -100], ["z", 0]], "version": 7}
        result = self._roundtrip(schema, "MetadataMap", data)
        assert result == data

    def test_nested_tuple(self, schema):
        data = [255, 65535, True]
        result = self._roundtrip(schema, "NestedTuple", data)
        assert result == data

    def test_nested_tuple_none(self, schema):
        data = [0, 0, None]
        result = self._roundtrip(schema, "NestedTuple", data)
        assert result == data

    def test_telemetry_complex(self, schema):
        data = {
            "sequence": 999999,
            "readings": [
                {"timestamp": 1000, "sensor_id": 1, "value": 0.0, "flags": 0},
                {"timestamp": 2000, "sensor_id": 2, "value": -273.0, "flags": 255},
                {"timestamp": 3000, "sensor_id": 3, "value": 100.0, "flags": 128},
            ],
            "status": {"Error": {"code": 404, "message": "not found"}},
            "label": None,
            "raw_data": bytes(range(256)),
        }
        result = self._roundtrip(schema, "TelemetryPacket", data)
        assert result["sequence"] == 999999
        assert len(result["readings"]) == 3
        assert result["readings"][1]["sensor_id"] == 2
        assert result["status"] == {"Error": {"code": 404, "message": "not found"}}
        assert result["label"] is None
        assert result["raw_data"] == bytes(range(256))

    def test_empty_seq_and_bytes(self, schema):
        data = {
            "sequence": 0,
            "readings": [],
            "status": "Idle",
            "label": None,
            "raw_data": b'',
        }
        result = self._roundtrip(schema, "TelemetryPacket", data)
        assert result["readings"] == []
        assert result["raw_data"] == b''


# === Framing Tests ===

class TestFraming:
    """Test COBS message framing."""

    def test_single_message(self):
        msg = b'\x01\x02\x03'
        stream = frame_messages([msg])
        decoded = unframe_messages(stream)
        assert len(decoded) == 1
        assert decoded[0] == msg

    def test_multiple_messages(self):
        msgs = [b'\x01\x02\x03', b'\x00', b'\xFF' * 300, b'']
        stream = frame_messages(msgs)
        decoded = unframe_messages(stream)
        assert len(decoded) == len(msgs)
        for orig, dec in zip(msgs, decoded):
            assert orig == dec

    def test_telemetry_stream(self, schema):
        """Test framing a stream of serialized messages."""
        packets = [
            serialize(schema, "Command", "Ping"),
            serialize(schema, "SensorReading", {
                "timestamp": 42, "sensor_id": 1, "value": 0.0, "flags": 0
            }),
            serialize(schema, "DeviceStatus", {"Active": 7}),
        ]
        stream = frame_messages(packets)
        recovered = unframe_messages(stream)
        assert len(recovered) == 3
        for orig, rec in zip(packets, recovered):
            assert orig == rec


# === Canonicalization Tests ===

class TestCanonicalization:
    """Test varint canonicalization checking."""

    def test_canonical_zero(self):
        assert is_canonical_varint(bytes([0x00]), 16) is True

    def test_canonical_127(self):
        assert is_canonical_varint(bytes([0x7F]), 16) is True

    def test_canonical_128(self):
        assert is_canonical_varint(bytes([0x80, 0x01]), 16) is True

    def test_canonical_max_u16(self):
        assert is_canonical_varint(bytes([0xFF, 0xFF, 0x03]), 16) is True

    def test_noncanonical_zero_2byte(self):
        assert is_canonical_varint(bytes([0x80, 0x00]), 16) is False

    def test_noncanonical_zero_3byte(self):
        assert is_canonical_varint(bytes([0x80, 0x80, 0x00]), 16) is False

    def test_overlong_rejected(self):
        assert is_canonical_varint(bytes([0x80, 0x80, 0x80, 0x00]), 16) is False

    def test_overflow_rejected(self):
        assert is_canonical_varint(bytes([0xFF, 0xFF, 0x07]), 16) is False


# === Max Varint Len Tests ===

class TestMaxVarintLen:
    """Test max varint length calculation."""

    def test_u16(self):
        assert max_varint_len(16) == 3

    def test_u32(self):
        assert max_varint_len(32) == 5

    def test_u64(self):
        assert max_varint_len(64) == 10

    def test_u128(self):
        assert max_varint_len(128) == 19


# === Full Pipeline Tests ===

class TestFullPipeline:
    """Test the complete pipeline: serialize -> COBS frame -> unframe -> deserialize."""

    def test_telemetry_pipeline(self, schema):
        telemetry = {
            "sequence": 42,
            "readings": [{"timestamp": 300, "sensor_id": 5, "value": 1.5, "flags": 1}],
            "status": "Idle",
            "label": "test",
            "raw_data": b'\x01\x02\x03',
        }
        command = "Ping"

        tel_bytes = serialize(schema, "TelemetryPacket", telemetry)
        cmd_bytes = serialize(schema, "Command", command)

        stream = frame_messages([tel_bytes, cmd_bytes])
        messages = unframe_messages(stream)
        assert len(messages) == 2

        tel_result, _ = deserialize(schema, "TelemetryPacket", messages[0])
        cmd_result, _ = deserialize(schema, "Command", messages[1])

        assert tel_result["sequence"] == 42
        assert tel_result["readings"][0]["timestamp"] == 300
        assert abs(tel_result["readings"][0]["value"] - 1.5) < 1e-6
        assert tel_result["status"] == "Idle"
        assert tel_result["label"] == "test"
        assert tel_result["raw_data"] == b'\x01\x02\x03'
        assert cmd_result == "Ping"

    def test_exact_cobs_of_telemetry(self, schema):
        """Verify exact COBS encoding of a known telemetry packet."""
        data = {
            "sequence": 42,
            "readings": [{"timestamp": 300, "sensor_id": 5, "value": 1.5, "flags": 1}],
            "status": "Idle",
            "label": "test",
            "raw_data": b'\x01\x02\x03',
        }
        postcard_bytes = serialize(schema, "TelemetryPacket", data)

        expected_postcard = bytes([
            0x2A, 0x01, 0xAC, 0x02, 0x05,
            0x00, 0x00,
            0xC0, 0x3F, 0x01,
            0x00,
            0x01, 0x04,
        ]) + b"test" + bytes([0x03, 0x01, 0x02, 0x03])
        assert postcard_bytes == expected_postcard

        expected_cobs = bytes([
            0x06, 0x2A, 0x01, 0xAC, 0x02, 0x05,
            0x01,
            0x04, 0xC0, 0x3F, 0x01,
            0x0B, 0x01, 0x04,
        ]) + b"test" + bytes([0x03, 0x01, 0x02, 0x03])
        cobs_bytes = cobs_encode(postcard_bytes)
        assert cobs_bytes == expected_cobs

    def test_complex_multi_type_pipeline(self, schema):
        """Pipeline with multiple different message types."""
        messages_data = [
            ("Command", {"SetConfig": {
                "interval_ms": 1000, "sensors": [1, 2], "threshold": 0.5, "label": "x"
            }}),
            ("TelemetryPacket", {
                "sequence": 1, "readings": [], "status": "Idle",
                "label": None, "raw_data": b'',
            }),
            ("MetadataMap", {"entries": [["key", 42]], "version": 1}),
            ("Color", {"Custom": [10, 20, 30]}),
            ("NestedTuple", [1, 2, None]),
        ]

        raw_messages = [serialize(schema, t, d) for t, d in messages_data]
        stream = frame_messages(raw_messages)
        recovered = unframe_messages(stream)
        assert len(recovered) == len(messages_data)

        for i, (type_name, original) in enumerate(messages_data):
            result, consumed = deserialize(schema, type_name, recovered[i])
            assert consumed == len(recovered[i])


# === Binary Test Vector Tests ===

class TestBinaryVectors:
    """Test against pre-generated binary test vectors from C reference at /app/vectors/."""

    def _read_vector_pairs(self, path):
        """Read pairs of (original, cobs_encoded) from a binary vector file.

        Format: repeated (u32_le orig_len, orig_data, u32_le enc_len, enc_data).
        """
        with open(path, 'rb') as f:
            data = f.read()
        pairs = []
        offset = 0
        while offset < len(data):
            orig_len = int.from_bytes(data[offset:offset+4], 'little')
            offset += 4
            original = data[offset:offset+orig_len]
            offset += orig_len
            enc_len = int.from_bytes(data[offset:offset+4], 'little')
            offset += 4
            encoded = data[offset:offset+enc_len]
            offset += enc_len
            pairs.append((original, encoded))
        return pairs

    def test_cobs_encode_matches_c_vectors(self):
        """Python COBS encode must match C reference output for all vector pairs."""
        pairs = self._read_vector_pairs('/app/vectors/cobs_vectors.bin')
        assert len(pairs) >= 10, f"Expected at least 10 vector pairs, got {len(pairs)}"
        for i, (original, expected_encoded) in enumerate(pairs):
            py_encoded = cobs_encode(original)
            assert py_encoded == expected_encoded, (
                f"Vector {i}: encode mismatch for {len(original)}-byte input"
            )

    def test_cobs_decode_matches_c_vectors(self):
        """Python COBS decode must recover original data for all vector pairs."""
        pairs = self._read_vector_pairs('/app/vectors/cobs_vectors.bin')
        for i, (original, encoded) in enumerate(pairs):
            py_decoded = cobs_decode(encoded)
            assert py_decoded == original, (
                f"Vector {i}: decode mismatch for {len(encoded)}-byte encoded"
            )

    def test_framed_stream_unframe(self):
        """Python unframe_messages must correctly decode the C-generated framed stream.

        The framed stream contains 4 messages: [0x01,0x02,0x03], [0x00],
        [0xFF]*300, and empty.
        """
        with open('/app/vectors/framed_stream.bin', 'rb') as f:
            stream = f.read()
        messages = unframe_messages(stream)
        assert len(messages) == 4
        assert messages[0] == bytes([0x01, 0x02, 0x03])
        assert messages[1] == bytes([0x00])
        assert messages[2] == bytes([0xFF] * 300)
        assert messages[3] == b''

    def test_framed_stream_reframe_roundtrip(self):
        """Re-framing the unframed messages must produce identical stream bytes."""
        with open('/app/vectors/framed_stream.bin', 'rb') as f:
            original_stream = f.read()
        messages = unframe_messages(original_stream)
        reframed = frame_messages(messages)
        assert reframed == original_stream


# === C Reference Cross-Validation Tests ===

class TestCrossValidation:
    """Cross-validate Python COBS against the compiled C reference binary at /app/reference/cobs_ref."""

    def test_cobs_encode_matches_c_ref_random(self):
        """Python COBS encoding must match C reference for random inputs."""
        import subprocess
        import random
        random.seed(999)
        for _ in range(50):
            length = random.randint(0, 500)
            data = bytes(random.randint(0, 255) for _ in range(length))

            proc = subprocess.run(
                ['/app/reference/cobs_ref', 'encode'],
                input=data,
                capture_output=True,
            )
            assert proc.returncode == 0, f"C ref encode failed: {proc.stderr}"
            c_encoded = proc.stdout
            py_encoded = cobs_encode(data)
            assert py_encoded == c_encoded, (
                f"COBS encode mismatch for {length}-byte input"
            )

    def test_cobs_decode_matches_c_ref_random(self):
        """Python COBS decoding must match C reference for encoded inputs."""
        import subprocess
        import random
        random.seed(888)
        for _ in range(50):
            length = random.randint(0, 500)
            original = bytes(random.randint(0, 255) for _ in range(length))
            encoded = cobs_encode(original)

            proc = subprocess.run(
                ['/app/reference/cobs_ref', 'decode'],
                input=encoded,
                capture_output=True,
            )
            assert proc.returncode == 0, f"C ref decode failed: {proc.stderr}"
            c_decoded = proc.stdout
            assert c_decoded == original, (
                f"COBS decode mismatch for {length}-byte input"
            )

    def test_c_ref_encode_then_python_decode(self):
        """Data encoded by C reference must be correctly decoded by Python."""
        import subprocess
        import random
        random.seed(777)
        for _ in range(30):
            length = random.randint(0, 400)
            data = bytes(random.randint(0, 255) for _ in range(length))

            proc = subprocess.run(
                ['/app/reference/cobs_ref', 'encode'],
                input=data,
                capture_output=True,
            )
            assert proc.returncode == 0
            c_encoded = proc.stdout
            py_decoded = cobs_decode(c_encoded)
            assert py_decoded == data, (
                f"C-encode -> Py-decode mismatch for {length}-byte input"
            )

    def test_python_encode_then_c_ref_decode(self):
        """Data encoded by Python must be correctly decoded by C reference."""
        import subprocess
        import random
        random.seed(666)
        for _ in range(30):
            length = random.randint(0, 400)
            data = bytes(random.randint(0, 255) for _ in range(length))
            py_encoded = cobs_encode(data)

            proc = subprocess.run(
                ['/app/reference/cobs_ref', 'decode'],
                input=py_encoded,
                capture_output=True,
            )
            assert proc.returncode == 0
            c_decoded = proc.stdout
            assert c_decoded == data, (
                f"Py-encode -> C-decode mismatch for {length}-byte input"
            )
