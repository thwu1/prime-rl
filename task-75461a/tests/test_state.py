"""
Tests for Flux multi-queue scheduling configuration.

These tests execute inside a Flux instance started with the agent's
TOML configuration. A session-scoped fixture handles queue startup
and drain state application before scheduling tests run.
"""

import subprocess
import os
import time
import pytest
import toml

CONFIG_PATH = "/app/flux_config/system.toml"


def flux_cmd(args, timeout=30):
    """Run a command and return the CompletedProcess."""
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout
    )


def submit_and_wait(queue=None, ntasks=1, nnodes=None, duration="1m"):
    """Submit a job, wait for clean, return (job_id, ranks).

    All submissions include an explicit duration to satisfy queue
    policy limits (batch=8h, highmem=48h, gpu=4h).
    """
    cmd = ["flux", "submit"]
    if queue:
        cmd.extend(["-q", queue])
    if nnodes:
        cmd.extend(["-N", str(nnodes)])
    cmd.extend(["-t", duration, "-n", str(ntasks), "true"])

    r = flux_cmd(cmd)
    assert r.returncode == 0, f"Submit failed: {r.stderr}"
    job_id = r.stdout.strip()

    r = flux_cmd(
        ["flux", "job", "wait-event", "--timeout=30", job_id, "clean"],
        timeout=35,
    )
    assert r.returncode == 0, f"Wait-event clean failed for {job_id}: {r.stderr}"

    r = flux_cmd(["flux", "jobs", "-no", "{ranks}", job_id])
    ranks = r.stdout.strip() if r.returncode == 0 else ""
    return job_id, ranks


# ------------------------------------------------------------------
# Session fixture: start queues and drain nodes
# ------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def setup_flux_instance():
    """Start all queues and apply drain states as per cluster spec."""
    # Named queues are stopped (scheduling paused) by default on config load.
    r = flux_cmd(["flux", "queue", "start", "--all"])
    assert r.returncode == 0, f"flux queue start --all failed: {r.stderr}"

    # Drain ranks 5 and 7 (rank 3 is excluded via config, not drained)
    r = flux_cmd([
        "flux", "resource", "drain", "5",
        "Memory ECC error rate exceeded threshold",
    ])
    assert r.returncode == 0, f"drain rank 5 failed: {r.stderr}"

    r = flux_cmd([
        "flux", "resource", "drain", "7",
        "GPU thermal throttling detected",
    ])
    assert r.returncode == 0, f"drain rank 7 failed: {r.stderr}"

    # Allow state to propagate
    time.sleep(1)
    yield


# ==================================================================
# CONFIGURATION STRUCTURE TESTS
# ==================================================================

class TestConfigStructure:
    """Validate the TOML configuration file structure and semantics."""

    def _load(self):
        return toml.load(CONFIG_PATH)

    # --- file-level checks ---

    def test_config_file_exists(self):
        assert os.path.exists(CONFIG_PATH), "system.toml not found"

    def test_config_is_valid_toml(self):
        cfg = self._load()
        assert isinstance(cfg, dict), "TOML did not parse to a dict"

    # --- resource section ---

    def test_resource_section_exists(self):
        cfg = self._load()
        assert "resource" in cfg, "Missing [resource] section"

    def test_resource_config_array(self):
        cfg = self._load()
        entries = cfg["resource"].get("config", [])
        assert len(entries) >= 3, (
            f"Expected >= 3 [[resource.config]] entries, got {len(entries)}"
        )

    def test_resource_noverify_enabled(self):
        cfg = self._load()
        res = cfg.get("resource", {})
        noverify = res.get("noverify", False)
        verify_off = res.get("verify") is False
        assert noverify or verify_off, (
            "resource.noverify must be true or resource.verify must be false"
        )

    def test_resource_exclude_rank3(self):
        cfg = self._load()
        exclude = str(cfg.get("resource", {}).get("exclude", ""))
        assert "3" in exclude, (
            f"resource.exclude must include rank 3, got: '{exclude}'"
        )

    def test_property_batch_defined(self):
        cfg = self._load()
        entries = cfg["resource"]["config"]
        found = any("batch" in e.get("properties", []) for e in entries)
        assert found, "No resource.config entry has property 'batch'"

    def test_property_highmem_defined(self):
        cfg = self._load()
        entries = cfg["resource"]["config"]
        found = any("highmem" in e.get("properties", []) for e in entries)
        assert found, "No resource.config entry has property 'highmem'"

    def test_property_gpu_defined(self):
        cfg = self._load()
        entries = cfg["resource"]["config"]
        found = any("gpu" in e.get("properties", []) for e in entries)
        assert found, "No resource.config entry has property 'gpu'"

    # --- queue section ---

    def test_queues_section_exists(self):
        cfg = self._load()
        assert "queues" in cfg, "Missing [queues] section"

    def test_queue_batch_defined(self):
        cfg = self._load()
        assert "batch" in cfg["queues"], "Missing [queues.batch]"

    def test_queue_highmem_defined(self):
        cfg = self._load()
        assert "highmem" in cfg["queues"], "Missing [queues.highmem]"

    def test_queue_gpu_defined(self):
        cfg = self._load()
        assert "gpu" in cfg["queues"], "Missing [queues.gpu]"

    def test_queue_batch_requires(self):
        cfg = self._load()
        req = cfg["queues"]["batch"].get("requires", [])
        assert "batch" in req, f"batch queue requires: expected 'batch', got {req}"

    def test_queue_highmem_requires(self):
        cfg = self._load()
        req = cfg["queues"]["highmem"].get("requires", [])
        assert "highmem" in req, (
            f"highmem queue requires: expected 'highmem', got {req}"
        )

    def test_queue_gpu_requires(self):
        cfg = self._load()
        req = cfg["queues"]["gpu"].get("requires", [])
        assert "gpu" in req, f"gpu queue requires: expected 'gpu', got {req}"

    # --- duration limits ---

    def test_batch_duration_limit(self):
        cfg = self._load()
        dur = cfg["queues"]["batch"].get("policy", {}).get("limits", {}).get("duration")
        assert dur == "8h", f"batch duration limit should be '8h', got '{dur}'"

    def test_highmem_duration_limit(self):
        cfg = self._load()
        dur = cfg["queues"]["highmem"].get("policy", {}).get("limits", {}).get("duration")
        assert dur == "48h", f"highmem duration limit should be '48h', got '{dur}'"

    def test_gpu_duration_limit(self):
        cfg = self._load()
        dur = cfg["queues"]["gpu"].get("policy", {}).get("limits", {}).get("duration")
        assert dur == "4h", f"gpu duration limit should be '4h', got '{dur}'"

    # --- default queue ---

    def test_default_queue_is_batch(self):
        cfg = self._load()
        try:
            dq = cfg["policy"]["jobspec"]["defaults"]["system"]["queue"]
        except (KeyError, TypeError):
            pytest.fail(
                "Default queue not set at policy.jobspec.defaults.system.queue"
            )
        assert dq == "batch", f"Default queue should be 'batch', got '{dq}'"

    # --- job-manager ---

    def test_job_manager_inactive_num_limit(self):
        cfg = self._load()
        assert "job-manager" in cfg, "Missing [job-manager] section"
        val = cfg["job-manager"].get("inactive-num-limit")
        assert val == 200, f"inactive-num-limit should be 200, got {val}"

    def test_job_manager_inactive_age_limit(self):
        cfg = self._load()
        val = cfg["job-manager"].get("inactive-age-limit")
        assert val == "2h", f"inactive-age-limit should be '2h', got {val}"


# ==================================================================
# LIVE SCHEDULING TESTS
# ==================================================================

class TestLiveScheduling:
    """Test actual scheduling behaviour in the running Flux instance."""

    def test_all_queues_visible(self):
        """flux queue list shows all three configured queues."""
        r = flux_cmd(["flux", "queue", "list"])
        assert r.returncode == 0, f"flux queue list failed: {r.stderr}"
        for q in ("batch", "highmem", "gpu"):
            assert q in r.stdout, f"Queue '{q}' missing from queue list"

    def test_drain_count_is_two(self):
        """Exactly two nodes should be in drain state (ranks 5 and 7)."""
        r = flux_cmd([
            "flux", "resource", "status", "-s", "drain", "-no", "{nnodes}",
        ])
        assert r.returncode == 0, f"resource status failed: {r.stderr}"
        count = int(r.stdout.strip()) if r.stdout.strip() else 0
        assert count == 2, f"Expected 2 drained nodes, got {count}"

    def test_exclude_count_is_one(self):
        """Exactly one node should be excluded (rank 3)."""
        r = flux_cmd([
            "flux", "resource", "status", "-s", "exclude", "-no", "{nnodes}",
        ])
        assert r.returncode == 0, f"resource status failed: {r.stderr}"
        count = int(r.stdout.strip()) if r.stdout.strip() else 0
        assert count == 1, f"Expected 1 excluded node, got {count}"

    def test_batch_job_routes_correctly(self):
        """A batch-queue job must run on ranks 0, 1, or 2 (rank 3 excluded)."""
        _, ranks = submit_and_wait(queue="batch", ntasks=1)
        assert ranks in ("0", "1", "2"), (
            f"Batch job ran on rank {ranks}, expected one of 0,1,2"
        )

    def test_highmem_job_routes_correctly(self):
        """A highmem-queue job must run on rank 4 (rank 5 drained)."""
        _, ranks = submit_and_wait(queue="highmem", ntasks=1)
        assert ranks == "4", (
            f"Highmem job ran on rank {ranks}, expected 4"
        )

    def test_gpu_job_routes_correctly(self):
        """A gpu-queue job must run on rank 6 (rank 7 drained)."""
        _, ranks = submit_and_wait(queue="gpu", ntasks=1)
        assert ranks == "6", (
            f"GPU job ran on rank {ranks}, expected 6"
        )

    def test_default_queue_routes_to_batch(self):
        """A job submitted without -q should default to batch queue."""
        _, ranks = submit_and_wait(ntasks=1)
        assert ranks in ("0", "1", "2"), (
            f"Default-queue job ran on rank {ranks}, expected batch ranks 0-2"
        )

    def test_oversized_highmem_gets_exception(self):
        """Requesting 3 highmem nodes is unsatisfiable (only 2 exist)."""
        cmd = ["flux", "submit", "-q", "highmem", "-N3", "-n3", "-t", "1m", "true"]
        r = flux_cmd(cmd)
        assert r.returncode == 0, f"Submit unexpectedly failed: {r.stderr}"
        job_id = r.stdout.strip()

        r = flux_cmd(
            ["flux", "job", "wait-event", "--timeout=15", job_id, "exception"],
            timeout=20,
        )
        assert r.returncode == 0, (
            "Expected scheduler exception for oversized highmem request"
        )

    def test_nonexistent_queue_rejected(self):
        """Submitting to an unknown queue must fail."""
        r = flux_cmd(["flux", "submit", "-q", "nonexistent", "-t", "1m", "-n1", "true"])
        assert r.returncode != 0, "Expected failure for nonexistent queue"

    def test_duration_exceeding_limit_rejected(self):
        """A job exceeding the queue's duration limit must fail."""
        # gpu queue has 4h limit; submit with 5h
        r = flux_cmd(["flux", "submit", "-q", "gpu", "-t", "5h", "-n1", "true"])
        assert r.returncode != 0, (
            "Expected rejection for duration exceeding gpu queue's 4h limit"
        )
