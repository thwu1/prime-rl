#!/usr/bin/env python3
"""ARC-AGI Task REST API Server using stdlib http.server."""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import re
import sqlite3

TASKS_DIR = "/app/task_data"
DB_PATH = "/app/pipeline.db"


class ARCHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/tasks":
            self._list_tasks()
        elif re.match(r"^/api/tasks/[^/]+$", self.path):
            task_id = self.path.split("/")[3]
            self._get_task(task_id)
        elif self.path == "/api/submissions":
            self._list_submissions()
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        m = re.match(r"^/api/tasks/([^/]+)/submit$", self.path)
        if m:
            task_id = m.group(1)
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len))
            self._submit_solution(task_id, body)
        else:
            self._send_json({"error": "not found"}, 404)

    def _send_json(self, data, code=200):
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _list_tasks(self):
        tasks = []
        for f in sorted(os.listdir(TASKS_DIR)):
            if f.endswith(".json"):
                tid = f[:-5]
                with open(os.path.join(TASKS_DIR, f)) as fh:
                    d = json.load(fh)
                tasks.append(
                    {"task_id": tid, "num_train": len(d["train"]), "num_test": len(d["test"])}
                )
        self._send_json({"tasks": tasks})

    def _get_task(self, task_id):
        path = os.path.join(TASKS_DIR, f"{task_id}.json")
        if not os.path.exists(path):
            self._send_json({"error": "not found"}, 404)
            return
        with open(path) as f:
            data = json.load(f)
        self._send_json({"task_id": task_id, "data": data})

    def _submit_solution(self, task_id, body):
        if "test_outputs" not in body:
            self._send_json({"error": "missing test_outputs"}, 400)
            return
        os.makedirs("/app/outputs", exist_ok=True)
        with open(f"/app/outputs/{task_id}.json", "w") as f:
            json.dump({"test_outputs": body["test_outputs"]}, f)
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO submissions (task_id, test_outputs, submitted_at) "
            "VALUES (?, ?, datetime('now'))",
            (task_id, json.dumps(body["test_outputs"])),
        )
        conn.commit()
        conn.close()
        self._send_json({"status": "accepted", "task_id": task_id})

    def _list_submissions(self):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT task_id, submitted_at FROM submissions ORDER BY task_id"
        ).fetchall()
        conn.close()
        self._send_json(
            {"submissions": [{"task_id": r[0], "submitted_at": r[1]} for r in rows]}
        )

    def log_message(self, format, *args):
        pass  # suppress request logging


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), ARCHandler)
    print("ARC API server running on port 8080")
    server.serve_forever()
