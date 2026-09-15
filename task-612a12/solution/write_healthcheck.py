#!/usr/bin/env python3
"""Generate the healthcheck.sh endpoint probe script."""

import os

healthcheck_script = r'''#!/bin/bash
# Protocol health-check for metrics collector endpoints
# Usage: healthcheck.sh [config_file]
# Probes each endpoint and reports binary protocol vs mismatched protocol.

CONFIG="${1:-/app/config/endpoints.conf}"

if [ ! -f "$CONFIG" ]; then
    echo "ERROR: Config file not found: $CONFIG" >&2
    exit 1
fi

python3 -c '
import socket, struct, sys

config_path = sys.argv[1]
ok_count = 0
fail_count = 0

with open(config_path) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        name, host, port = parts[0], parts[1], int(parts[2])

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((host, port))
            data = s.recv(4)
            s.close()

            if len(data) < 4:
                print(f"[{name}] {host}:{port} - ERROR: short read ({len(data)} bytes)")
                fail_count += 1
            elif data[:4] == b"HTTP":
                print(f"[{name}] {host}:{port} - MISMATCH: endpoint speaks HTTP, not binary protocol")
                fail_count += 1
            else:
                length = struct.unpack("!I", data[:4])[0]
                if length < 1048576:
                    print(f"[{name}] {host}:{port} - OK: binary protocol (payload {length} bytes)")
                    ok_count += 1
                else:
                    print(f"[{name}] {host}:{port} - SUSPECT: payload length {length} unreasonably large")
                    fail_count += 1
        except Exception as e:
            print(f"[{name}] {host}:{port} - ERROR: {e}")
            fail_count += 1

print()
print(f"Results: {ok_count} OK, {fail_count} FAILED")
sys.exit(0 if fail_count == 0 else 1)
' "$CONFIG"
'''

with open('/app/healthcheck.sh', 'w') as f:
    f.write(healthcheck_script)

os.chmod('/app/healthcheck.sh', 0o755)
print("Created /app/healthcheck.sh")
