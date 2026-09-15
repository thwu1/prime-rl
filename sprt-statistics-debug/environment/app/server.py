"""
SPRT Analysis REST API Server.

Provides endpoints for submitting chess engine game results,
computing SPRT statistics, and querying test status.

Endpoints:
    POST /api/submit_results  - Submit pre-parsed game results for a run
    POST /api/submit_raw      - Submit raw fastchess output for parsing and analysis
    GET  /api/get_elo/<run_id> - Retrieve SPRT analytics for a stored run
    GET  /api/calc_elo         - Calculate SPRT Elo from query parameters (no storage)
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, g

app = Flask(__name__)
DB_PATH = os.environ.get("SPRT_DB_PATH", "/app/sprt_results.db")


def get_db():
    """Get a database connection for the current request context."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize the database schema.

    Must create tables for storing:
    - Run configurations (run_id, elo0, elo1, elo_model, alpha, beta)
    - Accumulated game results per run (wins, losses, draws, pentanomial,
      crashes, time_losses)
    """
    # TODO: Implement database schema creation
    raise NotImplementedError("Database initialization not implemented")


@app.route('/api/submit_results', methods=['POST'])
def submit_results():
    """Accept pre-parsed game results for a run and return SPRT analytics.

    Request JSON:
        run_id: str (required) - unique identifier for this test run
        stats: dict (required) - game results with keys:
            wins: int, losses: int, draws: int,
            pentanomial: list[int] (optional, length 5),
            crashes: int (optional), time_losses: int (optional)
        elo0: float (optional, default 0)
        elo1: float (optional, default 5)
        elo_model: str (optional, default "logistic")
        alpha: float (optional, default 0.05)
        beta: float (optional, default 0.05)

    Returns JSON: elo, ci, LLR, LOS, a, b, run_id
    """
    # TODO: Validate input, store in DB, compute SPRT analytics, return
    return jsonify({"error": "not implemented"}), 501


@app.route('/api/submit_raw', methods=['POST'])
def submit_raw():
    """Accept raw fastchess output, parse it, store results, return analytics.

    Request JSON:
        run_id: str (required)
        raw_output: str (required) - raw fastchess console output
        elo0, elo1, elo_model, alpha, beta: same as submit_results

    Returns JSON: elo, ci, LLR, LOS, a, b, run_id
    """
    # TODO: Parse raw output with parser module, then store and compute
    return jsonify({"error": "not implemented"}), 501


@app.route('/api/get_elo/<run_id>')
def get_elo(run_id):
    """Get SPRT analytics for a previously stored run.

    Returns JSON: run_id, elo, ci, LLR, LOS, a, b
    Returns 404 if run_id not found.
    """
    # TODO: Look up run in DB, compute analytics from stored results
    return jsonify({"error": "not implemented"}), 501


@app.route('/api/calc_elo')
def calc_elo():
    """Calculate SPRT Elo from provided game results (no storage).

    Trinomial mode query parameters: W, D, L (int)
    Pentanomial mode query parameters: LL, LD, DDWL, WD, WW (int)
    Common parameters: elo0, elo1, elo_model, alpha, beta

    Returns JSON: elo, ci, LLR, LOS, a, b
    """
    # TODO: Parse query params, build results array, compute analytics
    return jsonify({"error": "not implemented"}), 501


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
