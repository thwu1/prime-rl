#!/usr/bin/env python3
"""Generate BLE capture files in various formats for the debug workspace.
This script is run during Docker build to create the capture data files.
"""
import base64
import struct
import os

# Raw BLE advertisement PDUs as hex strings (Link Layer, after preamble/access address, before CRC)
ALL_PDUS = [
    "401EF2E78B19A4C30201060B094E6F726469635F48524D020A0405030D180F18",
    "421DD123456789CB0201040BFF590001020304050607080709426561636F6E",
    "4414D123456789CB05030F180A1804160F1864020AFC",
    "410CF0F1F2F3F4C5112233445566",
    "4026AABBCCDDEECF0201061C09546F6F4C6F6E674465766963654E616D65457863656564734D6178",
    "001D123456789ABC02010603030D1809FF590003520801FFE305096E524635",
    "4618E1E2E3E4E5C602010708095363616E44657605FF5900AABB",
    "4010B1B2B3B4B5C6020106090948656C6C6F",
    "021F00112233445502010411077856341200DEBC9A78563412785634120319C100",
    "400FFFFFFFFFFFFF020106050954657374",
]

os.makedirs("/app/captures", exist_ok=True)

# Channel 37: plain hex-encoded PDUs, one per line
with open("/app/captures/ch37_adv.hex", "w") as f:
    for idx in [0, 3, 7, 9]:
        f.write(ALL_PDUS[idx] + "\n")

# Channel 38: base64-encoded PDUs, one per line
with open("/app/captures/ch38_adv.dat", "w") as f:
    for idx in [1, 4, 6]:
        raw = bytes.fromhex(ALL_PDUS[idx])
        f.write(base64.b64encode(raw).decode() + "\n")

# Channel 39: binary format — each entry is [2-byte LE length][raw PDU bytes]
with open("/app/captures/ch39_adv.bin", "wb") as f:
    for idx in [2, 5, 8]:
        raw = bytes.fromhex(ALL_PDUS[idx])
        f.write(struct.pack("<H", len(raw)))
        f.write(raw)

print("Capture files generated.")
