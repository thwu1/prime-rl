#!/usr/bin/env python3
"""Generate binary register dump file for the TWAI filter task."""
import struct
import os

entries = [
    # mode, register_bytes (8 bytes as hex), label
    # Entry 0: single_standard, ID=0x541 care only, don't care RTR/payload
    (0, "a8200000001fffff", "ecu_engine"),
    # Entry 1: single_extended, ID=0x1ABCDEF0 + RTR=1, care all ID+RTR
    (1, "d5e6f78400000003", "chassis_sensor"),
    # Entry 2: dual_standard, filter1 ID=0x100, filter2 ID=0x200
    (2, "20004000001f001f", "body_controller"),
    # Entry 3: dual_extended, filter1 upper16=0xA820, filter2 upper16=0x5040
    (3, "a820504000000000", "brake_monitor"),
    # Entry 4: single_standard, exact match ID=0x7FF RTR=1 payload=0xDEAD
    (0, "fff0dead00000000", "diag_request"),
    # Entry 5: single_extended, accept everything (all don't-care)
    (1, "00000000ffffffff", "promiscuous"),
]

os.makedirs("/app/reference", exist_ok=True)

with open("/app/reference/register_configs.bin", "wb") as f:
    f.write(b"TWAI")
    f.write(struct.pack("<H", len(entries)))
    for mode, reg_hex, label in entries:
        f.write(struct.pack("B", mode))
        f.write(bytes.fromhex(reg_hex))
        label_bytes = label.encode("ascii")
        f.write(struct.pack("B", len(label_bytes)))
        f.write(label_bytes)
