
import subprocess
import json
import pytest


def run_cli(*args):
    """Run the CLI with the given arguments and return stripped stdout."""
    str_args = []
    for a in args:
        if isinstance(a, (list, dict)):
            str_args.append(json.dumps(a))
        else:
            str_args.append(str(a))
    cmd = ["node", "/app/dist/cli.js"] + str_args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd="/app", timeout=30)
    if result.returncode != 0:
        pytest.fail(
            f"CLI failed (exit {result.returncode}):\n"
            f"  stderr: {result.stderr.strip()}\n"
            f"  stdout: {result.stdout.strip()}\n"
            f"  cmd: {' '.join(cmd)}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# ULEB128 Tests
# ---------------------------------------------------------------------------
class TestULEB128:
    def test_encode_zero(self):
        assert run_cli("encode-uleb", "0") == "00"

    def test_encode_one(self):
        assert run_cli("encode-uleb", "1") == "01"

    def test_encode_127(self):
        assert run_cli("encode-uleb", "127") == "7f"

    def test_encode_128(self):
        assert run_cli("encode-uleb", "128") == "80 01"

    def test_encode_300(self):
        assert run_cli("encode-uleb", "300") == "ac 02"

    def test_encode_16384(self):
        assert run_cli("encode-uleb", "16384") == "80 80 01"

    def test_roundtrip(self):
        for v in [0, 1, 42, 127, 128, 255, 300, 16383, 16384, 2097152]:
            encoded = run_cli("encode-uleb", str(v))
            decoded = int(run_cli("decode-uleb", encoded))
            assert decoded == v, f"ULEB128 roundtrip failed for {v}"


# ---------------------------------------------------------------------------
# SLEB128 Tests
# ---------------------------------------------------------------------------
class TestSLEB128:
    def test_encode_zero(self):
        assert run_cli("encode-sleb", "0") == "00"

    def test_encode_one(self):
        assert run_cli("encode-sleb", "1") == "01"

    def test_encode_63(self):
        assert run_cli("encode-sleb", "63") == "3f"

    def test_encode_64(self):
        assert run_cli("encode-sleb", "64") == "c0 00"

    def test_encode_neg_one(self):
        assert run_cli("encode-sleb", "-1") == "7f"

    def test_encode_neg_64(self):
        assert run_cli("encode-sleb", "-64") == "40"

    def test_encode_neg_65(self):
        assert run_cli("encode-sleb", "-65") == "bf 7f"

    def test_encode_127(self):
        assert run_cli("encode-sleb", "127") == "ff 00"

    def test_encode_neg_128(self):
        assert run_cli("encode-sleb", "-128") == "80 7f"

    def test_decode_neg_one(self):
        """Decoding 0x7f must produce -1 (requires sign extension)."""
        assert int(run_cli("decode-sleb", "7f")) == -1

    def test_decode_neg_64(self):
        assert int(run_cli("decode-sleb", "40")) == -64

    def test_decode_neg_65(self):
        assert int(run_cli("decode-sleb", "bf 7f")) == -65

    def test_decode_neg_128(self):
        assert int(run_cli("decode-sleb", "80 7f")) == -128

    def test_decode_neg_2097152(self):
        """Large negative value requiring 4 bytes."""
        assert int(run_cli("decode-sleb", "80 80 80 7f")) == -2097152

    def test_roundtrip_positive(self):
        for v in [0, 1, 42, 63, 64, 127, 128, 8191, 100000]:
            encoded = run_cli("encode-sleb", str(v))
            decoded = int(run_cli("decode-sleb", encoded))
            assert decoded == v, f"SLEB128 roundtrip failed for {v}"

    def test_roundtrip_negative(self):
        for v in [-1, -42, -64, -65, -128, -129, -8192, -100000]:
            encoded = run_cli("encode-sleb", str(v))
            decoded = int(run_cli("decode-sleb", encoded))
            assert decoded == v, f"SLEB128 roundtrip failed for {v}"


# ---------------------------------------------------------------------------
# RLE Tests
# ---------------------------------------------------------------------------
class TestRLE:
    def test_spec_example_encode(self):
        """Automerge spec test vector for RLE unsigned."""
        result = run_cli("encode-rle-uint", [0, 0, 0, None, None, 1, 2, 3])
        assert result == "03 00 00 02 7d 01 02 03"

    def test_spec_example_decode(self):
        result = run_cli("decode-rle-uint", "03 00 00 02 7d 01 02 03")
        assert json.loads(result) == [0, 0, 0, None, None, 1, 2, 3]

    def test_encode_empty(self):
        result = run_cli("encode-rle-uint", [])
        assert result == ""

    def test_encode_single_value(self):
        """Single value must be flushed as literal run of 1."""
        result = run_cli("encode-rle-uint", [42])
        assert result == "7f 2a"

    def test_encode_all_nulls(self):
        """All-null array produces empty output (InitialNullRun optimization)."""
        result = run_cli("encode-rle-uint", [None, None, None])
        assert result == ""

    def test_encode_null_then_value(self):
        """LoneVal at end must be flushed."""
        result = run_cli("encode-rle-uint", [None, 1])
        assert result == "00 01 7f 01"

    def test_encode_run_then_lone(self):
        """After a run ends, a trailing single value must be flushed."""
        result = run_cli("encode-rle-uint", [1, 1, 2])
        # Run(1,2) + LoneVal(2) -> "02 01 7f 02"
        assert result == "02 01 7f 02"

    def test_encode_run_of_same(self):
        result = run_cli("encode-rle-uint", [5, 5, 5, 5])
        assert result == "04 05"

    def test_encode_all_different(self):
        result = run_cli("encode-rle-uint", [1, 2, 3, 4])
        assert result == "7c 01 02 03 04"

    def test_encode_rle_int_negatives(self):
        result = run_cli("encode-rle-int", [3, -2, 1])
        assert result == "7d 03 7e 01"

    def test_roundtrip_uint(self):
        test_cases = [
            [0, 0, 0, None, None, 1, 2, 3],
            [1],
            [42, 42, 42],
            [1, 2, 3, 3, 3, 4, 5],
            [None, 1, None, 2, None],
            [0],
            [None, 1],
            [1, 1, 2],
        ]
        for tc in test_cases:
            encoded = run_cli("encode-rle-uint", tc)
            if encoded:
                result = json.loads(run_cli("decode-rle-uint", encoded))
                assert result == tc, f"RLE uint roundtrip failed for {tc}: got {result}"

    def test_roundtrip_int(self):
        test_cases = [
            [1, 1, 1, -5, -5, 0],
            [-1, -1, -1, -1],
            [0, 1, -1, 2, -2],
            [3, -2, 1],
        ]
        for tc in test_cases:
            encoded = run_cli("encode-rle-int", tc)
            result = json.loads(run_cli("decode-rle-int", encoded))
            assert result == tc, f"RLE int roundtrip failed for {tc}"

    def test_literal_to_run_transition(self):
        """Test transition from literal run to value run."""
        result = run_cli("encode-rle-uint", [1, 2, 3, 3, 3])
        # Literal [1,2] then Run(3,3)
        assert result == "7e 01 02 03 03"


# ---------------------------------------------------------------------------
# Delta Tests
# ---------------------------------------------------------------------------
class TestDelta:
    def test_spec_example_encode(self):
        """Automerge spec test vector for delta encoding."""
        result = run_cli("encode-delta", [3, 4, 5, 6, 9, 7, 8])
        assert result == "7f 03 03 01 7d 03 7e 01"

    def test_spec_example_decode(self):
        result = run_cli("decode-delta", "7f 03 03 01 7d 03 7e 01")
        assert json.loads(result) == [3, 4, 5, 6, 9, 7, 8]

    def test_monotonic_sequence(self):
        """[1,2,3,4,5] -> deltas [1,1,1,1,1] -> run of 5x1."""
        result = run_cli("encode-delta", [1, 2, 3, 4, 5])
        assert result == "05 01"

    def test_constant_sequence(self):
        """[0,0,0,0] -> deltas [0,0,0,0] -> run of 4x0."""
        result = run_cli("encode-delta", [0, 0, 0, 0])
        assert result == "04 00"

    def test_with_nulls(self):
        """Nulls pass through without affecting the running absolute value."""
        result = run_cli("encode-delta", [1, 2, None, 3])
        # Deltas: [1, 1, null, 1]. RLE: Run(1,2), NullRun(1), LitRun([1])
        assert result == "02 01 00 01 7f 01"

    def test_decode_with_nulls(self):
        result = run_cli("decode-delta", "02 01 00 01 7f 01")
        assert json.loads(result) == [1, 2, None, 3]

    def test_roundtrip(self):
        test_cases = [
            [3, 4, 5, 6, 9, 7, 8],
            [0, 0, 0, 0],
            [1, 2, 3, 4, 5],
            [100, 200, 150, 300],
            [0],
            [1, 2, None, 5, 6],
        ]
        for tc in test_cases:
            encoded = run_cli("encode-delta", tc)
            result = json.loads(run_cli("decode-delta", encoded))
            assert result == tc, f"Delta roundtrip failed for {tc}: got {result}"

    def test_single_value(self):
        """Single value encoding."""
        result = run_cli("encode-delta", [42])
        # Delta from 0: [42]. RLE: LitRun([42]) -> LEB(-1) + LEB(42)
        assert result == "7f 2a"

    def test_decreasing_sequence(self):
        """Decreasing values produce negative deltas."""
        result = run_cli("encode-delta", [10, 5, 0])
        # Deltas: [10, -5, -5] -> Lit(10), Run(-5, 2)
        encoded = run_cli("encode-delta", [10, 5, 0])
        decoded = json.loads(run_cli("decode-delta", encoded))
        assert decoded == [10, 5, 0]


# ---------------------------------------------------------------------------
# Boolean Tests
# ---------------------------------------------------------------------------
class TestBoolean:
    def test_spec_example_encode(self):
        """Automerge spec test vector for boolean encoding."""
        result = run_cli("encode-bool", [True, True, False, False, False])
        assert result == "00 02 03"

    def test_spec_example_decode(self):
        result = run_cli("decode-bool", "00 02 03")
        assert json.loads(result) == [True, True, False, False, False]

    def test_all_false(self):
        result = run_cli("encode-bool", [False, False, False])
        assert result == "03"

    def test_all_true(self):
        result = run_cli("encode-bool", [True, True, True])
        assert result == "00 03"

    def test_alternating(self):
        result = run_cli("encode-bool", [False, True, False, True])
        assert result == "01 01 01 01"

    def test_encode_empty(self):
        result = run_cli("encode-bool", [])
        assert result == ""

    def test_single_true(self):
        result = run_cli("encode-bool", [True])
        assert result == "00 01"

    def test_single_false(self):
        result = run_cli("encode-bool", [False])
        assert result == "01"

    def test_roundtrip(self):
        test_cases = [
            [True, True, False, False, False],
            [False, False, False],
            [True, True, True],
            [False, True, False, True],
            [True],
            [False],
            [True, False, True, False, True, False],
            [False, False, True, True, True, False, True],
        ]
        for tc in test_cases:
            encoded = run_cli("encode-bool", tc)
            if encoded:
                result = json.loads(run_cli("decode-bool", encoded))
                assert result == tc, f"Boolean roundtrip failed for {tc}: got {result}"

    def test_long_runs(self):
        """Test with longer runs to exercise encoder/decoder."""
        tc = [False] * 100 + [True] * 50 + [False] * 25
        encoded = run_cli("encode-bool", tc)
        result = json.loads(run_cli("decode-bool", encoded))
        assert result == tc


# ---------------------------------------------------------------------------
# Column Serialization Tests
# ---------------------------------------------------------------------------
class TestColumns:
    def test_serialize_single_uint_column(self):
        """Single UINT_RLE column with a value run."""
        result = run_cli("serialize-columns", [{"id": 1, "type": 0, "values": [5, 5, 5]}])
        # numCols=1, id=1, type=0(UINT_RLE), len=2, data=[03 05]
        assert result == "01 01 00 02 03 05"

    def test_serialize_multi_column_spec_vector(self):
        """Multi-column test vector: out-of-order IDs must be sorted."""
        result = run_cli("serialize-columns", [
            {"id": 3, "type": 3, "values": [True, True, False]},
            {"id": 1, "type": 2, "values": [1, 2, 3]},
        ])
        # Sorted: col1(DELTA [1,2,3]->2 bytes), col3(BOOL [T,T,F]->3 bytes)
        # Header: 02 | 01 02 02 | 03 03 03
        # Data: 03 01 | 00 02 01
        assert result == "02 01 02 02 03 03 03 03 01 00 02 01"

    def test_deserialize_single_column(self):
        """Deserialize a single UINT_RLE column."""
        result = json.loads(run_cli("deserialize-columns", "01 01 00 02 03 05"))
        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["type"] == 0
        assert result[0]["values"] == [5, 5, 5]

    def test_deserialize_multi_column(self):
        """Deserialize the multi-column test vector."""
        result = json.loads(run_cli("deserialize-columns",
            "02 01 02 02 03 03 03 03 01 00 02 01"))
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["type"] == 2
        assert result[0]["values"] == [1, 2, 3]
        assert result[1]["id"] == 3
        assert result[1]["type"] == 3
        assert result[1]["values"] == [True, True, False]

    def test_serialize_empty(self):
        """Empty column list serializes to just the count byte."""
        result = run_cli("serialize-columns", [])
        assert result == "00"

    def test_deserialize_empty(self):
        """Deserializing a zero-column message produces empty list."""
        result = json.loads(run_cli("deserialize-columns", "00"))
        assert result == []

    def test_roundtrip_mixed_types(self):
        """Round-trip with all four column types."""
        columns = [
            {"id": 2, "type": 0, "values": [1, 1, 2, 3]},
            {"id": 5, "type": 2, "values": [10, 20, 30, 40]},
            {"id": 1, "type": 1, "values": [-1, -1, 5, 0]},
            {"id": 4, "type": 3, "values": [False, True, True, False]},
        ]
        encoded = run_cli("serialize-columns", columns)
        decoded = json.loads(run_cli("deserialize-columns", encoded))
        expected = sorted(columns, key=lambda c: c["id"])
        assert len(decoded) == len(expected)
        for i, exp_col in enumerate(expected):
            assert decoded[i]["id"] == exp_col["id"], f"Column {i} id mismatch"
            assert decoded[i]["type"] == exp_col["type"], f"Column {i} type mismatch"
            assert decoded[i]["values"] == exp_col["values"], (
                f"Column {i} values mismatch: expected {exp_col['values']}, got {decoded[i]['values']}"
            )

    def test_roundtrip_with_nulls(self):
        """Round-trip columns containing null values."""
        columns = [
            {"id": 1, "type": 0, "values": [1, None, None, 2]},
            {"id": 2, "type": 2, "values": [10, None, 30, 40]},
        ]
        encoded = run_cli("serialize-columns", columns)
        decoded = json.loads(run_cli("deserialize-columns", encoded))
        for i, exp_col in enumerate(sorted(columns, key=lambda c: c["id"])):
            assert decoded[i]["values"] == exp_col["values"], (
                f"Column {exp_col['id']} values mismatch"
            )

    def test_serialize_all_null_column(self):
        """All-null RLE column encodes with zero data bytes."""
        result = run_cli("serialize-columns", [{"id": 1, "type": 0, "values": [None, None]}])
        # numCols=1, id=1, type=0, len=0, no data
        assert result == "01 01 00 00"

    def test_column_id_ordering(self):
        """Columns must be sorted by ascending ID regardless of input order."""
        columns = [
            {"id": 10, "type": 0, "values": [1]},
            {"id": 1, "type": 0, "values": [2]},
            {"id": 5, "type": 0, "values": [3]},
        ]
        encoded = run_cli("serialize-columns", columns)
        decoded = json.loads(run_cli("deserialize-columns", encoded))
        assert [c["id"] for c in decoded] == [1, 5, 10]
        assert decoded[0]["values"] == [2]
        assert decoded[1]["values"] == [3]
        assert decoded[2]["values"] == [1]

    def test_roundtrip_signed_rle_column(self):
        """INT_RLE column with negative values."""
        columns = [{"id": 1, "type": 1, "values": [-10, -10, -10, 5, -3]}]
        encoded = run_cli("serialize-columns", columns)
        decoded = json.loads(run_cli("deserialize-columns", encoded))
        assert decoded[0]["values"] == [-10, -10, -10, 5, -3]
