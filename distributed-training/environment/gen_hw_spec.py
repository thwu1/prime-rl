"""Generate the binary hardware specification file for the cost model generator."""
import struct
import os

hidden = 512
seq_length = 256
bandwidth = 1310720.0
latency = 0.1
checksum = hidden ^ seq_length ^ int(bandwidth / 1000.0)

os.makedirs('/app/native', exist_ok=True)
with open('/app/native/hw_spec.bin', 'wb') as f:
    f.write(struct.pack('<iiddi', hidden, seq_length, bandwidth, latency, checksum))
