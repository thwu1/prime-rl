
"""
Tests for the SCP Orchestration Engine.

Verifies zone-aware scheduling, concurrency limits, resumability,
error classification, targeting, template variables, webhook notifications,
cluster locking, crash recovery, and diagnostic reporting.
"""

import fcntl
import json
import os
import sqlite3
import subprocess
import time

import pytest

FILES_TO_CLEAN = [
    "/app/scp_jobs.db",
    "/app/cluster_state.json",
    "/app/execution_log.jsonl",
    "/app/webhook_log.jsonl",
    "/tmp/scp_messages-prd.lock",
]


@pytest.fixture(autouse=True)
def clean_state():
    """Remove state files before and after each test."""
    for f in FILES_TO_CLEAN:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
    yield
    for f in FILES_TO_CLEAN:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


@pytest.fixture
def webhook_server():
    """Start the webhook server in the background for webhook tests."""
    try:
        os.remove("/app/webhook_log.jsonl")
    except FileNotFoundError:
        pass

    proc = subprocess.Popen(
        ["python3", "/app/webhook_server.py", "9876"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)  # Wait for server to start
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_scp(*args, timeout=120):
    """Run the orchestration engine as a subprocess."""
    result = subprocess.run(
        ["python3", "/app/scp.py"] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/app",
    )
    return result


def get_execution_log():
    """Read the JSONL execution log."""
    entries = []
    if os.path.exists("/app/execution_log.jsonl"):
        with open("/app/execution_log.jsonl") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    return entries


def get_job_db():
    """Open a read-only connection to the job database."""
    return sqlite3.connect("/app/scp_jobs.db")


def load_cluster():
    """Load the cluster configuration."""
    with open("/app/cluster.json") as f:
        return json.load(f)


class TestBasicExecution:
    """Verify that a workflow runs to completion with correct state."""

    def test_all_nodes_complete(self):
        """All 9 nodes should have all 4 tasks completed after rolling restart."""
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
        )
        assert result.returncode == 0, (
            f"SCP failed (code={result.returncode}): {result.stderr}")

        db = get_job_db()

        # Exactly one job should exist
        cursor = db.execute("SELECT COUNT(*), status FROM jobs")
        count, status = cursor.fetchone()
        assert count == 1, f"Expected 1 job, got {count}"
        assert status == "completed"

        # 9 nodes x 4 tasks = 36 completed task executions
        cursor = db.execute(
            "SELECT COUNT(*) FROM task_executions WHERE status = 'completed'"
        )
        completed = cursor.fetchone()[0]
        assert completed == 36, f"Expected 36 completed tasks, got {completed}"

        # Each node should have exactly 4 completed tasks
        cursor = db.execute(
            """SELECT node_name, COUNT(*) AS cnt
               FROM task_executions
               WHERE status = 'completed'
               GROUP BY node_name"""
        )
        for node_name, cnt in cursor.fetchall():
            assert cnt == 4, (
                f"Node {node_name} has {cnt} completed tasks, expected 4")

        db.close()


class TestZoneScheduling:
    """Verify that zone-aware scheduling processes zones sequentially."""

    def test_zone_isolation(self):
        """With concurrency_unit=zonal, zones must not overlap in time."""
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
        )
        assert result.returncode == 0, f"SCP failed: {result.stderr}"

        log = get_execution_log()
        cluster = load_cluster()
        node_to_zone = {n["name"]: n["zone"] for n in cluster["nodes"]}
        zones = sorted(set(n["zone"] for n in cluster["nodes"]))

        # Compute the time range [first_start, last_end] for each zone
        zone_ranges = {}
        for zone in zones:
            zone_nodes = {n for n, z in node_to_zone.items() if z == zone}
            starts = []
            ends = []
            for e in log:
                if e["node"] in zone_nodes:
                    if e["event"] == "start":
                        starts.append(e["timestamp"])
                    elif e["event"] == "end":
                        ends.append(e["timestamp"])
            if starts and ends:
                zone_ranges[zone] = (min(starts), max(ends))

        assert len(zone_ranges) == 3, (
            f"Expected 3 zones with events, got {len(zone_ranges)}")

        # Sort zones by their start time and verify non-overlapping
        sorted_zones = sorted(zone_ranges, key=lambda z: zone_ranges[z][0])
        for i in range(len(sorted_zones) - 1):
            z1 = sorted_zones[i]
            z2 = sorted_zones[i + 1]
            z1_end = zone_ranges[z1][1]
            z2_start = zone_ranges[z2][0]
            assert z1_end < z2_start, (
                f"Zone {z1} (ends {z1_end:.4f}) overlaps with "
                f"zone {z2} (starts {z2_start:.4f})")


class TestConcurrencyLimit:
    """Verify concurrency limit enforcement."""

    def test_max_concurrent_operations(self):
        """With concurrency_limit=2, at most 2 operations run in parallel."""
        result = run_scp(
            "run",
            "/app/workflows/parallel_cleanup.yaml",
            "--cluster",
            "/app/cluster.json",
        )
        assert result.returncode == 0, f"SCP failed: {result.stderr}"

        log = get_execution_log()

        # Build a timeline from start/end events for run_cleanup
        events = []
        for entry in log:
            if entry["action"] == "run_cleanup":
                if entry["event"] == "start":
                    events.append((entry["timestamp"], +1))
                elif entry["event"] == "end":
                    events.append((entry["timestamp"], -1))

        events.sort(key=lambda x: x[0])

        max_concurrent = 0
        current = 0
        for _, delta in events:
            current += delta
            max_concurrent = max(max_concurrent, current)

        assert max_concurrent <= 2, (
            f"Concurrency limit violated: max concurrent was "
            f"{max_concurrent}, expected <= 2")
        assert max_concurrent >= 2, (
            f"Expected parallelism (concurrent >= 2), but max was "
            f"{max_concurrent}; concurrency_limit=2 should allow 2")


class TestResumability:
    """Verify interrupted jobs resume without re-executing completed tasks."""

    def test_resume_skips_completed(self):
        """Interrupt after 6 completions, resume, verify no re-execution."""
        # Run with interruption
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--interrupt-after",
            "6",
        )
        assert result.returncode == 2, (
            f"Expected interrupted (exit 2), got {result.returncode}: "
            f"{result.stderr}")

        # Extract completed tasks from SQLite
        db = get_job_db()
        cursor = db.execute(
            "SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT 1")
        job_id = cursor.fetchone()[0]

        cursor = db.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (job_id,))
        assert cursor.fetchone()[0] == "interrupted"

        cursor = db.execute(
            "SELECT node_name, task_name FROM task_executions "
            "WHERE job_id = ? AND status = 'completed'",
            (job_id,),
        )
        completed_before = set(
            (row[0], row[1]) for row in cursor.fetchall())
        db.close()

        assert len(completed_before) >= 4, (
            f"Expected >= 4 completed tasks before interrupt, "
            f"got {len(completed_before)}")

        # Clear execution log so we can track resume-only events
        try:
            os.remove("/app/execution_log.jsonl")
        except FileNotFoundError:
            pass

        # Resume the job
        result = run_scp("resume", job_id)
        assert result.returncode == 0, f"Resume failed: {result.stderr}"

        # Verify no log events for previously-completed action tasks
        log = get_execution_log()
        action_completed = {
            (n, t) for n, t in completed_before if t != "wait_compactions"
        }

        for entry in log:
            key = (entry["node"], entry["action"])
            assert key not in action_completed, (
                f"Completed task {key} was re-executed during resume "
                f"(event={entry['event']})")

        # Verify the job is now fully completed
        db = get_job_db()
        cursor = db.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (job_id,))
        assert cursor.fetchone()[0] == "completed"

        cursor = db.execute(
            "SELECT COUNT(*) FROM task_executions "
            "WHERE job_id = ? AND status = 'completed'",
            (job_id,),
        )
        assert cursor.fetchone()[0] == 36, (
            "All 36 tasks should be completed after resume")
        db.close()


class TestErrorHandling:
    """Verify error classification and handling."""

    def test_recoverable_error_retried(self):
        """Nodes ending in '-2' fail drain on first attempt; retried."""
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
        )
        assert result.returncode == 0, f"SCP failed: {result.stderr}"

        log = get_execution_log()

        # Find drain events for -2 nodes
        node2_names = {
            "node-us-east1-a-2",
            "node-us-east1-b-2",
            "node-us-east1-c-2",
        }

        retry_verified = False
        for node_name in node2_names:
            node_drains = [
                e for e in log
                if e["action"] == "drain" and e["node"] == node_name
            ]
            events_by_type = {}
            for e in node_drains:
                events_by_type.setdefault(e["event"], []).append(e)

            if "error" in events_by_type and "end" in events_by_type:
                error_ts = events_by_type["error"][0]["timestamp"]
                success_ts = events_by_type["end"][0]["timestamp"]
                assert error_ts < success_ts, (
                    f"Error should precede success for {node_name}")
                retry_verified = True

        assert retry_verified, (
            "Expected at least one -2 node to show "
            "error-then-success drain pattern")

        # Verify drain tasks for -2 nodes have attempts > 1 in SQLite
        db = get_job_db()
        cursor = db.execute("SELECT job_id FROM jobs LIMIT 1")
        job_id = cursor.fetchone()[0]

        for node_name in node2_names:
            cursor = db.execute(
                "SELECT attempts FROM task_executions "
                "WHERE job_id = ? AND node_name = ? AND task_name = 'drain'",
                (job_id, node_name),
            )
            row = cursor.fetchone()
            assert row is not None, f"No drain task record for {node_name}"
            assert row[0] >= 2, (
                f"Drain on {node_name} should have >= 2 attempts, "
                f"got {row[0]}")
        db.close()

    def test_unrecoverable_halts_job(self):
        """Unrecoverable errors should halt the job immediately."""
        result = run_scp(
            "run",
            "/app/workflows/unrecoverable_test.yaml",
            "--cluster",
            "/app/cluster.json",
        )
        assert result.returncode != 0, (
            "Job with unrecoverable error should exit non-zero")

        db = get_job_db()
        cursor = db.execute(
            "SELECT status FROM jobs ORDER BY created_at DESC LIMIT 1")
        status = cursor.fetchone()[0]
        assert status == "failed", (
            f"Job status should be 'failed', got '{status}'")

        # Not all nodes should have been processed
        cursor = db.execute(
            "SELECT COUNT(DISTINCT node_name) FROM task_executions")
        processed = cursor.fetchone()[0]
        cluster = load_cluster()
        total_nodes = len(cluster["nodes"])
        assert processed < total_nodes, (
            f"Expected fewer than {total_nodes} nodes processed, "
            f"got {processed}")
        db.close()


class TestTargeting:
    """Verify node and zone targeting."""

    def test_zone_targeting(self):
        """Only nodes in the targeted zone should be processed."""
        target_zone = "us-east1-a"
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-zone",
            target_zone,
        )
        assert result.returncode == 0, f"SCP failed: {result.stderr}"

        log = get_execution_log()
        cluster = load_cluster()
        node_to_zone = {n["name"]: n["zone"] for n in cluster["nodes"]}

        for entry in log:
            node = entry["node"]
            if node in node_to_zone:
                assert node_to_zone[node] == target_zone, (
                    f"Node {node} in zone {node_to_zone[node]} was "
                    f"processed (target={target_zone})")

        # 3 nodes x 4 tasks = 12
        db = get_job_db()
        cursor = db.execute(
            "SELECT COUNT(*) FROM task_executions "
            "WHERE status = 'completed'")
        assert cursor.fetchone()[0] == 12, (
            "Expected 12 completed tasks for 3-node zone")
        db.close()

    def test_node_targeting(self):
        """Only the targeted node should be processed."""
        target_node = "node-us-east1-a-1"
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            target_node,
        )
        assert result.returncode == 0, f"SCP failed: {result.stderr}"

        log = get_execution_log()
        for entry in log:
            assert entry["node"] == target_node, (
                f"Non-targeted node {entry['node']} was processed")

        db = get_job_db()
        cursor = db.execute(
            "SELECT COUNT(*) FROM task_executions "
            "WHERE status = 'completed'")
        assert cursor.fetchone()[0] == 4, (
            "Expected 4 completed tasks for single node")
        db.close()


class TestTemplateVariables:
    """Verify template variable substitution."""

    def test_variable_override(self):
        """Workflow variables should be overridable via --vars."""
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            "node-us-east1-a-1",
            "--vars",
            "compaction_timeout_seconds=10",
        )
        assert result.returncode == 0, f"SCP failed: {result.stderr}"

        db = get_job_db()
        cursor = db.execute(
            "SELECT status FROM task_executions "
            "WHERE task_name = 'wait_compactions'")
        row = cursor.fetchone()
        assert row is not None, "wait_compactions task should exist"
        assert row[0] == "completed", (
            f"wait_compactions should be completed, got {row[0]}")
        db.close()


class TestWebhookNotifications:
    """Verify webhook notifications are sent via curl at lifecycle events."""

    def test_lifecycle_events(self, webhook_server):
        """Core lifecycle events should be delivered to the webhook endpoint."""
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            "node-us-east1-a-1",
            "--webhook-url",
            "http://127.0.0.1:9876",
        )
        assert result.returncode == 0, (
            f"SCP failed: {result.stderr}")

        # Read webhook log
        events = []
        with open("/app/webhook_log.jsonl") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))

        event_types = [e["event"] for e in events]

        assert "job_started" in event_types, (
            f"Missing job_started. Events: {event_types}")
        assert "job_completed" in event_types, (
            f"Missing job_completed. Events: {event_types}")
        assert "zone_started" in event_types, (
            f"Missing zone_started. Events: {event_types}")
        assert "zone_completed" in event_types, (
            f"Missing zone_completed. Events: {event_types}")

        # Verify event structure
        for e in events:
            assert "job_id" in e, f"Event missing job_id: {e}"
            assert "event" in e, f"Event missing event: {e}"
            assert "timestamp" in e, f"Event missing timestamp: {e}"

    def test_error_events_sent(self, webhook_server):
        """Recoverable errors should generate task_error webhook events."""
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-zone",
            "us-east1-a",
            "--webhook-url",
            "http://127.0.0.1:9876",
        )
        assert result.returncode == 0

        events = []
        with open("/app/webhook_log.jsonl") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))

        error_events = [e for e in events if e["event"] == "task_error"]
        assert len(error_events) >= 1, (
            "Expected at least one task_error event (node-*-2 drain)")
        assert "details" in error_events[0], (
            "task_error should include details")
        assert "node" in error_events[0]["details"], (
            "task_error details should include node")
        assert "task" in error_events[0]["details"], (
            "task_error details should include task")


class TestClusterLocking:
    """Verify mutual exclusion via flock on the cluster lock file."""

    def test_lock_conflict_exits_code_3(self):
        """Concurrent access to same cluster should exit with code 3."""
        lockfile = "/tmp/scp_messages-prd.lock"
        fd = open(lockfile, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            result = run_scp(
                "run",
                "/app/workflows/rolling_restart.yaml",
                "--cluster",
                "/app/cluster.json",
                "--target-nodes",
                "node-us-east1-a-1",
                timeout=30,
            )
            assert result.returncode == 3, (
                f"Expected lock conflict (exit 3), got "
                f"{result.returncode}: {result.stderr}")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
            try:
                os.remove(lockfile)
            except FileNotFoundError:
                pass

    def test_lock_released_after_completion(self):
        """Lock should be released after job completes, allowing next run."""
        # First run
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            "node-us-east1-a-1",
        )
        assert result.returncode == 0

        # Clean state for second run
        for f in ["/app/scp_jobs.db", "/app/cluster_state.json",
                  "/app/execution_log.jsonl"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

        # Second run should succeed (lock was released)
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            "node-us-east1-a-1",
        )
        assert result.returncode == 0, (
            f"Second run failed (lock not released?): {result.stderr}")


class TestCrashRecovery:
    """Verify reconciliation of orphaned in_progress tasks on resume."""

    def test_orphaned_task_reconciled_from_node_state(self):
        """Tasks left in_progress after crash should be reconciled by
        probing actual node state, not blindly re-executed."""
        # Run single node, interrupt after 2 tasks (drain + stop_service)
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            "node-us-east1-a-1",
            "--interrupt-after",
            "2",
        )
        assert result.returncode == 2, (
            f"Expected interrupted (exit 2), got {result.returncode}")

        db = get_job_db()
        cursor = db.execute(
            "SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT 1")
        job_id = cursor.fetchone()[0]

        # Verify 2 completed tasks
        cursor = db.execute(
            "SELECT COUNT(*) FROM task_executions "
            "WHERE job_id = ? AND status = 'completed'",
            (job_id,))
        assert cursor.fetchone()[0] == 2

        # Simulate crash: change completed 'drain' to 'in_progress'.
        # The drain actually completed (simulator state: drained=True),
        # so crash recovery should detect this and mark it completed.
        db.execute(
            "UPDATE task_executions SET status = 'in_progress' "
            "WHERE job_id = ? AND node_name = 'node-us-east1-a-1' "
            "AND task_name = 'drain'",
            (job_id,))
        db.commit()
        db.close()

        # Clear execution log for clean tracking
        try:
            os.remove("/app/execution_log.jsonl")
        except FileNotFoundError:
            pass

        # Resume should reconcile the orphan and complete the job
        result = run_scp("resume", job_id)
        assert result.returncode == 0, (
            f"Resume failed: {result.stderr}")

        # Verify all 4 tasks completed
        db = get_job_db()
        cursor = db.execute(
            "SELECT COUNT(*) FROM task_executions "
            "WHERE job_id = ? AND status = 'completed'",
            (job_id,))
        assert cursor.fetchone()[0] == 4, (
            "All 4 tasks should be completed after resume")

        # Verify drain was NOT re-executed (reconciled from state)
        log = get_execution_log()
        drain_events = [
            e for e in log
            if e["action"] == "drain"
            and e["node"] == "node-us-east1-a-1"
        ]
        assert len(drain_events) == 0, (
            "Drain should not have been re-executed; crash recovery "
            "should have reconciled it from simulator state")

        cursor = db.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (job_id,))
        assert cursor.fetchone()[0] == "completed"
        db.close()

    def test_indeterminate_action_reset_to_pending(self):
        """Actions with no observable state (run_cleanup) should be
        reset to pending and re-executed on resume."""
        # Run parallel_cleanup, interrupt after 2 tasks
        result = run_scp(
            "run",
            "/app/workflows/parallel_cleanup.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            "node-us-east1-a-1",
            "--interrupt-after",
            "1",
        )
        assert result.returncode == 2

        db = get_job_db()
        cursor = db.execute(
            "SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT 1")
        job_id = cursor.fetchone()[0]

        # Simulate crash: change completed run_cleanup to in_progress
        db.execute(
            "UPDATE task_executions SET status = 'in_progress' "
            "WHERE job_id = ? AND node_name = 'node-us-east1-a-1' "
            "AND task_name = 'run_cleanup'",
            (job_id,))
        db.commit()
        db.close()

        try:
            os.remove("/app/execution_log.jsonl")
        except FileNotFoundError:
            pass

        # Resume — run_cleanup is indeterminate, should be re-executed
        result = run_scp("resume", job_id)
        assert result.returncode == 0

        log = get_execution_log()
        cleanup_events = [
            e for e in log
            if e["action"] == "run_cleanup"
            and e["node"] == "node-us-east1-a-1"
        ]
        assert len(cleanup_events) > 0, (
            "run_cleanup should be re-executed (indeterminate state)")


class TestDiagnostics:
    """Verify the diagnose subcommand uses sqlite3 CLI and jq."""

    def test_diagnose_report_structure(self):
        """Diagnose should produce valid JSON with expected structure."""
        # Run a workflow to create state
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            "node-us-east1-a-1",
        )
        assert result.returncode == 0

        # Run diagnose
        result = run_scp(
            "diagnose",
            "--db", "/app/scp_jobs.db",
            "--log", "/app/execution_log.jsonl",
        )
        assert result.returncode == 0, (
            f"Diagnose failed: {result.stderr}")

        report = json.loads(result.stdout)

        # Verify integrity check (via sqlite3 CLI)
        assert report["integrity_check"] == "ok", (
            f"integrity_check should be 'ok', got '{report['integrity_check']}'")

        # Verify job summary (via sqlite3 CLI)
        assert isinstance(report["job_summary"], list)
        assert len(report["job_summary"]) >= 1, (
            "job_summary should have at least one entry")
        job = report["job_summary"][0]
        assert "job_id" in job
        assert "workflow_name" in job
        assert "status" in job

        # Verify task summary (via sqlite3 CLI)
        assert isinstance(report["task_summary"], list)
        assert len(report["task_summary"]) >= 1, (
            "task_summary should have at least one entry")
        task = report["task_summary"][0]
        assert "task_name" in task
        assert "status" in task
        assert "count" in task

        # Verify latency analysis (via jq)
        assert isinstance(report["latency_analysis"], list)
        assert len(report["latency_analysis"]) >= 1, (
            "latency_analysis should have at least one entry")
        lat = report["latency_analysis"][0]
        assert "action" in lat
        assert "operation_count" in lat
        assert "error_count" in lat

    def test_diagnose_counts_operations_correctly(self):
        """Latency analysis should correctly count operations and errors."""
        result = run_scp(
            "run",
            "/app/workflows/rolling_restart.yaml",
            "--cluster",
            "/app/cluster.json",
            "--target-nodes",
            "node-us-east1-a-1,node-us-east1-a-2",
        )
        assert result.returncode == 0

        result = run_scp(
            "diagnose",
            "--db", "/app/scp_jobs.db",
            "--log", "/app/execution_log.jsonl",
        )
        report = json.loads(result.stdout)

        # Find drain analysis
        drain_analysis = [
            a for a in report["latency_analysis"]
            if a["action"] == "drain"
        ]
        assert len(drain_analysis) == 1, "Should have drain analysis"
        # node-a-1 succeeds first try (1 end), node-a-2 fails then succeeds
        # (1 error + 1 end) = 2 ends total, 1 error
        assert drain_analysis[0]["operation_count"] == 2, (
            f"Expected 2 drain operations, got "
            f"{drain_analysis[0]['operation_count']}")
        assert drain_analysis[0]["error_count"] == 1, (
            f"Expected 1 drain error (node-a-2), got "
            f"{drain_analysis[0]['error_count']}")
