"""
Node Simulator - Simulates a cluster of database nodes for the orchestration engine.

Provides actions (drain, stop_service, start_service, run_cleanup, trigger_unrecoverable)
and conditions (is_quorum_safe, is_cluster_normal, get_compaction_level) that the
orchestration engine calls during workflow execution.

Logs all operations to an execution log (JSONL) for verification by tests.
"""

import json
import os
import threading
import time


class NodeSimulator:
    """Simulates a cluster of database nodes."""

    def __init__(self, cluster_config_path, state_path="/app/cluster_state.json",
                 log_path="/app/execution_log.jsonl"):
        with open(cluster_config_path) as f:
            self.config = json.load(f)
        self.state_path = state_path
        self.log_path = log_path
        self.lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._init_state()

    def _init_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                self.state = json.load(f)
        else:
            self.state = {}
            for node in self.config["nodes"]:
                self.state[node["name"]] = {
                    "status": "up",
                    "drained": False,
                    "service_running": True,
                    "compaction_pending": 0,
                    "drain_count": 0,
                    "cleanup_count": 0,
                }
            self._save_state()

    def _save_state(self):
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def _log_event(self, action, node, event, details=""):
        ts = time.time()
        entry = {
            "timestamp": ts,
            "action": action,
            "node": node,
            "event": event,
            "details": details,
        }
        with self._log_lock:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def _get_zone(self, node_name):
        for node in self.config["nodes"]:
            if node["name"] == node_name:
                return node["zone"]
        return None

    # ---- Actions ----

    def drain(self, node_name):
        """Drain a node. Idempotent.
        Nodes whose name ends with '-2' fail with recoverable_error on first attempt.
        """
        with self.lock:
            node = self.state[node_name]
            if node["drained"]:
                self._log_event("drain", node_name, "skip", "already_drained")
                return {"status": "success", "message": "already drained"}

            node["drain_count"] += 1

            if node_name.endswith("-2") and node["drain_count"] == 1:
                self._save_state()
                self._log_event("drain", node_name, "error", "recoverable")
                return {"status": "recoverable_error", "message": "connection timeout"}

            node["drained"] = True
            node["status"] = "drained"
            self._save_state()

        self._log_event("drain", node_name, "start")
        time.sleep(0.1)
        self._log_event("drain", node_name, "end", "success")
        return {"status": "success", "message": "drain completed"}

    def stop_service(self, node_name):
        """Stop the database service on a node. Idempotent."""
        with self.lock:
            node = self.state[node_name]
            if not node["service_running"]:
                self._log_event("stop_service", node_name, "skip", "already_stopped")
                return {"status": "success", "message": "already stopped"}

            node["service_running"] = False
            node["status"] = "stopped"
            self._save_state()

        self._log_event("stop_service", node_name, "start")
        time.sleep(0.05)
        self._log_event("stop_service", node_name, "end", "success")
        return {"status": "success", "message": "service stopped"}

    def start_service(self, node_name):
        """Start the database service on a node. Idempotent."""
        with self.lock:
            node = self.state[node_name]
            if node["service_running"]:
                self._log_event("start_service", node_name, "skip", "already_running")
                return {"status": "success", "message": "already running"}

            node["service_running"] = True
            node["drained"] = False
            node["status"] = "up"
            node["compaction_pending"] = 3
            self._save_state()

        self._log_event("start_service", node_name, "start")
        time.sleep(0.05)
        self._log_event("start_service", node_name, "end", "success")
        return {"status": "success", "message": "service started"}

    def run_cleanup(self, node_name):
        """Run a cleanup operation. Always succeeds. Not idempotent."""
        self._log_event("run_cleanup", node_name, "start")
        time.sleep(0.2)

        with self.lock:
            self.state[node_name]["cleanup_count"] += 1
            self._save_state()

        self._log_event("run_cleanup", node_name, "end", "success")
        return {"status": "success", "message": "cleanup completed"}

    def trigger_unrecoverable(self, node_name):
        """Always returns an unrecoverable error. For testing error handling."""
        self._log_event("trigger_unrecoverable", node_name, "error", "unrecoverable")
        return {"status": "unrecoverable_error", "message": "data corruption detected"}

    # ---- Conditions ----

    def is_quorum_safe(self, node_name):
        """Check if draining this node would still maintain quorum in its zone."""
        zone = self._get_zone(node_name)
        zone_nodes = [n["name"] for n in self.config["nodes"] if n["zone"] == zone]
        with self.lock:
            up_count = sum(
                1 for n in zone_nodes if self.state[n]["status"] == "up"
            )
        return up_count >= 1

    def is_cluster_normal(self):
        """Check if the cluster is in a normal state (majority of nodes up)."""
        total = len(self.config["nodes"])
        with self.lock:
            up_count = sum(
                1 for n in self.state.values() if n["status"] == "up"
            )
        return up_count > total // 2

    def get_compaction_level(self, node_name):
        """Get pending compaction count. Decreases by 1 each call (simulates work)."""
        with self.lock:
            node = self.state[node_name]
            level = node.get("compaction_pending", 0)
            if level > 0:
                node["compaction_pending"] = level - 1
                self._save_state()
            return level
