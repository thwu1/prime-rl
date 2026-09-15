#!/usr/bin/env python3
"""
Decrypt the captured QUIC packet and produce decrypted.json.

"""
import json
import sys

sys.path.insert(0, "/app")
from quic_crypto import derive_initial_keys, remove_header_protection, decrypt_payload, parse_frames

with open("/app/capture/metadata.json") as f:
    meta = json.load(f)
dcid = bytes.fromhex(meta["dcid"])

with open("/app/capture/packet.hex") as f:
    packet = bytes.fromhex(f.read().strip())

keys = derive_initial_keys(dcid, 0x00000001, "client")
hdr, pn, pn_len, ps = remove_header_protection(packet, keys["hp"])
dec = decrypt_payload(packet[ps:], pn, keys["key"], keys["iv"], hdr)
frames = parse_frames(dec)

crypto_frames = [f for f in frames if f["type"] == "CRYPTO"]
if not crypto_frames:
    print("ERROR: No CRYPTO frame found in decrypted packet")
    sys.exit(1)

result = {"crypto_data": crypto_frames[0]["data"].hex()}
with open("/app/capture/decrypted.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"Decrypted output written to /app/capture/decrypted.json")
print(f"CRYPTO data ({len(crypto_frames[0]['data'])} bytes): {crypto_frames[0]['data']!r}")
