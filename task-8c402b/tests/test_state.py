
import json
import pytest

AUDIT_PATH = "/app/audit.json"


@pytest.fixture
def audit():
    with open(AUDIT_PATH) as f:
        return json.load(f)


# =====================================================================
# Structural tests
# =====================================================================

def test_required_top_level_keys(audit):
    required = [
        "rdb_version", "total_keys", "databases", "type_counts",
        "keys_with_expiry", "checksum_valid", "key_details",
        "encoding_report", "server_info", "optimization_findings",
    ]
    for key in required:
        assert key in audit, f"Missing top-level key: {key}"


def test_rdb_version_is_int(audit):
    assert isinstance(audit["rdb_version"], int)
    assert audit["rdb_version"] >= 1


# =====================================================================
# RDB parsing — aggregate counts
# =====================================================================

def test_total_keys(audit):
    assert audit["total_keys"] == 71


def test_database_key_counts(audit):
    dbs = audit["databases"]
    db0 = dbs.get("0", dbs.get(0, 0))
    db2 = dbs.get("2", dbs.get(2, 0))
    assert int(db0) == 66
    assert int(db2) == 5
    assert len(dbs) == 2


def test_type_counts(audit):
    tc = audit["type_counts"]
    assert tc["string"] == 63
    assert tc["list"] == 2
    assert tc["set"] == 2
    assert tc["hash"] == 2
    assert tc["zset"] == 2


# =====================================================================
# RDB parsing — checksum
# =====================================================================

def test_checksum_valid(audit):
    assert audit["checksum_valid"] is True


# =====================================================================
# RDB parsing — expiry
# =====================================================================

def test_keys_with_expiry_count(audit):
    assert len(audit["keys_with_expiry"]) == 3


def test_keys_with_expiry_names(audit):
    keys = sorted([e["key"] for e in audit["keys_with_expiry"]])
    assert keys == ["cache:page:1", "cache:page:2", "cache:page:3"]


def test_expiry_timestamps(audit):
    exp_by_key = {e["key"]: e for e in audit["keys_with_expiry"]}
    assert exp_by_key["cache:page:1"]["expiry_ms"] == 1893456000000
    assert exp_by_key["cache:page:2"]["expiry_ms"] == 1924992000000
    assert exp_by_key["cache:page:3"]["expiry_ms"] == 1956528000000


# =====================================================================
# RDB parsing — string values
# =====================================================================

def test_integer_encoded_strings(audit):
    kd = audit["key_details"]
    assert str(kd["user:1"]["value"]) == "100"
    assert kd["user:1"]["type"] == "string"
    assert kd["user:1"]["db"] == 0
    assert str(kd["user:50"]["value"]) == "5000"


def test_all_user_keys_present(audit):
    kd = audit["key_details"]
    for i in range(1, 51):
        key = f"user:{i}"
        assert key in kd, f"Missing key {key}"
        assert kd[key]["type"] == "string"
        assert str(kd[key]["value"]) == str(i * 100)


def test_raw_string_config(audit):
    kd = audit["key_details"]
    assert kd["config:app_name"]["type"] == "string"
    assert kd["config:app_name"]["value"] == "MyApplication-Production-Server-v2.1"


def test_long_string_value(audit):
    kd = audit["key_details"]
    assert kd["config:description"]["value"] == (
        "This is a longer configuration value that tests raw string encoding in the RDB format"
    )


def test_string_with_expiry_value(audit):
    kd = audit["key_details"]
    assert kd["cache:page:1"]["value"] == "cached_homepage_content_v1"


# =====================================================================
# RDB parsing — hash values
# =====================================================================

def test_hash_small(audit):
    kd = audit["key_details"]
    session = kd["session:data"]
    assert session["type"] == "hash"
    assert session["size"] == 5
    val = session["value"]
    assert val["username"] == "alice"
    assert val["role"] == "admin"
    assert str(val["login_time"]) == "1700000000"
    assert val["ip_addr"] == "192.168.1.100"
    assert val["user_agent"] == "Mozilla/5.0"


def test_hash_large(audit):
    kd = audit["key_details"]
    metrics = kd["metrics:daily"]
    assert metrics["type"] == "hash"
    assert metrics["size"] == 200
    val = metrics["value"]
    assert str(val["metric_1"]) == "20"
    assert str(val["metric_100"]) == "713"
    assert str(val["metric_200"]) == "1413"


# =====================================================================
# RDB parsing — list values
# =====================================================================

def test_list_small(audit):
    kd = audit["key_details"]
    queue = kd["queue:jobs"]
    assert queue["type"] == "list"
    assert queue["size"] == 10
    assert queue["value"][0] == "job_task_1"
    assert queue["value"][9] == "job_task_10"


def test_list_large(audit):
    kd = audit["key_details"]
    logs = kd["logs:recent"]
    assert logs["type"] == "list"
    assert logs["size"] == 1000
    assert logs["value"][0] == "log_entry_1_event_data"
    assert logs["value"][499] == "log_entry_500_event_data"
    assert logs["value"][999] == "log_entry_1000_event_data"


# =====================================================================
# RDB parsing — set values
# =====================================================================

def test_set_small(audit):
    kd = audit["key_details"]
    tags = kd["tags:active"]
    assert tags["type"] == "set"
    assert tags["size"] == 5
    members = sorted([str(m) for m in tags["value"]])
    assert members == ["1", "2", "3", "4", "5"]


def test_set_large(audit):
    kd = audit["key_details"]
    users = kd["users:online"]
    assert users["type"] == "set"
    assert users["size"] == 200
    members = [str(m) for m in users["value"]]
    assert "user_0001" in members
    assert "user_0100" in members
    assert "user_0200" in members


# =====================================================================
# RDB parsing — sorted set values
# =====================================================================

def test_zset_small(audit):
    kd = audit["key_details"]
    lb = kd["leaderboard:scores"]
    assert lb["type"] == "zset"
    assert lb["size"] == 10
    pairs = lb["value"]
    assert pairs[0][0] == "player_1"
    assert float(pairs[0][1]) == 100.0
    assert pairs[9][0] == "player_10"
    assert float(pairs[9][1]) == 1000.0


def test_zset_large(audit):
    kd = audit["key_details"]
    rankings = kd["rankings:global"]
    assert rankings["type"] == "zset"
    assert rankings["size"] == 500
    pairs = rankings["value"]
    assert pairs[0][0] == "contestant_0001"
    assert float(pairs[0][1]) == 10.0
    assert pairs[249][0] == "contestant_0250"
    assert float(pairs[249][1]) == 757.0
    assert pairs[499][0] == "contestant_0500"
    assert float(pairs[499][1]) == 1507.0


# =====================================================================
# RDB parsing — multi-database
# =====================================================================

def test_db2_string_keys(audit):
    kd = audit["key_details"]
    assert kd["db2:key1"]["db"] == 2
    assert kd["db2:key1"]["value"] == "value_in_db2_first"
    assert kd["db2:key2"]["db"] == 2
    assert kd["db2:key2"]["value"] == "value_in_db2_second"
    assert kd["db2:key3"]["db"] == 2
    assert kd["db2:key3"]["value"] == "value_in_db2_third"


def test_db2_integer_values(audit):
    kd = audit["key_details"]
    assert str(kd["db2:counter"]["value"]) == "42"
    assert kd["db2:counter"]["db"] == 2
    assert str(kd["db2:flag"]["value"]) == "1"
    assert kd["db2:flag"]["db"] == 2


def test_key_details_total_count(audit):
    assert len(audit["key_details"]) == 71


# =====================================================================
# Encoding report — completeness
# =====================================================================

def test_encoding_report_has_all_keys(audit):
    for key in audit["key_details"]:
        assert key in audit["encoding_report"], f"Missing encoding for {key}"


# =====================================================================
# Encoding report — string encodings
# =====================================================================

def test_encoding_int_string(audit):
    enc = audit["encoding_report"]["user:1"]
    assert enc["live_encoding"] == "int"
    assert enc["memory_bytes"] > 0


def test_encoding_int_string_db2(audit):
    enc = audit["encoding_report"]["db2:counter"]
    assert enc["live_encoding"] == "int"


def test_encoding_embstr(audit):
    enc = audit["encoding_report"]["config:app_name"]
    assert enc["live_encoding"] == "embstr"


def test_encoding_raw_string(audit):
    enc = audit["encoding_report"]["config:description"]
    assert enc["live_encoding"] == "raw"


def test_encoding_embstr_cache(audit):
    enc = audit["encoding_report"]["cache:page:1"]
    assert enc["live_encoding"] == "embstr"


def test_encoding_embstr_db2(audit):
    enc = audit["encoding_report"]["db2:key1"]
    assert enc["live_encoding"] == "embstr"


# =====================================================================
# Encoding report — hash encodings
# =====================================================================

def test_encoding_hash_small_is_hashtable(audit):
    """session:data has 5 fields but threshold is 3 so it uses hashtable."""
    enc = audit["encoding_report"]["session:data"]
    assert enc["live_encoding"] == "hashtable"


def test_encoding_hash_large(audit):
    enc = audit["encoding_report"]["metrics:daily"]
    assert enc["live_encoding"] == "hashtable"


# =====================================================================
# Encoding report — list encodings
# =====================================================================

def test_encoding_list_small(audit):
    enc = audit["encoding_report"]["queue:jobs"]
    assert enc["live_encoding"] == "quicklist"


def test_encoding_list_large(audit):
    enc = audit["encoding_report"]["logs:recent"]
    assert enc["live_encoding"] == "quicklist"


# =====================================================================
# Encoding report — set encodings
# =====================================================================

def test_encoding_set_small_is_hashtable(audit):
    """tags:active has 5 int members but threshold is 3 so it uses hashtable."""
    enc = audit["encoding_report"]["tags:active"]
    assert enc["live_encoding"] == "hashtable"


def test_encoding_set_large(audit):
    enc = audit["encoding_report"]["users:online"]
    assert enc["live_encoding"] == "hashtable"


# =====================================================================
# Encoding report — sorted set encodings
# =====================================================================

def test_encoding_zset_small_is_skiplist(audit):
    """leaderboard:scores has 10 members but threshold is 5 so it uses skiplist."""
    enc = audit["encoding_report"]["leaderboard:scores"]
    assert enc["live_encoding"] == "skiplist"


def test_encoding_zset_large(audit):
    enc = audit["encoding_report"]["rankings:global"]
    assert enc["live_encoding"] == "skiplist"


# =====================================================================
# Encoding report — memory
# =====================================================================

def test_memory_bytes_positive(audit):
    for key, enc in audit["encoding_report"].items():
        assert enc["memory_bytes"] > 0, f"Memory for {key} should be > 0"


def test_memory_large_list_exceeds_small(audit):
    enc = audit["encoding_report"]
    assert enc["logs:recent"]["memory_bytes"] > enc["queue:jobs"]["memory_bytes"]


def test_memory_large_hash_exceeds_small(audit):
    enc = audit["encoding_report"]
    assert enc["metrics:daily"]["memory_bytes"] > enc["session:data"]["memory_bytes"]


def test_memory_large_zset_exceeds_small(audit):
    enc = audit["encoding_report"]
    assert enc["rankings:global"]["memory_bytes"] > enc["leaderboard:scores"]["memory_bytes"]


# =====================================================================
# Server info
# =====================================================================

def test_server_info_present(audit):
    si = audit["server_info"]
    assert "redis_version" in si
    assert isinstance(si["redis_version"], str)
    assert len(si["redis_version"]) > 0
    assert "used_memory_bytes" in si
    assert si["used_memory_bytes"] > 0


# =====================================================================
# Optimization findings
# =====================================================================

def test_optimization_findings_count(audit):
    assert len(audit["optimization_findings"]) == 3


def test_optimization_sorted_by_key(audit):
    keys = [f["key"] for f in audit["optimization_findings"]]
    assert keys == sorted(keys)


def test_optimization_session_data(audit):
    findings = {f["key"]: f for f in audit["optimization_findings"]}
    assert "session:data" in findings
    f = findings["session:data"]
    assert f["current_encoding"] == "hashtable"
    assert f["optimal_encoding"] == "listpack"
    assert f["config_parameter"] == "hash-max-listpack-entries"
    assert f["current_threshold"] == 3
    assert f["recommended_threshold"] >= 5


def test_optimization_leaderboard_scores(audit):
    findings = {f["key"]: f for f in audit["optimization_findings"]}
    assert "leaderboard:scores" in findings
    f = findings["leaderboard:scores"]
    assert f["current_encoding"] == "skiplist"
    assert f["optimal_encoding"] == "listpack"
    assert f["config_parameter"] == "zset-max-listpack-entries"
    assert f["current_threshold"] == 5
    assert f["recommended_threshold"] >= 10


def test_optimization_tags_active(audit):
    findings = {f["key"]: f for f in audit["optimization_findings"]}
    assert "tags:active" in findings
    f = findings["tags:active"]
    assert f["current_encoding"] == "hashtable"
    assert f["optimal_encoding"] == "intset"
    assert f["config_parameter"] == "set-max-intset-entries"
    assert f["current_threshold"] == 3
    assert f["recommended_threshold"] >= 5
