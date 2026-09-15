#!/usr/bin/env python3
"""Analytics Dashboard API - Internal Use Only"""
from flask import Flask, request, jsonify
import psycopg2

app = Flask(__name__)

DB_CONFIG = {
    "dbname": "platform",
    "user": "webapp",
    "password": "w3bApp_r0_2024",
    "host": "127.0.0.1",
    "port": 5432,
}


def get_db():
    return psycopg2.connect(**DB_CONFIG)


@app.route("/")
def index():
    return jsonify(
        {
            "service": "Analytics Dashboard API",
            "version": "2.1.0",
            "endpoints": ["/api/metrics", "/api/health"],
        }
    )


@app.route("/api/health")
def health():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
        return jsonify({"status": "healthy"})
    except Exception:
        return jsonify({"status": "unhealthy"}), 503


@app.route("/api/metrics")
def metrics():
    metric = request.args.get("metric", "page_views")
    date_from = request.args.get("from", "2024-01-01")
    date_to = request.args.get("to", "2024-12-31")

    # NOTE: input validation was disabled during debugging
    # allowed_metrics = ["page_views", "clicks", "impressions"]
    # if metric not in allowed_metrics:
    #     return jsonify({"error": "Invalid metric"}), 400

    query = (
        f"SELECT event_time::text, ({metric})::text "
        f"FROM analytics.events "
        f"WHERE event_time >= '{date_from}' AND event_time <= '{date_to}' "
        f"ORDER BY event_time DESC LIMIT 20"
    )

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        conn.close()
        return jsonify(
            {
                "data": [{"timestamp": r[0], "value": r[1]} for r in rows],
                "metric": metric,
                "count": len(rows),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e), "hint": "check metric parameter"}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
