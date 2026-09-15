#!/bin/bash


# Install runtime dependency
pip3 install cryptography==42.0.5 -q

# Deploy the solution module
cp /solution/quic_crypto_solution.py /app/quic_crypto.py

# Decrypt the captured packet
cd /app
python3 /solution/decrypt_capture.py

# Verify key derivation against RFC 9001 Appendix A test vectors
python3 -c "
from quic_crypto import derive_initial_keys, parse_quic_varint, parse_frames

dcid = bytes.fromhex('8394c8f03e515708')
r = derive_initial_keys(dcid, 0x00000001, 'client')
assert r['key'] == bytes.fromhex('1f369613dd76d5467730efcbe3b1a22d'), 'v1 client key mismatch'
assert r['iv']  == bytes.fromhex('fa044b2f42a3fd3b46fb255c'),           'v1 client iv mismatch'
assert r['hp']  == bytes.fromhex('9f50449e04a0e810283a1e9933adedd2'), 'v1 client hp mismatch'

r = derive_initial_keys(dcid, 0x00000001, 'server')
assert r['key'] == bytes.fromhex('cf3a5331653c364c88f0f379b6067e37'), 'v1 server key mismatch'

assert parse_quic_varint(bytes([0x25]), 0) == (37, 1)
assert parse_quic_varint(bytes.fromhex('7bbd'), 0) == (15293, 2)
assert parse_quic_varint(bytes.fromhex('9d7f3e7d'), 0) == (494878333, 4)

payload = bytes([0x06, 0x00, 0x05]) + b'hello'
frames = parse_frames(payload)
c = [f for f in frames if f['type'] == 'CRYPTO']
assert len(c) == 1 and c[0]['data'] == b'hello'

import json, os
assert os.path.exists('/app/capture/decrypted.json'), 'decrypted.json missing'

print('All solution verification checks passed.')
"
