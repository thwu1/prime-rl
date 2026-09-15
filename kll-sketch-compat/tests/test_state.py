"""Tests for KLL Doubles Sketch toolkit: algorithm, binary format, CLI, SQLite, JSON schema, tool interop."""


import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, "/app")

import datasketches

RANK_ERROR_BOUND = 0.0175
DB_PATH = "/app/sketch_store.db"
TOOL = "/app/kll_tool.py"

JSON_REQUIRED_KEYS = {
    "name", "k", "n", "min_value", "max_value",
    "is_empty", "is_estimation_mode", "num_retained",
    "quantiles", "created_at",
}

QUANTILE_KEYS = {"0.0", "0.25", "0.5", "0.75", "1.0"}


def _clean_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def _run_cli(args, stdin_data=None, binary_stdout=False):
    """Run kll_tool.py with given args. Returns (stdout, stderr, returncode)."""
    cmd = [sys.executable, TOOL] + args
    proc = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        cwd="/app",
    )
    if binary_stdout:
        return proc.stdout, proc.stderr.decode(), proc.returncode
    return proc.stdout.decode(), proc.stderr.decode(), proc.returncode


def _validate_json_schema(obj, expect_empty=False):
    """Validate that obj conforms to the documented JSON output schema."""
    assert set(obj.keys()) == JSON_REQUIRED_KEYS, f"keys mismatch: {set(obj.keys())}"
    assert isinstance(obj["name"], str)
    assert isinstance(obj["k"], int)
    assert isinstance(obj["n"], int)
    assert isinstance(obj["is_empty"], bool)
    assert isinstance(obj["is_estimation_mode"], bool)
    assert isinstance(obj["num_retained"], int)
    assert isinstance(obj["created_at"], str)
    # ISO 8601 basic check
    assert "T" in obj["created_at"], "created_at must be ISO 8601"

    if expect_empty or obj["is_empty"]:
        assert obj["min_value"] is None
        assert obj["max_value"] is None
        assert obj["quantiles"] is None
    else:
        assert isinstance(obj["min_value"], (int, float))
        assert isinstance(obj["max_value"], (int, float))
        assert isinstance(obj["quantiles"], dict)
        assert set(obj["quantiles"].keys()) == QUANTILE_KEYS
        for qk in QUANTILE_KEYS:
            assert isinstance(obj["quantiles"][qk], (int, float))


# -- Core algorithm tests --


class TestBasicProperties:
    def test_empty_sketch(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        assert sk.is_empty is True
        assert sk.n == 0
        assert sk.k == 200
        assert sk.num_retained == 0
        assert sk.is_estimation_mode is False

    def test_single_item(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        sk.update(42.0)
        assert sk.is_empty is False
        assert sk.n == 1
        assert sk.min_value == 42.0
        assert sk.max_value == 42.0
        assert sk.is_estimation_mode is False
        assert sk.num_retained == 1

    def test_small_exact_mode(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        for i in range(1, 101):
            sk.update(float(i))
        assert sk.n == 100
        assert sk.min_value == 1.0
        assert sk.max_value == 100.0
        assert sk.is_estimation_mode is False

    def test_large_estimation_mode(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        for i in range(1, 10001):
            sk.update(float(i))
        assert sk.n == 10000
        assert sk.min_value == 1.0
        assert sk.max_value == 10000.0
        assert sk.is_estimation_mode is True
        assert 0 < sk.num_retained < 10000

    def test_nan_ignored(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        sk.update(1.0)
        sk.update(float("nan"))
        sk.update(3.0)
        assert sk.n == 2
        assert sk.min_value == 1.0
        assert sk.max_value == 3.0

    def test_quantile_boundaries(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        for i in range(1, 1001):
            sk.update(float(i))
        assert sk.get_quantile(0.0) == 1.0
        assert sk.get_quantile(1.0) == 1000.0


class TestAccuracy:
    def test_median_accuracy(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        n = 100000
        for i in range(1, n + 1):
            sk.update(float(i))
        median = sk.get_quantile(0.5)
        true_rank = (median - 0.5) / n
        assert abs(true_rank - 0.5) <= RANK_ERROR_BOUND

    def test_multiple_quantiles(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        n = 100000
        for i in range(1, n + 1):
            sk.update(float(i))
        for target in [0.1, 0.25, 0.5, 0.75, 0.9]:
            q = sk.get_quantile(target)
            true_rank = (q - 0.5) / n
            assert abs(true_rank - target) <= RANK_ERROR_BOUND

    def test_rank_accuracy(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        n = 100000
        for i in range(1, n + 1):
            sk.update(float(i))
        for value in [10000, 25000, 50000, 75000, 90000]:
            rank = sk.get_rank(float(value))
            true_rank = (value - 1) / n
            assert abs(rank - true_rank) <= RANK_ERROR_BOUND


class TestMerge:
    def test_merge_non_overlapping(self):
        from kll_sketch import KllDoublesSketch
        sk1 = KllDoublesSketch(200)
        sk2 = KllDoublesSketch(200)
        for i in range(1, 5001):
            sk1.update(float(i))
        for i in range(5001, 10001):
            sk2.update(float(i))
        sk1.merge(sk2)
        assert sk1.n == 10000
        assert sk1.min_value == 1.0
        assert sk1.max_value == 10000.0
        median = sk1.get_quantile(0.5)
        true_rank = (median - 0.5) / 10000
        assert abs(true_rank - 0.5) <= RANK_ERROR_BOUND

    def test_merge_empty_into_nonempty(self):
        from kll_sketch import KllDoublesSketch
        sk1 = KllDoublesSketch(200)
        for i in range(1, 101):
            sk1.update(float(i))
        sk2 = KllDoublesSketch(200)
        orig_n = sk1.n
        sk1.merge(sk2)
        assert sk1.n == orig_n

    def test_merge_nonempty_into_empty(self):
        from kll_sketch import KllDoublesSketch
        sk1 = KllDoublesSketch(200)
        sk2 = KllDoublesSketch(200)
        for i in range(1, 101):
            sk2.update(float(i))
        sk1.merge(sk2)
        assert sk1.n == 100
        assert sk1.min_value == 1.0
        assert sk1.max_value == 100.0


# -- Binary format compatibility --


class TestDeserializeFromReference:
    def test_deser_empty(self):
        from kll_sketch import KllDoublesSketch
        ref = datasketches.kll_doubles_sketch(200)
        sk = KllDoublesSketch.deserialize(ref.serialize())
        assert sk.is_empty is True
        assert sk.n == 0
        assert sk.k == 200

    def test_deser_single(self):
        from kll_sketch import KllDoublesSketch
        ref = datasketches.kll_doubles_sketch(200)
        ref.update(42.0)
        sk = KllDoublesSketch.deserialize(ref.serialize())
        assert sk.n == 1
        assert sk.min_value == 42.0
        assert sk.max_value == 42.0

    def test_deser_large(self):
        from kll_sketch import KllDoublesSketch
        ref = datasketches.kll_doubles_sketch(200)
        for i in range(1, 100001):
            ref.update(float(i))
        sk = KllDoublesSketch.deserialize(ref.serialize())
        assert sk.n == 100000
        assert sk.min_value == 1.0
        assert sk.max_value == 100000.0
        assert sk.num_retained == ref.num_retained


class TestSerializeToReference:
    def test_ser_empty(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        sk_bytes = sk.serialize()
        assert len(sk_bytes) == 8
        ref = datasketches.kll_doubles_sketch.deserialize(sk_bytes)
        assert ref.is_empty()
        assert ref.k == 200

    def test_ser_single(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        sk.update(42.0)
        sk_bytes = sk.serialize()
        assert len(sk_bytes) == 16
        ref = datasketches.kll_doubles_sketch.deserialize(sk_bytes)
        assert ref.n == 1
        assert ref.get_min_value() == 42.0

    def test_ser_large(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        for i in range(1, 10001):
            sk.update(float(i))
        ref = datasketches.kll_doubles_sketch.deserialize(sk.serialize())
        assert ref.n == 10000
        assert ref.get_min_value() == 1.0
        assert ref.get_max_value() == 10000.0

    def test_ser_negative_values(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        for i in range(-500, 501):
            sk.update(float(i))
        ref = datasketches.kll_doubles_sketch.deserialize(sk.serialize())
        assert ref.n == 1001
        assert ref.get_min_value() == -500.0
        assert ref.get_max_value() == 500.0


class TestRoundtrip:
    def test_roundtrip_small(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        for i in range(1, 101):
            sk.update(float(i))
        sk2 = KllDoublesSketch.deserialize(sk.serialize())
        assert sk2.n == sk.n
        assert sk2.min_value == sk.min_value
        assert sk2.max_value == sk.max_value
        assert sk2.num_retained == sk.num_retained

    def test_roundtrip_via_reference(self):
        from kll_sketch import KllDoublesSketch
        sk = KllDoublesSketch(200)
        for i in range(1, 5001):
            sk.update(float(i))
        ref = datasketches.kll_doubles_sketch.deserialize(sk.serialize())
        sk2 = KllDoublesSketch.deserialize(ref.serialize())
        assert sk2.n == sk.n
        assert sk2.min_value == sk.min_value
        assert sk2.max_value == sk.max_value


# -- CLI tool tests --


class TestCLIIngest:
    def setup_method(self):
        _clean_db()

    def test_ingest_basic(self):
        data = "\n".join(str(float(i)) for i in range(1, 101)) + "\n"
        stdout, stderr, rc = _run_cli(
            ["ingest", "--name", "test1"],
            stdin_data=data.encode(),
        )
        assert rc == 0, f"ingest failed: {stderr}"
        obj = json.loads(stdout)
        _validate_json_schema(obj)
        assert obj["name"] == "test1"
        assert obj["n"] == 100
        assert obj["k"] == 200
        assert obj["min_value"] == 1.0
        assert obj["max_value"] == 100.0
        assert obj["is_empty"] is False

    def test_ingest_empty_stdin(self):
        stdout, stderr, rc = _run_cli(
            ["ingest", "--name", "empty_sk"],
            stdin_data=b"",
        )
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj, expect_empty=True)
        assert obj["is_empty"] is True
        assert obj["n"] == 0
        assert obj["min_value"] is None
        assert obj["max_value"] is None
        assert obj["quantiles"] is None

    def test_ingest_custom_k(self):
        data = "\n".join(str(float(i)) for i in range(1, 51)) + "\n"
        stdout, _, rc = _run_cli(
            ["ingest", "--name", "custom_k", "--k", "100"],
            stdin_data=data.encode(),
        )
        assert rc == 0
        obj = json.loads(stdout)
        assert obj["k"] == 100

    def test_ingest_overwrite(self):
        data1 = "1.0\n2.0\n3.0\n"
        _run_cli(["ingest", "--name", "ow"], stdin_data=data1.encode())
        data2 = "10.0\n20.0\n"
        stdout, _, rc = _run_cli(
            ["ingest", "--name", "ow"], stdin_data=data2.encode()
        )
        assert rc == 0
        obj = json.loads(stdout)
        assert obj["n"] == 2
        assert obj["min_value"] == 10.0
        assert obj["max_value"] == 20.0


class TestCLIInspect:
    def setup_method(self):
        _clean_db()

    def test_inspect_existing(self):
        data = "\n".join(str(float(i)) for i in range(1, 1001)) + "\n"
        _run_cli(["ingest", "--name", "insp1"], stdin_data=data.encode())
        stdout, _, rc = _run_cli(["inspect", "--name", "insp1"])
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj)
        assert obj["name"] == "insp1"
        assert obj["n"] == 1000
        assert obj["min_value"] == 1.0
        assert obj["max_value"] == 1000.0

    def test_inspect_nonexistent(self):
        stdout, _, rc = _run_cli(["inspect", "--name", "nope"])
        assert rc == 1
        obj = json.loads(stdout)
        assert "error" in obj

    def test_inspect_quantiles_present(self):
        data = "\n".join(str(float(i)) for i in range(1, 10001)) + "\n"
        _run_cli(["ingest", "--name", "qtest"], stdin_data=data.encode())
        stdout, _, rc = _run_cli(["inspect", "--name", "qtest"])
        assert rc == 0
        obj = json.loads(stdout)
        q = obj["quantiles"]
        assert q is not None
        assert set(q.keys()) == QUANTILE_KEYS
        # quantile at 0.0 should be close to min
        assert q["0.0"] == 1.0
        # quantile at 1.0 should be close to max
        assert q["1.0"] == 10000.0
        # median should be roughly 5000
        assert abs(q["0.5"] - 5000) < 10000 * RANK_ERROR_BOUND * 2


class TestCLIMerge:
    def setup_method(self):
        _clean_db()

    def test_merge_two(self):
        d1 = "\n".join(str(float(i)) for i in range(1, 5001)) + "\n"
        d2 = "\n".join(str(float(i)) for i in range(5001, 10001)) + "\n"
        _run_cli(["ingest", "--name", "m1"], stdin_data=d1.encode())
        _run_cli(["ingest", "--name", "m2"], stdin_data=d2.encode())
        stdout, _, rc = _run_cli(
            ["merge", "--output", "merged", "--inputs", "m1", "m2"]
        )
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj)
        assert obj["name"] == "merged"
        assert obj["n"] == 10000
        assert obj["min_value"] == 1.0
        assert obj["max_value"] == 10000.0

    def test_merge_single_input(self):
        d1 = "\n".join(str(float(i)) for i in range(1, 101)) + "\n"
        _run_cli(["ingest", "--name", "solo"], stdin_data=d1.encode())
        stdout, _, rc = _run_cli(
            ["merge", "--output", "solo_copy", "--inputs", "solo"]
        )
        assert rc == 0
        obj = json.loads(stdout)
        assert obj["n"] == 100

    def test_merge_nonexistent(self):
        stdout, _, rc = _run_cli(
            ["merge", "--output", "bad", "--inputs", "ghost1", "ghost2"]
        )
        assert rc == 1
        obj = json.loads(stdout)
        assert "error" in obj


class TestCLIExportImport:
    def setup_method(self):
        _clean_db()

    def test_export_binary(self):
        data = "\n".join(str(float(i)) for i in range(1, 101)) + "\n"
        _run_cli(["ingest", "--name", "exp1"], stdin_data=data.encode())
        raw, _, rc = _run_cli(["export", "--name", "exp1"], binary_stdout=True)
        assert rc == 0
        assert len(raw) > 0
        # The exported bytes should be valid DataSketches binary
        ref = datasketches.kll_doubles_sketch.deserialize(raw)
        assert ref.n == 100
        assert ref.get_min_value() == 1.0
        assert ref.get_max_value() == 100.0

    def test_export_empty_sketch(self):
        _run_cli(["ingest", "--name", "exp_empty"], stdin_data=b"")
        raw, _, rc = _run_cli(["export", "--name", "exp_empty"], binary_stdout=True)
        assert rc == 0
        assert len(raw) == 8
        ref = datasketches.kll_doubles_sketch.deserialize(raw)
        assert ref.is_empty()

    def test_export_nonexistent(self):
        _, stderr, rc = _run_cli(["export", "--name", "noexist"], binary_stdout=True)
        assert rc == 1

    def test_import_from_reference(self):
        """Import a binary sketch generated by the reference library via stdin."""
        ref = datasketches.kll_doubles_sketch(200)
        for i in range(1, 5001):
            ref.update(float(i))
        ref_bytes = ref.serialize()

        stdout, _, rc = _run_cli(
            ["import", "--name", "imported"],
            stdin_data=ref_bytes,
        )
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj)
        assert obj["name"] == "imported"
        assert obj["n"] == 5000
        assert obj["min_value"] == 1.0
        assert obj["max_value"] == 5000.0

    def test_import_then_inspect(self):
        """Import a sketch via stdin, then inspect it."""
        ref = datasketches.kll_doubles_sketch(200)
        for i in range(1, 201):
            ref.update(float(i))
        ref_bytes = ref.serialize()

        _run_cli(["import", "--name", "imp_insp"], stdin_data=ref_bytes)
        stdout, _, rc = _run_cli(["inspect", "--name", "imp_insp"])
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj)
        assert obj["n"] == 200


# -- SQLite schema tests --


class TestSQLiteSchema:
    def setup_method(self):
        _clean_db()

    def test_table_exists_after_ingest(self):
        _run_cli(["ingest", "--name", "db1"], stdin_data=b"1.0\n2.0\n")
        assert os.path.exists(DB_PATH), "sketch_store.db not created"
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sketches'"
        )
        assert cur.fetchone() is not None, "sketches table not found"
        conn.close()

    def test_table_columns(self):
        _run_cli(["ingest", "--name", "db2"], stdin_data=b"1.0\n")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("PRAGMA table_info(sketches)")
        cols = {row[1]: row[2].upper() for row in cur.fetchall()}
        assert "name" in cols
        assert "k" in cols
        assert "n" in cols
        assert "created_at" in cols
        assert "sketch_blob" in cols
        # Check types
        assert cols["name"] == "TEXT"
        assert cols["k"] == "INTEGER"
        assert cols["n"] == "INTEGER"
        assert cols["created_at"] == "TEXT"
        assert cols["sketch_blob"] == "BLOB"
        conn.close()

    def test_row_content(self):
        data = "\n".join(str(float(i)) for i in range(1, 51)) + "\n"
        _run_cli(["ingest", "--name", "db3", "--k", "100"], stdin_data=data.encode())
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT name, k, n, created_at, sketch_blob FROM sketches WHERE name='db3'"
        ).fetchone()
        assert row is not None
        name, k, n, created_at, blob = row
        assert name == "db3"
        assert k == 100
        assert n == 50
        assert "T" in created_at  # ISO 8601
        assert isinstance(blob, bytes)
        assert len(blob) > 0
        # Blob must be valid DataSketches format
        ref = datasketches.kll_doubles_sketch.deserialize(blob)
        assert ref.n == 50
        conn.close()

    def test_overwrite_updates_row(self):
        _run_cli(["ingest", "--name", "ow_db"], stdin_data=b"1.0\n2.0\n")
        conn = sqlite3.connect(DB_PATH)
        row1 = conn.execute(
            "SELECT n, created_at FROM sketches WHERE name='ow_db'"
        ).fetchone()
        conn.close()

        import time
        time.sleep(1.1)

        _run_cli(["ingest", "--name", "ow_db"], stdin_data=b"10.0\n20.0\n30.0\n")
        conn = sqlite3.connect(DB_PATH)
        row2 = conn.execute(
            "SELECT n, created_at FROM sketches WHERE name='ow_db'"
        ).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM sketches WHERE name='ow_db'").fetchone()[0]
        conn.close()
        assert count == 1, "overwrite should not create duplicate rows"
        assert row2[0] == 3
        assert row2[1] >= row1[1]  # created_at should be updated

    def test_name_is_primary_key(self):
        _run_cli(["ingest", "--name", "pk1"], stdin_data=b"1.0\n")
        _run_cli(["ingest", "--name", "pk2"], stdin_data=b"2.0\n")
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM sketches").fetchone()[0]
        conn.close()
        assert count == 2


# -- JSON output schema tests --


class TestJSONSchema:
    def setup_method(self):
        _clean_db()

    def test_ingest_json_all_keys(self):
        data = "\n".join(str(float(i)) for i in range(1, 1001)) + "\n"
        stdout, _, rc = _run_cli(
            ["ingest", "--name", "jtest"], stdin_data=data.encode()
        )
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj)

    def test_inspect_json_all_keys(self):
        data = "\n".join(str(float(i)) for i in range(1, 501)) + "\n"
        _run_cli(["ingest", "--name", "jtest2"], stdin_data=data.encode())
        stdout, _, rc = _run_cli(["inspect", "--name", "jtest2"])
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj)

    def test_merge_json_all_keys(self):
        _run_cli(["ingest", "--name", "jm1"], stdin_data=b"1.0\n2.0\n")
        _run_cli(["ingest", "--name", "jm2"], stdin_data=b"3.0\n4.0\n")
        stdout, _, rc = _run_cli(
            ["merge", "--output", "jmerged", "--inputs", "jm1", "jm2"]
        )
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj)

    def test_import_json_all_keys(self):
        ref = datasketches.kll_doubles_sketch(200)
        ref.update(99.0)
        ref_bytes = ref.serialize()
        stdout, _, rc = _run_cli(
            ["import", "--name", "jimp"],
            stdin_data=ref_bytes,
        )
        assert rc == 0
        obj = json.loads(stdout)
        _validate_json_schema(obj)

    def test_error_json_format(self):
        stdout, _, rc = _run_cli(["inspect", "--name", "nonexistent"])
        assert rc == 1
        obj = json.loads(stdout)
        assert "error" in obj
        assert isinstance(obj["error"], str)

    def test_quantiles_types(self):
        data = "\n".join(str(float(i)) for i in range(1, 10001)) + "\n"
        _run_cli(["ingest", "--name", "qt"], stdin_data=data.encode())
        stdout, _, _ = _run_cli(["inspect", "--name", "qt"])
        obj = json.loads(stdout)
        q = obj["quantiles"]
        for key in QUANTILE_KEYS:
            assert isinstance(q[key], (int, float)), f"quantile {key} is not numeric"
            assert not math.isnan(q[key]), f"quantile {key} is NaN"
            assert not math.isinf(q[key]), f"quantile {key} is infinite"


# -- Tool interoperability tests --


class TestToolInterop:
    """Verify CLI works in multi-tool shell pipelines (jq, sqlite3, xxd)."""
    def setup_method(self):
        _clean_db()

    def test_export_pipe_import(self):
        """Binary pipeline: export sketch -> stdin -> import as new sketch."""
        data = "\n".join(str(float(i)) for i in range(1, 5001)) + "\n"
        _run_cli(["ingest", "--name", "pipe_src"], stdin_data=data.encode())
        raw, _, rc = _run_cli(["export", "--name", "pipe_src"], binary_stdout=True)
        assert rc == 0
        stdout, _, rc = _run_cli(["import", "--name", "pipe_dst"], stdin_data=raw)
        assert rc == 0
        obj = json.loads(stdout)
        assert obj["n"] == 5000
        assert obj["min_value"] == 1.0
        assert obj["max_value"] == 5000.0
        # Cross-validate via reference library
        raw2, _, _ = _run_cli(["export", "--name", "pipe_dst"], binary_stdout=True)
        ref = datasketches.kll_doubles_sketch.deserialize(raw2)
        assert ref.n == 5000

    def test_jq_json_extraction(self):
        """Verify CLI JSON output is parseable by jq for field extraction."""
        data = "\n".join(str(float(i)) for i in range(1, 10001)) + "\n"
        _run_cli(["ingest", "--name", "jq_sk"], stdin_data=data.encode())
        stdout, _, rc = _run_cli(["inspect", "--name", "jq_sk"])
        assert rc == 0
        # Extract nested quantile field via jq
        proc = subprocess.run(
            ["jq", "-e", '.quantiles["0.5"]'],
            input=stdout, capture_output=True, text=True,
        )
        assert proc.returncode == 0
        median = float(proc.stdout.strip())
        assert 1.0 <= median <= 10000.0
        # Extract top-level integer field via jq
        proc2 = subprocess.run(
            ["jq", "-e", ".n"],
            input=stdout, capture_output=True, text=True,
        )
        assert proc2.returncode == 0
        assert int(proc2.stdout.strip()) == 10000

    def test_sqlite3_cli_query(self):
        """Verify the sketch database is queryable via the sqlite3 CLI."""
        data = "\n".join(str(float(i)) for i in range(1, 101)) + "\n"
        _run_cli(["ingest", "--name", "sq_test", "--k", "100"], stdin_data=data.encode())
        proc = subprocess.run(
            ["sqlite3", DB_PATH, "SELECT name, k, n FROM sketches WHERE name='sq_test';"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        parts = proc.stdout.strip().split("|")
        assert parts[0] == "sq_test"
        assert int(parts[1]) == 100
        assert int(parts[2]) == 100

    def test_xxd_binary_header(self):
        """Verify exported binary sketch header is inspectable with xxd."""
        data = "\n".join(str(float(i)) for i in range(1, 11)) + "\n"
        _run_cli(["ingest", "--name", "xxd_sk"], stdin_data=data.encode())
        raw, _, rc = _run_cli(["export", "--name", "xxd_sk"], binary_stdout=True)
        assert rc == 0
        assert len(raw) > 0
        # raw is bytes; pass as binary input to xxd and decode output manually
        proc = subprocess.run(
            ["xxd", "-l", "4", "-p"],
            input=raw, capture_output=True,
        )
        assert proc.returncode == 0
        hex_hdr = proc.stdout.decode().strip()
        assert len(hex_hdr) == 8  # 4 bytes -> 8 hex chars
        # Family byte (3rd byte, offset 2) must be 0f (decimal 15)
        assert hex_hdr[4:6] == "0f"

    def test_sqlite3_blob_roundtrip(self):
        """Verify sketch_blob stored in SQLite is valid binary via sqlite3 + reference lib."""
        data = "\n".join(str(float(i)) for i in range(1, 1001)) + "\n"
        _run_cli(["ingest", "--name", "blob_rt"], stdin_data=data.encode())
        conn = sqlite3.connect(DB_PATH)
        blob = conn.execute(
            "SELECT sketch_blob FROM sketches WHERE name='blob_rt'"
        ).fetchone()[0]
        conn.close()
        ref = datasketches.kll_doubles_sketch.deserialize(blob)
        assert ref.n == 1000
        assert ref.get_min_value() == 1.0
        assert ref.get_max_value() == 1000.0


# -- End-to-end pipeline --


class TestEndToEnd:
    def setup_method(self):
        _clean_db()

    def test_ingest_merge_export_cross_validate(self):
        """Full pipeline: ingest two datasets -> merge -> export -> validate with datasketches."""
        d1 = "\n".join(str(float(i)) for i in range(1, 5001)) + "\n"
        d2 = "\n".join(str(float(i)) for i in range(5001, 10001)) + "\n"
        _run_cli(["ingest", "--name", "e2e_a"], stdin_data=d1.encode())
        _run_cli(["ingest", "--name", "e2e_b"], stdin_data=d2.encode())

        stdout, _, rc = _run_cli(
            ["merge", "--output", "e2e_merged", "--inputs", "e2e_a", "e2e_b"]
        )
        assert rc == 0
        merge_obj = json.loads(stdout)
        assert merge_obj["n"] == 10000
        assert merge_obj["min_value"] == 1.0
        assert merge_obj["max_value"] == 10000.0

        raw, _, rc = _run_cli(
            ["export", "--name", "e2e_merged"], binary_stdout=True
        )
        assert rc == 0
        ref = datasketches.kll_doubles_sketch.deserialize(raw)
        assert ref.n == 10000
        assert ref.get_min_value() == 1.0
        assert ref.get_max_value() == 10000.0

    def test_export_reimport_roundtrip(self):
        """Export a sketch, re-import via stdin under a new name, verify match."""
        data = "\n".join(str(float(i)) for i in range(1, 2001)) + "\n"
        _run_cli(["ingest", "--name", "rt_orig"], stdin_data=data.encode())

        raw, _, rc = _run_cli(
            ["export", "--name", "rt_orig"], binary_stdout=True
        )
        assert rc == 0

        stdout, _, rc = _run_cli(
            ["import", "--name", "rt_copy"],
            stdin_data=raw,
        )
        assert rc == 0
        obj = json.loads(stdout)
        assert obj["n"] == 2000
        assert obj["min_value"] == 1.0
        assert obj["max_value"] == 2000.0

        # Both should produce identical exports
        raw2, _, _ = _run_cli(
            ["export", "--name", "rt_copy"], binary_stdout=True
        )
        ref_orig = datasketches.kll_doubles_sketch.deserialize(raw)
        ref_copy = datasketches.kll_doubles_sketch.deserialize(raw2)
        assert ref_orig.n == ref_copy.n
        assert ref_orig.get_min_value() == ref_copy.get_min_value()
        assert ref_orig.get_max_value() == ref_copy.get_max_value()

    def test_reference_sk_import_then_merge(self):
        """Import two reference sketches via stdin, merge them, validate accuracy."""
        ref1 = datasketches.kll_doubles_sketch(200)
        ref2 = datasketches.kll_doubles_sketch(200)
        for i in range(1, 50001):
            ref1.update(float(i))
        for i in range(50001, 100001):
            ref2.update(float(i))

        _run_cli(["import", "--name", "ref_a"], stdin_data=ref1.serialize())
        _run_cli(["import", "--name", "ref_b"], stdin_data=ref2.serialize())

        stdout, _, rc = _run_cli(
            ["merge", "--output", "ref_merged", "--inputs", "ref_a", "ref_b"]
        )
        assert rc == 0
        obj = json.loads(stdout)
        assert obj["n"] == 100000
        assert obj["min_value"] == 1.0
        assert obj["max_value"] == 100000.0

        # Verify merged quantiles are accurate
        q = obj["quantiles"]
        true_median = 50000.5
        assert abs(q["0.5"] - true_median) / 100000 <= RANK_ERROR_BOUND * 2
