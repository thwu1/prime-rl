
import json
import os
import struct
import subprocess
import tempfile

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

BINARY = "/app/arrow_ipc_reader/target/release/arrow_ipc_reader"
TMPDIR = tempfile.mkdtemp(prefix="arrow_ipc_test_")


# ── helpers ──────────────────────────────────────────────────────────────────

def write_ipc_stream(path, schema, batches):
    sink = pa.BufferOutputStream()
    writer = ipc.new_stream(sink, schema)
    for b in batches:
        writer.write_batch(b)
    writer.close()
    with open(path, "wb") as f:
        f.write(sink.getvalue())


def run_reader(arrows_path):
    json_path = arrows_path + ".out.json"
    r = subprocess.run(
        [BINARY, arrows_path, json_path],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"binary failed: {r.stderr}"
    with open(json_path) as f:
        return json.load(f)


# ── reference JSON builder ──────────────────────────────────────────────────

def _type_json(t):
    if pa.types.is_null(t):
        return {"name": "null"}
    if pa.types.is_boolean(t):
        return {"name": "bool"}
    if pa.types.is_integer(t):
        return {"name": "int", "bitWidth": t.bit_width, "isSigned": str(t).startswith("int")}
    if pa.types.is_floating(t):
        prec = {16: "HALF", 32: "SINGLE", 64: "DOUBLE"}[t.bit_width]
        return {"name": "floatingpoint", "precision": prec}
    if pa.types.is_string(t):
        return {"name": "utf8"}
    if pa.types.is_binary(t):
        return {"name": "binary"}
    if pa.types.is_list(t):
        return {"name": "list"}
    if pa.types.is_struct(t):
        return {"name": "struct"}
    if pa.types.is_dictionary(t):
        return _type_json(t.value_type)
    return {"name": "unknown"}


def _field_json(field):
    r = {
        "name": field.name,
        "nullable": field.nullable,
        "type": _type_json(field.type if not pa.types.is_dictionary(field.type) else field.type.value_type),
        "children": [],
    }
    t = field.type
    if pa.types.is_dictionary(t):
        vt = t.value_type
    else:
        vt = t
    if pa.types.is_list(vt):
        r["children"] = [_field_json(vt.value_field)]
    elif pa.types.is_struct(vt):
        r["children"] = [_field_json(vt.field(i)) for i in range(vt.num_fields)]
    if pa.types.is_dictionary(t):
        r["dictionary"] = {
            "id": _dict_id_counter(field),
            "indexType": _type_json(t.index_type),
            "isOrdered": t.ordered,
        }
    return r


_dict_id_map = {}
_dict_id_next = [0]


def _dict_id_counter(field):
    key = id(field)
    if key not in _dict_id_map:
        _dict_id_map[key] = _dict_id_next[0]
        _dict_id_next[0] += 1
    return _dict_id_map[key]


def _column_json(name, arr):
    """Convert a pyarrow array to integration-test JSON column."""
    count = len(arr)
    t = arr.type

    if pa.types.is_dictionary(t):
        indices = arr.indices
        result = {"name": name, "count": count}
        result["VALIDITY"] = [0 if arr[i].as_py() is None else 1 for i in range(count)]
        data = []
        for i in range(count):
            v = indices[i].as_py()
            data.append(0 if v is None else int(v))
        if t.index_type.bit_width == 64:
            data = [str(d) for d in data]
        result["DATA"] = data
        return result

    result = {"name": name, "count": count}

    if pa.types.is_null(t):
        result["VALIDITY"] = [0] * count
        return result

    validity = [0 if arr[i].as_py() is None else 1 for i in range(count)]
    result["VALIDITY"] = validity

    if pa.types.is_boolean(t):
        result["DATA"] = [int(bool(arr[i].as_py())) if arr[i].as_py() is not None else 0
                          for i in range(count)]

    elif pa.types.is_integer(t):
        data = []
        for i in range(count):
            v = arr[i].as_py()
            v = 0 if v is None else int(v)
            data.append(str(v) if t.bit_width == 64 else v)
        result["DATA"] = data

    elif pa.types.is_floating(t):
        data = []
        for i in range(count):
            v = arr[i].as_py()
            data.append(0.0 if v is None else float(v))
        result["DATA"] = data

    elif pa.types.is_string(t):
        bufs = arr.buffers()
        off_buf = bufs[1]
        offsets = [struct.unpack_from("<i", off_buf, j * 4)[0] for j in range(count + 1)]
        data_buf = bufs[2]
        data = []
        for i in range(count):
            s = bytes(data_buf[offsets[i]:offsets[i + 1]]).decode("utf-8") if data_buf else ""
            data.append(s)
        result["OFFSET"] = offsets
        result["DATA"] = data

    elif pa.types.is_binary(t):
        bufs = arr.buffers()
        off_buf = bufs[1]
        offsets = [struct.unpack_from("<i", off_buf, j * 4)[0] for j in range(count + 1)]
        data_buf = bufs[2]
        data = []
        for i in range(count):
            b = bytes(data_buf[offsets[i]:offsets[i + 1]]) if data_buf else b""
            data.append(b.hex().upper())
        result["OFFSET"] = offsets
        result["DATA"] = data

    elif pa.types.is_list(t):
        bufs = arr.buffers()
        off_buf = bufs[1]
        offsets = [struct.unpack_from("<i", off_buf, j * 4)[0] for j in range(count + 1)]
        result["OFFSET"] = offsets
        child_name = t.value_field.name
        result["children"] = [_column_json(child_name, arr.values)]

    elif pa.types.is_struct(t):
        children = []
        for i in range(t.num_fields):
            children.append(_column_json(t.field(i).name, arr.field(i)))
        result["children"] = children

    return result


def _dict_batch_json(dict_id, arr):
    """Build a dictionary batch JSON from a pyarrow dictionary array."""
    dictionary = arr.dictionary
    col = _column_json(f"DICT{dict_id}", dictionary)
    return {"id": dict_id, "data": {"count": len(dictionary), "columns": [col]}}


# ── deep comparison ─────────────────────────────────────────────────────────

def _deep_cmp(expected, actual, path="root"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict got {type(actual).__name__}"
        for k in expected:
            assert k in actual, f"{path}: missing key '{k}' (actual keys: {list(actual.keys())})"
            _deep_cmp(expected[k], actual[k], f"{path}.{k}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list got {type(actual).__name__}"
        assert len(expected) == len(actual), f"{path}: len {len(expected)} vs {len(actual)}"
        for i, (e, a) in enumerate(zip(expected, actual)):
            _deep_cmp(e, a, f"{path}[{i}]")
    elif isinstance(expected, float):
        assert isinstance(actual, (int, float)), f"{path}: expected number got {type(actual).__name__}"
        assert abs(expected - float(actual)) < 1e-3, f"{path}: {expected} vs {actual}"
    elif isinstance(expected, bool):
        assert actual == expected, f"{path}: {expected!r} vs {actual!r}"
    elif isinstance(expected, str):
        assert isinstance(actual, str), f"{path}: expected str got {type(actual).__name__}: {actual!r}"
        assert expected == actual, f"{path}: {expected!r} vs {actual!r}"
    elif isinstance(expected, int):
        assert isinstance(actual, (int, float)), f"{path}: expected int got {type(actual).__name__}"
        assert int(expected) == int(actual), f"{path}: {expected} vs {actual}"
    else:
        assert expected == actual, f"{path}: {expected!r} vs {actual!r}"


# ── tests ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_dict_ids():
    _dict_id_map.clear()
    _dict_id_next[0] = 0


def test_binary_exists():
    assert os.path.isfile(BINARY), f"Binary not found at {BINARY}"


def test_int32_with_nulls():
    schema = pa.schema([pa.field("i32", pa.int32())])
    batch = pa.record_batch([pa.array([1, None, 3, -42, 0], type=pa.int32())], schema=schema)
    p = os.path.join(TMPDIR, "int32.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    assert out["schema"]["fields"][0]["type"]["name"] == "int"
    assert out["schema"]["fields"][0]["type"]["bitWidth"] == 32
    assert out["schema"]["fields"][0]["type"]["isSigned"] is True

    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [1, 0, 1, 1, 1]
    assert col["DATA"][0] == 1
    assert col["DATA"][2] == 3
    assert col["DATA"][3] == -42


def test_multiple_primitives():
    schema = pa.schema([
        pa.field("i32", pa.int32()),
        pa.field("f64", pa.float64()),
        pa.field("b", pa.bool_()),
    ])
    batch = pa.record_batch([
        pa.array([10, None, 30], type=pa.int32()),
        pa.array([1.5, None, -3.25], type=pa.float64()),
        pa.array([True, False, None], type=pa.bool_()),
    ], schema=schema)
    p = os.path.join(TMPDIR, "multi_prim.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    assert len(out["schema"]["fields"]) == 3
    b = out["batches"][0]
    assert b["count"] == 3

    # int32
    c0 = b["columns"][0]
    assert c0["VALIDITY"] == [1, 0, 1]
    assert c0["DATA"][0] == 10

    # float64
    c1 = b["columns"][1]
    assert c1["VALIDITY"] == [1, 0, 1]
    assert abs(c1["DATA"][0] - 1.5) < 1e-6
    assert abs(c1["DATA"][2] - (-3.25)) < 1e-6

    # bool
    c2 = b["columns"][2]
    assert c2["VALIDITY"] == [1, 1, 0]
    assert c2["DATA"][0] == 1  # True
    assert c2["DATA"][1] == 0  # False


def test_utf8():
    schema = pa.schema([pa.field("s", pa.utf8())])
    batch = pa.record_batch(
        [pa.array(["hello", None, "", "world"], type=pa.utf8())], schema=schema
    )
    p = os.path.join(TMPDIR, "utf8.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    assert out["schema"]["fields"][0]["type"]["name"] == "utf8"
    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [1, 0, 1, 1]
    assert col["DATA"][0] == "hello"
    assert col["DATA"][2] == ""
    assert col["DATA"][3] == "world"
    assert "OFFSET" in col
    assert len(col["OFFSET"]) == 5  # count + 1


def test_integer_types():
    schema = pa.schema([
        pa.field("i8", pa.int8()),
        pa.field("i16", pa.int16()),
        pa.field("i64", pa.int64()),
        pa.field("u8", pa.uint8()),
        pa.field("u16", pa.uint16()),
        pa.field("u32", pa.uint32()),
        pa.field("u64", pa.uint64()),
    ])
    batch = pa.record_batch([
        pa.array([1, -2, None], type=pa.int8()),
        pa.array([100, -200, None], type=pa.int16()),
        pa.array([1000000, -2000000, None], type=pa.int64()),
        pa.array([1, 2, None], type=pa.uint8()),
        pa.array([100, 200, None], type=pa.uint16()),
        pa.array([1000, 2000, None], type=pa.uint32()),
        pa.array([10000, 20000, None], type=pa.uint64()),
    ], schema=schema)
    p = os.path.join(TMPDIR, "int_types.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    b = out["batches"][0]
    # i8
    assert b["columns"][0]["DATA"][0] == 1
    assert b["columns"][0]["DATA"][1] == -2
    # i16
    assert b["columns"][1]["DATA"][0] == 100
    assert b["columns"][1]["DATA"][1] == -200
    # i64 — must be strings
    assert b["columns"][2]["DATA"][0] == "1000000"
    assert b["columns"][2]["DATA"][1] == "-2000000"
    # u8
    assert b["columns"][3]["DATA"][0] == 1
    # u64 — must be strings
    assert b["columns"][6]["DATA"][0] == "10000"
    assert b["columns"][6]["DATA"][1] == "20000"


def test_float32():
    """Verify Float32 type is supported with correct schema and data."""
    schema = pa.schema([pa.field("f32", pa.float32())])
    batch = pa.record_batch(
        [pa.array([1.25, None, -0.5, 0.0], type=pa.float32())], schema=schema
    )
    p = os.path.join(TMPDIR, "float32.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    # Schema check: precision must be SINGLE for float32
    assert out["schema"]["fields"][0]["type"]["name"] == "floatingpoint"
    assert out["schema"]["fields"][0]["type"]["precision"] == "SINGLE"

    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [1, 0, 1, 1]
    assert abs(col["DATA"][0] - 1.25) < 1e-3
    assert abs(col["DATA"][2] - (-0.5)) < 1e-3
    assert abs(col["DATA"][3] - 0.0) < 1e-6


def test_binary():
    """Verify Binary type is supported with uppercase hex DATA and OFFSET."""
    schema = pa.schema([pa.field("bin", pa.binary())])
    batch = pa.record_batch(
        [pa.array([b"\x00\x01\x02", None, b"", b"\xff\xab"], type=pa.binary())],
        schema=schema,
    )
    p = os.path.join(TMPDIR, "binary.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    # Schema check
    assert out["schema"]["fields"][0]["type"]["name"] == "binary"

    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [1, 0, 1, 1]
    assert "OFFSET" in col
    assert len(col["OFFSET"]) == 5  # count + 1
    # Binary DATA must be uppercase hex strings
    assert col["DATA"][0] == "000102"
    assert col["DATA"][2] == ""
    assert col["DATA"][3] == "FFAB"


def test_null_type():
    """Verify standalone Null type columns are handled (no data buffers)."""
    schema = pa.schema([pa.field("n", pa.null()), pa.field("x", pa.int32())])
    batch = pa.record_batch([
        pa.array([None, None, None], type=pa.null()),
        pa.array([10, 20, 30], type=pa.int32()),
    ], schema=schema)
    p = os.path.join(TMPDIR, "null_type.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    # Schema check
    assert out["schema"]["fields"][0]["type"]["name"] == "null"
    assert out["schema"]["fields"][1]["type"]["name"] == "int"

    # Null column: all validity 0, no DATA key required
    null_col = out["batches"][0]["columns"][0]
    assert null_col["VALIDITY"] == [0, 0, 0]
    assert null_col["count"] == 3

    # Int column alongside should still work
    int_col = out["batches"][0]["columns"][1]
    assert int_col["DATA"] == [10, 20, 30]


def test_list():
    schema = pa.schema([pa.field("l", pa.list_(pa.int32()))])
    batch = pa.record_batch(
        [pa.array([[1, 2, 3], None, [], [4], [5, 6]], type=pa.list_(pa.int32()))],
        schema=schema,
    )
    p = os.path.join(TMPDIR, "list.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    assert out["schema"]["fields"][0]["type"]["name"] == "list"
    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [1, 0, 1, 1, 1]
    assert "OFFSET" in col
    assert col["OFFSET"][0] == 0
    assert col["OFFSET"][1] == 3  # first list has 3 elements
    child = col["children"][0]
    assert child["count"] == 6  # total flat child elements
    assert child["DATA"][0] == 1
    assert child["DATA"][5] == 6


def test_struct():
    st_type = pa.struct([pa.field("a", pa.int32()), pa.field("b", pa.utf8())])
    schema = pa.schema([pa.field("st", st_type)])
    batch = pa.record_batch(
        [pa.array(
            [{"a": 1, "b": "x"}, None, {"a": 3, "b": None}, {"a": None, "b": "y"}],
            type=st_type,
        )],
        schema=schema,
    )
    p = os.path.join(TMPDIR, "struct.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    assert out["schema"]["fields"][0]["type"]["name"] == "struct"
    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [1, 0, 1, 1]
    assert len(col["children"]) == 2
    # child 'a' is Int32
    ca = col["children"][0]
    assert ca["name"] == "a"
    assert ca["DATA"][0] == 1
    # child 'b' is Utf8
    cb = col["children"][1]
    assert cb["name"] == "b"
    assert cb["DATA"][0] == "x"
    assert cb["VALIDITY"][2] == 0  # null 'b' in third struct


def test_dictionary():
    arr = pa.array(["foo", "bar", "foo", None, "baz"]).dictionary_encode()
    schema = pa.schema([pa.field("d", arr.type)])
    batch = pa.record_batch([arr], schema=schema)
    p = os.path.join(TMPDIR, "dict.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    # Schema should show dictionary info
    f = out["schema"]["fields"][0]
    assert "dictionary" in f
    assert "indexType" in f["dictionary"]
    assert f["type"]["name"] == "utf8"  # value type

    # Batch column should contain indices
    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [1, 1, 1, 0, 1]
    # indices: foo=0, bar=1, foo=0, null, baz=2
    assert col["DATA"][0] == 0
    assert col["DATA"][1] == 1
    assert col["DATA"][2] == 0
    assert col["DATA"][4] == 2

    # Dictionary batch should exist
    assert "dictionaries" in out
    assert len(out["dictionaries"]) >= 1
    db = out["dictionaries"][0]
    dict_col = db["data"]["columns"][0]
    # dictionary values: foo, bar, baz
    assert dict_col["count"] == 3
    assert "foo" in dict_col["DATA"]
    assert "bar" in dict_col["DATA"]
    assert "baz" in dict_col["DATA"]


def test_multiple_batches():
    schema = pa.schema([pa.field("x", pa.int32())])
    b1 = pa.record_batch([pa.array([1, 2], type=pa.int32())], schema=schema)
    b2 = pa.record_batch([pa.array([3, 4, 5], type=pa.int32())], schema=schema)
    p = os.path.join(TMPDIR, "multi_batch.arrows")
    write_ipc_stream(p, schema, [b1, b2])
    out = run_reader(p)

    assert len(out["batches"]) == 2
    assert out["batches"][0]["count"] == 2
    assert out["batches"][1]["count"] == 3
    assert out["batches"][0]["columns"][0]["DATA"] == [1, 2]
    assert out["batches"][1]["columns"][0]["DATA"] == [3, 4, 5]


def test_empty_batch():
    schema = pa.schema([pa.field("v", pa.int32())])
    batch = pa.record_batch([pa.array([], type=pa.int32())], schema=schema)
    p = os.path.join(TMPDIR, "empty.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    assert out["batches"][0]["count"] == 0
    assert out["batches"][0]["columns"][0]["count"] == 0


def test_all_null():
    schema = pa.schema([pa.field("n", pa.int32())])
    batch = pa.record_batch([pa.array([None, None, None], type=pa.int32())], schema=schema)
    p = os.path.join(TMPDIR, "allnull.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [0, 0, 0]


def test_nested_struct_list():
    inner = pa.struct([pa.field("x", pa.int32()), pa.field("y", pa.list_(pa.utf8()))])
    schema = pa.schema([pa.field("n", inner)])
    batch = pa.record_batch(
        [pa.array(
            [
                {"x": 10, "y": ["a", "b"]},
                None,
                {"x": 30, "y": []},
            ],
            type=inner,
        )],
        schema=schema,
    )
    p = os.path.join(TMPDIR, "nested.arrows")
    write_ipc_stream(p, schema, [batch])
    out = run_reader(p)

    col = out["batches"][0]["columns"][0]
    assert col["VALIDITY"] == [1, 0, 1]
    # child 'x' (Int32)
    cx = col["children"][0]
    assert cx["DATA"][0] == 10
    assert cx["DATA"][2] == 30
    # child 'y' (List<Utf8>)
    cy = col["children"][1]
    assert cy["OFFSET"][0] == 0
    assert cy["OFFSET"][1] == 2  # first list has 2 elements
    gc = cy["children"][0]  # grandchild Utf8
    assert gc["DATA"][0] == "a"
    assert gc["DATA"][1] == "b"
