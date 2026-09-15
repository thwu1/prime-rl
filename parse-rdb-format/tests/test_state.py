
import subprocess
import json
import pytest


def _run_parser():
    """Run the RDB parser and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "/app/rdb_parser.py", "/app/data.rdb"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Parser exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout[:500]}"
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def data():
    return _run_parser()


# ---------------------------------------------------------------------------
# Database structure
# ---------------------------------------------------------------------------

def test_databases_present(data):
    assert "databases" in data
    assert "0" in data["databases"]
    assert "2" in data["databases"]


def test_no_extra_databases(data):
    for db_id in data["databases"]:
        assert db_id in ("0", "2"), f"Unexpected database: {db_id}"


def test_total_key_count(data):
    total = sum(len(db) for db in data["databases"].values())
    # DB 0: greeting, counter, big_number, negative, medium_number,
    #        long_value, server:config, events, languages, highscores,
    #        with_expiry, primes = 12
    # DB 2: alt_db_key, info = 2
    assert total == 14


# ---------------------------------------------------------------------------
# String type — raw encoding
# ---------------------------------------------------------------------------

def test_simple_string(data):
    entry = data["databases"]["0"]["greeting"]
    assert entry["type"] == "string"
    assert entry["value"] == "Hello, World!"


# ---------------------------------------------------------------------------
# String type — integer encodings
# ---------------------------------------------------------------------------

def test_int8_encoding(data):
    entry = data["databases"]["0"]["counter"]
    assert entry["type"] == "string"
    assert entry["value"] == "42"


def test_int8_negative(data):
    entry = data["databases"]["0"]["negative"]
    assert entry["type"] == "string"
    assert entry["value"] == "-100"


def test_int16_encoding(data):
    entry = data["databases"]["0"]["medium_number"]
    assert entry["type"] == "string"
    assert entry["value"] == "12345"


def test_int32_encoding(data):
    entry = data["databases"]["0"]["big_number"]
    assert entry["type"] == "string"
    assert entry["value"] == "2147483647"


# ---------------------------------------------------------------------------
# String type — LZF compressed
# ---------------------------------------------------------------------------

def test_lzf_decompression(data):
    entry = data["databases"]["0"]["long_value"]
    assert entry["type"] == "string"
    expected = (
        "The quick brown fox jumps over the lazy dog. "
        "The quick brown fox jumps over the lazy dog. "
        "The quick brown fox jumps over the lazy dog. "
        "The quick brown fox jumps over the lazy dog."
    )
    assert entry["value"] == expected


# ---------------------------------------------------------------------------
# Hash (listpack encoding)
# ---------------------------------------------------------------------------

def test_hash_type(data):
    entry = data["databases"]["0"]["server:config"]
    assert entry["type"] == "hash"


def test_hash_field_host(data):
    h = data["databases"]["0"]["server:config"]["value"]
    assert h["host"] == "127.0.0.1"


def test_hash_field_port(data):
    h = data["databases"]["0"]["server:config"]["value"]
    assert h["port"] == "6379"


def test_hash_field_timeout(data):
    h = data["databases"]["0"]["server:config"]["value"]
    assert h["timeout"] == "300"


def test_hash_field_loglevel(data):
    h = data["databases"]["0"]["server:config"]["value"]
    assert h["loglevel"] == "notice"


def test_hash_field_count(data):
    h = data["databases"]["0"]["server:config"]["value"]
    assert len(h) == 4


# ---------------------------------------------------------------------------
# List (quicklist2 encoding)
# ---------------------------------------------------------------------------

def test_list_type(data):
    entry = data["databases"]["0"]["events"]
    assert entry["type"] == "list"


def test_list_order(data):
    entry = data["databases"]["0"]["events"]
    assert entry["value"] == ["click", "scroll", "keypress", "submit", "hover"]


# ---------------------------------------------------------------------------
# Set (listpack encoding)
# ---------------------------------------------------------------------------

def test_set_type(data):
    entry = data["databases"]["0"]["languages"]
    assert entry["type"] == "set"


def test_set_members(data):
    entry = data["databases"]["0"]["languages"]
    assert set(entry["value"]) == {"python", "rust", "go", "java", "typescript"}


# ---------------------------------------------------------------------------
# Set (intset encoding)
# ---------------------------------------------------------------------------

def test_intset_type(data):
    entry = data["databases"]["0"]["primes"]
    assert entry["type"] == "set"


def test_intset_members(data):
    entry = data["databases"]["0"]["primes"]
    assert set(entry["value"]) == {
        "2", "3", "5", "7", "11", "13", "17", "19", "23", "29"
    }


# ---------------------------------------------------------------------------
# Sorted set (listpack encoding)
# ---------------------------------------------------------------------------

def test_zset_type(data):
    entry = data["databases"]["0"]["highscores"]
    assert entry["type"] == "zset"


def test_zset_member_count(data):
    entry = data["databases"]["0"]["highscores"]
    assert len(entry["value"]) == 5


def test_zset_score_alice(data):
    scores = {item[0]: item[1] for item in data["databases"]["0"]["highscores"]["value"]}
    assert abs(scores["Alice"] - 1500.5) < 0.01


def test_zset_score_bob(data):
    scores = {item[0]: item[1] for item in data["databases"]["0"]["highscores"]["value"]}
    assert abs(scores["Bob"] - 1200.75) < 0.01


def test_zset_score_charlie(data):
    scores = {item[0]: item[1] for item in data["databases"]["0"]["highscores"]["value"]}
    assert abs(scores["Charlie"] - 980.0) < 0.01


def test_zset_score_diana(data):
    scores = {item[0]: item[1] for item in data["databases"]["0"]["highscores"]["value"]}
    assert abs(scores["Diana"] - 2100.25) < 0.01


def test_zset_score_eve(data):
    scores = {item[0]: item[1] for item in data["databases"]["0"]["highscores"]["value"]}
    assert abs(scores["Eve"] - 750.5) < 0.01


# ---------------------------------------------------------------------------
# Key expiry
# ---------------------------------------------------------------------------

def test_expiry_present(data):
    entry = data["databases"]["0"]["with_expiry"]
    assert entry["value"] == "ephemeral"
    assert "expiry_ms" in entry


def test_expiry_timestamp(data):
    entry = data["databases"]["0"]["with_expiry"]
    # EXPIREAT 4102444800 → stored as ms: 4102444800000
    assert entry["expiry_ms"] == 4102444800000


def test_no_expiry_on_regular_keys(data):
    db0 = data["databases"]["0"]
    assert "expiry_ms" not in db0["greeting"]
    assert "expiry_ms" not in db0["counter"]
    assert "expiry_ms" not in db0["server:config"]


# ---------------------------------------------------------------------------
# Secondary database (DB 2)
# ---------------------------------------------------------------------------

def test_db2_string(data):
    entry = data["databases"]["2"]["alt_db_key"]
    assert entry["type"] == "string"
    assert entry["value"] == "value_in_db2"


def test_db2_hash_type(data):
    entry = data["databases"]["2"]["info"]
    assert entry["type"] == "hash"


def test_db2_hash_values(data):
    h = data["databases"]["2"]["info"]["value"]
    assert h["type"] == "benchmark"
    assert h["version"] == "1.0"
