#!/usr/bin/env python3

"""
SCP - Simulated Control Plane Orchestration Engine

Workflow orchestration for database cluster operations with zone-aware
scheduling, SQLite-based resumability, error classification, webhook
notifications via curl, cluster locking via flock, crash recovery with
state reconciliation, and diagnostic tooling via sqlite3 CLI and jq.
"""

import argparse
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

import yaml

sys.path.insert(0, "/app")
from node_simulator import NodeSimulator


# ---------------------------------------------------------------------------
# Webhook Notifications (via curl subprocess)
# ---------------------------------------------------------------------------

def send_webhook(webhook_url, event_type, job_id, details=None):
    """Send a JSON webhook notification via curl. Best-effort, never raises."""
    if not webhook_url:
        return
    payload = {
        "event": event_type,
        "job_id": job_id,
        "timestamp": time.time(),
    }
    if details:
        payload["details"] = details
    try:
        subprocess.run(
            [
                "curl", "-s", "-X", "POST",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(payload),
                "--connect-timeout", "2",
                webhook_url,
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Cluster Locking (via fcntl.flock)
# ---------------------------------------------------------------------------

class ClusterLock:
    """Exclusive advisory lock on a cluster to prevent concurrent orchestrators."""

    def __init__(self, cluster_name, timeout=5):
        self.lockfile_path = f"/tmp/scp_{cluster_name}.lock"
        self.timeout = timeout
        self.fd = None

    def acquire(self):
        self.fd = open(self.lockfile_path, "w")
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fd.write(str(os.getpid()))
                self.fd.flush()
                return True
            except (IOError, OSError):
                time.sleep(0.1)
        self.fd.close()
        self.fd = None
        return False

    def release(self):
        if self.fd:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
                os.remove(self.lockfile_path)
            except Exception:
                pass
            self.fd = None


# ---------------------------------------------------------------------------
# Job Database
# ---------------------------------------------------------------------------

class JobDB:
    """Thread-safe SQLite-backed job state database."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                workflow_path TEXT NOT NULL,
                cluster_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                target_zone TEXT,
                target_nodes TEXT,
                variables TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                task_name TEXT NOT NULL,
                task_index INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                started_at REAL,
                completed_at REAL,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                UNIQUE(job_id, node_name, task_name, task_index)
            );
            """
        )
        self.conn.commit()

    def create_job(self, workflow_name, workflow_path, cluster_path,
                   target_zone=None, target_nodes=None, variables=None):
        job_id = str(uuid.uuid4())[:8]
        now = time.time()
        with self._lock:
            self.conn.execute(
                """INSERT INTO jobs
                   (job_id, workflow_name, workflow_path, cluster_path, status,
                    target_zone, target_nodes, variables, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)""",
                (job_id, workflow_name, workflow_path, cluster_path,
                 target_zone, target_nodes, json.dumps(variables or {}),
                 now, now),
            )
            self.conn.commit()
        return job_id

    def get_job(self, job_id):
        cursor = self.conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cursor.description]
        job = dict(zip(cols, row))
        job["variables"] = json.loads(job.get("variables") or "{}")
        return job

    def update_job_status(self, job_id, status):
        with self._lock:
            self.conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (status, time.time(), job_id),
            )
            self.conn.commit()

    def get_task_status(self, job_id, node_name, task_name, task_index):
        cursor = self.conn.execute(
            """SELECT status FROM task_executions
               WHERE job_id = ? AND node_name = ? AND task_name = ?
               AND task_index = ?""",
            (job_id, node_name, task_name, task_index),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def upsert_task(self, job_id, node_name, task_name, task_index, status,
                    attempts=0, error_message=None):
        now = time.time()
        with self._lock:
            existing = self.conn.execute(
                """SELECT id FROM task_executions
                   WHERE job_id = ? AND node_name = ? AND task_name = ?
                   AND task_index = ?""",
                (job_id, node_name, task_name, task_index),
            ).fetchone()

            if existing:
                completed_at = now if status in ("completed", "failed") else None
                self.conn.execute(
                    """UPDATE task_executions
                       SET status = ?, attempts = ?, error_message = ?,
                           completed_at = ?
                       WHERE id = ?""",
                    (status, attempts, error_message, completed_at, existing[0]),
                )
            else:
                self.conn.execute(
                    """INSERT INTO task_executions
                       (job_id, node_name, task_name, task_index, status,
                        attempts, error_message, started_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job_id, node_name, task_name, task_index, status,
                     attempts, error_message, now),
                )
            self.conn.commit()

    def get_in_progress_tasks(self, job_id):
        """Return tasks stuck in 'in_progress' state (crash orphans)."""
        cursor = self.conn.execute(
            """SELECT node_name, task_name, task_index
               FROM task_executions
               WHERE job_id = ? AND status = 'in_progress'""",
            (job_id,),
        )
        return cursor.fetchall()


# ---------------------------------------------------------------------------
# Crash Recovery
# ---------------------------------------------------------------------------

def reconcile_orphans(db, job_id, simulator, workflow_tasks):
    """Reconcile tasks left in 'in_progress' after a process crash.

    Probes the node simulator's persisted state to determine whether each
    orphaned action actually completed on the node. If the action's observable
    effects are present, mark completed; otherwise reset to pending.
    """
    orphans = db.get_in_progress_tasks(job_id)
    if not orphans:
        return

    for node_name, task_name, task_index in orphans:
        # Find matching task definition
        task_def = None
        if task_index < len(workflow_tasks):
            candidate = workflow_tasks[task_index]
            if candidate["name"] == task_name:
                task_def = candidate
        if task_def is None:
            for i, t in enumerate(workflow_tasks):
                if t["name"] == task_name and i == task_index:
                    task_def = t
                    break

        if task_def is None:
            db.upsert_task(job_id, node_name, task_name, task_index,
                           "pending", 0)
            continue

        action = task_def.get("action", task_name)
        node_state = simulator.state.get(node_name, {})

        # Check observable effects to determine if the action completed
        completed = False
        if action == "drain":
            completed = node_state.get("drained", False)
        elif action == "stop_service":
            completed = not node_state.get("service_running", True)
        elif action == "start_service":
            completed = node_state.get("service_running", False)
        # wait_condition, run_cleanup: indeterminate — reset to pending

        if completed:
            db.upsert_task(job_id, node_name, task_name, task_index,
                           "completed", 1)
        else:
            db.upsert_task(job_id, node_name, task_name, task_index,
                           "pending", 0)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class UnrecoverableError(Exception):
    pass


class Orchestrator:
    """Executes workflows with zone-aware scheduling and resumability."""

    def __init__(self, db, simulator, interrupt_after=0, webhook_url=None):
        self.db = db
        self.sim = simulator
        self.interrupt_after = interrupt_after
        self.webhook_url = webhook_url
        self._completed_count = 0
        self._count_lock = threading.Lock()
        self._interrupted = False

    def run_workflow(self, workflow, cluster_config, job_id,
                     target_zone=None, target_nodes=None, variables=None):
        send_webhook(self.webhook_url, "job_started", job_id)

        # Filter nodes
        nodes = list(cluster_config["nodes"])
        if target_zone:
            nodes = [n for n in nodes if n["zone"] == target_zone]
        if target_nodes:
            target_list = [t.strip() for t in target_nodes.split(",")]
            nodes = [n for n in nodes if n["name"] in target_list]

        # Resolve template variables
        resolved_vars = {}
        for var_def in workflow.get("variables", []):
            resolved_vars[var_def["name"]] = var_def.get("default")
        if variables:
            resolved_vars.update(variables)

        # Build zone batches
        concurrency_unit = workflow.get("concurrency_unit", "global")
        concurrency_limit = workflow.get("concurrency_limit", 1)

        if concurrency_unit == "zonal":
            zone_order = []
            zone_groups = {}
            for node in nodes:
                zone = node["zone"]
                if zone not in zone_groups:
                    zone_order.append(zone)
                    zone_groups[zone] = []
                zone_groups[zone].append(node)
            batches = [(z, zone_groups[z]) for z in zone_order]
        else:
            batches = [("global", nodes)]

        tasks = workflow["node_tasks"]

        try:
            for zone_name, batch_nodes in batches:
                if self._interrupted:
                    break
                send_webhook(self.webhook_url, "zone_started", job_id,
                             {"zone": zone_name})
                self._run_batch(batch_nodes, tasks, concurrency_limit,
                                job_id, resolved_vars)
                if not self._interrupted:
                    send_webhook(self.webhook_url, "zone_completed", job_id,
                                 {"zone": zone_name})
        except UnrecoverableError:
            self.db.update_job_status(job_id, "failed")
            send_webhook(self.webhook_url, "job_failed", job_id)
            raise

        if self._interrupted:
            self.db.update_job_status(job_id, "interrupted")
            return False

        self.db.update_job_status(job_id, "completed")
        send_webhook(self.webhook_url, "job_completed", job_id)
        return True

    def _run_batch(self, nodes, tasks, concurrency_limit, job_id, variables):
        semaphore = threading.Semaphore(concurrency_limit)
        threads = []
        error_event = threading.Event()

        for node in nodes:
            if self._interrupted or error_event.is_set():
                break

            semaphore.acquire()

            if self._interrupted or error_event.is_set():
                semaphore.release()
                break

            t = threading.Thread(
                target=self._run_node_tasks,
                args=(node, tasks, job_id, variables, semaphore, error_event),
                daemon=True,
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        if error_event.is_set():
            raise UnrecoverableError("Job halted due to error")

    def _run_node_tasks(self, node, tasks, job_id, variables, semaphore,
                        error_event):
        try:
            for i, task_def in enumerate(tasks):
                if self._interrupted or error_event.is_set():
                    return

                task_name = task_def["name"]

                # Resumability: skip completed tasks
                existing_status = self.db.get_task_status(
                    job_id, node["name"], task_name, i)
                if existing_status == "completed":
                    continue

                # Check preconditions
                preconditions = task_def.get("preconditions", [])
                if not self._check_preconditions(preconditions, node["name"]):
                    self.db.upsert_task(
                        job_id, node["name"], task_name, i, "failed", 0,
                        "precondition timeout")
                    error_event.set()
                    return

                # Execute with retry logic
                action = task_def.get("action", task_name)
                retries = task_def.get("retries", 0)
                on_error = task_def.get("on_error", "retry")

                success = False
                attempts = 0
                last_error = None

                for attempt in range(retries + 1):
                    if self._interrupted or error_event.is_set():
                        return

                    attempts = attempt + 1
                    self.db.upsert_task(
                        job_id, node["name"], task_name, i,
                        "in_progress", attempts)

                    if action == "wait_condition":
                        result = self._wait_condition(
                            task_def, node["name"], variables)
                    else:
                        result = self._execute_action(action, node["name"])

                    if result["status"] == "success":
                        self.db.upsert_task(
                            job_id, node["name"], task_name, i,
                            "completed", attempts)
                        success = True

                        with self._count_lock:
                            self._completed_count += 1
                            if (self.interrupt_after > 0
                                    and self._completed_count
                                    >= self.interrupt_after):
                                self._interrupted = True
                        break

                    elif result["status"] == "unrecoverable_error":
                        self.db.upsert_task(
                            job_id, node["name"], task_name, i,
                            "failed", attempts,
                            result.get("message", ""))
                        send_webhook(
                            self.webhook_url, "task_error", job_id,
                            {"node": node["name"], "task": task_name,
                             "error_type": "unrecoverable"})
                        error_event.set()
                        return

                    else:  # recoverable_error
                        last_error = result.get("message", "recoverable error")
                        send_webhook(
                            self.webhook_url, "task_error", job_id,
                            {"node": node["name"], "task": task_name,
                             "error_type": "recoverable",
                             "attempt": attempts})
                        if on_error == "halt":
                            self.db.upsert_task(
                                job_id, node["name"], task_name, i,
                                "failed", attempts, last_error)
                            error_event.set()
                            return
                        # on_error == "retry": continue to next attempt

                if not success and not self._interrupted:
                    self.db.upsert_task(
                        job_id, node["name"], task_name, i,
                        "failed", attempts,
                        last_error or "max retries exceeded")
                    error_event.set()
                    return
        finally:
            semaphore.release()

    def _execute_action(self, action, node_name):
        action_map = {
            "drain": self.sim.drain,
            "stop_service": self.sim.stop_service,
            "start_service": self.sim.start_service,
            "run_cleanup": self.sim.run_cleanup,
            "trigger_unrecoverable": self.sim.trigger_unrecoverable,
        }
        if action not in action_map:
            return {"status": "unrecoverable_error",
                    "message": f"Unknown action: {action}"}
        return action_map[action](node_name)

    def _check_preconditions(self, preconditions, node_name, timeout=30):
        if not preconditions:
            return True

        start = time.time()
        while time.time() - start < timeout:
            all_met = True
            for precond in preconditions:
                if precond == "quorum_safe":
                    if not self.sim.is_quorum_safe(node_name):
                        all_met = False
                        break
                elif precond == "cluster_normal":
                    if not self.sim.is_cluster_normal():
                        all_met = False
                        break
            if all_met:
                return True
            time.sleep(0.5)

        return False

    def _wait_condition(self, task_def, node_name, variables):
        condition = task_def["condition"]

        timeout_raw = str(task_def.get("timeout_seconds", 30))
        if timeout_raw.startswith("+") and timeout_raw.endswith("+"):
            var_name = timeout_raw[1:-1]
            timeout = float(variables.get(var_name, 30))
        else:
            timeout = float(timeout_raw)

        poll_interval = float(task_def.get("poll_interval_seconds", 1))

        condition_fn = {
            "compactions_nominal":
                lambda: self.sim.get_compaction_level(node_name) == 0,
        }

        if condition not in condition_fn:
            return {"status": "unrecoverable_error",
                    "message": f"Unknown condition: {condition}"}

        start = time.time()
        while time.time() - start < timeout:
            if condition_fn[condition]():
                return {"status": "success",
                        "message": f"{condition} met"}
            time.sleep(poll_interval)

        return {"status": "recoverable_error",
                "message": f"Condition {condition} timed out after {timeout}s"}


# ---------------------------------------------------------------------------
# Diagnostics (via sqlite3 CLI + jq)
# ---------------------------------------------------------------------------

def run_diagnose(args):
    """Generate diagnostic report using sqlite3 CLI and jq tools."""
    report = {}

    # Integrity check via sqlite3 CLI
    r = subprocess.run(
        ["sqlite3", args.db, "PRAGMA integrity_check;"],
        capture_output=True, text=True)
    report["integrity_check"] = r.stdout.strip()

    # Job summary via sqlite3 CLI with -json flag
    r = subprocess.run(
        ["sqlite3", "-json", args.db,
         "SELECT job_id, workflow_name, status, created_at, updated_at "
         "FROM jobs ORDER BY created_at DESC;"],
        capture_output=True, text=True)
    try:
        report["job_summary"] = (
            json.loads(r.stdout) if r.stdout.strip() else [])
    except json.JSONDecodeError:
        report["job_summary"] = []

    # Task summary via sqlite3 CLI with -json flag
    r = subprocess.run(
        ["sqlite3", "-json", args.db,
         "SELECT task_name, status, COUNT(*) as count, "
         "ROUND(AVG(attempts), 2) as avg_attempts "
         "FROM task_executions GROUP BY task_name, status "
         "ORDER BY task_name;"],
        capture_output=True, text=True)
    try:
        report["task_summary"] = (
            json.loads(r.stdout) if r.stdout.strip() else [])
    except json.JSONDecodeError:
        report["task_summary"] = []

    # Log analysis via jq
    log_path = args.log or "/app/execution_log.jsonl"
    if os.path.exists(log_path):
        jq_filter = (
            '[group_by(.action)[] | '
            '{action: .[0].action, '
            'operation_count: ([.[] | select(.event == "end")] | length), '
            'error_count: ([.[] | select(.event == "error")] | length)}]'
        )
        r = subprocess.run(
            ["jq", "-s", jq_filter, log_path],
            capture_output=True, text=True)
        try:
            report["latency_analysis"] = (
                json.loads(r.stdout) if r.stdout.strip() else [])
        except json.JSONDecodeError:
            report["latency_analysis"] = []
    else:
        report["latency_analysis"] = []

    print(json.dumps(report, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="SCP Orchestration Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_p = subparsers.add_parser("run", help="Run a workflow")
    run_p.add_argument("workflow", help="Path to workflow YAML file")
    run_p.add_argument("--cluster", required=True,
                       help="Path to cluster config JSON")
    run_p.add_argument("--target-zone", help="Target specific zone")
    run_p.add_argument("--target-nodes",
                       help="Comma-separated list of target nodes")
    run_p.add_argument("--vars",
                       help="Comma-separated key=value variable overrides")
    run_p.add_argument("--db", default="/app/scp_jobs.db",
                       help="SQLite database path")
    run_p.add_argument("--interrupt-after", type=int, default=0,
                       help="Interrupt after N completed tasks (testing)")
    run_p.add_argument("--webhook-url",
                       help="URL for lifecycle webhook notifications")

    resume_p = subparsers.add_parser("resume",
                                     help="Resume interrupted job")
    resume_p.add_argument("job_id", help="Job ID to resume")
    resume_p.add_argument("--db", default="/app/scp_jobs.db",
                          help="SQLite database path")
    resume_p.add_argument("--webhook-url",
                          help="URL for lifecycle webhook notifications")

    diag_p = subparsers.add_parser("diagnose",
                                   help="Generate diagnostic report")
    diag_p.add_argument("--db", required=True, help="SQLite database path")
    diag_p.add_argument("--log", help="Execution log path (JSONL)")

    return parser.parse_args()


def main():
    args = parse_args()

    if args.command == "run":
        with open(args.workflow) as f:
            workflow = yaml.safe_load(f)
        with open(args.cluster) as f:
            cluster = json.load(f)

        # Cluster locking
        cluster_name = cluster.get("name", "default")
        lock = ClusterLock(cluster_name)
        if not lock.acquire():
            print("Failed to acquire cluster lock "
                  "(another instance is operating on this cluster)",
                  file=sys.stderr)
            sys.exit(3)

        try:
            variables = {}
            if args.vars:
                for pair in args.vars.split(","):
                    key, value = pair.split("=", 1)
                    try:
                        variables[key] = int(value)
                    except ValueError:
                        try:
                            variables[key] = float(value)
                        except ValueError:
                            variables[key] = value

            db = JobDB(args.db)
            sim = NodeSimulator(args.cluster)

            job_id = db.create_job(
                workflow["name"], args.workflow, args.cluster,
                args.target_zone, args.target_nodes, variables)

            print(f"Job {job_id} started", file=sys.stderr)

            orch = Orchestrator(db, sim, args.interrupt_after,
                                args.webhook_url)

            try:
                success = orch.run_workflow(
                    workflow, cluster, job_id,
                    args.target_zone, args.target_nodes, variables)
                if success:
                    print(f"Job {job_id} completed", file=sys.stderr)
                    sys.exit(0)
                else:
                    print(f"Job {job_id} interrupted", file=sys.stderr)
                    sys.exit(2)
            except UnrecoverableError as e:
                print(f"Job {job_id} failed: {e}", file=sys.stderr)
                sys.exit(1)
        finally:
            lock.release()

    elif args.command == "resume":
        db = JobDB(args.db)
        job = db.get_job(args.job_id)

        if not job:
            print(f"Job {args.job_id} not found", file=sys.stderr)
            sys.exit(1)

        if job["status"] == "completed":
            print(f"Job {args.job_id} already completed", file=sys.stderr)
            sys.exit(0)

        with open(job["workflow_path"]) as f:
            workflow = yaml.safe_load(f)
        with open(job["cluster_path"]) as f:
            cluster = json.load(f)

        # Cluster locking
        cluster_name = cluster.get("name", "default")
        lock = ClusterLock(cluster_name)
        if not lock.acquire():
            print("Failed to acquire cluster lock", file=sys.stderr)
            sys.exit(3)

        try:
            sim = NodeSimulator(job["cluster_path"])

            # Crash recovery: reconcile orphaned in_progress tasks
            reconcile_orphans(db, args.job_id, sim, workflow["node_tasks"])

            db.update_job_status(args.job_id, "running")
            print(f"Resuming job {args.job_id}", file=sys.stderr)

            orch = Orchestrator(db, sim,
                                webhook_url=args.webhook_url)

            try:
                success = orch.run_workflow(
                    workflow, cluster, args.job_id,
                    job.get("target_zone"),
                    job.get("target_nodes"),
                    job.get("variables"))
                if success:
                    print(f"Job {args.job_id} completed", file=sys.stderr)
                    sys.exit(0)
                else:
                    print(f"Job {args.job_id} interrupted", file=sys.stderr)
                    sys.exit(2)
            except UnrecoverableError as e:
                print(f"Job {args.job_id} failed: {e}", file=sys.stderr)
                sys.exit(1)
        finally:
            lock.release()

    elif args.command == "diagnose":
        run_diagnose(args)


if __name__ == "__main__":
    main()
