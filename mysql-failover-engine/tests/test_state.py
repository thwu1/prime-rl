"""
Tests for MySQL HA Failover Recovery Pipeline.

Validates correct failure classification, promotion selection, Consul KV state,
HAProxy configuration validity, and outage estimation across 5 incident scenarios.

"""

import json
import os
import subprocess
import time
import signal
import pytest

TOPOLOGIES_DIR = "/app/topologies"
OUTPUT_BASE = "/app/output"
PIPELINE = "/app/pipeline.sh"

_consul_proc = None


def _start_consul():
    global _consul_proc
    if _consul_proc is not None:
        return
    _consul_proc = subprocess.Popen(
        ["consul", "agent", "-dev", "-bind=127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            r = subprocess.run(
                ["consul", "members"],
                capture_output=True, timeout=2,
            )
            if r.returncode == 0:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("Consul agent failed to start")


def _stop_consul():
    global _consul_proc
    if _consul_proc is not None:
        _consul_proc.send_signal(signal.SIGTERM)
        try:
            _consul_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _consul_proc.kill()
        _consul_proc = None


@pytest.fixture(scope="session", autouse=True)
def consul_agent():
    _start_consul()
    yield
    _stop_consul()


def _prepopulate_consul(cluster_name, primary_host, primary_port):
    """Set the initial primary in Consul KV before running the pipeline."""
    val = json.dumps({"hostname": primary_host, "port": primary_port})
    subprocess.run(
        ["consul", "kv", "put", f"mysql/{cluster_name}/primary", val],
        check=True, capture_output=True, timeout=5,
    )


def _run_pipeline(incident_num):
    """Run the pipeline for a given incident number and return the report dict."""
    topology = f"{TOPOLOGIES_DIR}/incident_{incident_num:03d}.json"
    output_dir = f"{OUTPUT_BASE}/incident_{incident_num:03d}"
    os.makedirs(output_dir, exist_ok=True)

    with open(topology) as f:
        topo = json.load(f)
    cluster_name = topo["cluster"]["name"]

    # Find current primary to pre-populate consul
    for inst in topo["instances"]:
        if not inst["role_info"]["read_only"] and (
            inst["role_info"]["master"]["host"] == ""
            or inst["role_info"]["master"]["host"] is None
        ):
            _prepopulate_consul(
                cluster_name,
                inst["key"]["host"],
                inst["key"]["port"],
            )
            break

    result = subprocess.run(
        ["bash", PIPELINE, topology, output_dir],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Pipeline failed for incident {incident_num}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    report_path = f"{output_dir}/report.json"
    assert os.path.exists(report_path), f"Report not found at {report_path}"
    with open(report_path) as f:
        report = json.load(f)
    return report, cluster_name


# ===================================================================
# Incident 1: Classic DeadMaster with ideal same-DC candidate
# ===================================================================


class TestIncident1:

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, consul_agent):
        report, cluster = _run_pipeline(1)
        TestIncident1._report = report
        TestIncident1._cluster = cluster

    def test_failure_type(self):
        failures = self._report["failures"]
        assert len(failures) == 1
        assert failures[0]["type"] == "DeadMaster"
        assert failures[0]["actionable"] is True

    def test_failed_instance(self):
        assert self._report["failures"][0]["instance"] == "db-primary-01:3306"

    def test_recovery_attempted(self):
        assert self._report["recovery_attempted"] is True

    def test_promoted_server(self):
        assert self._report["promoted_server"] == "db-replica-01:3306"

    def test_raft_leader(self):
        assert self._report["raft_leader"] == "orch-01"

    def test_outage_estimate(self):
        # ideal (prefer + semi-sync) + same DC: 5+3+1+1 = 10
        assert self._report["estimated_outage_seconds"] == 10.0

    def test_consul_kv_updated(self):
        result = subprocess.run(
            ["consul", "kv", "get", f"mysql/{self._cluster}/primary"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0
        kv = json.loads(result.stdout.strip())
        assert kv["hostname"] == "db-replica-01"
        assert kv["port"] == 3306

    def test_haproxy_config_valid(self):
        cfg = f"{OUTPUT_BASE}/incident_001/haproxy.cfg"
        assert os.path.exists(cfg), "HAProxy config not generated"
        r = subprocess.run(
            ["haproxy", "-c", "-f", cfg],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"HAProxy config invalid: {r.stderr}"

    def test_haproxy_has_promoted_server(self):
        cfg = f"{OUTPUT_BASE}/incident_001/haproxy.cfg"
        with open(cfg) as f:
            content = f.read()
        assert "db-replica-01" in content


# ===================================================================
# Incident 2: DeadMasterAndSomeReplicas, cross-DC non-ideal candidate
# ===================================================================


class TestIncident2:

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, consul_agent):
        report, cluster = _run_pipeline(2)
        TestIncident2._report = report
        TestIncident2._cluster = cluster

    def test_failure_type(self):
        failures = self._report["failures"]
        assert len(failures) == 1
        assert failures[0]["type"] == "DeadMasterAndSomeReplicas"
        assert failures[0]["actionable"] is True

    def test_promoted_server(self):
        assert self._report["promoted_server"] == "db-replica-05:3306"

    def test_outage_estimate(self):
        # non-ideal + cross-DC: 5+10+2+2 = 19
        assert self._report["estimated_outage_seconds"] == 19.0

    def test_consul_kv_updated(self):
        result = subprocess.run(
            ["consul", "kv", "get", f"mysql/{self._cluster}/primary"],
            capture_output=True, text=True, timeout=5,
        )
        kv = json.loads(result.stdout.strip())
        assert kv["hostname"] == "db-replica-05"

    def test_haproxy_config_valid(self):
        cfg = f"{OUTPUT_BASE}/incident_002/haproxy.cfg"
        assert os.path.exists(cfg)
        r = subprocess.run(
            ["haproxy", "-c", "-f", cfg],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"HAProxy config invalid: {r.stderr}"


# ===================================================================
# Incident 3: DeadIntermediateMaster, primary healthy
# ===================================================================


class TestIncident3:

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, consul_agent):
        report, cluster = _run_pipeline(3)
        TestIncident3._report = report
        TestIncident3._cluster = cluster

    def test_im_failure_detected(self):
        failures = self._report["failures"]
        im_failures = [f for f in failures if "db-im-01" in f["instance"]]
        assert len(im_failures) == 1
        assert im_failures[0]["type"] == "DeadIntermediateMaster"
        assert im_failures[0]["actionable"] is True

    def test_no_master_failure(self):
        failures = self._report["failures"]
        master_failures = [f for f in failures if "db-primary-03" in f["instance"]]
        assert len(master_failures) == 0

    def test_recovery_attempted(self):
        assert self._report["recovery_attempted"] is True

    def test_promoted_server(self):
        # db-sub-r1 has higher GTID than db-sub-r2
        assert self._report["promoted_server"] == "db-sub-r1:3306"

    def test_outage_estimate(self):
        # non-ideal, same DC as IM (us-east-1b): 5+10+1+1 = 17
        assert self._report["estimated_outage_seconds"] == 17.0

    def test_consul_not_updated_for_im_failure(self):
        """IM failure does not change the master - Consul KV keeps original."""
        result = subprocess.run(
            ["consul", "kv", "get", f"mysql/{self._cluster}/primary"],
            capture_output=True, text=True, timeout=5,
        )
        kv = json.loads(result.stdout.strip())
        assert kv["hostname"] == "db-primary-03"


# ===================================================================
# Incident 4: LockedSemiSyncMaster blocked by anti-flapping
# ===================================================================


class TestIncident4:

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, consul_agent):
        report, cluster = _run_pipeline(4)
        TestIncident4._report = report
        TestIncident4._cluster = cluster

    def test_failure_type(self):
        failures = self._report["failures"]
        assert len(failures) == 1
        assert failures[0]["type"] == "LockedSemiSyncMaster"
        assert failures[0]["actionable"] is True

    def test_recovery_blocked(self):
        assert self._report["recovery_attempted"] is False
        reason = self._report["recovery_blocked_reason"].lower()
        assert any(w in reason for w in ["flap", "block", "period", "recent"])

    def test_no_promotion(self):
        assert self._report["promoted_server"] is None

    def test_consul_not_updated(self):
        result = subprocess.run(
            ["consul", "kv", "get", f"mysql/{self._cluster}/primary"],
            capture_output=True, text=True, timeout=5,
        )
        kv = json.loads(result.stdout.strip())
        assert kv["hostname"] == "db-primary-04"


# ===================================================================
# Incident 5: Simultaneous DeadMaster + DeadIntermediateMaster
# ===================================================================


class TestIncident5:

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, consul_agent):
        report, cluster = _run_pipeline(5)
        TestIncident5._report = report
        TestIncident5._cluster = cluster

    def test_multiple_failures_detected(self):
        failures = self._report["failures"]
        assert len(failures) >= 2
        types = {f["type"] for f in failures}
        assert "DeadMasterAndSomeReplicas" in types
        assert "DeadIntermediateMaster" in types

    def test_master_failure_priority(self):
        """Master failure takes priority - promoted server is direct replica."""
        assert self._report["recovery_attempted"] is True
        assert self._report["promoted_server"] == "db-replica-09:3306"

    def test_outage_estimate(self):
        # neutral, no semi-sync, same DC: 5+10+1+1 = 17
        assert self._report["estimated_outage_seconds"] == 17.0

    def test_consul_updated_for_master(self):
        result = subprocess.run(
            ["consul", "kv", "get", f"mysql/{self._cluster}/primary"],
            capture_output=True, text=True, timeout=5,
        )
        kv = json.loads(result.stdout.strip())
        assert kv["hostname"] == "db-replica-09"

    def test_haproxy_config_valid(self):
        cfg = f"{OUTPUT_BASE}/incident_005/haproxy.cfg"
        assert os.path.exists(cfg)
        r = subprocess.run(
            ["haproxy", "-c", "-f", cfg],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0


# ===================================================================
# Pipeline Tool Usage Verification
# ===================================================================


class TestPipelineToolUsage:
    """Verify the pipeline uses the required tools."""

    def test_pipeline_uses_jq(self):
        with open(PIPELINE) as f:
            content = f.read()
        assert "jq " in content or "jq\n" in content or "jq'" in content or "| jq" in content, \
            "pipeline.sh must use jq for JSON processing"

    def test_pipeline_uses_consul(self):
        with open(PIPELINE) as f:
            content = f.read()
        assert "consul" in content, "pipeline.sh must use consul CLI"

    def test_pipeline_uses_haproxy(self):
        with open(PIPELINE) as f:
            content = f.read()
        assert "haproxy" in content, "pipeline.sh must use haproxy"
