
import pytest
import subprocess
import json
import os
import struct
import tempfile
import ctypes

INTERP = "/app/ddl_interpreter.py"
SPECS = "/app/specs"


def run_interp(spec_name, input_data, expect_fail=False):
    """Run the DDL interpreter on a spec file with given binary input."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(input_data)
        input_path = f.name
    try:
        result = subprocess.run(
            ["python3", INTERP, os.path.join(SPECS, spec_name), input_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        os.unlink(input_path)

    if expect_fail:
        assert result.returncode != 0, (
            f"Expected failure but got success. stdout={result.stdout[:200]}"
        )
        return None

    assert result.returncode == 0, (
        f"Interpreter failed (exit {result.returncode}): {result.stderr[:500]}"
    )
    return json.loads(result.stdout)


# ===================================================================
# Flex/gcc/ctypes pipeline verification tests
# ===================================================================

def test_flex_spec_exists():
    """Verify the flex lexer specification file exists with valid flex constructs."""
    assert os.path.exists("/app/ddl_lexer.l"), "Missing /app/ddl_lexer.l"
    with open("/app/ddl_lexer.l") as f:
        content = f.read()
    # Flex files must contain the %% section delimiter
    assert content.count("%%") >= 2, (
        "Flex spec must contain at least two %% delimiters (definitions/rules/code sections)"
    )
    # Must have flex-specific directives
    assert "%option" in content or "%x" in content or "%s" in content, (
        "Flex spec should contain flex-specific directives (%option, %x, or %s)"
    )


def test_build_script_produces_library():
    """Build script compiles flex spec into shared library."""
    assert os.path.exists("/app/build.sh"), "Missing /app/build.sh"
    result = subprocess.run(
        ["bash", "/app/build.sh"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"build.sh failed (exit {result.returncode}): {result.stderr[:500]}"
    )
    assert os.path.exists("/app/libddl_lexer.so"), (
        "build.sh must produce /app/libddl_lexer.so"
    )


def test_interpreter_depends_on_library():
    """Interpreter must depend on the flex-generated shared library."""
    # Ensure library exists first
    subprocess.run(["bash", "/app/build.sh"], capture_output=True, timeout=60, cwd="/app")
    assert os.path.exists("/app/libddl_lexer.so"), "Library must exist for this test"

    # Verify interpreter works WITH the library
    inp = _make_simple_msg(1, [(0x01, b"Hi")])
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(inp)
        ipath = f.name

    try:
        r_ok = subprocess.run(
            ["python3", INTERP, os.path.join(SPECS, "simple_msg.ddl"), ipath],
            capture_output=True, text=True, timeout=30,
        )
        assert r_ok.returncode == 0, (
            f"Interpreter should succeed with library present: {r_ok.stderr[:300]}"
        )

        # Temporarily rename library — interpreter should fail
        os.rename("/app/libddl_lexer.so", "/app/libddl_lexer.so.hidden")
        try:
            r_fail = subprocess.run(
                ["python3", INTERP, os.path.join(SPECS, "simple_msg.ddl"), ipath],
                capture_output=True, text=True, timeout=30,
            )
            assert r_fail.returncode != 0, (
                "Interpreter must fail without the shared library (no pure-Python fallback allowed)"
            )
        finally:
            os.rename("/app/libddl_lexer.so.hidden", "/app/libddl_lexer.so")
    finally:
        os.unlink(ipath)


# ===================================================================
# simple_msg.ddl tests
# ===================================================================

def _make_simple_msg(version, messages):
    """Build binary for simple_msg.ddl.
    messages: list of (tag_byte, payload_bytes)
    """
    data = bytearray()
    data += bytes([0x48, 0x44, 0x52])          # magic
    data += bytes([version])                    # version
    data += struct.pack(">H", len(messages))    # msg_count
    for tag, payload in messages:
        data += bytes([tag])
        data += bytes([len(payload)])
        data += payload
    return bytes(data)


def test_simple_msg_two_messages():
    inp = _make_simple_msg(1, [
        (0x01, b"Hello"),               # text tag
        (0x02, bytes([0xDE, 0xAD, 0xFF])),  # binary tag
    ])
    r = run_interp("simple_msg.ddl", inp)
    assert r["version"] == 1
    assert r["msg_count"] == 2
    assert len(r["messages"]) == 2
    m0 = r["messages"][0]
    assert m0["tag"] == "text"
    assert m0["len"] == 5
    assert m0["payload"] == [72, 101, 108, 108, 111]
    m1 = r["messages"][1]
    assert m1["tag"] == "binary"
    assert m1["len"] == 3
    assert m1["payload"] == [0xDE, 0xAD, 0xFF]


def test_simple_msg_zero_messages():
    inp = _make_simple_msg(5, [])
    r = run_interp("simple_msg.ddl", inp)
    assert r["version"] == 5
    assert r["msg_count"] == 0
    assert r["messages"] == []


def test_simple_msg_bad_magic():
    bad = bytes([0x00, 0x00, 0x00, 0x01, 0x00, 0x00])
    run_interp("simple_msg.ddl", bad, expect_fail=True)


# ===================================================================
# sensor_data.ddl tests
# ===================================================================

def _make_sensor_data(version, flags_byte, records):
    """Build binary for sensor_data.ddl.
    records: list of (sensor_id, reading_type, reading_bytes)
        reading_type: 1=temp(2-byte value), 2=pressure(4-byte value), 3=raw(1-byte len + data)
    """
    data = bytearray()
    data += bytes([0x53, 0x44])                 # magic
    data += bytes([version])                    # version
    data += bytes([flags_byte])                 # flags
    data += struct.pack(">H", len(records))     # count
    for sid, rtype, rbytes in records:
        data += struct.pack(">H", sid)          # sensor_id
        data += bytes([rtype])                  # reading tag
        data += rbytes                          # reading data
    data += bytes([0xFF, 0xFF])                 # end marker
    return bytes(data)


def test_sensor_data_mixed_readings():
    inp = _make_sensor_data(
        version=2,
        flags_byte=0x80,  # compressed=1, signed=0, reserved=0
        records=[
            (1, 0x01, struct.pack(">H", 300)),       # temperature=300
            (2, 0x02, struct.pack(">I", 100000)),     # pressure=100000
            (3, 0x03, bytes([4, 0xAA, 0xBB, 0xCC, 0xDD])),  # raw len=4
        ],
    )
    r = run_interp("sensor_data.ddl", inp)

    # header
    assert r["header"]["version"] == 2
    assert r["header"]["flags"]["compressed"] == 1
    assert r["header"]["flags"]["signed"] == 0
    assert r["header"]["flags"]["reserved"] == 0
    assert r["header"]["count"] == 3

    # records
    assert len(r["records"]) == 3

    rec0 = r["records"][0]
    assert rec0["sensor_id"] == 1
    assert "temperature" in rec0["reading"]
    assert rec0["reading"]["temperature"]["value"] == 300

    rec1 = r["records"][1]
    assert rec1["sensor_id"] == 2
    assert "pressure" in rec1["reading"]
    assert rec1["reading"]["pressure"]["value"] == 100000

    rec2 = r["records"][2]
    assert rec2["sensor_id"] == 3
    assert "raw" in rec2["reading"]
    assert rec2["reading"]["raw"]["data"] == [0xAA, 0xBB, 0xCC, 0xDD]


def test_sensor_data_single_temp():
    inp = _make_sensor_data(
        version=1,
        flags_byte=0x00,  # all flags zero
        records=[
            (42, 0x01, struct.pack(">H", 0)),  # temperature=0
        ],
    )
    r = run_interp("sensor_data.ddl", inp)
    assert r["header"]["flags"]["compressed"] == 0
    assert r["header"]["flags"]["signed"] == 0
    assert len(r["records"]) == 1
    assert r["records"][0]["sensor_id"] == 42
    assert r["records"][0]["reading"]["temperature"]["value"] == 0


def test_sensor_data_missing_end_marker():
    data = bytes([0x53, 0x44, 0x01, 0x00, 0x00, 0x00])  # no end marker
    run_interp("sensor_data.ddl", data, expect_fail=True)


# ===================================================================
# packet.ddl tests
# ===================================================================

def _make_packet(version, ptype, body_bytes, checksum):
    data = bytearray()
    data += bytes([0x50, 0x4B])
    data += bytes([version])
    data += bytes([ptype])
    data += body_bytes
    data += struct.pack(">H", checksum)
    return bytes(data)


def test_packet_text_body():
    text = b"Hello"
    body = text + b"\x00"
    inp = _make_packet(1, 0x01, body, 0xABCD)
    r = run_interp("packet.ddl", inp)
    assert r["version"] == 1
    assert r["ptype"] == 1
    assert "text" in r["body"]
    assert r["body"]["text"] == list(text)
    assert r["checksum"] == 0xABCD


def test_packet_pairs_body():
    body = bytearray()
    body += bytes([2])                    # count=2
    body += b"k1\x00"                     # key1
    body += struct.pack(">H", 10)         # value1
    body += b"k2\x00"                     # key2
    body += struct.pack(">H", 20)         # value2
    inp = _make_packet(2, 0x02, bytes(body), 0)
    r = run_interp("packet.ddl", inp)
    assert r["version"] == 2
    assert r["ptype"] == 2
    assert "pairs" in r["body"]
    pairs = r["body"]["pairs"]
    assert pairs["count"] == 2
    assert len(pairs["items"]) == 2
    assert pairs["items"][0]["key"] == [0x6B, 0x31]  # "k1"
    assert pairs["items"][0]["value"] == 10
    assert pairs["items"][1]["key"] == [0x6B, 0x32]  # "k2"
    assert pairs["items"][1]["value"] == 20


def test_packet_raw_body_wildcard():
    """ptype=5 hits the _ wildcard -> raw body."""
    body = struct.pack(">H", 3) + bytes([0x11, 0x22, 0x33])
    inp = _make_packet(1, 0x05, body, 0x1234)
    r = run_interp("packet.ddl", inp)
    assert r["ptype"] == 5
    assert "raw" in r["body"]
    assert r["body"]["raw"]["len"] == 3
    assert r["body"]["raw"]["data"] == [0x11, 0x22, 0x33]
    assert r["checksum"] == 0x1234


def test_packet_bad_magic():
    run_interp("packet.ddl", bytes([0x00, 0x00, 0x01, 0x01, 0x00, 0x00]), expect_fail=True)
