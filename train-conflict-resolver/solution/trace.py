
"""
SQLite trace writer for simulation results.
"""

import sqlite3
from typing import List


def write_trace(db_path: str, results: List[dict]):
    """Write simulation step results to a SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_traces (
            step          INTEGER NOT NULL,
            agent_handle  INTEGER NOT NULL,
            state         INTEGER NOT NULL,
            position_row  INTEGER,
            position_col  INTEGER,
            speed         REAL    NOT NULL,
            moving        INTEGER NOT NULL,
            PRIMARY KEY (step, agent_handle)
        )
    """)
    for step_result in results:
        step = step_result["step"]
        for handle_str, agent_data in step_result["agents"].items():
            pos = agent_data["position"]
            conn.execute(
                "INSERT INTO agent_traces VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    step,
                    int(handle_str),
                    agent_data["state"],
                    pos[0] if pos else None,
                    pos[1] if pos else None,
                    agent_data["speed"],
                    1 if agent_data["moving"] else 0,
                )
            )
    conn.commit()
    conn.close()
