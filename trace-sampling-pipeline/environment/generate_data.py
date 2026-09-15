#!/usr/bin/env python3
"""Generate deterministic telemetry span data and load into SQLite for the
tail-based sampling task."""
import json
import random
import os
import sqlite3

SEED = 42
NUM_TRACES = 10000
BASE_TIMESTAMP = 1700000000000000000  # nanoseconds

REGIONS = ["us-east-1", "us-west-2", "eu-west-1"]
HOSTNAMES = [f"app-{i:02d}" for i in range(1, 11)]
BUILD_IDS = ["build-1847", "build-1848", "build-1849"]

ENDPOINT_WEIGHTS = [
    ("/api/v1/products", "GET", 40),
    ("/api/v1/orders", "POST", 20),
    ("/api/v1/users/{id}", "GET", 25),
    ("/api/v1/payments", "POST", 10),
    ("/health", "GET", 5),
]

DOWNSTREAM = {
    "/api/v1/products": [
        ("inventory-service", "/internal/inventory/check", "GET", 10, 5),
    ],
    "/api/v1/orders": [
        ("user-service", "/internal/users/validate", "POST", 20, 10),
        ("inventory-service", "/internal/inventory/reserve", "POST", 25, 12),
        ("payment-service", "/internal/payments/process", "POST", 150, 80),
    ],
    "/api/v1/users/{id}": [
        ("user-service", "/internal/users/lookup", "GET", 15, 8),
    ],
    "/api/v1/payments": [
        ("payment-service", "/internal/payments/process", "POST", 150, 80),
    ],
    "/health": [],
}

LATENCY_CONFIG = {
    "/api/v1/products": (30, 15),
    "/api/v1/orders": (120, 60),
    "/api/v1/users/{id}": (25, 10),
    "/api/v1/payments": (200, 100),
    "/health": (2, 1),
}


def generate_id():
    return "%016x" % random.getrandbits(64)


def generate_trace_id():
    return "%032x" % random.getrandbits(128)


def weighted_choice(items):
    total = sum(w for _, _, w in items)
    r = random.random() * total
    cumulative = 0
    for route, method, weight in items:
        cumulative += weight
        if r <= cumulative:
            return route, method
    return items[-1][0], items[-1][1]


def generate_spans():
    random.seed(SEED)
    all_spans = []
    timestamp = BASE_TIMESTAMP

    for _ in range(NUM_TRACES):
        trace_id = generate_trace_id()
        route, method = weighted_choice(ENDPOINT_WEIGHTS)

        is_error = random.random() < 0.03
        is_slow = random.random() < 0.01

        user_id = f"user-{random.randint(1, 5000)}"
        region = random.choice(REGIONS)
        hostname = random.choice(HOSTNAMES)
        build_id = random.choice(BUILD_IDS)

        root_span_id = generate_id()

        # Variable encoding for root span parent_span_id
        encoding_roll = random.random()
        if encoding_roll < 0.80:
            root_parent = ""
        elif encoding_roll < 0.90:
            root_parent = None  # field will be omitted
        else:
            root_parent = "0000000000000000"

        base_lat, lat_std = LATENCY_CONFIG[route]
        root_duration = max(1.0, random.gauss(base_lat, lat_std))
        if is_slow:
            root_duration = max(501.0, random.gauss(800, 200))

        downstream = DOWNSTREAM.get(route, [])
        error_span_idx = None
        if is_error:
            error_span_idx = random.randint(0, len(downstream))

        root_status = 200
        root_error = False
        if is_error and error_span_idx == 0:
            root_status = random.choice([500, 502, 503])
            root_error = True

        root_span = {
            "trace_id": trace_id,
            "span_id": root_span_id,
            "service_name": "api-gateway",
            "operation_name": f"{method} {route}",
            "start_time_unix_nano": timestamp,
            "duration_ms": round(root_duration, 2),
            "http_status_code": root_status,
            "http_method": method,
            "http_route": route,
            "error": root_error,
            "user_id": user_id,
            "region": region,
            "build_id": build_id,
            "hostname": hostname,
        }
        if root_parent is not None:
            root_span["parent_span_id"] = root_parent

        all_spans.append(root_span)

        # Downstream spans
        is_incomplete = random.random() < 0.02
        skip_idx = (
            random.randint(0, len(downstream) - 1)
            if is_incomplete and downstream
            else -1
        )

        for i, (svc, op_route, op_method, op_base, op_std) in enumerate(downstream):
            if is_incomplete and i == skip_idx:
                continue

            child_span_id = generate_id()
            child_duration = max(1.0, random.gauss(op_base, op_std))
            if is_slow:
                child_duration *= 3.0

            child_status = 200
            child_error = False
            if is_error and error_span_idx == i + 1:
                child_status = random.choice([500, 502, 503])
                child_error = True
                if not root_error:
                    root_span["http_status_code"] = 502
                    root_span["error"] = True

            child_span = {
                "trace_id": trace_id,
                "span_id": child_span_id,
                "parent_span_id": root_span_id,
                "service_name": svc,
                "operation_name": f"{op_method} {op_route}",
                "start_time_unix_nano": timestamp
                + int(random.uniform(1, 5) * 1_000_000),
                "duration_ms": round(child_duration, 2),
                "http_status_code": child_status,
                "http_method": op_method,
                "http_route": op_route,
                "error": child_error,
                "user_id": user_id,
                "region": region,
                "build_id": build_id,
                "hostname": random.choice(HOSTNAMES),
            }

            if svc == "user-service":
                child_span["db_type"] = "postgresql"
                child_span["db_statement"] = (
                    f"SELECT * FROM users WHERE id = '{user_id}'"
                )
                child_span["cache_hit"] = random.random() < 0.7
            elif svc == "inventory-service":
                product_id = f"prod-{random.randint(1, 500)}"
                child_span["db_type"] = "postgresql"
                child_span["db_statement"] = (
                    f"SELECT stock FROM inventory WHERE product_id = '{product_id}'"
                )
                child_span["product_id"] = product_id
            elif svc == "payment-service":
                child_span["payment_provider"] = random.choice(
                    ["stripe", "paypal", "square"]
                )
                child_span["payment_amount_cents"] = random.randint(100, 50000)

            all_spans.append(child_span)

        timestamp += int(random.uniform(50, 200) * 1_000_000)

    # Shuffle spans to simulate out-of-order arrival
    random.shuffle(all_spans)
    return all_spans


def create_sqlite_db(spans, db_path):
    """Load spans into a SQLite database with analytical schema."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE spans (
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            parent_span_id TEXT,
            service_name TEXT,
            operation_name TEXT,
            start_time_unix_nano INTEGER,
            duration_ms REAL,
            http_status_code INTEGER,
            http_method TEXT,
            http_route TEXT,
            error INTEGER DEFAULT 0,
            user_id TEXT,
            region TEXT,
            build_id TEXT,
            hostname TEXT,
            is_root INTEGER DEFAULT 0
        )
    """)

    for span in spans:
        parent = span.get("parent_span_id")
        is_root = 1 if (parent is None or parent == ""
                        or parent == "0000000000000000") else 0
        c.execute(
            "INSERT INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                span["trace_id"],
                span["span_id"],
                span.get("parent_span_id"),
                span.get("service_name"),
                span.get("operation_name"),
                span.get("start_time_unix_nano"),
                span.get("duration_ms"),
                span.get("http_status_code"),
                span.get("http_method"),
                span.get("http_route"),
                1 if span.get("error") else 0,
                span.get("user_id"),
                span.get("region"),
                span.get("build_id"),
                span.get("hostname"),
                is_root,
            ),
        )

    c.execute("CREATE INDEX idx_trace_id ON spans(trace_id)")
    c.execute("CREATE INDEX idx_service ON spans(service_name)")
    c.execute("CREATE INDEX idx_route ON spans(http_route)")
    c.execute("CREATE INDEX idx_is_root ON spans(is_root)")
    c.execute("CREATE INDEX idx_parent ON spans(parent_span_id)")
    c.execute("CREATE INDEX idx_span_id ON spans(span_id)")

    conn.commit()
    conn.close()


def main():
    os.makedirs("/app/data", exist_ok=True)
    spans = generate_spans()

    with open("/app/data/spans.jsonl", "w") as f:
        for span in spans:
            f.write(json.dumps(span) + "\n")

    create_sqlite_db(spans, "/app/data/telemetry.db")

    print(f"Generated {len(spans)} spans from {NUM_TRACES} traces")
    print(f"SQLite database created at /app/data/telemetry.db")


if __name__ == "__main__":
    main()
