#!/usr/bin/env python3
import os
os.makedirs('/app/testdata', exist_ok=True)
with open('/app/testdata/msg_01.bin', 'wb') as f:
    f.write(b'Hello')
with open('/app/testdata/msg_02.bin', 'wb') as f:
    f.write(bytes(range(1, 33)))
with open('/app/testdata/msg_03.bin', 'wb') as f:
    f.write(b'\xff' * 8)
with open('/app/testdata/msg_04.bin', 'wb') as f:
    f.write(b'\x00' * 4 + b'\xff' * 4)
