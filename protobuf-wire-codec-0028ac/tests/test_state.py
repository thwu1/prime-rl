
import subprocess
import json
import os
import tempfile
import pytest

BINARY = "/app/pbcodec"
PROTO_FILE = "messages.proto"
PROTO_PATH = "/app/testdata"


@pytest.fixture(autouse=True, scope="session")
def build_binary():
    """Build the Go binary once before all tests."""
    result = subprocess.run(
        ["go", "build", "-o", BINARY, "."],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def write_schema(schema_dict):
    """Write a schema dict to a temp file, return the path."""
    fd, path = tempfile.mkstemp(suffix=".json", dir="/tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(schema_dict, f)
    return path


def run_cmd(args):
    """Run a command and return the CompletedProcess."""
    return subprocess.run(args, capture_output=True, text=True, timeout=30)


def protoc_encode(message_name, textproto):
    """Use protoc --encode to produce canonical protobuf binary output.
    Returns raw bytes (not hex)."""
    result = subprocess.run(
        ["protoc", f"--encode={message_name}",
         f"-I{PROTO_PATH}", PROTO_FILE],
        input=textproto.encode(),
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"protoc --encode={message_name} failed: "
        f"{result.stderr.decode()}"
    )
    return result.stdout


# ===========================================================================
# Conformance tests: validate codec output matches protoc canonical encoding
# ===========================================================================

class TestProtocConformance:
    """Cross-validate codec encode output against protoc reference."""

    def test_encode_double_conforms(self):
        """Codec encode of double must match protoc byte-for-byte."""
        schema_path = write_schema({
            "name": "FloatTest",
            "fields": [
                {"number": 1, "name": "val", "type": "double",
                 "repeated": False, "packed": False},
            ],
        })
        data_path = "/tmp/conform_double.json"
        with open(data_path, "w") as f:
            json.dump({"val": 3.14}, f)

        enc = run_cmd([BINARY, "encode", schema_path, data_path])
        assert enc.returncode == 0, f"Encode failed: {enc.stderr}"
        codec_hex = enc.stdout.strip()

        ref_bytes = protoc_encode("FloatTest", "val: 3.14\n")
        assert codec_hex == ref_bytes.hex(), (
            f"Codec={codec_hex} protoc={ref_bytes.hex()}"
        )

    def test_encode_fixed64_conforms(self):
        """Codec encode of fixed64 must match protoc byte-for-byte."""
        schema_path = write_schema({
            "name": "Fixed64Test",
            "fields": [
                {"number": 1, "name": "val", "type": "fixed64",
                 "repeated": False, "packed": False},
            ],
        })
        data_path = "/tmp/conform_f64.json"
        with open(data_path, "w") as f:
            json.dump({"val": 305419896}, f)

        enc = run_cmd([BINARY, "encode", schema_path, data_path])
        assert enc.returncode == 0, f"Encode failed: {enc.stderr}"
        codec_hex = enc.stdout.strip()

        ref_bytes = protoc_encode(
            "Fixed64Test", "val: 305419896\n"
        )
        assert codec_hex == ref_bytes.hex(), (
            f"Codec={codec_hex} protoc={ref_bytes.hex()}"
        )

    def test_roundtrip_via_protoc(self):
        """Encode with protoc, decode+re-encode with codec, must match."""
        schema_path = write_schema({
            "name": "RoundtripTest",
            "fields": [
                {"number": 1, "name": "signed_val", "type": "sint64",
                 "repeated": False, "packed": False},
                {"number": 2, "name": "float_val", "type": "double",
                 "repeated": False, "packed": False},
            ],
        })
        textproto = "signed_val: -42\nfloat_val: 2.718\n"
        ref_bytes = protoc_encode("RoundtripTest", textproto)
        ref_hex = ref_bytes.hex()

        # Decode protoc output with codec
        dec = run_cmd([BINARY, "decode", schema_path, ref_hex])
        assert dec.returncode == 0, f"Decode failed: {dec.stderr}"
        decoded = json.loads(dec.stdout)

        # Re-encode decoded data with codec
        data_path = "/tmp/conform_rt.json"
        with open(data_path, "w") as f:
            json.dump(decoded, f)
        enc = run_cmd([BINARY, "encode", schema_path, data_path])
        assert enc.returncode == 0, f"Re-encode failed: {enc.stderr}"
        re_hex = enc.stdout.strip()

        assert re_hex == ref_hex, (
            f"Roundtrip mismatch: codec={re_hex} protoc={ref_hex}"
        )

    def test_encode_composite_conforms(self):
        """Codec encode of composite message must match protoc."""
        schema_path = write_schema({
            "name": "CompositeTest",
            "fields": [
                {"number": 1, "name": "version", "type": "int32",
                 "repeated": False, "packed": False},
                {"number": 2, "name": "info", "type": "message",
                 "repeated": False, "packed": False,
                 "schema": {
                     "name": "NestedInner",
                     "fields": [
                         {"number": 1, "name": "label", "type": "string",
                          "repeated": False, "packed": False},
                         {"number": 2, "name": "count", "type": "int32",
                          "repeated": False, "packed": False},
                     ],
                 }},
                {"number": 3, "name": "offset", "type": "sint32",
                 "repeated": False, "packed": False},
                {"number": 4, "name": "score", "type": "double",
                 "repeated": False, "packed": False},
            ],
        })
        data_path = "/tmp/conform_comp.json"
        with open(data_path, "w") as f:
            json.dump({
                "version": 42,
                "info": {"label": "test", "count": 7},
                "offset": -100,
                "score": 1.618,
            }, f)

        enc = run_cmd([BINARY, "encode", schema_path, data_path])
        assert enc.returncode == 0, f"Encode failed: {enc.stderr}"
        codec_hex = enc.stdout.strip()

        textproto = (
            'version: 42\n'
            'info {\n'
            '  label: "test"\n'
            '  count: 7\n'
            '}\n'
            'offset: -100\n'
            'score: 1.618\n'
        )
        ref_bytes = protoc_encode("CompositeTest", textproto)
        assert codec_hex == ref_bytes.hex(), (
            f"Codec={codec_hex} protoc={ref_bytes.hex()}"
        )

    def test_packed_encode_conforms(self):
        """Codec packed repeated encode must match protoc."""
        schema_path = write_schema({
            "name": "PackedTest",
            "fields": [
                {"number": 1, "name": "vals", "type": "int32",
                 "repeated": True, "packed": True},
            ],
        })
        data_path = "/tmp/conform_packed.json"
        with open(data_path, "w") as f:
            json.dump({"vals": [3, 270, 86942]}, f)

        enc = run_cmd([BINARY, "encode", schema_path, data_path])
        assert enc.returncode == 0, f"Encode failed: {enc.stderr}"
        codec_hex = enc.stdout.strip()

        textproto = "vals: 3\nvals: 270\nvals: 86942\n"
        ref_bytes = protoc_encode("PackedTest", textproto)
        assert codec_hex == ref_bytes.hex(), (
            f"Codec={codec_hex} protoc={ref_bytes.hex()}"
        )


# ===========================================================================
# Decode tests: known hex vectors
# ===========================================================================

def test_basic_varint_decode():
    schema_path = write_schema({
        "name": "Simple",
        "fields": [{"number": 1, "name": "a", "type": "int32"}],
    })
    # Field 1, varint, value 150: tag=08, val=9601
    r = run_cmd([BINARY, "decode", schema_path, "089601"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["a"] == 150


def test_zigzag_decode_negative():
    schema_path = write_schema({
        "name": "ZZ",
        "fields": [{"number": 1, "name": "val", "type": "sint64"}],
    })
    # ZigZag(-500)=999, varint(999)=e707, tag field1 varint=08
    r = run_cmd([BINARY, "decode", schema_path, "08e707"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["val"] == -500, f"Expected -500, got {data['val']}"


def test_zigzag_decode_minus_one():
    schema_path = write_schema({
        "name": "ZZ",
        "fields": [{"number": 1, "name": "val", "type": "sint64"}],
    })
    # ZigZag(-1)=1, varint(1)=01, tag=08
    r = run_cmd([BINARY, "decode", schema_path, "0801"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["val"] == -1, f"Expected -1, got {data['val']}"


def test_double_decode():
    schema_path = write_schema({
        "name": "Dbl",
        "fields": [{"number": 1, "name": "d", "type": "double"}],
    })
    # 3.14 as LE float64 = 1f85eb51b81e0940
    # Tag field 1 I64: (1<<3)|1 = 9 -> 09
    r = run_cmd([BINARY, "decode", schema_path, "091f85eb51b81e0940"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert abs(data["d"] - 3.14) < 1e-10, f"Expected ~3.14, got {data['d']}"


def test_packed_repeated_decode():
    schema_path = write_schema({
        "name": "Pk",
        "fields": [
            {"number": 1, "name": "vals", "type": "int32",
             "repeated": True, "packed": True},
        ],
    })
    # Packed [1, 2, 150]: varints 01,02,9601 = 4 bytes payload
    # Tag field 1 LEN: (1<<3)|2 = 0a, length=04
    r = run_cmd([BINARY, "decode", schema_path, "0a0401029601"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["vals"] == [1, 2, 150], (
        f"Expected [1,2,150], got {data['vals']}"
    )


def test_varint_overflow_rejection():
    schema_path = write_schema({
        "name": "Simple",
        "fields": [{"number": 1, "name": "a", "type": "uint64"}],
    })
    # tag=08, then 10-byte varint with last byte = 0x02 -> overflow
    r = run_cmd([BINARY, "decode", schema_path,
                 "08ffffffffffffffffff02"])
    assert r.returncode != 0, (
        "Expected error for varint overflow, but got success"
    )


def test_group_decode():
    schema_path = write_schema({
        "name": "WG",
        "fields": [
            {"number": 1, "name": "id", "type": "uint32"},
            {
                "number": 2,
                "name": "meta",
                "type": "group",
                "schema": {
                    "name": "Meta",
                    "fields": [
                        {"number": 1, "name": "key", "type": "string"},
                        {"number": 2, "name": "value", "type": "string"},
                    ],
                },
            },
        ],
    })
    # id=42: tag=08 val=2a
    # group field 2 SGROUP: (2<<3)|3=19 -> 13
    #   key="color": tag=0a len=05 val=636f6c6f72
    #   value="red": tag=12 len=03 val=726564
    # EGROUP field 2: (2<<3)|4=20 -> 14
    hex_in = "082a130a05636f6c6f72120372656414"
    r = run_cmd([BINARY, "decode", schema_path, hex_in])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["id"] == 42
    assert data["meta"]["key"] == "color"
    assert data["meta"]["value"] == "red"


def test_skip_unknown_group():
    schema_path = write_schema({
        "name": "Simple",
        "fields": [{"number": 1, "name": "a", "type": "int32"}],
    })
    # Unknown field 5 group:
    #   SGROUP: (5<<3)|3 = 43 -> 2b
    #   inner field 1 varint 99: 08 63
    #   EGROUP: (5<<3)|4 = 44 -> 2c
    # Then field 1 = 42: 08 2a
    r = run_cmd([BINARY, "decode", schema_path, "2b08632c082a"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["a"] == 42


# ===========================================================================
# Encode-decode roundtrip
# ===========================================================================

def test_encode_decode_roundtrip():
    schema_path = write_schema({
        "name": "RT",
        "fields": [
            {"number": 1, "name": "id", "type": "uint32"},
            {"number": 2, "name": "name", "type": "string"},
            {"number": 3, "name": "active", "type": "bool"},
            {"number": 4, "name": "score", "type": "float"},
            {"number": 5, "name": "offset", "type": "sint32"},
        ],
    })
    data_in = {"id": 42, "name": "test", "active": True,
               "score": 1.5, "offset": -7}
    data_path = "/tmp/rt_data.json"
    with open(data_path, "w") as f:
        json.dump(data_in, f)

    enc = run_cmd([BINARY, "encode", schema_path, data_path])
    assert enc.returncode == 0, f"Encode failed: {enc.stderr}"
    hex_str = enc.stdout.strip()

    dec = run_cmd([BINARY, "decode", schema_path, hex_str])
    assert dec.returncode == 0, f"Decode failed: {dec.stderr}"
    data_out = json.loads(dec.stdout)

    assert data_out["id"] == 42
    assert data_out["name"] == "test"
    assert data_out["active"] is True
    assert abs(data_out["score"] - 1.5) < 1e-6
    assert data_out["offset"] == -7, f"Expected -7, got {data_out['offset']}"


# ===========================================================================
# Merge tests
# ===========================================================================

def test_merge_submessage_recursive():
    schema_path = write_schema({
        "name": "MT",
        "fields": [
            {"number": 1, "name": "name", "type": "string"},
            {
                "number": 2,
                "name": "inner",
                "type": "message",
                "schema": {
                    "name": "Inner",
                    "fields": [
                        {"number": 1, "name": "x", "type": "int32"},
                        {"number": 2, "name": "y", "type": "int32"},
                        {"number": 3, "name": "label", "type": "string"},
                    ],
                },
            },
            {"number": 3, "name": "items", "type": "int32",
             "repeated": True, "packed": True},
        ],
    })
    # msg1: name="hello", inner={x:10, y:20}, items=[1,2]
    msg1 = "0a0568656c6c6f1204080a10141a020102"
    # msg2: name="world", inner={x:30, label:"test"}, items=[3]
    msg2 = "0a05776f726c641208081e1a04746573741a0103"

    r = run_cmd([BINARY, "merge", schema_path, msg1, msg2])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["name"] == "world"
    assert data["inner"]["x"] == 30
    assert data["inner"]["y"] == 20
    assert data["inner"]["label"] == "test"
    assert data["items"] == [1, 2, 3]


def test_merge_scalar_and_repeated():
    schema_path = write_schema({
        "name": "M2",
        "fields": [
            {"number": 1, "name": "count", "type": "int32"},
            {"number": 2, "name": "tags", "type": "int32",
             "repeated": True, "packed": True},
        ],
    })
    # msg1: count=10, tags=[1,2]
    msg1 = "080a12020102"
    # msg2: count=20, tags=[3]
    msg2 = "0814120103"

    r = run_cmd([BINARY, "merge", schema_path, msg1, msg2])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["count"] == 20
    assert data["tags"] == [1, 2, 3]
