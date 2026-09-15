#!/usr/bin/env python3
"""
Complete the REST API server implementation using stat_util.SPRT_elo.

"""

SERVER_CODE = r'''
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, g
from stats import stat_util

app = Flask(__name__)
DB_PATH = os.environ.get("SPRT_DB_PATH", "/app/sprt_results.db")


def get_db():
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
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        draws INTEGER DEFAULT 0,
        pentanomial TEXT DEFAULT '[]',
        crashes INTEGER DEFAULT 0,
        time_losses INTEGER DEFAULT 0,
        elo0 REAL DEFAULT 0,
        elo1 REAL DEFAULT 5,
        elo_model TEXT DEFAULT 'logistic',
        alpha REAL DEFAULT 0.05,
        beta REAL DEFAULT 0.05
    )""")
    conn.commit()
    conn.close()


def compute_analytics(R_dict, elo0=0, elo1=5, elo_model='logistic',
                      alpha=0.05, beta=0.05):
    """Compute SPRT analytics using stat_util.SPRT_elo orchestrator."""
    return stat_util.SPRT_elo(R_dict, alpha=alpha, beta=beta,
                              elo0=elo0, elo1=elo1, elo_model=elo_model)


def build_R_dict(wins, losses, draws, pentanomial):
    """Build the R dict expected by stat_util.SPRT_elo."""
    R = {"wins": wins, "losses": losses, "draws": draws}
    if pentanomial and len(pentanomial) == 5 and sum(pentanomial) > 0:
        R["pentanomial"] = pentanomial
    return R


@app.route('/api/submit_results', methods=['POST'])
def submit_results():
    data = request.get_json()
    if not data or 'run_id' not in data or 'stats' not in data:
        return jsonify({'error': 'run_id and stats are required'}), 400

    run_id = data['run_id']
    stats = data['stats']
    elo0 = float(data.get('elo0', 0))
    elo1 = float(data.get('elo1', 5))
    elo_model = data.get('elo_model', 'logistic')
    alpha = float(data.get('alpha', 0.05))
    beta = float(data.get('beta', 0.05))

    wins = stats.get('wins', 0)
    losses = stats.get('losses', 0)
    draws = stats.get('draws', 0)
    pentanomial = stats.get('pentanomial', [])
    crashes = stats.get('crashes', 0)
    time_losses = stats.get('time_losses', 0)

    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO runs
        (run_id, wins, losses, draws, pentanomial, crashes, time_losses,
         elo0, elo1, elo_model, alpha, beta)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, wins, losses, draws, json.dumps(pentanomial),
         crashes, time_losses, elo0, elo1, elo_model, alpha, beta)
    )
    db.commit()

    R = build_R_dict(wins, losses, draws, pentanomial)
    analytics = compute_analytics(R, elo0, elo1, elo_model, alpha, beta)
    analytics['run_id'] = run_id
    return jsonify(analytics)


@app.route('/api/submit_raw', methods=['POST'])
def submit_raw():
    data = request.get_json()
    if not data or 'run_id' not in data or 'raw_output' not in data:
        return jsonify({'error': 'run_id and raw_output are required'}), 400

    from parser import parse_fastchess_output
    run_id = data['run_id']
    parsed = parse_fastchess_output(data['raw_output'])

    elo0 = float(data.get('elo0', 0))
    elo1 = float(data.get('elo1', 5))
    elo_model = data.get('elo_model', 'logistic')
    alpha = float(data.get('alpha', 0.05))
    beta = float(data.get('beta', 0.05))

    wins = parsed['wins']
    losses = parsed['losses']
    draws = parsed['draws']
    pentanomial = parsed.get('pentanomial', [])
    crashes = parsed.get('crashes', 0)
    time_losses = parsed.get('time_losses', 0)

    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO runs
        (run_id, wins, losses, draws, pentanomial, crashes, time_losses,
         elo0, elo1, elo_model, alpha, beta)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, wins, losses, draws, json.dumps(pentanomial),
         crashes, time_losses, elo0, elo1, elo_model, alpha, beta)
    )
    db.commit()

    R = build_R_dict(wins, losses, draws, pentanomial)
    analytics = compute_analytics(R, elo0, elo1, elo_model, alpha, beta)
    analytics['run_id'] = run_id
    return jsonify(analytics)


@app.route('/api/get_elo/<run_id>')
def get_elo(run_id):
    db = get_db()
    row = db.execute('SELECT * FROM runs WHERE run_id = ?',
                     (run_id,)).fetchone()
    if row is None:
        return jsonify({'error': f'Run {run_id} not found'}), 404

    pentanomial = json.loads(row['pentanomial']) if row['pentanomial'] else []
    R = build_R_dict(row['wins'], row['losses'], row['draws'], pentanomial)

    analytics = compute_analytics(
        R, row['elo0'], row['elo1'], row['elo_model'],
        row['alpha'], row['beta']
    )
    analytics['run_id'] = run_id
    return jsonify(analytics)


@app.route('/api/calc_elo')
def calc_elo():
    elo0 = float(request.args.get('elo0', 0))
    elo1 = float(request.args.get('elo1', 5))
    elo_model = request.args.get('elo_model', 'logistic')
    alpha = float(request.args.get('alpha', 0.05))
    beta = float(request.args.get('beta', 0.05))

    if 'LL' in request.args:
        ptnml = [int(request.args[k]) for k in ['LL', 'LD', 'DDWL', 'WD', 'WW']]
        R = {"pentanomial": ptnml, "wins": 0, "losses": 0, "draws": 0}
    elif 'W' in request.args:
        R = {
            "wins": int(request.args['W']),
            "losses": int(request.args['L']),
            "draws": int(request.args['D']),
        }
    else:
        return jsonify({'error': 'Provide W/D/L or LL/LD/DDWL/WD/WW'}), 400

    analytics = compute_analytics(R, elo0, elo1, elo_model, alpha, beta)
    return jsonify(analytics)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
'''

with open("/app/server.py", "w") as f:
    f.write(SERVER_CODE.lstrip('\n'))

print("Server implementation complete.")
