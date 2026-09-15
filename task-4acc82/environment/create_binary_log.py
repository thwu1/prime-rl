#!/usr/bin/env python3
"""Create a log file with embedded NUL bytes simulating binary protocol data."""

lines = [
    b"\x00\x01\x02\x03BINARY_PROTOCOL_v2\x00\xff\xfe\xfd\n",
    b"2024-01-15T11:05:00Z [ERROR] code=E001 msg=\"Connection reset\" client=10.0.1.100\n",
    b"\x00\x00DATA_BLOCK\x89PNG\x0d\x0a\x1a\x0a\x00\x00\x00\n",
    b"2024-01-15T11:06:00Z [ERROR] code=E002 msg=\"Timeout exceeded\" client=10.0.1.101\n",
    b"\x00\x01\x02END_STREAM\x00\n",
]

with open("/app/logs/binary_mixed.log", "wb") as f:
    for line in lines:
        f.write(line)
