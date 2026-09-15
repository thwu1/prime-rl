#!/usr/bin/env python3
"""Create the initial replay database with schema."""

import sqlite3
import os

DB_PATH = "/app/replays.db"


def create_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS replays (
            id INTEGER PRIMARY KEY,
            num_steps INTEGER NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS states (
            replay_id INTEGER NOT NULL REFERENCES replays(id),
            step_idx INTEGER NOT NULL,
            data BLOB NOT NULL,
            PRIMARY KEY (replay_id, step_idx)
        );

        CREATE TABLE IF NOT EXISTS actions (
            replay_id INTEGER NOT NULL REFERENCES replays(id),
            step_idx INTEGER NOT NULL,
            data BLOB NOT NULL,
            PRIMARY KEY (replay_id, step_idx)
        );

        CREATE TABLE IF NOT EXISTS known_params (
            replay_id INTEGER NOT NULL REFERENCES replays(id),
            param_name TEXT NOT NULL,
            param_value REAL NOT NULL,
            PRIMARY KEY (replay_id, param_name)
        );

        CREATE TABLE IF NOT EXISTS results (
            replay_id INTEGER NOT NULL REFERENCES replays(id),
            param_name TEXT NOT NULL,
            param_value REAL NOT NULL,
            PRIMARY KEY (replay_id, param_name)
        );

        CREATE INDEX IF NOT EXISTS idx_states_replay ON states(replay_id);
        CREATE INDEX IF NOT EXISTS idx_actions_replay ON actions(replay_id);
    """)


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    create_schema(db)
    db.commit()
    db.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
