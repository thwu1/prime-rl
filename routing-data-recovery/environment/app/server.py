#!/usr/bin/env python3
"""Network Control Plane API Server.

Serves routing configuration from the SQLite database via REST API.
Manages route CRUD operations and health monitoring.
"""

import json
import sqlite3
import sys
import os
import configparser
from flask import Flask, jsonify, request

app = Flask(__name__)


def get_config():
    config = configparser.ConfigParser()
    config.read('/app/config/server.ini')
    return config


def get_db():
    config = get_config()
    db_path = config.get('server', 'db_path', fallback='/app/db/network.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/health')
def health():
    try:
        db = get_db()
        cursor = db.execute('SELECT COUNT(*) as cnt FROM routes')
        count = cursor.fetchone()['cnt']
        db.close()
        return jsonify({'status': 'healthy', 'route_count': count}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500


@app.route('/routes', methods=['GET'])
def get_routes():
    try:
        db = get_db()
        routes = db.execute(
            'SELECT source_node, destination_network, next_hop_node, metric, status '
            'FROM routes ORDER BY source_node, destination_network'
        ).fetchall()
        db.close()
        return jsonify([dict(r) for r in routes])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/routes/<source_node>', methods=['GET'])
def get_routes_for_node(source_node):
    try:
        db = get_db()
        routes = db.execute(
            'SELECT source_node, destination_network, next_hop_node, metric, status '
            'FROM routes WHERE source_node = ? ORDER BY destination_network',
            (source_node,)
        ).fetchall()
        db.close()
        if not routes:
            return jsonify({'error': f'No routes found for node {source_node}'}), 404
        return jsonify([dict(r) for r in routes])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/routes', methods=['POST'])
def add_route():
    data = request.get_json()
    required = ['source_node', 'destination_network', 'next_hop_node', 'metric']
    if not all(k in data for k in required):
        return jsonify({'error': f'Missing required fields: {required}'}), 400
    try:
        db = get_db()
        db.execute(
            'INSERT OR REPLACE INTO routes '
            '(source_node, destination_network, next_hop_node, metric, status) '
            'VALUES (?, ?, ?, ?, ?)',
            (data['source_node'], data['destination_network'],
             data['next_hop_node'], data['metric'],
             data.get('status', 'active'))
        )
        db.commit()
        db.close()
        return jsonify({'status': 'ok'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/topology', methods=['GET'])
def get_topology():
    try:
        with open('/app/config/topology.json') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def write_pid():
    config = get_config()
    pid_file = config.get('health', 'pid_file', fallback='/var/run/control_plane.pid')
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))


if __name__ == '__main__':
    config = get_config()
    host = config.get('server', 'host', fallback='0.0.0.0')
    port = config.getint('server', 'port', fallback=5000)
    write_pid()
    app.run(host=host, port=port)
