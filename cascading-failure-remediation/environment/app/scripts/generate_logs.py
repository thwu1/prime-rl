#!/usr/bin/env python3
"""Generate realistic crash logs from the cascading failure.

Simulates the log output that would have been produced by the service-
control crash loop and the gateway's corresponding connection-refused
errors.  The logs are written to /app/logs/ to give the agent forensic
evidence to work with.
"""
import os

LOG_DIR = '/app/logs'


def generate_service_control_log(instance_id, region, filepath):
    """Write a crash-loop log for one service-control instance."""

    entries = []

    # First boot attempt
    entries.append(
        f"2025-06-12 10:45:03 [INFO] service_control: "
        f"Initializing Service Control for region: {region}\n"
    )
    entries.append(
        f"2025-06-12 10:45:03 [INFO] service_control: "
        f"Loading policies from: /app/data/policies_{region}.db\n"
    )
    entries.append(
        "2025-06-12 10:45:03 [INFO] service_control.feature_flags: "
        "Loaded 3 feature flags\n"
    )
    entries.append(
        "2025-06-12 10:45:03 [INFO] service_control.policy_loader: "
        "Loading all policies from database\n"
    )
    for svc in ['compute.googleapis.com', 'storage.googleapis.com',
                'bigquery.googleapis.com', 'pubsub.googleapis.com',
                'spanner.googleapis.com',
                'cloudresourcemanager.googleapis.com',
                'container.googleapis.com']:
        entries.append(
            f"2025-06-12 10:45:03 [INFO] service_control.policy_loader: "
            f"Processing policy for service: {svc}\n"
        )
    entries.append(
        "2025-06-12 10:45:03 [INFO] service_control.policy_loader: "
        "Processing policy for service: internal-quota-sync\n"
    )
    entries.append(
        "2025-06-12 10:45:03 [ERROR] service_control: "
        "Unhandled exception during initialization\n"
    )
    entries.append(
        "Traceback (most recent call last):\n"
        '  File "/app/service_control/server.py", line 50, in initialize\n'
        "    policy_cache = loader.load_all_policies()\n"
        '  File "/app/service_control/policy_loader.py", line 42, '
        "in load_all_policies\n"
        "    policy = self._apply_enhanced_quota_check(policy, row)\n"
        '  File "/app/service_control/policy_loader.py", line 73, '
        "in _apply_enhanced_quota_check\n"
        "    policy['rate_limit_tier'] = rate_config['tier']\n"
        "TypeError: 'NoneType' object is not subscriptable\n"
    )
    entries.append(
        "2025-06-12 10:45:03 [CRITICAL] service_control: "
        "Service Control failed to start, exiting with code 1\n"
    )

    # Rapid restart attempts (thundering herd)
    base_sec = 4
    for restart in range(1, 16):
        ts = f"2025-06-12 10:45:{base_sec + restart:02d}"
        entries.append(
            f"{ts} [INFO] service_control: "
            f"Initializing Service Control for region: {region}\n"
        )
        entries.append(
            f"{ts} [INFO] service_control: "
            f"Loading policies from: /app/data/policies_{region}.db\n"
        )
        entries.append(
            f"{ts} [WARNING] service_control.db_connector: "
            f"Connection attempt 1/10 failed: database is locked\n"
        )
        entries.append(
            f"{ts} [WARNING] service_control.db_connector: "
            f"Connection attempt 2/10 failed: database is locked\n"
        )
        entries.append(
            f"{ts} [WARNING] service_control.db_connector: "
            f"Connection attempt 3/10 failed: database is locked\n"
        )
        entries.append(
            f"{ts} [INFO] service_control.policy_loader: "
            "Loading all policies from database\n"
        )
        entries.append(
            f"{ts} [INFO] service_control.policy_loader: "
            "Processing policy for service: compute.googleapis.com\n"
        )
        entries.append(
            f"{ts} [INFO] service_control.policy_loader: "
            "Processing policy for service: internal-quota-sync\n"
        )
        entries.append(
            f"{ts} [ERROR] service_control: "
            "Unhandled exception during initialization\n"
        )
        entries.append(
            "Traceback (most recent call last):\n"
            '  File "/app/service_control/server.py", line 50, '
            "in initialize\n"
            "    policy_cache = loader.load_all_policies()\n"
            '  File "/app/service_control/policy_loader.py", line 42, '
            "in load_all_policies\n"
            "    policy = self._apply_enhanced_quota_check(policy, row)\n"
            '  File "/app/service_control/policy_loader.py", line 73, '
            "in _apply_enhanced_quota_check\n"
            "    policy['rate_limit_tier'] = rate_config['tier']\n"
            "TypeError: 'NoneType' object is not subscriptable\n"
        )
        entries.append(
            f"{ts} [CRITICAL] service_control: "
            "Service Control failed to start, exiting with code 1\n"
        )

    with open(filepath, 'w') as f:
        f.writelines(entries)


def generate_gateway_log(filepath):
    """Write gateway error logs showing service_control unavailability."""
    entries = []
    for sec in range(5, 30):
        ts = f"2025-06-12 10:45:{sec:02d}"
        for port in [5001, 5002, 5003]:
            entries.append(
                f"{ts} [ERROR] gateway: Failed to reach service_control "
                f"at http://localhost:{port}/check_quota: "
                "ConnectionRefusedError: [Errno 111] Connection refused\n"
            )
        entries.append(
            f"{ts} [ERROR] gateway: "
            "Returning 503 to client - service_control unavailable\n"
        )

    with open(filepath, 'w') as f:
        f.writelines(entries)


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    for instance_id, region in [('1', 'region1'), ('2', 'region2'),
                                 ('3', 'region3')]:
        path = os.path.join(LOG_DIR, f'service_control_{instance_id}.log')
        generate_service_control_log(instance_id, region, path)
        print(f"  Generated {path}")

    gateway_path = os.path.join(LOG_DIR, 'gateway.log')
    generate_gateway_log(gateway_path)
    print(f"  Generated {gateway_path}")

    print("Crash logs generated.")


if __name__ == '__main__':
    main()
