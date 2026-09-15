#!/usr/bin/env python3
"""Flask query service with multi-layer WAF middleware protection."""

import sys
import sqlite3
from flask import Flask, request, jsonify

sys.path.insert(0, '/app')
from waf import WAF

app = Flask(__name__)
DB_PATH = '/app/database.db'


@app.route('/query', methods=['POST'])
def query_endpoint():
    data = request.get_json(force=True, silent=True)
    if not data or 'where' not in data:
        return jsonify({"error": "Missing 'where' parameter"}), 400

    where_clause = data['where']
    waf = WAF()
    headers = dict(request.headers)
    allowed, triggered = waf.check(where_clause, headers=headers)

    if not allowed:
        rules = [{"id": r[0], "description": r[1]} for r in triggered]
        return jsonify({"status": "blocked", "rules": rules}), 403

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        sql = f"SELECT * FROM users WHERE {where_clause}"
        cursor.execute(sql)
        results = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if results else []
        rows = [dict(row) for row in results]
        conn.close()
        return jsonify({"status": "ok", "columns": columns, "rows": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
