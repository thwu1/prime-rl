#!/usr/bin/env python3
"""
CDN Configuration API Server

Serves feature metadata and manages IP prefix lifecycle for the
bot management configuration pipeline. Feature metadata is sourced
from the distributed database cluster's system tables.

Part of the configuration management system that generates feature
files for the ML-based bot detection model running on edge proxies.
"""

from flask import Flask, request, jsonify
import sqlite3
import logging
import os

app = Flask(__name__)

DB_PATH = '/app/db/features.db'

logger = logging.getLogger('api_server')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/api/features')
def get_features():
    """Return feature column metadata for a given table.

    Queries the feature_columns metadata table (analogous to
    ClickHouse system.columns) to retrieve feature definitions
    used by the bot management ML model.
    """
    table = request.args.get('table', 'http_requests_features')
    conn = get_db()

    # Retrieve feature columns for the specified table.
    # After migration 002_expose_replica_access, users can see
    # metadata from both default and r0 schemas for improved
    # distributed query security and reliability.
    cursor = conn.execute(
        """SELECT name, type, schema_name
           FROM feature_columns
           WHERE table_name = ?
           ORDER BY name""",
        (table,)
    )

    features = [dict(row) for row in cursor]
    logger.info("GET /api/features?table=%s -> %d features", table, len(features))
    conn.close()
    return jsonify(features)


@app.route('/api/prefixes')
def get_prefixes():
    """Return IP prefixes, optionally filtered by pending_delete status.

    The cleanup task calls this endpoint with ?pending_delete to get
    prefixes queued for removal from the BYOIP service.
    """
    conn = get_db()

    pending_delete_filter = request.args.get('pending_delete')
    if pending_delete_filter:
        # Return only prefixes pending deletion
        cursor = conn.execute(
            """SELECT id, cidr, customer_id, pending_delete, service_binding
               FROM prefixes WHERE pending_delete = 1"""
        )
        prefixes = [dict(row) for row in cursor]
        logger.info(
            "GET /api/prefixes?pending_delete -> %d pending prefixes",
            len(prefixes),
        )
    else:
        # Return all prefixes
        cursor = conn.execute(
            """SELECT id, cidr, customer_id, pending_delete, service_binding
               FROM prefixes"""
        )
        prefixes = [dict(row) for row in cursor]
        logger.info("GET /api/prefixes -> %d total prefixes", len(prefixes))

    conn.close()
    return jsonify(prefixes)


@app.route('/api/prefixes/withdraw', methods=['POST'])
def withdraw_prefix():
    """Withdraw a prefix and remove its service bindings.

    Called by the cleanup task to remove prefixes that have been
    queued for deletion by customers.
    """
    data = request.get_json()
    prefix_id = data.get('id')

    if prefix_id is None:
        return jsonify({"error": "missing prefix id"}), 400

    conn = get_db()
    conn.execute("DELETE FROM service_bindings WHERE prefix_id = ?", (prefix_id,))
    conn.execute("UPDATE prefixes SET advertised = 0 WHERE id = ?", (prefix_id,))
    conn.commit()
    conn.close()

    logger.info("POST /api/prefixes/withdraw id=%s", prefix_id)
    return jsonify({"status": "withdrawn", "id": prefix_id})


@app.route('/health')
def health():
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    os.makedirs('/app/logs', exist_ok=True)
    logging.basicConfig(
        filename='/app/logs/api_requests.log',
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    print("API server starting on :8080")
    app.run(host='0.0.0.0', port=8080)
