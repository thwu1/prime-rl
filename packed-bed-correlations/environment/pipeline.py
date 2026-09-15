#!/usr/bin/env python3
"""Packed-bed reactor analysis pipeline.

Reads scenario definitions from scenarios.toml, computes pressure drops
across all configured correlations (including native C implementations),
determines minimum fluidization velocities, and calculates terminal
settling velocities.  Results are stored in an SQLite database.
"""

import sqlite3
import tomllib

from correlations import CORRELATIONS
from fluidization import compute_vmf
from settling import v_terminal

DB_PATH = "/app/results.db"


def init_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS pressure_drops (
        scenario TEXT NOT NULL,
        correlation TEXT NOT NULL,
        value REAL NOT NULL,
        PRIMARY KEY (scenario, correlation)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS fluidization (
        scenario TEXT NOT NULL,
        correlation TEXT NOT NULL,
        vmf REAL NOT NULL,
        PRIMARY KEY (scenario, correlation)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS terminal_velocity (
        scenario TEXT NOT NULL,
        vt REAL NOT NULL,
        PRIMARY KEY (scenario)
    )""")
    conn.commit()
    return conn


def load_config(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def process_scenario(conn, s):
    dp = s["dp"]
    voidage = s["voidage"]
    vs = s["vs"]
    rho = s["rho_fluid"]
    mu = s["mu"]
    L = s["L"]
    rho_p = s["rho_particle"]
    Dt = s.get("Dt")
    name = s["name"]

    c = conn.cursor()

    for corr_name, (func, uses_dt) in CORRELATIONS.items():
        kw = dict(dp=dp, voidage=voidage, vs=vs, rho=rho, mu=mu, L=L)
        if uses_dt:
            kw["Dt"] = Dt
        dp_val = func(**kw)
        c.execute(
            "INSERT OR REPLACE INTO pressure_drops VALUES (?, ?, ?)",
            (name, corr_name, dp_val),
        )

        vmf_val = compute_vmf(func, dp, voidage, rho, mu, rho_p)
        c.execute(
            "INSERT OR REPLACE INTO fluidization VALUES (?, ?, ?)",
            (name, corr_name, vmf_val),
        )

    vt = v_terminal(dp, rho_p, rho, mu)
    c.execute(
        "INSERT OR REPLACE INTO terminal_velocity VALUES (?, ?)",
        (name, vt),
    )
    conn.commit()


def main():
    config = load_config("/app/scenarios.toml")
    conn = init_db(DB_PATH)
    for s in config["scenarios"]:
        process_scenario(conn, s)
    conn.close()


if __name__ == "__main__":
    main()
