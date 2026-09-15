#!/usr/bin/env python3
"""
Set up the pipeline database simulating a ClickHouse distributed table layout.
Creates feature_columns table with entries in both 'default' and 'r0' schemas,
mirroring how distributed tables have local replicas.
"""
import sqlite3
import os

DB_PATH = "/app/data/pipeline.db"

# ML feature definitions for bot management model
# Organized by category, each with descriptive column names
FEATURE_GROUPS = {
    "request": [
        "rate_1m", "rate_5m", "rate_15m", "rate_1h",
        "method_entropy", "path_depth", "path_entropy",
        "query_param_count", "query_entropy", "body_size",
        "body_entropy", "content_type_valid"
    ],
    "header": [
        "count", "order_hash", "accept_valid", "accept_lang_valid",
        "accept_encoding_valid", "connection_type", "cache_control_present",
        "pragma_present", "dnt_present", "upgrade_insecure"
    ],
    "ua": [
        "length", "entropy", "known_browser", "known_bot",
        "version_valid", "os_valid", "platform_valid",
        "mobile_flag", "consistency_score", "update_frequency"
    ],
    "ip": [
        "reputation_score", "country_risk", "asn_type", "asn_size",
        "prefix_age", "rdns_valid", "blocklist_count", "tor_exit",
        "vpn_detected", "proxy_detected", "datacenter_ip", "residential_score"
    ],
    "tls": [
        "version", "cipher_count", "ja3_hash", "ja3_known",
        "extensions_count", "alpn_valid", "sni_match",
        "cert_valid", "session_reuse", "early_data"
    ],
    "timing": [
        "ttfb_mean", "ttfb_std", "inter_request_mean", "inter_request_std",
        "regularity_score", "burst_count", "idle_time_mean",
        "session_duration", "night_ratio", "weekend_ratio"
    ],
    "behavior": [
        "page_depth_mean", "resource_ratio", "js_execution",
        "css_loaded", "image_loaded", "font_loaded", "ajax_count",
        "websocket_used", "form_interaction", "scroll_depth",
        "mouse_entropy", "click_rate", "viewport_changes"
    ],
    "cookie": [
        "count", "entropy", "cf_clearance", "session_age", "persistence_score"
    ],
    "fingerprint": [
        "canvas_hash", "webgl_hash", "audio_hash", "font_list_hash",
        "plugin_count", "screen_resolution", "color_depth",
        "timezone_offset", "language_count", "do_not_track"
    ],
    "geo": [
        "distance_from_previous", "country_change_rate", "region_consistency"
    ],
    "session": [
        "page_count", "unique_paths", "error_rate", "redirect_count",
        "avg_response_size", "total_bytes", "auth_attempts",
        "api_call_ratio", "static_ratio", "dynamic_ratio"
    ],
}

# Map feature name suffixes to ClickHouse-style column types
TYPE_MAP = {
    "rate": "Float64", "count": "UInt32", "entropy": "Float64",
    "score": "Float64", "hash": "String", "valid": "UInt8",
    "present": "UInt8", "detected": "UInt8", "flag": "UInt8",
    "type": "String", "size": "UInt32", "depth": "UInt32",
    "mean": "Float64", "std": "Float64", "ratio": "Float64",
    "age": "UInt32", "duration": "Float64", "version": "String",
    "match": "UInt8", "reuse": "UInt8", "data": "UInt8",
    "resolution": "String", "offset": "Int32", "ip": "UInt8",
    "exit": "UInt8", "frequency": "Float64", "loaded": "UInt8",
    "used": "UInt8", "interaction": "Float64", "changes": "UInt32",
    "time": "Float64", "bytes": "UInt64", "attempts": "UInt32",
    "paths": "UInt32", "clearance": "String", "insecure": "UInt8",
    "browser": "UInt8", "bot": "UInt8",
}


def get_column_type(feature_name):
    for suffix, col_type in TYPE_MAP.items():
        if feature_name.endswith(suffix):
            return col_type
    return "Float64"


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS feature_columns")
    cursor.execute("""
        CREATE TABLE feature_columns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_name TEXT NOT NULL,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            column_type TEXT NOT NULL
        )
    """)

    row_id = 1
    for schema in ['default', 'r0']:
        for category, features in FEATURE_GROUPS.items():
            for feat in features:
                col_name = f"{category}_{feat}"
                col_type = get_column_type(feat)
                cursor.execute(
                    "INSERT INTO feature_columns (id, schema_name, table_name, column_name, column_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (row_id, schema, 'http_requests_features', col_name, col_type)
                )
                row_id += 1

    conn.commit()

    # Verify counts
    cursor.execute("SELECT COUNT(*) FROM feature_columns WHERE schema_name = 'default'")
    default_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM feature_columns WHERE schema_name = 'r0'")
    r0_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM feature_columns")
    total = cursor.fetchone()[0]

    print(f"Database created at {DB_PATH}")
    print(f"  default schema: {default_count} features")
    print(f"  r0 schema:      {r0_count} features")
    print(f"  total rows:     {total}")

    conn.close()


if __name__ == "__main__":
    main()
