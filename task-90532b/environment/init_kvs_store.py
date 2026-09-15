#!/usr/bin/env python3
"""Generate a Flux-style content-addressable KVS store with controlled corruption."""
import hashlib
import json
import base64
import sqlite3
import os


def sha1_blobref(data):
    return "sha1-" + hashlib.sha1(data).hexdigest()


def val_encode(value):
    """Encode a Python value as NUL-terminated JSON, then base64."""
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\x00'
    return base64.b64encode(raw).decode()


def make_val(v):
    return {"type": "val", "data": val_encode(v), "ver": 1}


def make_symlink(target, namespace=None):
    if namespace:
        return {"type": "symlink", "data": {"namespace": namespace, "target": target}, "ver": 1}
    return {"type": "symlink", "data": target, "ver": 1}


def make_dirref(h):
    return {"type": "dirref", "data": [h], "ver": 1}


def make_valref(h):
    return {"type": "valref", "data": [h], "ver": 1}


def ser_dir(children):
    """Serialize directory children map to deterministic JSON bytes."""
    return json.dumps(children, sort_keys=True, separators=(',', ':')).encode()


class Store:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE objects ("
            "hash TEXT PRIMARY KEY NOT NULL, "
            "size INTEGER NOT NULL, "
            "object_data BLOB NOT NULL)"
        )
        self.conn.commit()

    def put(self, data):
        h = sha1_blobref(data)
        try:
            self.conn.execute("INSERT INTO objects VALUES (?,?,?)", (h, len(data), data))
        except sqlite3.IntegrityError:
            pass
        return h

    def put_corrupt(self, correct_data, stored_data):
        """Store stored_data under the hash of correct_data (simulates corruption)."""
        h = sha1_blobref(correct_data)
        try:
            self.conn.execute("INSERT INTO objects VALUES (?,?,?)",
                              (h, len(stored_data), stored_data))
        except sqlite3.IntegrityError:
            pass
        return h

    def dangling(self, phantom):
        """Return a hash for data that is NOT inserted into the store."""
        return sha1_blobref(phantom)

    def put_dir(self, children):
        return self.put(ser_dir(children))

    def put_dir_corrupt(self, correct_children, corrupt_children):
        return self.put_corrupt(ser_dir(correct_children), ser_dir(corrupt_children))

    def finish(self):
        self.conn.commit()
        self.conn.close()


def build_primary(s):
    """Build primary namespace (cluster configuration). Returns root hash."""

    # config.access
    access_h = s.put_dir({
        "allow_guest_user": make_val(False),
        "allow_root_owner": make_val(True),
    })

    # config.resource.properties — CORRUPTED (standard: "0-7" vs "0-3")
    props_correct = {
        "gpu": make_val("8-15"),
        "highmem": make_val("4-7,12-15"),
        "standard": make_val("0-7"),
    }
    props_corrupt = {
        "gpu": make_val("8-15"),
        "highmem": make_val("4-7,12-15"),
        "standard": make_val("0-3"),
    }
    props_h = s.put_dir_corrupt(props_correct, props_corrupt)

    # config.resource.R — TRUNCATED valref blob
    full_R = json.dumps({
        "version": 1,
        "execution": {
            "R_lite": [
                {"rank": "0-7", "children": {"core": "0-15"}},
                {"rank": "4-7", "children": {"core": "0-15"},
                 "properties": {"highmem": True}},
                {"rank": "8-15", "children": {"core": "0-15", "gpu": "0-3"},
                 "properties": {"gpu": True}},
                {"rank": "12-15", "children": {"core": "0-15", "gpu": "0-3"},
                 "properties": {"gpu": True, "highmem": True}},
            ],
            "starttime": 0,
            "expiration": 0,
            "nodelist": ["node[0-15]"],
        }
    }, indent=2).encode()
    R_h = s.put_corrupt(full_R, full_R[:len(full_R) // 2])

    # config.resource
    cfg_res_h = s.put_dir({
        "R": make_valref(R_h),
        "properties": make_dirref(props_h),
        "topology": make_val({
            "cluster": "testcluster",
            "cores_per_node": 16,
            "gpus_per_node": {"8-15": 4},
            "nodes_per_rack": 8,
            "racks": 2,
        }),
    })

    # Queue config subdirectories
    batch_h = s.put_dir({
        "max_duration": make_val(43200),
        "max_nodes": make_val(8),
        "properties": make_val("standard"),
    })
    gpu_h = s.put_dir({
        "max_duration": make_val(14400),
        "max_nodes": make_val(8),
        "properties": make_val("gpu"),
    })
    prio_h = s.put_dir({
        "max_duration": make_val(7200),
        "max_nodes": make_val(4),
        "properties": make_val("highmem"),
    })
    qcfg_h = s.put_dir({
        "batch": make_dirref(batch_h),
        "gpu": make_dirref(gpu_h),
        "priority": make_dirref(prio_h),
    })

    # config.scheduler
    cfg_sched_h = s.put_dir({
        "policy": make_val("fcfs"),
        "queue_config": make_dirref(qcfg_h),
        "queues": make_symlink("config.scheduler.queue_config"),
    })

    # config (top-level)
    config_h = s.put_dir({
        "access": make_dirref(access_h),
        "resource": make_dirref(cfg_res_h),
        "scheduler": make_dirref(cfg_sched_h),
    })

    # resource.status.drain
    drain_h = s.put_dir({
        "idset": make_val("10-11"),
        "reason": make_val("hardware_fault"),
        "timestamp": make_val(1718280000.0),
    })

    # resource.status
    status_h = s.put_dir({
        "drain": make_dirref(drain_h),
        "online": make_val("0-15"),
    })

    # resource
    resource_h = s.put_dir({
        "R": make_symlink("config.resource.R"),
        "status": make_dirref(status_h),
    })

    # jobs (cross-namespace symlinks)
    jobs_h = s.put_dir({
        "active": make_symlink("active", namespace="jobs"),
        "completed": make_symlink("completed", namespace="jobs"),
    })

    # Root
    root_h = s.put_dir({
        "config": make_dirref(config_h),
        "jobs": make_dirref(jobs_h),
        "resource": make_dirref(resource_h),
    })
    return root_h


def build_jobs(s):
    """Build jobs namespace. Returns root hash."""

    f1234_h = s.put_dir({
        "nnodes": make_val(2),
        "ranks": make_val("8,9"),
        "state": make_val("running"),
        "t_run": make_val(1718280105.0),
        "t_submit": make_val(1718280100.0),
        "userid": make_val(1000),
    })
    f1235_h = s.put_dir({
        "nnodes": make_val(4),
        "ranks": make_val("12-15"),
        "state": make_val("running"),
        "t_run": make_val(1718280210.0),
        "t_submit": make_val(1718280200.0),
        "userid": make_val(1000),
    })
    active_h = s.put_dir({
        "f1234": make_dirref(f1234_h),
        "f1235": make_dirref(f1235_h),
    })

    f1230_h = s.put_dir({
        "nnodes": make_val(1),
        "ranks": make_val("0"),
        "state": make_val("completed"),
        "t_cleanup": make_val(1718280600.0),
        "t_inactive": make_val(1718280605.0),
        "t_run": make_val(1718280005.0),
        "t_submit": make_val(1718280000.0),
        "userid": make_val(1000),
    })

    # f1231 — DANGLING reference (hash not in store)
    f1231_h = s.dangling(b"dangling-f1231-blob-never-stored")

    completed_h = s.put_dir({
        "f1230": make_dirref(f1230_h),
        "f1231": make_dirref(f1231_h),
    })

    root_h = s.put_dir({
        "active": make_dirref(active_h),
        "completed": make_dirref(completed_h),
    })
    return root_h


def build_checkpoint(s, pri_root, job_root):
    """Build checkpoint namespace storing root references. Returns root hash."""
    kp_h = s.put_dir({
        "rootref": make_val(pri_root),
        "sequence": make_val(5),
    })
    kj_h = s.put_dir({
        "rootref": make_val(job_root),
        "sequence": make_val(3),
    })
    root_h = s.put_dir({
        "kvs-jobs": make_dirref(kj_h),
        "kvs-primary": make_dirref(kp_h),
        "timestamp": make_val(1718280300.0),
    })
    return root_h


def main():
    os.makedirs("/app/output", exist_ok=True)

    s = Store("/app/content.sqlite")

    pri = build_primary(s)
    job = build_jobs(s)
    chk = build_checkpoint(s, pri, job)

    # Orphaned blobs — not referenced from any namespace root
    s.put(json.dumps({"policy": "fifo", "version": "deprecated"},
                     sort_keys=True).encode())
    s.put(b"orphaned data from a previous KVS version not garbage collected")
    s.put(json.dumps({"migration_note":
                       "scheduler policy changed from fifo to fcfs at epoch 1718279000"
                       }).encode())

    s.finish()

    roots = {
        "namespaces": {
            "primary": {"root": make_dirref(pri), "sequence": 5, "owner": 0},
            "jobs": {"root": make_dirref(job), "sequence": 3, "owner": 0},
            "checkpoint": {"root": make_dirref(chk), "sequence": 1, "owner": 0},
        }
    }
    with open("/app/roots.json", "w") as f:
        json.dump(roots, f, indent=2)


if __name__ == "__main__":
    main()
