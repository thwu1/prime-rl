
"""
Tests for the fixed Flux multi-queue cluster configuration.
Validates results produced by validate.sh running inside a Flux instance.
"""

import json
import os
import pytest

RESULTS_DIR = "/tmp/flux-results"

# Expected rank-to-queue mapping:
#   debug: ranks 0-1
#   batch: ranks 2-5
#   gpu:   ranks 6-7
DEBUG_RANKS = {0, 1}
BATCH_RANKS = {2, 3, 4, 5}
GPU_RANKS = {6, 7}


def read_result(filename):
    """Read a result file, return None if missing."""
    path = os.path.join(RESULTS_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read().strip()


def read_json(filename):
    """Read and parse a JSON result file."""
    content = read_result(filename)
    if content is None or content == "SUBMIT_FAILED":
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def get_ranks_from_R(R_json):
    """Extract the set of ranks from an RFC 20 R (version 1) JSON object."""
    ranks = set()
    r_lite = R_json.get("execution", {}).get("R_lite", [])
    for entry in r_lite:
        rank_str = str(entry.get("rank", ""))
        for part in rank_str.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                ranks.update(range(int(start), int(end) + 1))
            else:
                ranks.add(int(part))
    return ranks


# ---- Core tests ----

class TestConfigApplied:
    """Verify the configuration was successfully parsed and applied."""

    def test_apply_config_succeeded(self):
        rc = read_result("apply_config_rc.txt")
        assert rc is not None, \
            "apply_config_rc.txt missing — apply_config.py may not have run"
        assert rc == "0", \
            f"apply_config.py failed (rc={rc}) — check apply_config.log for details"


class TestFluxStarted:
    """Verify the Flux instance started and queues are configured."""

    def test_queue_status_captured(self):
        status = read_result("queue_status.txt")
        assert status is not None, \
            "Queue status not captured — Flux likely failed to start with the config"

    def test_queue_status_success(self):
        rc = read_result("queue_status_rc.txt")
        assert rc is not None and rc == "0", \
            "flux queue status returned non-zero — config may have errors"


class TestQueuesExist:
    """Verify all three queues are configured."""

    def test_debug_queue_exists(self):
        status = read_result("queue_status.txt")
        assert status is not None
        assert "debug" in status.lower(), "Debug queue not found in queue status"

    def test_batch_queue_exists(self):
        status = read_result("queue_status.txt")
        assert status is not None
        assert "batch" in status.lower(), "Batch queue not found in queue status"

    def test_gpu_queue_exists(self):
        status = read_result("queue_status.txt")
        assert status is not None
        assert "gpu" in status.lower(), "GPU queue not found in queue status"


class TestResourceIsolation:
    """Verify jobs in each queue run only on their designated ranks."""

    def test_debug_job_runs_on_debug_ranks(self):
        R = read_json("debug_R.json")
        assert R is not None, \
            "Debug job R not captured — job submission or scheduling may have failed"
        ranks = get_ranks_from_R(R)
        assert len(ranks) > 0, "No ranks found in debug job allocation"
        assert ranks.issubset(DEBUG_RANKS), \
            f"Debug job allocated to ranks {ranks}, expected subset of {DEBUG_RANKS}"

    def test_batch_job_runs_on_batch_ranks(self):
        R = read_json("batch_R.json")
        assert R is not None, \
            "Batch job R not captured — job submission or scheduling may have failed"
        ranks = get_ranks_from_R(R)
        assert len(ranks) > 0, "No ranks found in batch job allocation"
        assert ranks.issubset(BATCH_RANKS), \
            f"Batch job allocated to ranks {ranks}, expected subset of {BATCH_RANKS}"

    def test_gpu_job_runs_on_gpu_ranks(self):
        R = read_json("gpu_R.json")
        assert R is not None, \
            "GPU job R not captured — job submission or scheduling may have failed"
        ranks = get_ranks_from_R(R)
        assert len(ranks) > 0, "No ranks found in GPU job allocation"
        assert ranks.issubset(GPU_RANKS), \
            f"GPU job allocated to ranks {ranks}, expected subset of {GPU_RANKS}"


class TestDefaultQueue:
    """Verify the default queue is 'batch'."""

    def test_default_queue_is_batch(self):
        jobspec = read_json("default_jobspec.json")
        assert jobspec is not None, \
            "Default job jobspec not captured — submission without -q may have failed"
        queue = jobspec.get("attributes", {}).get("system", {}).get("queue", "")
        assert queue == "batch", \
            f"Default queue is '{queue}', expected 'batch'"

    def test_default_job_runs_on_batch_ranks(self):
        R = read_json("default_R.json")
        assert R is not None, \
            "Default job R not captured — job may not have been scheduled"
        ranks = get_ranks_from_R(R)
        assert len(ranks) > 0, "No ranks found in default job allocation"
        assert ranks.issubset(BATCH_RANKS), \
            f"Default job allocated to ranks {ranks}, expected subset of {BATCH_RANKS}"


class TestAllNodesAvailable:
    """Verify no nodes are excluded — all nodes in each group are schedulable."""

    def test_all_debug_nodes(self):
        rc = read_result("debug_multi_rc.txt")
        assert rc is not None, "Debug multi-node test did not run"
        assert rc == "0", \
            "2-node debug job failed — a debug node may be excluded or missing"
        R = read_json("debug_multi_R.json")
        assert R is not None, \
            "Debug multi-node job R not captured — allocation may have failed"
        ranks = get_ranks_from_R(R)
        assert ranks == DEBUG_RANKS, \
            f"Debug multi-node job got ranks {ranks}, expected {DEBUG_RANKS}"

    def test_all_batch_nodes(self):
        rc = read_result("batch_multi_rc.txt")
        assert rc is not None, "Batch multi-node test did not run"
        assert rc == "0", \
            "4-node batch job failed — a batch node may be excluded or missing"
        R = read_json("batch_multi_R.json")
        assert R is not None, \
            "Batch multi-node job R not captured — allocation may have failed"
        ranks = get_ranks_from_R(R)
        assert ranks == BATCH_RANKS, \
            f"Batch multi-node job got ranks {ranks}, expected {BATCH_RANKS}"

    def test_all_gpu_nodes(self):
        rc = read_result("gpu_multi_rc.txt")
        assert rc is not None, "GPU multi-node test did not run"
        assert rc == "0", \
            "2-node GPU job failed — a GPU node may be excluded or missing"
        R = read_json("gpu_multi_R.json")
        assert R is not None, \
            "GPU multi-node job R not captured — allocation may have failed"
        ranks = get_ranks_from_R(R)
        assert ranks == GPU_RANKS, \
            f"GPU multi-node job got ranks {ranks}, expected {GPU_RANKS}"


class TestQueueIndependence:
    """Verify disabling one queue does not affect others."""

    def test_batch_works_after_debug_disabled(self):
        rc = read_result("batch_after_debug_disable_rc.txt")
        assert rc is not None, "Queue independence test did not run"
        assert rc == "0", \
            "Batch job submission failed after disabling debug queue — queues not independent"


class TestConsistentIsolation:
    """Verify resource isolation holds across multiple job submissions."""

    def test_repeated_debug_jobs_on_debug_ranks(self):
        content = read_result("debug_R_repeat.jsonl")
        assert content is not None and content != "", \
            "Repeated debug job results not captured"
        for i, line in enumerate(content.strip().split("\n")):
            line = line.strip()
            if not line:
                continue
            R = json.loads(line)
            ranks = get_ranks_from_R(R)
            assert ranks.issubset(DEBUG_RANKS), \
                f"Debug job #{i+1} allocated to ranks {ranks}, " \
                f"expected subset of {DEBUG_RANKS}"

    def test_repeated_batch_jobs_on_batch_ranks(self):
        content = read_result("batch_R_repeat.jsonl")
        assert content is not None and content != "", \
            "Repeated batch job results not captured"
        for i, line in enumerate(content.strip().split("\n")):
            line = line.strip()
            if not line:
                continue
            R = json.loads(line)
            ranks = get_ranks_from_R(R)
            assert ranks.issubset(BATCH_RANKS), \
                f"Batch job #{i+1} allocated to ranks {ranks}, " \
                f"expected subset of {BATCH_RANKS}"
