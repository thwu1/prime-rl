#!/usr/bin/env python3
"""Generate the post-incident analysis by computationally analyzing the
failure mode — decoding the magic number and mapping the causal chain."""

import struct
import socket

# Compute the magic number: when the collector reads "HTTP" as a 4-byte
# big-endian length prefix, what value does it get?
http_bytes = b"HTTP"
magic_number = struct.unpack('!I', http_bytes)[0]
hex_val = f'0x{magic_number:08X}'

# Decode byte by byte
byte_lines = []
for i in range(4):
    byte = (magic_number >> (24 - 8 * i)) & 0xFF
    byte_lines.append(f"  Byte {i}: 0x{byte:02X} = '{chr(byte)}'")
byte_analysis = '\n'.join(byte_lines)

# Verify which port speaks HTTP by probing (if services are running)
http_port = '9003'
http_name = 'svc-gamma'
try:
    with open('/app/config/endpoints.conf') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            parts = line.split()
            if len(parts) >= 3:
                name, host, port = parts[0], parts[1], int(parts[2])
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(2)
                    s.connect((host, port))
                    data = s.recv(4)
                    s.close()
                    if data[:4] == b'HTTP':
                        http_port = str(port)
                        http_name = name
                except Exception:
                    pass
except Exception:
    pass

gb_size = magic_number / (1024**3)

postmortem = f"""# Post-Incident Analysis: Metrics Collector Cascade Failure

## Incident Summary

The metrics collector daemon entered a crash loop, being killed by its watchdog
every ~10 seconds for exceeding the 1 GB virtual memory limit. The collector's
own log file contained no entries from the crash loop period, leaving operators
with no diagnostic visibility into the root cause.

## Root Cause Analysis

### Trigger: Protocol Mismatch on Port {http_port}

The service on port {http_port} ({http_name}) was replaced with an HTTP
health-check endpoint, but the collector's endpoint configuration was not
updated. When the collector connects, the HTTP service responds with
"HTTP/1.0 200 OK\\r\\n...".

The collector's binary protocol reads the first 4 bytes as a network-order
(big-endian) 32-bit length prefix:

  Raw bytes: 0x48 0x54 0x54 0x50
{byte_analysis}

  Decoded integer: {magic_number} ({hex_val})
  This is the ASCII string "HTTP" interpreted as a uint32.

The collector interprets this as a request for a {magic_number}-byte
(~{gb_size:.2f} GB) payload buffer.

### Vulnerability: No Payload Size Validation (Severity: CRITICAL)

The collector passes the 4-byte length prefix directly to malloc() without any
sanity check. A valid metrics payload is typically 50-200 bytes. The lack of an
upper bound means ANY data interpreted as a length prefix — including protocol
identification strings like "HTTP" — results in a multi-gigabyte allocation.

This is the primary vulnerability. Without it, the protocol mismatch would
cause a parse error but not a resource exhaustion crash.

Impact: Enables the entire cascade. Any endpoint speaking a different protocol
can crash the collector.

### Amplifier 1: Memory Leak on Truncation Path (Severity: HIGH)

When recv() fails to read the full expected payload (because the HTTP service
only sends ~80 bytes before closing), the truncation error handler returns
without calling free(buf). The ~{gb_size:.2f} GB buffer is leaked on every poll
cycle.

Even if the allocation were smaller, this leak would eventually exhaust memory
over time. Combined with the missing size validation, it accelerates the
crash to a single poll cycle.

Impact: Guarantees memory exhaustion even if a single oversized allocation
doesn't immediately exceed limits.

### Amplifier 2: Socket File Descriptor Leak (Severity: MEDIUM)

The same truncation error path returns without calling close(sock). Each failed
poll cycle leaks one file descriptor. While the immediate crash is caused by
virtual memory exhaustion (which happens first), the fd leak would independently
cause "too many open files" errors after prolonged operation, even with smaller
payloads.

Impact: Would cause independent failures over time. Secondary to the memory
issue in this incident but indicates systemic resource cleanup neglect.

### Observability Failure: Missing Log Entries (Severity: HIGH)

The collector opens its log file with standard fopen() which, for non-terminal
file descriptors, defaults to fully-buffered I/O. Log messages accumulate in
an internal stdio buffer (~4-8 KB) and are only flushed when the buffer fills
or the file is explicitly flushed/closed.

When the watchdog kills the collector with SIGKILL (signal 9), the process is
terminated immediately — no signal handlers run, no atexit handlers execute,
and no stdio buffers are flushed. All buffered log data is lost.

This is why the collector log shows only a shutdown message from the previous
graceful run: that run terminated via SIGTERM, which allowed the signal handler
to set running=0, exit the poll loop, and call fclose() (which flushes). The
crash loop runs never get to fclose().

Impact: Eliminated diagnostic visibility. Without logs, operators cannot
determine what the collector was doing when it was killed. This turned a
potentially quick diagnosis ("payload size 1213486160 — that's obviously wrong")
into a tools-intensive investigation requiring strace, lsof, or manual protocol
probing.

## Causal Chain

1. **Root trigger**: {http_name} replaced with HTTP endpoint (configuration drift)
2. **Primary vulnerability**: No payload size validation before malloc (code defect)
3. **Memory amplifier**: Buffer not freed on truncation path (code defect)
4. **FD amplifier**: Socket not closed on truncation path (code defect)
5. **Observability loss**: No stdio log flushing before SIGKILL (code defect)
6. **Observable symptom**: Watchdog kills collector every ~10 seconds; no logs

## Severity Evaluation

| Bug | Severity | Category | Independent Impact |
|-----|----------|----------|--------------------|
| Missing size validation | Critical | Vulnerability | Enables crash from any protocol mismatch |
| Memory leak on error path | High | Resource leak | Guarantees eventual OOM even with smaller payloads |
| Missing log flush/setlinebuf | High | Observability | Prevents diagnosis, extends incident duration |
| Socket FD leak on error path | Medium | Resource leak | Would cause fd exhaustion independently over time |
| Stale endpoint config | Trigger | Configuration | Exposes the vulnerability to exploitation |

## Remediation

1. Added `setlinebuf(logfp)` after fopen to ensure line-buffered log output
2. Added MAX_PAYLOAD_SIZE (10 MB) validation before malloc()
3. Added free(buf) on truncation error path
4. Added close(sock) on truncation error path
5. Removed {http_name} (port {http_port}) from endpoint configuration
6. Created healthcheck.sh to detect protocol mismatches proactively
"""

with open('/app/postmortem.md', 'w') as f:
    f.write(postmortem)

print(f"Postmortem written to /app/postmortem.md")
print(f"Key finding: {magic_number} = {hex_val} = 'HTTP'")
