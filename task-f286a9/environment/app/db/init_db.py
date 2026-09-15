#!/usr/bin/env python3
"""Initialize the feature metadata database.

This simulates a distributed database cluster (similar to ClickHouse)
with distributed tables. The 'default' schema contains distributed
table metadata. The 'r0' schema contains the underlying shard-local
(replica) tables.

Migration 002 (applied 2025-11-18 11:05 UTC) made r0 schema
metadata explicitly visible to users for improved query security.
"""

import sqlite3
import json
import os

DB_PATH = '/app/db/features.db'

# Feature definitions for the bot management ML model.
# Each category maps to a group of features used for bot scoring.
FEATURE_CATEGORIES = {
    'request': [
        ('req_header_count', 'UInt16'),
        ('req_body_size', 'UInt32'),
        ('req_method_encoded', 'UInt8'),
        ('req_path_depth', 'UInt8'),
        ('req_path_length', 'UInt16'),
        ('req_query_param_count', 'UInt8'),
        ('req_query_length', 'UInt16'),
        ('req_content_type_encoded', 'UInt8'),
        ('req_accept_encoding', 'UInt8'),
        ('req_accept_language_count', 'UInt8'),
        ('req_cookie_count', 'UInt8'),
        ('req_cookie_total_size', 'UInt16'),
        ('req_referrer_present', 'UInt8'),
        ('req_referrer_same_origin', 'UInt8'),
        ('req_cache_control_encoded', 'UInt8'),
        ('req_connection_encoded', 'UInt8'),
        ('req_upgrade_insecure', 'UInt8'),
        ('req_dnt_present', 'UInt8'),
    ],
    'tls': [
        ('tls_version_encoded', 'UInt8'),
        ('tls_cipher_strength', 'UInt8'),
        ('tls_cipher_suite_encoded', 'UInt16'),
        ('tls_session_resumed', 'UInt8'),
        ('tls_client_hello_size', 'UInt16'),
        ('tls_extensions_count', 'UInt8'),
        ('tls_alpn_encoded', 'UInt8'),
        ('tls_sni_present', 'UInt8'),
        ('tls_cert_compression', 'UInt8'),
        ('tls_early_data', 'UInt8'),
        ('tls_supported_versions_count', 'UInt8'),
        ('tls_signature_algorithms_count', 'UInt8'),
    ],
    'network': [
        ('net_ip_version', 'UInt8'),
        ('net_asn', 'UInt32'),
        ('net_country_encoded', 'UInt16'),
        ('net_continent_encoded', 'UInt8'),
        ('net_ip_reputation_score', 'Float32'),
        ('net_ip_age_days', 'UInt32'),
        ('net_datacenter_encoded', 'UInt16'),
        ('net_tcp_rtt_ms', 'Float32'),
        ('net_tcp_window_scale', 'UInt8'),
        ('net_tcp_mss', 'UInt16'),
        ('net_tcp_options_encoded', 'UInt16'),
        ('net_ip_is_proxy', 'UInt8'),
        ('net_ip_is_vpn', 'UInt8'),
        ('net_ip_is_tor', 'UInt8'),
        ('net_ip_is_datacenter', 'UInt8'),
        ('net_ip_threat_score', 'Float32'),
    ],
    'browser': [
        ('js_fingerprint_hash', 'UInt64'),
        ('js_canvas_hash', 'UInt64'),
        ('js_webgl_renderer_encoded', 'UInt16'),
        ('js_webgl_vendor_encoded', 'UInt16'),
        ('js_timezone_offset', 'Int16'),
        ('js_screen_resolution_encoded', 'UInt16'),
        ('js_color_depth', 'UInt8'),
        ('js_platform_encoded', 'UInt8'),
        ('js_language_count', 'UInt8'),
        ('js_plugin_count', 'UInt8'),
        ('js_font_count', 'UInt16'),
        ('js_touch_support', 'UInt8'),
        ('js_hardware_concurrency', 'UInt8'),
        ('js_device_memory', 'UInt8'),
        ('js_audio_fingerprint', 'UInt64'),
        ('js_webrtc_leak', 'UInt8'),
    ],
    'behavioral': [
        ('beh_request_rate_1m', 'Float32'),
        ('beh_request_rate_5m', 'Float32'),
        ('beh_request_rate_15m', 'Float32'),
        ('beh_unique_paths_1m', 'UInt16'),
        ('beh_unique_paths_5m', 'UInt16'),
        ('beh_error_rate_1m', 'Float32'),
        ('beh_avg_response_time_ms', 'Float32'),
        ('beh_session_duration_sec', 'UInt32'),
        ('beh_page_dwell_time_ms', 'UInt32'),
        ('beh_scroll_depth_pct', 'UInt8'),
        ('beh_click_rate', 'Float32'),
        ('beh_mouse_movement_entropy', 'Float32'),
        ('beh_keystroke_dynamics', 'Float32'),
        ('beh_form_fill_time_ms', 'UInt32'),
        ('beh_navigation_pattern_encoded', 'UInt8'),
        ('beh_ajax_request_ratio', 'Float32'),
    ],
    'header_analysis': [
        ('hdr_user_agent_length', 'UInt16'),
        ('hdr_user_agent_entropy', 'Float32'),
        ('hdr_user_agent_tokens', 'UInt8'),
        ('hdr_user_agent_version_encoded', 'UInt16'),
        ('hdr_accept_header_encoded', 'UInt8'),
        ('hdr_accept_quality_values', 'UInt8'),
        ('hdr_via_present', 'UInt8'),
        ('hdr_forwarded_present', 'UInt8'),
        ('hdr_custom_header_count', 'UInt8'),
        ('hdr_header_order_hash', 'UInt64'),
        ('hdr_header_case_anomaly', 'UInt8'),
        ('hdr_duplicate_headers', 'UInt8'),
    ],
    'response': [
        ('resp_status_code_encoded', 'UInt8'),
        ('resp_body_size', 'UInt32'),
        ('resp_content_type_encoded', 'UInt8'),
        ('resp_cache_status_encoded', 'UInt8'),
        ('resp_compression_ratio', 'Float32'),
        ('resp_ttfb_ms', 'Float32'),
        ('resp_server_timing_ms', 'Float32'),
        ('resp_edge_colos_visited', 'UInt8'),
    ],
    'session': [
        ('sess_duration_sec', 'UInt32'),
        ('sess_page_count', 'UInt16'),
        ('sess_unique_pages', 'UInt16'),
        ('sess_bounce_indicator', 'UInt8'),
        ('sess_referral_chain_length', 'UInt8'),
        ('sess_device_switch_count', 'UInt8'),
        ('sess_geo_consistency_score', 'Float32'),
        ('sess_time_on_page_variance', 'Float32'),
    ],
    'ml_derived': [
        ('ml_anomaly_score', 'Float32'),
        ('ml_cluster_id', 'UInt16'),
        ('ml_embedding_distance', 'Float32'),
        ('ml_similarity_score', 'Float32'),
        ('ml_prediction_confidence', 'Float32'),
        ('ml_feature_entropy', 'Float32'),
    ],
}


def get_all_features():
    """Flatten all feature categories into a single ordered list."""
    features = []
    for category in FEATURE_CATEGORIES:
        features.extend(FEATURE_CATEGORIES[category])
    return features


def init_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    # Create feature metadata table (simulates system.columns)
    conn.execute("""
        CREATE TABLE feature_columns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_name TEXT NOT NULL,
            table_name TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL
        )
    """)

    # Create prefix management tables
    conn.execute("""
        CREATE TABLE prefixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cidr TEXT NOT NULL,
            customer_id INTEGER NOT NULL,
            pending_delete INTEGER DEFAULT 0,
            service_binding TEXT,
            advertised INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE service_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prefix_id INTEGER NOT NULL,
            service_type TEXT NOT NULL,
            config TEXT,
            FOREIGN KEY (prefix_id) REFERENCES prefixes(id)
        )
    """)

    # Create migration history
    conn.execute("""
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)

    all_features = get_all_features()

    # Migration 001: Initial schema with 'default' namespace only
    feature_id = 0
    for name, ftype in all_features:
        feature_id += 1
        conn.execute(
            "INSERT INTO feature_columns (id, schema_name, table_name, name, type) "
            "VALUES (?, ?, ?, ?, ?)",
            (feature_id, 'default', 'http_requests_features', name, ftype),
        )

    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (1, '001_initial_schema', '2024-03-15 10:00:00'),
    )

    # Migration 002: Expose replica schema metadata
    # This change makes r0 (replica) schema metadata visible to users
    # for improved distributed query security and reliability.
    base_id = feature_id
    for name, ftype in all_features:
        base_id += 1
        conn.execute(
            "INSERT INTO feature_columns (id, schema_name, table_name, name, type) "
            "VALUES (?, ?, ?, ?, ?)",
            (base_id, 'r0', 'http_requests_features', name, ftype),
        )

    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (2, '002_expose_replica_access', '2025-11-18 11:05:00'),
    )

    # Populate prefix data (simulates BYOIP prefixes)
    services = ['magic_transit', 'spectrum', 'cdn', 'dedicated_egress']

    for i in range(50):
        cidr = f"198.51.{100 + i}.0/24"
        customer_id = 1000 + (i % 15)
        pending_delete = 1 if i < 5 else 0
        service = services[i % len(services)]

        conn.execute(
            "INSERT INTO prefixes (cidr, customer_id, pending_delete, "
            "service_binding, advertised) VALUES (?, ?, ?, ?, ?)",
            (cidr, customer_id, pending_delete, service, 1),
        )

        conn.execute(
            "INSERT INTO service_bindings (prefix_id, service_type, config) "
            "VALUES (?, ?, ?)",
            (i + 1, service, json.dumps({"region": "global", "priority": 100})),
        )

    conn.commit()

    # Print summary
    total = conn.execute("SELECT COUNT(*) FROM feature_columns").fetchone()[0]
    default_count = conn.execute(
        "SELECT COUNT(*) FROM feature_columns WHERE schema_name = 'default'"
    ).fetchone()[0]
    r0_count = conn.execute(
        "SELECT COUNT(*) FROM feature_columns WHERE schema_name = 'r0'"
    ).fetchone()[0]
    prefix_count = conn.execute("SELECT COUNT(*) FROM prefixes").fetchone()[0]
    pending_count = conn.execute(
        "SELECT COUNT(*) FROM prefixes WHERE pending_delete = 1"
    ).fetchone()[0]

    print(f"Database initialized at {DB_PATH}:")
    print(f"  Features: {total} total ({default_count} default + {r0_count} r0)")
    print(f"  Prefixes: {prefix_count} total ({pending_count} pending deletion)")

    conn.close()


if __name__ == '__main__':
    init_database()
