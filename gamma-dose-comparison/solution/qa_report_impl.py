
"""QA report generator with SQLite persistence."""

import json
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np
from gamma import gamma

DB_PATH = "/app/results.db"


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            pass_rate REAL NOT NULL,
            mean_gamma REAL NOT NULL,
            max_gamma REAL NOT NULL,
            points_evaluated INTEGER NOT NULL,
            points_passing INTEGER NOT NULL,
            passed INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def generate_qa_report(reference_path, evaluation_path, axes_path, criteria_path):
    with open(axes_path) as f:
        axes_data = json.load(f)
    axes = tuple(np.array(a) for a in axes_data["axes"])

    ref = np.loadtxt(reference_path)
    evl = np.loadtxt(evaluation_path)

    if len(axes) > 1:
        shape = tuple(len(a) for a in axes)
        ref = ref.reshape(shape)
        evl = evl.reshape(shape)

    with open(criteria_path) as f:
        criteria = json.load(f)

    g = gamma(
        axes,
        ref,
        axes,
        evl,
        criteria["dose_percent_threshold"],
        criteria["distance_mm_threshold"],
        lower_percent_dose_cutoff=criteria["lower_percent_dose_cutoff"],
    )

    finite_mask = np.isfinite(g)
    finite_gamma = g[finite_mask]

    points_evaluated = int(len(finite_gamma))
    points_passing = int(np.sum(finite_gamma <= 1.0))
    pass_rate = (
        float(points_passing / points_evaluated * 100)
        if points_evaluated > 0
        else 0.0
    )
    mean_gamma_val = (
        float(np.mean(finite_gamma)) if points_evaluated > 0 else 0.0
    )
    max_gamma_val = (
        float(np.max(finite_gamma)) if points_evaluated > 0 else 0.0
    )
    passed = pass_rate >= criteria["pass_rate_threshold"]

    # Persist to SQLite
    session_name = os.path.splitext(os.path.basename(reference_path))[0]
    conn = _init_db()
    conn.execute(
        "INSERT OR REPLACE INTO sessions "
        "(session_name, created_at, pass_rate, mean_gamma, max_gamma, "
        "points_evaluated, points_passing, passed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_name,
            datetime.now(timezone.utc).isoformat(),
            pass_rate,
            mean_gamma_val,
            max_gamma_val,
            points_evaluated,
            points_passing,
            1 if passed else 0,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "pass_rate": pass_rate,
        "mean_gamma": mean_gamma_val,
        "max_gamma": max_gamma_val,
        "points_evaluated": points_evaluated,
        "points_passing": points_passing,
        "passed": passed,
    }
