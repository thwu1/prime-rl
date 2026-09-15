"""
REST API server for the Noisy Polyomino Localization simulator.
Uses Python stdlib http.server — no external dependencies.

Start: python3 /app/server.py [--port PORT]
Default port: 5000

Endpoints:
  POST /session       {"case_id": 0..4}                    -> session info
  POST /drill         {"session_id", "i", "j"}             -> exact query
  POST /divine        {"session_id", "cells": [[i,j],...]} -> noisy group query
  GET  /status/<sid>                                       -> session stats
  POST /submit        {"session_id", "cells": [[i,j],...]} -> correctness check
  GET  /health                                             -> {"status": "ok"}

"""

import json
import math
import sys
import uuid
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from simulator import Simulator, NUM_CASES


_sessions = {}


class _Session:
    def __init__(self, case_id):
        self.sim = Simulator(case_id)
        self.case_id = case_id
        self.session_id = str(uuid.uuid4())
        self.submitted = False
        self.submit_result = None


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})
        elif self.path.startswith("/status/"):
            sid = self.path[len("/status/"):]
            if sid not in _sessions:
                self._send_json({"error": "unknown session"}, 404)
                return
            s = _sessions[sid]
            self._send_json({
                "session_id": sid,
                "case_id": s.case_id,
                "cost": s.sim.cost,
                "num_operations": s.sim.num_operations,
                "max_operations": s.sim.max_operations,
            })
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            data = self._read_json()
        except Exception:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        if self.path == "/session":
            case_id = data.get("case_id")
            if case_id is None or not (0 <= case_id < NUM_CASES):
                self._send_json(
                    {"error": "case_id must be in 0..%d" % (NUM_CASES - 1)}, 400
                )
                return
            s = _Session(case_id)
            _sessions[s.session_id] = s
            self._send_json({
                "session_id": s.session_id,
                "case_id": case_id,
                "N": s.sim.N,
                "M": s.sim.M,
                "epsilon": s.sim.epsilon,
                "polyominoes": s.sim.polyominoes,
                "max_operations": s.sim.max_operations,
            })

        elif self.path == "/drill":
            sid = data.get("session_id")
            if sid not in _sessions:
                self._send_json({"error": "unknown session"}, 404)
                return
            s = _sessions[sid]
            try:
                val = s.sim.drill(data["i"], data["j"])
            except (ValueError, RuntimeError) as e:
                self._send_json({"error": str(e)}, 400)
                return
            self._send_json({
                "value": val,
                "cost": 1.0,
                "total_cost": s.sim.cost,
                "num_operations": s.sim.num_operations,
            })

        elif self.path == "/divine":
            sid = data.get("session_id")
            if sid not in _sessions:
                self._send_json({"error": "unknown session"}, 404)
                return
            s = _sessions[sid]
            cells = data.get("cells", [])
            try:
                cells_tuples = [(c[0], c[1]) for c in cells]
                val = s.sim.divine(cells_tuples)
            except (ValueError, RuntimeError, IndexError) as e:
                self._send_json({"error": str(e)}, 400)
                return
            self._send_json({
                "value": val,
                "cost": 1.0 / math.sqrt(len(cells_tuples)),
                "total_cost": s.sim.cost,
                "num_operations": s.sim.num_operations,
            })

        elif self.path == "/submit":
            sid = data.get("session_id")
            if sid not in _sessions:
                self._send_json({"error": "unknown session"}, 404)
                return
            s = _sessions[sid]
            cells = data.get("cells", [])
            answer = {(c[0], c[1]) for c in cells}
            truth = s.sim._get_active()
            tp = len(answer & truth)
            precision = tp / len(answer) if answer else 0.0
            recall = tp / len(truth) if truth else 0.0
            correct = answer == truth
            s.submitted = True
            s.submit_result = {
                "correct": correct,
                "precision": precision,
                "recall": recall,
                "total_cost": s.sim.cost,
                "num_operations": s.sim.num_operations,
            }
            self._send_json(s.submit_result)

        else:
            self._send_json({"error": "not found"}, 404)

    def log_message(self, format, *args):
        pass  # suppress per-request logging


def main():
    parser = argparse.ArgumentParser(description="Polyomino Localization API")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), _Handler)
    print(
        "Simulator API running on http://127.0.0.1:%d" % args.port,
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
