#!/usr/bin/env python3
"""Initialize the distributed database simulation.

Creates SQLite databases simulating ClickHouse shards with the
system_columns metadata table. Shards 0-3 are 'migrated' (expose
both default and r0 databases), shard 4 is still pending migration.

Also creates configuration history entries for audit trail.
"""

import sqlite3
import os
import json

SHARD_DIR = "/app/db/shards"
HISTORY_DIR = "/app/config/history"

# Feature definitions for the bot management ML model
# 113 features across 8 categories
FEATURES = [
    # Request metadata (15 features)
    ("user_agent_entropy", "Float64"),
    ("user_agent_length", "UInt32"),
    ("accept_language_count", "UInt8"),
    ("accept_encoding_flags", "UInt16"),
    ("content_type_hash", "UInt64"),
    ("referer_domain_hash", "UInt64"),
    ("request_method_id", "UInt8"),
    ("uri_path_depth", "UInt8"),
    ("uri_query_param_count", "UInt8"),
    ("uri_path_entropy", "Float64"),
    ("header_count", "UInt8"),
    ("header_order_hash", "UInt64"),
    ("cookie_count", "UInt8"),
    ("cookie_total_size", "UInt32"),
    ("has_authorization_header", "UInt8"),

    # Timing features (14 features)
    ("request_rate_1m", "Float64"),
    ("request_rate_5m", "Float64"),
    ("request_rate_15m", "Float64"),
    ("inter_request_interval_mean", "Float64"),
    ("inter_request_interval_std", "Float64"),
    ("inter_request_interval_min", "Float64"),
    ("inter_request_interval_max", "Float64"),
    ("session_duration_seconds", "Float64"),
    ("time_to_first_byte_ms", "Float64"),
    ("connection_reuse_ratio", "Float64"),
    ("tcp_syn_interval_mean", "Float64"),
    ("tls_handshake_duration_ms", "Float64"),
    ("request_burst_score", "Float64"),
    ("idle_time_ratio", "Float64"),

    # Network features (14 features)
    ("ip_reputation_score", "Float64"),
    ("asn_bot_ratio", "Float64"),
    ("geo_country_risk_score", "Float64"),
    ("ip_age_days", "UInt32"),
    ("subnet_request_diversity", "Float64"),
    ("ip_request_count_24h", "UInt32"),
    ("ip_unique_paths_24h", "UInt32"),
    ("ip_unique_hosts_24h", "UInt16"),
    ("datacenter_ip_flag", "UInt8"),
    ("tor_exit_node_flag", "UInt8"),
    ("vpn_detected_flag", "UInt8"),
    ("proxy_detected_flag", "UInt8"),
    ("ip_geolocation_consistency", "Float64"),
    ("dns_ptr_exists", "UInt8"),

    # Browser fingerprint features (15 features)
    ("js_engine_fingerprint", "UInt64"),
    ("canvas_fingerprint_hash", "UInt64"),
    ("webgl_renderer_hash", "UInt64"),
    ("audio_fingerprint_hash", "UInt64"),
    ("font_list_hash", "UInt64"),
    ("screen_resolution_hash", "UInt32"),
    ("timezone_offset_minutes", "Int16"),
    ("language_consistency_score", "Float64"),
    ("plugin_count", "UInt8"),
    ("navigator_properties_hash", "UInt64"),
    ("window_properties_anomaly", "Float64"),
    ("dom_depth_score", "Float64"),
    ("event_timing_humanness", "Float64"),
    ("mouse_movement_entropy", "Float64"),
    ("keyboard_timing_entropy", "Float64"),

    # Behavioral features (15 features)
    ("page_view_sequence_entropy", "Float64"),
    ("form_fill_speed_wpm", "Float64"),
    ("scroll_pattern_score", "Float64"),
    ("click_pattern_entropy", "Float64"),
    ("navigation_depth_mean", "Float64"),
    ("resource_load_pattern", "Float64"),
    ("ajax_request_ratio", "Float64"),
    ("websocket_usage_flag", "UInt8"),
    ("service_worker_active", "UInt8"),
    ("web_worker_count", "UInt8"),
    ("local_storage_item_count", "UInt8"),
    ("session_storage_item_count", "UInt8"),
    ("indexeddb_usage_flag", "UInt8"),
    ("performance_api_available", "UInt8"),
    ("beacon_api_usage_flag", "UInt8"),

    # Challenge features (14 features)
    ("challenge_solve_rate", "Float64"),
    ("challenge_solve_time_ms", "Float64"),
    ("turnstile_score", "Float64"),
    ("captcha_pass_rate", "Float64"),
    ("js_challenge_pass_rate", "Float64"),
    ("managed_challenge_pass_rate", "Float64"),
    ("challenge_interaction_score", "Float64"),
    ("challenge_consistency_score", "Float64"),
    ("proof_of_work_speed", "Float64"),
    ("challenge_evasion_attempts", "UInt8"),
    ("challenge_type_diversity", "UInt8"),
    ("challenge_timing_anomaly", "Float64"),
    ("challenge_replay_detected", "UInt8"),
    ("challenge_fingerprint_match", "Float64"),

    # Historical features (14 features)
    ("ip_threat_score_7d", "Float64"),
    ("ip_threat_score_30d", "Float64"),
    ("domain_visit_frequency", "Float64"),
    ("returning_visitor_flag", "UInt8"),
    ("account_age_days", "UInt32"),
    ("login_failure_rate_24h", "Float64"),
    ("credential_stuffing_score", "Float64"),
    ("api_abuse_score_7d", "Float64"),
    ("scraping_score_7d", "Float64"),
    ("ddos_participation_score", "Float64"),
    ("reputation_volatility", "Float64"),
    ("threat_category_history", "UInt64"),
    ("blocklist_hit_count_30d", "UInt16"),
    ("allowlist_membership", "UInt8"),

    # Content analysis features (12 features)
    ("payload_entropy", "Float64"),
    ("payload_size_bytes", "UInt32"),
    ("sql_injection_score", "Float64"),
    ("xss_detection_score", "Float64"),
    ("path_traversal_score", "Float64"),
    ("command_injection_score", "Float64"),
    ("request_body_anomaly", "Float64"),
    ("content_type_mismatch", "UInt8"),
    ("encoding_anomaly_score", "Float64"),
    ("unicode_anomaly_score", "Float64"),
    ("null_byte_detected", "UInt8"),
    ("oversized_field_count", "UInt8"),
]

assert len(FEATURES) == 113, f"Expected 113 features, got {len(FEATURES)}"


def create_shard(shard_id, migrated=True):
    """Create a single database shard."""
    os.makedirs(SHARD_DIR, exist_ok=True)
    db_path = os.path.join(SHARD_DIR, f"shard_{shard_id}.db")

    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_columns (
            database TEXT NOT NULL,
            table_name TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            position INTEGER NOT NULL,
            comment TEXT DEFAULT ''
        )
    """)

    for pos, (feat_name, feat_type) in enumerate(FEATURES):
        conn.execute(
            "INSERT INTO system_columns VALUES (?, ?, ?, ?, ?, ?)",
            ('default', 'http_requests_features', feat_name, feat_type, pos, '')
        )

    if migrated:
        for pos, (feat_name, feat_type) in enumerate(FEATURES):
            conn.execute(
                "INSERT INTO system_columns VALUES (?, ?, ?, ?, ?, ?)",
                ('r0', 'http_requests_features', feat_name, feat_type, pos, '')
            )

    conn.commit()
    conn.close()

    return db_path


def create_config_history():
    """Create configuration change history entries for audit trail."""
    os.makedirs(HISTORY_DIR, exist_ok=True)

    entries = [
        {
            "timestamp": "2025-11-18T10:55:01",
            "action": "generate",
            "shard": "shard_4",
            "feature_count": 113,
            "status": "success",
            "validated": False,
            "note": "Scheduled regeneration (5-min cycle)"
        },
        {
            "timestamp": "2025-11-18T11:00:01",
            "action": "generate",
            "shard": "shard_2",
            "feature_count": 226,
            "status": "success",
            "validated": False,
            "note": "Scheduled regeneration (5-min cycle)"
        },
        {
            "timestamp": "2025-11-18T11:05:03",
            "action": "generate",
            "shard": "shard_0",
            "feature_count": 226,
            "status": "success",
            "validated": False,
            "note": "Scheduled regeneration (5-min cycle)"
        },
        {
            "timestamp": "2025-11-18T11:10:01",
            "action": "generate",
            "shard": "shard_1",
            "feature_count": 226,
            "status": "success",
            "validated": False,
            "note": "Scheduled regeneration (5-min cycle)"
        },
        {
            "timestamp": "2025-11-18T11:15:01",
            "action": "generate",
            "shard": "shard_3",
            "feature_count": 226,
            "status": "success",
            "validated": False,
            "note": "Scheduled regeneration (5-min cycle)"
        },
        {
            "timestamp": "2025-11-18T11:20:01",
            "action": "generate",
            "shard": "shard_4",
            "feature_count": 113,
            "status": "success",
            "validated": False,
            "note": "Scheduled regeneration (5-min cycle)"
        },
        {
            "timestamp": "2025-11-18T11:25:01",
            "action": "generate",
            "shard": "shard_0",
            "feature_count": 226,
            "status": "success",
            "validated": False,
            "note": "Scheduled regeneration (5-min cycle)"
        },
    ]

    for entry in entries:
        ts = entry["timestamp"].replace(":", "").replace("-", "").replace("T", "_")
        filepath = os.path.join(HISTORY_DIR, f"{ts}.json")
        with open(filepath, 'w') as f:
            json.dump(entry, f, indent=2)


def main():
    print("Initializing database shards...")

    for i in range(5):
        migrated = (i < 4)
        path = create_shard(i, migrated=migrated)
        status = "MIGRATED" if migrated else "PENDING"
        print(f"  Created {path} [{status}]")

    create_config_history()
    print("  Created configuration history entries")

    print("Database initialization complete.")
    print(f"  Total shards: 5")
    print(f"  Migrated: 4 (shards 0-3)")
    print(f"  Pending: 1 (shard 4)")
    print(f"  Features per shard: {len(FEATURES)}")


if __name__ == "__main__":
    main()
