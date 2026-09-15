#!/usr/bin/env python3
"""ZMQ Plan Query Server — serves inference plans from the plan database.

Accepts JSON-encoded requests over ZMQ and returns JSON responses.
Endpoints:
    ping            — health check
    get_episodes    — list all episodes
    get_chunks      — chunks for an episode
    get_geometry    — geometry + view crops for an episode
    get_schedule    — denoising schedule for a specific chunk
"""

import zmq
import json
import sys
import os
import sqlite3
import signal

sys.path.insert(0, '/app')


class PlanQueryServer:
    """Serves inference plan queries over ZMQ REQ-REP protocol."""

    def __init__(self, db_path, port=5555):
        self.db_path = db_path
        self.port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(f"tcp://*:{self.port}")
        self.running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        self.running = False

    def _query_db(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def handle_ping(self, request):
        return {"status": "ok", "server": "plan-query", "version": "1.0"}

    def handle_get_episodes(self, request):
        rows = self._query_db("SELECT * FROM episodes ORDER BY id")
        return {"status": "ok", "episodes": rows}

    def handle_get_chunks(self, request):
        episode_id = request.get("episode_id")
        if episode_id is None:
            return {"status": "error", "message": "missing episode_id"}
        rows = self._query_db(
            "SELECT * FROM chunks WHERE episode_id=? ORDER BY chunk_index",
            (episode_id,)
        )
        return {"status": "ok", "chunks": rows}

    def handle_get_geometry(self, request):
        episode_id = request.get("episode_id")
        if episode_id is None:
            return {"status": "error", "message": "missing episode_id"}
        rows = self._query_db(
            "SELECT * FROM geometry WHERE episode_id=?", (episode_id,)
        )
        geo = rows[0] if rows else None
        if geo is None:
            return {"status": "error", "message": "episode not found"}
        crops = self._query_db(
            "SELECT * FROM view_crops WHERE episode_id=? ORDER BY view_index",
            (episode_id,)
        )
        geo["view_crops"] = crops
        return {"status": "ok", "geometry": geo}

    def handle_get_schedule(self, request):
        """Return the denoising schedule for a specific chunk."""
        episode_id = request.get("episode_id")
        chunk_index = request.get("chunk_index")
        if episode_id is None or chunk_index is None:
            return {"status": "error", "message": "missing episode_id or chunk_index"}
        rows = self._query_db(
            "SELECT * FROM chunks WHERE episode_id=? AND chunk_index=?",
            (episode_id, chunk_index)
        )
        if not rows:
            return {"status": "error", "message": "chunk not found"}
        chunk = rows[0]
        from pipeline.scheduler import compute_sigmas
        sigmas = compute_sigmas(chunk["num_steps"], chunk["flow_shift"])
        return {
            "status": "ok",
            "schedule": {
                "sigmas": sigmas,
                "num_steps": chunk["num_steps"],
                "flow_shift": chunk["flow_shift"],
                "stage_boundary": chunk["stage_boundary"],
            }
        }

    ENDPOINTS = {
        "ping": handle_ping,
        "get_episodes": handle_get_episodes,
        "get_chunks": handle_get_chunks,
        "get_geometry": handle_get_geometry,
        "get_schedule": handle_get_schedule,
    }

    def run(self):
        print(f"Plan server listening on tcp://*:{self.port}")
        while self.running:
            try:
                message = self.socket.recv()
                request = json.loads(message.decode('utf-8'))
            except zmq.Again:
                continue
            except Exception:
                continue

            endpoint = request.get("endpoint", "")
            handler = self.ENDPOINTS.get(endpoint)
            if handler is None:
                response = {"status": "error", "message": f"unknown endpoint: {endpoint}"}
            else:
                try:
                    response = handler(self, request)
                except Exception as e:
                    response = {"status": "error", "message": str(e)}

            self.socket.send(str(response).encode('utf-8'))

        self.socket.close()
        self.context.term()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/app/output/plan.db")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()
    server = PlanQueryServer(args.db, args.port)
    server.run()
