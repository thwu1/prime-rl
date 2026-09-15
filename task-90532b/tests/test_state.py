
import hashlib
import json
import os
import sqlite3

import pytest

RESULT_PATH = "/app/output/manifest.json"


@pytest.fixture
def results():
    assert os.path.exists(RESULT_PATH), (
        f"Output file {RESULT_PATH} not found. Did the reconstruction tool run?"
    )
    with open(RESULT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def db():
    conn = sqlite3.connect("/app/content.sqlite")
    yield conn
    conn.close()


@pytest.fixture
def roots_json():
    with open("/app/roots.json") as f:
        return json.load(f)


# --- Schema and structure tests ---

def test_output_schema(results):
    """Output must have correct top-level keys and all 3 namespaces."""
    assert "namespaces" in results
    assert "integrity" in results
    assert "orphaned_blob_count" in results
    assert set(results["namespaces"].keys()) == {"primary", "jobs", "checkpoint"}
    for ns in results["namespaces"].values():
        assert "root_hash" in ns
        assert "resolved_values" in ns
        assert "symlinks" in ns


# --- Primary namespace value tests ---

def test_primary_access_values(results):
    """Primary namespace access control values."""
    rv = results["namespaces"]["primary"]["resolved_values"]
    assert rv["config.access.allow_root_owner"] is True
    assert rv["config.access.allow_guest_user"] is False


def test_primary_scheduler_policy(results):
    """Scheduler policy is 'fcfs'."""
    rv = results["namespaces"]["primary"]["resolved_values"]
    assert rv["config.scheduler.policy"] == "fcfs"


def test_primary_queue_configs(results):
    """All three queue configurations with correct limits."""
    rv = results["namespaces"]["primary"]["resolved_values"]
    assert rv["config.scheduler.queue_config.batch.max_nodes"] == 8
    assert rv["config.scheduler.queue_config.batch.max_duration"] == 43200
    assert rv["config.scheduler.queue_config.batch.properties"] == "standard"
    assert rv["config.scheduler.queue_config.gpu.max_nodes"] == 8
    assert rv["config.scheduler.queue_config.gpu.max_duration"] == 14400
    assert rv["config.scheduler.queue_config.gpu.properties"] == "gpu"
    assert rv["config.scheduler.queue_config.priority.max_nodes"] == 4
    assert rv["config.scheduler.queue_config.priority.max_duration"] == 7200
    assert rv["config.scheduler.queue_config.priority.properties"] == "highmem"


def test_primary_topology(results):
    """Topology value is correctly decoded from inline val."""
    rv = results["namespaces"]["primary"]["resolved_values"]
    topo = rv["config.resource.topology"]
    assert topo["cluster"] == "testcluster"
    assert topo["racks"] == 2
    assert topo["nodes_per_rack"] == 8
    assert topo["cores_per_node"] == 16
    assert topo["gpus_per_node"] == {"8-15": 4}


def test_primary_drain_values(results):
    """Drain status correctly decoded."""
    rv = results["namespaces"]["primary"]["resolved_values"]
    assert rv["resource.status.drain.idset"] == "10-11"
    assert rv["resource.status.drain.reason"] == "hardware_fault"
    assert rv["resource.status.drain.timestamp"] == 1718280000.0
    assert rv["resource.status.online"] == "0-15"


def test_primary_resolved_count(results):
    """Primary namespace should have exactly 17 resolvable leaf values."""
    rv = results["namespaces"]["primary"]["resolved_values"]
    assert len(rv) == 17, f"Expected 17, got {len(rv)}: {sorted(rv.keys())}"


# --- Primary symlink tests ---

def test_primary_symlinks(results):
    """Primary namespace has 4 symlinks with correct targets and resolution."""
    sym = results["namespaces"]["primary"]["symlinks"]
    assert len(sym) == 4, f"Expected 4 symlinks, got {len(sym)}: {sorted(sym.keys())}"

    # Same-namespace symlink to valid directory
    assert sym["config.scheduler.queues"]["target"] == "config.scheduler.queue_config"
    assert sym["config.scheduler.queues"]["target_namespace"] is None
    assert sym["config.scheduler.queues"]["resolves"] is True

    # Same-namespace symlink to corrupted valref
    assert sym["resource.R"]["target"] == "config.resource.R"
    assert sym["resource.R"]["target_namespace"] is None
    assert sym["resource.R"]["resolves"] is False

    # Cross-namespace symlinks to valid directories
    assert sym["jobs.active"]["target"] == "active"
    assert sym["jobs.active"]["target_namespace"] == "jobs"
    assert sym["jobs.active"]["resolves"] is True

    assert sym["jobs.completed"]["target"] == "completed"
    assert sym["jobs.completed"]["target_namespace"] == "jobs"
    assert sym["jobs.completed"]["resolves"] is True


# --- Jobs namespace tests ---

def test_jobs_active_entries(results):
    """Active jobs have correct state and resource info."""
    rv = results["namespaces"]["jobs"]["resolved_values"]
    assert rv["active.f1234.state"] == "running"
    assert rv["active.f1234.nnodes"] == 2
    assert rv["active.f1234.ranks"] == "8,9"
    assert rv["active.f1234.userid"] == 1000
    assert rv["active.f1234.t_submit"] == 1718280100.0
    assert rv["active.f1234.t_run"] == 1718280105.0

    assert rv["active.f1235.state"] == "running"
    assert rv["active.f1235.nnodes"] == 4
    assert rv["active.f1235.ranks"] == "12-15"


def test_jobs_completed_f1230(results):
    """Completed job f1230 has full lifecycle timestamps."""
    rv = results["namespaces"]["jobs"]["resolved_values"]
    assert rv["completed.f1230.state"] == "completed"
    assert rv["completed.f1230.nnodes"] == 1
    assert rv["completed.f1230.ranks"] == "0"
    assert rv["completed.f1230.t_cleanup"] == 1718280600.0
    assert rv["completed.f1230.t_inactive"] == 1718280605.0


def test_jobs_resolved_count(results):
    """Jobs namespace should have exactly 20 resolvable leaf values."""
    rv = results["namespaces"]["jobs"]["resolved_values"]
    assert len(rv) == 20, f"Expected 20, got {len(rv)}: {sorted(rv.keys())}"


# --- Checkpoint namespace tests ---

def test_checkpoint_values(results, roots_json):
    """Checkpoint stores correct root hashes and sequences."""
    rv = results["namespaces"]["checkpoint"]["resolved_values"]
    assert rv["kvs-primary.sequence"] == 5
    assert rv["kvs-jobs.sequence"] == 3
    assert rv["timestamp"] == 1718280300.0

    # Rootrefs must match actual namespace roots
    pri_root = roots_json["namespaces"]["primary"]["root"]["data"][0]
    jobs_root = roots_json["namespaces"]["jobs"]["root"]["data"][0]
    assert rv["kvs-primary.rootref"] == pri_root
    assert rv["kvs-jobs.rootref"] == jobs_root


# --- Integrity tests ---

def test_corrupted_blob_count(results):
    """Exactly 2 blobs should have hash mismatches."""
    assert len(results["integrity"]["corrupted_blobs"]) == 2


def test_corrupted_blobs_verified(results, db):
    """Each reported corrupted blob actually has a hash mismatch in the DB."""
    for entry in results["integrity"]["corrupted_blobs"]:
        row = db.execute(
            "SELECT object_data FROM objects WHERE hash = ?",
            (entry["stored_hash"],)
        ).fetchone()
        assert row is not None, f"Blob {entry['stored_hash']} not found in store"
        actual = "sha1-" + hashlib.sha1(row[0]).hexdigest()
        assert actual != entry["stored_hash"], (
            f"Blob {entry['stored_hash']} is NOT actually corrupted"
        )
        assert actual == entry["computed_hash"], (
            f"Computed hash mismatch: expected {entry['computed_hash']}, got {actual}"
        )


def test_dangling_ref_count(results):
    """Exactly 1 dangling reference (hash not in store)."""
    assert len(results["integrity"]["dangling_refs"]) == 1


def test_dangling_ref_verified(results, db):
    """The reported dangling ref hash does not exist in the store."""
    for h in results["integrity"]["dangling_refs"]:
        row = db.execute("SELECT 1 FROM objects WHERE hash = ?", (h,)).fetchone()
        assert row is None, f"Hash {h} IS in the store (not dangling)"


def test_unreachable_keys(results):
    """Correct unreachable keys due to corruption."""
    unreachable = set(results["integrity"]["unreachable_keys"])
    expected = {
        "primary::config.resource.properties",
        "primary::config.resource.R",
        "jobs::completed.f1231",
    }
    assert expected == unreachable, (
        f"Missing: {expected - unreachable}, Extra: {unreachable - expected}"
    )


def test_total_blobs(results, db):
    """Total blob count matches actual database row count."""
    count = db.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
    assert results["integrity"]["total_blobs"] == count


# --- Orphan and root tests ---

def test_orphaned_blob_count(results):
    """Exactly 3 orphaned blobs (unreferenced from any root)."""
    assert results["orphaned_blob_count"] == 3


def test_root_hashes_match(results, roots_json):
    """Root hashes in manifest match roots.json."""
    for ns_name, ns_info in roots_json["namespaces"].items():
        expected_hash = ns_info["root"]["data"][0]
        assert results["namespaces"][ns_name]["root_hash"] == expected_hash, (
            f"Root hash mismatch for {ns_name}"
        )


def test_no_false_unreachable(results):
    """No key should appear in both resolved_values and unreachable_keys."""
    for key in results["integrity"]["unreachable_keys"]:
        ns, path = key.split("::", 1)
        assert path not in results["namespaces"][ns]["resolved_values"], (
            f"Key {key} listed as unreachable but found in resolved_values"
        )
