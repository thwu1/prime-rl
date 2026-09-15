#!/usr/bin/env python3
"""Generate deterministic OpenTelemetry-style telemetry data for the observability pipeline task."""

import random
import csv
import os
from datetime import datetime, timezone, timedelta

random.seed(42)

SERVICES = {
    "api-gateway": {
        "operations": [
            "GET /api/users", "POST /api/orders", "GET /api/products",
            "PUT /api/users/{id}", "DELETE /api/orders/{id}"
        ],
        "base_latency_us": 5000,
        "error_rate": 0.03
    },
    "auth-service": {
        "operations": ["login", "logout", "refresh_token", "validate_token"],
        "base_latency_us": 12000,
        "error_rate": 0.06
    },
    "user-service": {
        "operations": ["get_user", "create_user", "update_user", "list_users"],
        "base_latency_us": 8000,
        "error_rate": 0.02
    },
    "payment-service": {
        "operations": ["process_payment", "refund", "get_transaction", "validate_card"],
        "base_latency_us": 45000,
        "error_rate": 0.09
    },
    "notification-service": {
        "operations": ["send_email", "send_sms", "send_push", "get_status"],
        "base_latency_us": 25000,
        "error_rate": 0.04
    }
}

ERROR_CODES = [400, 401, 403, 404, 500, 502, 503]
BASE_DT = datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone.utc)
NUM_TRACES = 15000

rows = []
service_list = list(SERVICES.keys())

for i in range(NUM_TRACES):
    trace_id = format(i, '032x')
    num_spans = random.choices(
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        weights=[10, 20, 25, 18, 12, 7, 4, 2, 1, 1],
        k=1
    )[0]

    trace_offset_seconds = random.uniform(0, 86400)

    for j in range(num_spans):
        span_id = format(i * 100 + j, '016x')
        parent_span_id = format(i * 100 + (j - 1), '016x') if j > 0 else ""

        service = random.choice(service_list)
        svc_config = SERVICES[service]
        operation = random.choice(svc_config["operations"])

        base_lat = svc_config["base_latency_us"]
        duration_us = max(100, int(random.gauss(base_lat, base_lat * 0.3)))

        is_error = random.random() < svc_config["error_rate"]
        if is_error:
            status_code = random.choice(ERROR_CODES)
            log_level = "ERROR" if random.random() < 0.75 else "CRITICAL"
        else:
            status_code = 200
            log_level = "INFO" if random.random() < 0.9 else "WARN"

        span_dt = BASE_DT + timedelta(seconds=trace_offset_seconds + j * 0.001)
        ts_formatted = span_dt.strftime("%Y-%m-%d %H:%M:%S.%f")

        if " " in operation:
            parts = operation.split(" ", 1)
            http_method = parts[0]
            http_url = parts[1]
        else:
            http_method = "POST"
            http_url = "/internal/" + operation

        rows.append([
            ts_formatted, trace_id, span_id, parent_span_id,
            service, operation, duration_us, status_code,
            http_method, http_url, log_level
        ])

os.makedirs("/app/data", exist_ok=True)

with open("/app/data/telemetry.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "timestamp", "trace_id", "span_id", "parent_span_id",
        "service_name", "operation_name", "duration_us", "status_code",
        "http_method", "http_url", "log_level"
    ])
    writer.writerows(rows)

with open("/app/data/row_count.txt", "w") as f:
    f.write(str(len(rows)))

print("Generated {} telemetry spans from {} traces".format(len(rows), NUM_TRACES))
