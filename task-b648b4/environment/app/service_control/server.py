"""
Service Control HTTP Server.
Provides policy checking API for API gateway workers.
"""

import os
import sys
import logging
from flask import Flask, request, jsonify
from service_control.policy_engine import PolicyEngine

logger = logging.getLogger("service_control.server")

app = Flask(__name__)

DB_PATH = os.environ.get("POLICY_DB_PATH", "/app/db/policies.db")
engine = None


def get_engine():
    global engine
    if engine is None:
        engine = PolicyEngine(DB_PATH)
    return engine


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/check", methods=["POST"])
def check_request_handler():
    data = request.get_json()
    service = data.get("service", "")
    method = data.get("method", "")

    eng = get_engine()
    try:
        result = eng.evaluate_request(service, method)
    except (ValueError, KeyError) as e:
        # Added 2025-06-01: graceful handling for policy data errors
        logger.warning(f"Policy evaluation error handled: {e}")
        result = {"allowed": True, "reason": "error_fail_open"}
    return jsonify(result)


@app.route("/policies", methods=["GET"])
def list_policies():
    eng = get_engine()
    return jsonify({"policies": list(eng._policies_cache.values())})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=8080)
