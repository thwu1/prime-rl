"""
Tests for the zone-aware workflow orchestration engine.

Verifies: execution ordering, zone-aware concurrency, concurrency limits,
precondition polling with success windows, crash recovery / resumability,
error classification with retries, template variables, node targeting,
SQLite persistence, and multi-phase workflow execution.
"""

import asyncio
import json
import os
import sys
import time
import sqlite3
import pytest

sys.path.insert(0, "/app")

import yaml
from orchestrator import WorkflowEngine, TaskRegistry, TaskResult, ErrorKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_cluster(nodes_per_zone=2, zones=None):
    if zones is None:
        zones = ["us-east1-b", "us-east1-c", "us-east1-d"]
    nodes = []
    for zone in zones:
        zone_short = zone.split("-")[-1]
        for i in range(1, nodes_per_zone + 1):
            nodes.append({"name": f"node-{zone_short}-{i}", "zone": zone})
    return {"name": "test-cluster", "nodes": nodes}


def write_workflow(tmpdir, workflow_dict):
    path = os.path.join(str(tmpdir), "workflow.yaml")
    with open(path, "w") as f:
        yaml.dump(workflow_dict, f, default_flow_style=False)
    return path


# =====================================================================
# 1. Basic sequential execution
# =====================================================================
class TestBasicExecution:
    @pytest.mark.asyncio
    async def test_all_tasks_run_in_order(self, tmp_path):
        """Every node must have all its tasks executed in sequence."""
        log = []

        registry = TaskRegistry()

        @registry.register("drain")
        async def drain_h(node, params, ctx):
            log.append(("drain", node["name"]))
            return TaskResult.ok()

        @registry.register("restart")
        async def restart_h(node, params, ctx):
            log.append(("restart", node["name"]))
            return TaskResult.ok()

        workflow = {
            "name": "basic test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "drain and restart",
                    "concurrency_unit": "all",
                    "concurrency_limit": 100,
                    "node_tasks": [
                        {"type": "drain"},
                        {"type": "restart"},
                    ],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a", "zone-b"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        assert len(log) == 4  # 2 nodes * 2 tasks

        for node_name in ["node-a-1", "node-b-1"]:
            node_log = [(t, n) for t, n in log if n == node_name]
            assert node_log == [("drain", node_name), ("restart", node_name)]


# =====================================================================
# 2. Zone-aware sequential execution
# =====================================================================
class TestZoneConcurrency:
    @pytest.mark.asyncio
    async def test_zones_processed_sequentially(self, tmp_path):
        """With concurrency_unit=zone, tasks in different zones must
        never overlap in time."""
        log = []  # (node, zone, start, end)

        registry = TaskRegistry()

        @registry.register("slow_task")
        async def slow_h(node, params, ctx):
            start = time.monotonic()
            await asyncio.sleep(0.05)
            end = time.monotonic()
            log.append((node["name"], node["zone"], start, end))
            return TaskResult.ok()

        workflow = {
            "name": "zone test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "zone-aware",
                    "concurrency_unit": "zone",
                    "concurrency_limit": 10,
                    "node_tasks": [{"type": "slow_task"}],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=2, zones=["zone-a", "zone-b", "zone-c"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        assert len(log) == 6

        eps = 0.002
        for i in range(len(log)):
            for j in range(i + 1, len(log)):
                n1, z1, s1, e1 = log[i]
                n2, z2, s2, e2 = log[j]
                if z1 != z2:
                    overlaps = not (e1 <= s2 + eps or e2 <= s1 + eps)
                    assert not overlaps, (
                        f"Cross-zone overlap: {n1}@{z1} [{s1:.4f}-{e1:.4f}] "
                        f"vs {n2}@{z2} [{s2:.4f}-{e2:.4f}]"
                    )


# =====================================================================
# 3. Concurrency limit within a batch
# =====================================================================
class TestConcurrencyLimit:
    @pytest.mark.asyncio
    async def test_respects_concurrency_limit(self, tmp_path):
        """At most concurrency_limit nodes should execute concurrently."""
        peak = {"value": 0}
        active = {"count": 0}
        lock = asyncio.Lock()

        registry = TaskRegistry()

        @registry.register("counted")
        async def counted_h(node, params, ctx):
            async with lock:
                active["count"] += 1
                peak["value"] = max(peak["value"], active["count"])
            await asyncio.sleep(0.05)
            async with lock:
                active["count"] -= 1
            return TaskResult.ok()

        workflow = {
            "name": "limit test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "limited",
                    "concurrency_unit": "all",
                    "concurrency_limit": 2,
                    "node_tasks": [{"type": "counted"}],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=4, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        assert peak["value"] <= 2, (
            f"Concurrency limit violated: peak={peak['value']}"
        )
        assert peak["value"] == 2, (
            f"Concurrency not utilized: peak={peak['value']}"
        )


# =====================================================================
# 4. Precondition polling
# =====================================================================
class TestPreconditions:
    @pytest.mark.asyncio
    async def test_condition_polling(self, tmp_path):
        """wait_for_condition must poll until the condition passes."""
        polls = {"count": 0}
        pass_after = 3

        registry = TaskRegistry()

        @registry.register("condition:node_healthy")
        async def health_h(node, params, ctx):
            polls["count"] += 1
            if polls["count"] > pass_after:
                return TaskResult.ok()
            return TaskResult.fail(ErrorKind.RECOVERABLE, "not healthy")

        @registry.register("noop")
        async def noop_h(node, params, ctx):
            return TaskResult.ok()

        workflow = {
            "name": "condition test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "wait",
                    "concurrency_unit": "all",
                    "concurrency_limit": 1,
                    "node_tasks": [
                        {
                            "type": "wait_for_condition",
                            "condition": "node_healthy",
                            "params": {
                                "timeout_seconds": 10,
                                "poll_interval_seconds": 0.05,
                                "success_window_seconds": 0,
                            },
                        },
                        {"type": "noop"},
                    ],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        assert polls["count"] > pass_after

    @pytest.mark.asyncio
    async def test_condition_timeout(self, tmp_path):
        """A condition that never passes must time out and fail."""
        registry = TaskRegistry()

        @registry.register("condition:never_ready")
        async def never_h(node, params, ctx):
            return TaskResult.fail(ErrorKind.RECOVERABLE, "nope")

        workflow = {
            "name": "timeout test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "doomed",
                    "concurrency_unit": "all",
                    "concurrency_limit": 1,
                    "node_tasks": [
                        {
                            "type": "wait_for_condition",
                            "condition": "never_ready",
                            "params": {
                                "timeout_seconds": 0.3,
                                "poll_interval_seconds": 0.05,
                                "success_window_seconds": 0,
                            },
                        }
                    ],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "failed"


# =====================================================================
# 5. Condition success window
# =====================================================================
class TestConditionSuccessWindow:
    @pytest.mark.asyncio
    async def test_success_window_resets_on_blip(self, tmp_path):
        """The success window must reset when a condition poll fails
        after previously passing."""
        polls = {"count": 0}

        registry = TaskRegistry()

        @registry.register("condition:flaky")
        async def flaky_h(node, params, ctx):
            polls["count"] += 1
            n = polls["count"]
            # fail first 2, pass 3-4, blip on 5, then pass continuously
            if n <= 2:
                return TaskResult.fail(ErrorKind.RECOVERABLE, "warmup")
            if n == 5:
                return TaskResult.fail(ErrorKind.RECOVERABLE, "blip")
            return TaskResult.ok()

        workflow = {
            "name": "window test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "flaky",
                    "concurrency_unit": "all",
                    "concurrency_limit": 1,
                    "node_tasks": [
                        {
                            "type": "wait_for_condition",
                            "condition": "flaky",
                            "params": {
                                "timeout_seconds": 5,
                                "poll_interval_seconds": 0.03,
                                "success_window_seconds": 0.1,
                            },
                        }
                    ],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        # Must have polled beyond the blip at poll 5
        assert polls["count"] > 5


# =====================================================================
# 6. Resumability — same engine
# =====================================================================
class TestResumability:
    @pytest.mark.asyncio
    async def test_resume_skips_completed_tasks(self, tmp_path):
        """Resuming a failed job skips completed tasks."""
        log = []
        attempts = {}

        registry = TaskRegistry()

        @registry.register("tracked")
        async def tracked_h(node, params, ctx):
            key = node["name"]
            attempts[key] = attempts.get(key, 0) + 1
            log.append(key)
            if key == "node-b-1" and attempts[key] == 1:
                return TaskResult.fail(ErrorKind.UNRECOVERABLE, "boom")
            return TaskResult.ok()

        workflow = {
            "name": "resume test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "work",
                    "concurrency_unit": "zone",
                    "concurrency_limit": 1,
                    "node_tasks": [{"type": "tracked"}],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(
            nodes_per_zone=1, zones=["zone-a", "zone-b", "zone-c"]
        )

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)

        result = await engine.run_job(job_id)
        assert result["status"] == "failed"
        assert "node-a-1" in log
        assert "node-b-1" in log

        log.clear()
        result = await engine.resume_job(job_id)
        assert result["status"] == "completed"
        assert "node-a-1" not in log  # already completed, must not re-run
        assert "node-b-1" in log
        assert "node-c-1" in log

    @pytest.mark.asyncio
    async def test_resume_across_engine_restart(self, tmp_path):
        """A new engine instance must resume jobs from SQLite state."""
        log = []
        attempts = {}

        registry = TaskRegistry()

        @registry.register("tracked")
        async def tracked_h(node, params, ctx):
            key = node["name"]
            attempts[key] = attempts.get(key, 0) + 1
            log.append(key)
            if key == "node-b-1" and attempts[key] == 1:
                return TaskResult.fail(ErrorKind.UNRECOVERABLE, "crash")
            return TaskResult.ok()

        workflow = {
            "name": "cross-engine resume",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "work",
                    "concurrency_unit": "zone",
                    "concurrency_limit": 1,
                    "node_tasks": [{"type": "tracked"}],
                }
            ],
        }

        db_path = str(tmp_path / "resume.db")
        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(
            nodes_per_zone=1, zones=["zone-a", "zone-b", "zone-c"]
        )

        engine1 = WorkflowEngine(db_path=db_path, registry=registry)
        wf = engine1.load_workflow(wf_path)
        job_id = engine1.create_job(wf, cluster)
        result = await engine1.run_job(job_id)
        assert result["status"] == "failed"
        del engine1

        log.clear()
        engine2 = WorkflowEngine(db_path=db_path, registry=registry)
        result = await engine2.resume_job(job_id)
        assert result["status"] == "completed"
        assert "node-a-1" not in log
        assert "node-b-1" in log
        assert "node-c-1" in log


# =====================================================================
# 7. Recoverable error with retry
# =====================================================================
class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_recoverable_retry(self, tmp_path):
        """Recoverable failures must be retried up to the limit."""
        calls = {"count": 0}

        registry = TaskRegistry()

        @registry.register("flaky")
        async def flaky_h(node, params, ctx):
            calls["count"] += 1
            if calls["count"] < 3:
                return TaskResult.fail(ErrorKind.RECOVERABLE, "transient")
            return TaskResult.ok()

        workflow = {
            "name": "retry test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "retry",
                    "concurrency_unit": "all",
                    "concurrency_limit": 1,
                    "node_tasks": [{"type": "flaky", "retries": 5}],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        assert calls["count"] == 3

    @pytest.mark.asyncio
    async def test_unrecoverable_halts_job(self, tmp_path):
        """Unrecoverable error must halt the job; later tasks must not run."""
        log = []

        registry = TaskRegistry()

        @registry.register("fatal")
        async def fatal_h(node, params, ctx):
            log.append(("fatal", node["name"]))
            return TaskResult.fail(ErrorKind.UNRECOVERABLE, "corrupt")

        @registry.register("after")
        async def after_h(node, params, ctx):
            log.append(("after", node["name"]))
            return TaskResult.ok()

        workflow = {
            "name": "halt test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "halting",
                    "concurrency_unit": "all",
                    "concurrency_limit": 1,
                    "node_tasks": [
                        {"type": "fatal"},
                        {"type": "after"},
                    ],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "failed"
        assert ("after", "node-a-1") not in log

    @pytest.mark.asyncio
    async def test_exception_treated_as_recoverable(self, tmp_path):
        """Handler exceptions must be caught and treated as recoverable."""
        calls = {"count": 0}

        registry = TaskRegistry()

        @registry.register("crashy")
        async def crashy_h(node, params, ctx):
            calls["count"] += 1
            if calls["count"] < 2:
                raise RuntimeError("boom")
            return TaskResult.ok()

        workflow = {
            "name": "exception test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "exc",
                    "concurrency_unit": "all",
                    "concurrency_limit": 1,
                    "node_tasks": [{"type": "crashy", "retries": 3}],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        assert calls["count"] == 2


# =====================================================================
# 8. Template variables
# =====================================================================
class TestTemplateVariables:
    @pytest.mark.asyncio
    async def test_variable_substitution_and_defaults(self, tmp_path):
        """Template vars must be substituted; defaults used when
        no override is provided."""
        captured = {}

        registry = TaskRegistry()

        @registry.register("parameterized")
        async def param_h(node, params, ctx):
            captured[node["name"]] = dict(params)
            return TaskResult.ok()

        workflow = {
            "name": "var test",
            "variables": [
                {"name": "svc", "default": "scylla-server"},
                {"name": "timeout", "default": 60},
            ],
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "param",
                    "concurrency_unit": "all",
                    "concurrency_limit": 1,
                    "node_tasks": [
                        {
                            "type": "parameterized",
                            "params": {
                                "service": "{{svc}}",
                                "wait": "{{timeout}}",
                            },
                        }
                    ],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)

        # --- with overrides ---
        job1 = engine.create_job(
            wf, cluster, variables={"svc": "postgres", "timeout": "120"}
        )
        r1 = await engine.run_job(job1)
        assert r1["status"] == "completed"
        assert captured["node-a-1"]["service"] == "postgres"
        assert captured["node-a-1"]["wait"] == "120"

        # --- defaults only ---
        captured.clear()
        job2 = engine.create_job(wf, cluster)
        r2 = await engine.run_job(job2)
        assert r2["status"] == "completed"
        assert captured["node-a-1"]["service"] == "scylla-server"
        assert str(captured["node-a-1"]["wait"]) == "60"


# =====================================================================
# 9. Node targeting
# =====================================================================
class TestNodeTargeting:
    @pytest.mark.asyncio
    async def test_target_specific_nodes(self, tmp_path):
        """Only targeted nodes should be processed."""
        log = []

        registry = TaskRegistry()

        @registry.register("targeted")
        async def targeted_h(node, params, ctx):
            log.append(node["name"])
            return TaskResult.ok()

        workflow = {
            "name": "targeting",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "pick",
                    "concurrency_unit": "all",
                    "concurrency_limit": 10,
                    "node_tasks": [{"type": "targeted"}],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=2, zones=["zone-a", "zone-b"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(
            wf, cluster, target_nodes=["node-a-1", "node-b-2"]
        )
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        assert set(log) == {"node-a-1", "node-b-2"}


# =====================================================================
# 10. SQLite persistence across engine restart
# =====================================================================
class TestSQLitePersistence:
    @pytest.mark.asyncio
    async def test_state_survives_engine_restart(self, tmp_path):
        """Job state must persist in SQLite and be readable by a
        fresh engine instance."""
        registry = TaskRegistry()

        @registry.register("persist")
        async def persist_h(node, params, ctx):
            return TaskResult.ok()

        workflow = {
            "name": "persistence",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "persist",
                    "concurrency_unit": "all",
                    "concurrency_limit": 10,
                    "node_tasks": [{"type": "persist"}],
                }
            ],
        }

        db_path = str(tmp_path / "persist.db")
        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a", "zone-b"])

        engine = WorkflowEngine(db_path=db_path, registry=registry)
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)
        assert result["status"] == "completed"
        del engine

        engine2 = WorkflowEngine(db_path=db_path, registry=registry)
        status = engine2.get_job_status(job_id)
        assert status is not None
        assert status["job_status"] == "completed"
        assert len(status["tasks"]) == 2
        assert all(t["status"] == "completed" for t in status["tasks"])


# =====================================================================
# 11. Multiple cluster_tasks run in order
# =====================================================================
class TestMultipleClusterTasks:
    @pytest.mark.asyncio
    async def test_cluster_tasks_sequential(self, tmp_path):
        """Distinct cluster_tasks must execute in definition order."""
        log = []

        registry = TaskRegistry()

        @registry.register("phase1")
        async def p1_h(node, params, ctx):
            log.append(("phase1", node["name"]))
            return TaskResult.ok()

        @registry.register("phase2")
        async def p2_h(node, params, ctx):
            log.append(("phase2", node["name"]))
            return TaskResult.ok()

        workflow = {
            "name": "multi-phase",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "phase 1",
                    "concurrency_unit": "all",
                    "concurrency_limit": 10,
                    "node_tasks": [{"type": "phase1"}],
                },
                {
                    "type": "node_workflow",
                    "name": "phase 2",
                    "concurrency_unit": "all",
                    "concurrency_limit": 10,
                    "node_tasks": [{"type": "phase2"}],
                },
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a", "zone-b"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "completed"
        p1_idx = [i for i, (t, _) in enumerate(log) if t == "phase1"]
        p2_idx = [i for i, (t, _) in enumerate(log) if t == "phase2"]
        assert max(p1_idx) < min(p2_idx)


# =====================================================================
# 12. Retry exhaustion
# =====================================================================
class TestRetryExhaustion:
    @pytest.mark.asyncio
    async def test_exhausted_retries_fail_job(self, tmp_path):
        """When all retries are exhausted the job must fail.
        Total attempts = 1 initial + retries."""
        calls = {"count": 0}

        registry = TaskRegistry()

        @registry.register("always_fail")
        async def af_h(node, params, ctx):
            calls["count"] += 1
            return TaskResult.fail(ErrorKind.RECOVERABLE, "broken")

        workflow = {
            "name": "exhaust test",
            "cluster_tasks": [
                {
                    "type": "node_workflow",
                    "name": "doomed",
                    "concurrency_unit": "all",
                    "concurrency_limit": 1,
                    "node_tasks": [{"type": "always_fail", "retries": 3}],
                }
            ],
        }

        wf_path = write_workflow(tmp_path, workflow)
        cluster = make_cluster(nodes_per_zone=1, zones=["zone-a"])

        engine = WorkflowEngine(
            db_path=str(tmp_path / "test.db"), registry=registry
        )
        wf = engine.load_workflow(wf_path)
        job_id = engine.create_job(wf, cluster)
        result = await engine.run_job(job_id)

        assert result["status"] == "failed"
        assert calls["count"] == 4  # 1 initial + 3 retries
