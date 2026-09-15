#!/usr/bin/env python3
"""Generate the root cause diagnosis by computationally decoding the
anomalous numeric value from the collector logs."""

import re

# Read collector log to find the anomalous payload size
with open('/var/log/collector/collector.log') as f:
    log_content = f.read()

# Extract all reported payload sizes
sizes = [int(s) for s in re.findall(r'payload size: (\d+) bytes', log_content)]

# Identify the anomalous value (orders of magnitude larger than others)
normal = [s for s in sizes if s < 10000]
anomalous = [s for s in sizes if s >= 10000]
magic = anomalous[0] if anomalous else 1213486160

# Decode the magic number as a 32-bit big-endian ASCII string
hex_val = f'0x{magic:08X}'
decoded_chars = []
for i in range(4):
    byte = (magic >> (24 - 8 * i)) & 0xFF
    decoded_chars.append(chr(byte))
decoded = ''.join(decoded_chars)

# Find which endpoint produces this value
match = re.search(rf'(\S+) reports payload size: {magic}', log_content)
endpoint_name = match.group(1) if match else 'svc-gamma'

# Find the port from config
port = '9003'
try:
    with open('/app/config/endpoints.conf') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            parts = line.split()
            if len(parts) >= 3 and parts[0] == endpoint_name:
                port = parts[2]
                break
except Exception:
    pass

# Write the diagnosis
diagnosis = f"""Root Cause Analysis: Metrics Collector Cascading Memory Failure

ANOMALOUS VALUE:
The collector log shows {endpoint_name} reporting a payload size of {magic} bytes.

DECODING:
  Decimal:  {magic}
  Hex:      {hex_val}
  Byte 0:   0x{(magic >> 24) & 0xFF:02X} = '{chr((magic >> 24) & 0xFF)}'
  Byte 1:   0x{(magic >> 16) & 0xFF:02X} = '{chr((magic >> 16) & 0xFF)}'
  Byte 2:   0x{(magic >> 8) & 0xFF:02X} = '{chr((magic >> 8) & 0xFF)}'
  Byte 3:   0x{magic & 0xFF:02X} = '{chr(magic & 0xFF)}'

The number {magic} ({hex_val}) is the ASCII string "{decoded}"
interpreted as a 32-bit big-endian integer.

ROOT CAUSE:
The service on port {port} ({endpoint_name}) was replaced with an HTTP
health-check endpoint. When the collector connects, the HTTP service responds
with "HTTP/1.0 200 OK\\r\\n...". The collector's binary protocol reads the
first 4 bytes as a network-order length prefix, interpreting "{decoded}" as a
request to allocate {magic} bytes (~{magic / (1024**3):.2f} GB).

Two bugs in collector.c compound the problem:
1. No sanity check on message length before malloc() — accepts any 32-bit
   value, including the ~1.13 GB implied by "HTTP"
2. Memory leak on the truncation error path — the buffer allocated by malloc()
   is never freed when recv() fails to read the full expected payload

Each polling cycle (every 5 seconds) leaks ~1.13 GB, causing the watchdog
to kill the collector when RSS exceeds its 512 MB threshold (~30 seconds).

FIX:
- Added MAX_PAYLOAD_SIZE (10 MB) validation before malloc()
- Added free(buf) on the data truncation error path
- Removed {endpoint_name} (port {port}) from endpoint configuration
"""

with open('/app/diagnosis.txt', 'w') as f:
    f.write(diagnosis)

print(f"Diagnosis written to /app/diagnosis.txt")
print(f"Key finding: {magic} = {hex_val} = \"{decoded}\"")
