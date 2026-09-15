#!/usr/bin/env python3
"""Initialize the Cilium endpoint state SQLite database."""
import sqlite3
import json

DB_PATH = "/app/cilium-state.db"

ENDPOINTS = [
    {
        "id": 1001,
        "name": "frontend",
        "pod_name": "frontend-7b9d5c6f4-xr9m2",
        "namespace": "default",
        "ip_v4": "10.0.1.10",
        "identity_id": 48291,
        "labels": {"app": "frontend", "env": "prod", "team": "platform"},
    },
    {
        "id": 1002,
        "name": "backend-api",
        "pod_name": "backend-api-6d8f7c9a2-kp4n7",
        "namespace": "default",
        "ip_v4": "10.0.2.20",
        "identity_id": 52847,
        "labels": {"app": "backend", "component": "api", "env": "prod"},
    },
    {
        "id": 1003,
        "name": "backend-worker",
        "pod_name": "backend-worker-3e5a8b1c7-zt6w3",
        "namespace": "default",
        "ip_v4": "10.0.2.30",
        "identity_id": 53912,
        "labels": {"app": "backend", "component": "worker", "env": "prod"},
    },
    {
        "id": 1004,
        "name": "database",
        "pod_name": "database-0",
        "namespace": "default",
        "ip_v4": "10.0.3.40",
        "identity_id": 67234,
        "labels": {"app": "database", "env": "prod", "tier": "data"},
    },
    {
        "id": 1005,
        "name": "cache",
        "pod_name": "cache-redis-0",
        "namespace": "default",
        "ip_v4": "10.0.3.50",
        "identity_id": 68501,
        "labels": {"app": "cache", "env": "prod", "tier": "data"},
    },
    {
        "id": 1006,
        "name": "monitoring",
        "pod_name": "monitoring-prometheus-0",
        "namespace": "monitoring",
        "ip_v4": "10.0.4.60",
        "identity_id": 71893,
        "labels": {"app": "monitoring", "env": "ops"},
    },
    {
        "id": 1007,
        "name": "staging-fe",
        "pod_name": "frontend-staging-8c4d2e1f3-bv5j1",
        "namespace": "staging",
        "ip_v4": "10.0.5.70",
        "identity_id": 84562,
        "labels": {"app": "frontend", "env": "staging"},
    },
]

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE endpoints (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            pod_name TEXT NOT NULL,
            namespace TEXT DEFAULT 'default',
            ip_v4 TEXT NOT NULL,
            ip_v6 TEXT DEFAULT '',
            identity_id INTEGER NOT NULL,
            state TEXT DEFAULT 'ready',
            FOREIGN KEY (identity_id) REFERENCES identities(id)
        )
    """)

    c.execute("""
        CREATE TABLE identities (
            id INTEGER PRIMARY KEY,
            labels TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE endpoint_labels (
            endpoint_id INTEGER NOT NULL,
            source TEXT DEFAULT 'k8s',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            FOREIGN KEY (endpoint_id) REFERENCES endpoints(id)
        )
    """)

    c.execute("""
        CREATE TABLE ip_cache (
            ip TEXT PRIMARY KEY,
            identity_id INTEGER NOT NULL,
            host_ip TEXT DEFAULT '',
            encryptkey INTEGER DEFAULT 0,
            FOREIGN KEY (identity_id) REFERENCES identities(id)
        )
    """)

    seen_identities = set()
    for ep in ENDPOINTS:
        c.execute(
            "INSERT INTO endpoints (id, name, pod_name, namespace, ip_v4, identity_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ep["id"], ep["name"], ep["pod_name"], ep["namespace"],
             ep["ip_v4"], ep["identity_id"]),
        )

        identity_labels = [f"k8s:{k}={v}" for k, v in ep["labels"].items()]
        identity_labels.append(f"k8s:io.kubernetes.pod.namespace={ep['namespace']}")

        if ep["identity_id"] not in seen_identities:
            c.execute(
                "INSERT INTO identities (id, labels) VALUES (?, ?)",
                (ep["identity_id"], json.dumps(identity_labels)),
            )
            seen_identities.add(ep["identity_id"])

        for k, v in ep["labels"].items():
            c.execute(
                "INSERT INTO endpoint_labels (endpoint_id, source, key, value) "
                "VALUES (?, 'k8s', ?, ?)",
                (ep["id"], k, v),
            )

        c.execute(
            "INSERT INTO ip_cache (ip, identity_id) VALUES (?, ?)",
            (ep["ip_v4"], ep["identity_id"]),
        )

    # Add reserved identities
    reserved = [
        (1, ["reserved:host"]),
        (2, ["reserved:world"]),
        (3, ["reserved:unmanaged"]),
        (4, ["reserved:health"]),
        (5, ["reserved:init"]),
        (6, ["reserved:remote-node"]),
        (7, ["reserved:kube-apiserver"]),
    ]
    for rid, rlabels in reserved:
        c.execute(
            "INSERT INTO identities (id, labels) VALUES (?, ?)",
            (rid, json.dumps(rlabels)),
        )

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
