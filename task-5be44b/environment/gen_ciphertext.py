#!/usr/bin/env python3
"""Encrypt the plaintext using candidate alpha via the compiled VM binary."""
import subprocess
import sys
import os

PLAINTEXT = b"R3v3rs3_Th3_VM!!"

with open("/tmp/_pt.bin", "wb") as f:
    f.write(PLAINTEXT)

result = subprocess.run(
    ["/build/vm", "/app/candidates/alpha.bin", "/tmp/_pt.bin", "/app/encrypted.bin"],
    capture_output=True
)
if result.returncode != 0:
    print(f"VM failed: {result.stderr.decode()}", file=sys.stderr)
    sys.exit(1)

os.remove("/tmp/_pt.bin")

ct = open("/app/encrypted.bin", "rb").read()
print(f"Generated encrypted.bin: {len(ct)} bytes, hex: {ct.hex()}")
